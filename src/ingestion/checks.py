"""
Ingestion sanity checks (docs/audit_logging_design.md, section 6).

The 5,540-chunk run "succeeded" while every chunk was raw PDF bytes, because
nothing looked at what had been indexed. These checks look. Each is a pure
function over plain data (page records and chunk texts), so they can be
tested on fake garbage without a PDF, an embedding model or Chroma, and run
both before embedding (on parsed pages and chunks) and against an existing
collection (`--check-only`).

Every check returns a dict: name, passed (True / False / None = not
applicable), metric, threshold, action (block | warn). Thresholds come from
src/config.py.
"""

import re
from collections import Counter

from src import config

RAW_PDF_MARKERS = re.compile(r"%PDF-|\bendobj\b|\bendstream\b")


def _result(name, passed, metric, threshold, action, **data):
    return {"name": name, "passed": passed, "metric": metric, "threshold": threshold, "action": action, "data": data}


def is_bad_char(ch: str) -> bool:
    """Non-printable (whitespace such as a non-breaking space is fine) or the U+FFFD replacement character."""
    return ch == "\ufffd" or not (ch.isprintable() or ch.isspace())


def check_pdf_reader(pdf_pages: list[dict]) -> dict:
    """
    Every PDF page record carries a page label, which only a real PDF reader
    produces. The plain-text fallback that caused the 5,540-chunk run reads
    each file as one unlabelled document.
    pdf_pages: [{"file_name", "page_label", "text"}] for .pdf sources.
    """
    if not pdf_pages:
        return _result("pdf_reader_used", None, None, 1.0, "block", reason="no PDF sources")
    labelled = sum(1 for p in pdf_pages if p.get("page_label") is not None)
    share = labelled / len(pdf_pages)
    return _result("pdf_reader_used", share == 1.0, round(share, 4), 1.0, "block",
                   pdf_page_records=len(pdf_pages), labelled=labelled)


def check_raw_pdf_markers(chunks: list[str]) -> dict:
    hits = [i for i, c in enumerate(chunks) if RAW_PDF_MARKERS.search(c)]
    return _result("no_raw_pdf_markers", not hits, len(hits), 0, "block",
                   chunks=len(chunks), first_hits=hits[:5])


def check_bad_char_share(chunks: list[str]) -> dict:
    total = sum(len(c) for c in chunks)
    if total == 0:
        return _result("bad_char_share", False, None, config.INGEST_MAX_BAD_CHAR_SHARE, "block", reason="no text")
    bad = sum(1 for c in chunks for ch in c if is_bad_char(ch))
    share = bad / total
    return _result("bad_char_share", share < config.INGEST_MAX_BAD_CHAR_SHARE, round(share, 6),
                   config.INGEST_MAX_BAD_CHAR_SHARE, "block", characters=total, bad=bad)


def check_chunks_per_page(n_chunks: int, n_pdf_pages: int) -> dict:
    lo, hi = config.INGEST_CHUNKS_PER_PAGE_MIN, config.INGEST_CHUNKS_PER_PAGE_MAX
    if n_pdf_pages == 0:
        return _result("chunks_per_page", None, None, [lo, hi], "block", reason="no PDF pages")
    ratio = n_chunks / n_pdf_pages
    return _result("chunks_per_page", lo <= ratio <= hi, round(ratio, 3), [lo, hi], "block",
                   chunks=n_chunks, pdf_pages=n_pdf_pages)


def check_pages_with_text(pages_with_text: int, n_pdf_pages: int) -> dict:
    """Catches a PDF that opens but yields no text (e.g. encryption not handled)."""
    if n_pdf_pages == 0:
        return _result("pages_with_text", None, None, config.INGEST_MIN_PAGES_WITH_TEXT_SHARE, "block",
                       reason="no PDF pages")
    share = pages_with_text / n_pdf_pages
    return _result("pages_with_text", share >= config.INGEST_MIN_PAGES_WITH_TEXT_SHARE, round(share, 4),
                   config.INGEST_MIN_PAGES_WITH_TEXT_SHARE, "block",
                   pages_with_text=pages_with_text, pdf_pages=n_pdf_pages)


def check_file_coverage(chunks_per_file: dict[str, int], pages_per_file: dict[str, int]) -> dict:
    """Every source file has chunks; each file's chunk share is within the ratio of its page share. Warn only."""
    ratio_max = config.INGEST_MAX_FILE_SHARE_RATIO
    total_chunks, total_pages = sum(chunks_per_file.values()), sum(pages_per_file.values())
    missing = sorted(f for f in pages_per_file if not chunks_per_file.get(f))
    out_of_range = {}
    if total_chunks and total_pages:
        for f, pages in pages_per_file.items():
            if pages and chunks_per_file.get(f):
                r = (chunks_per_file[f] / total_chunks) / (pages / total_pages)
                if not (1 / ratio_max <= r <= ratio_max):
                    out_of_range[f] = round(r, 3)
    return _result("file_coverage", not missing and not out_of_range, {"missing": missing, "out_of_range": out_of_range},
                   ratio_max, "warn", chunks_per_file=chunks_per_file, pages_per_file=pages_per_file)


def check_smoke_retrieval(results: list[dict] | None) -> dict:
    """
    results: [{"question", "expected_file", "top": [(file_name, score), ...]}],
    or None when the collection has no configured questions (not applicable).
    Each expected file must appear in the top k with score >= the minimum.
    """
    if results is None:
        return _result("smoke_retrieval", None, None, config.INGEST_SMOKE_MIN_SCORE, "block",
                       reason="no smoke questions configured for this collection")
    passed_each = [
        any(f == r["expected_file"] and s >= config.INGEST_SMOKE_MIN_SCORE for f, s in r["top"])
        for r in results
    ]
    return _result("smoke_retrieval", all(passed_each), f"{sum(passed_each)}/{len(results)}",
                   config.INGEST_SMOKE_MIN_SCORE, "block",
                   questions=[{**r, "passed": p} for r, p in zip(results, passed_each)])


def content_checks(pdf_pages: list[dict], chunk_texts: list[str], chunk_files: list[str],
                   pages_per_file: dict[str, int]) -> list[dict]:
    """
    The checks that run on parsed content, before anything is embedded.
    pages_per_file: the true page count of each PDF (counted independently of
    the reader that parsed it), and 1 for each non-PDF file. Using true page
    counts means a reader that returns one record per file still fails the
    per-page checks.
    """
    pdf_files = {f for f in pages_per_file if f.lower().endswith(".pdf")}
    n_pdf_pages = sum(pages_per_file[f] for f in pdf_files)
    pages_with_text = sum(
        1 for p in pdf_pages if len(re.sub(r"\s", "", p.get("text") or "")) >= config.INGEST_MIN_CHARS_FOR_TEXT_PAGE
    )
    n_pdf_chunks = sum(1 for f in chunk_files if f in pdf_files)
    return [
        check_pdf_reader(pdf_pages),
        check_raw_pdf_markers(chunk_texts),
        check_bad_char_share(chunk_texts),
        check_chunks_per_page(n_pdf_chunks, n_pdf_pages),
        check_pages_with_text(pages_with_text, n_pdf_pages),
        check_file_coverage(dict(Counter(chunk_files)), pages_per_file),
    ]


def blocking_failures(results: list[dict]) -> list[dict]:
    return [r for r in results if r["passed"] is False and r["action"] == "block"]

"""
Ingestion sanity checks (docs/audit_logging_design.md, section 6).

Feeds the check functions fake data shaped like the 5,540-chunk run (raw PDF
bytes read as text, one unlabelled record per file) and like the good index
(558 clean chunks over 344 labelled pages). Nothing is reproduced: the
original run was not logged, and this tests the checks, not the past.
Also: the gate leaves the live collection untouched when a blocking check
fails, and `--allow-failed-checks` is logged as an override. Offline: no
PDF, no embedding model, no Chroma.
"""

import json

import pytest
from llama_index.core import Document

from src import config
from src.ingestion import checks, ingest
from src.monitoring import audit

PAGES = {"FCA Handbook - PRIN 2A The Consumer Duty.pdf": 62, "fg22-5.pdf": 121, "ps22-9.pdf": 161}
GARBAGE = "%PDF-1.4\n1 0 obj\n<< /Type /Page >>\nstream\nx\x9c\x00\x01\ufffd\ufffd\x03endstream\nendobj\n"
CLEAN = ("Firms must consider all the costs and charges a consumer may pay for the product or service "
         "over time, and be able to demonstrate that the price is reasonable relative to the benefits. ") * 3


def _good():
    pdf_pages, chunk_files = [], []
    for f, n in PAGES.items():
        pdf_pages += [{"file_name": f, "page_label": str(i), "text": CLEAN} for i in range(1, n + 1)]
    per_file = {"FCA Handbook - PRIN 2A The Consumer Duty.pdf": 66, "fg22-5.pdf": 221, "ps22-9.pdf": 271}
    for f, n in per_file.items():
        chunk_files += [f] * n
    return pdf_pages, [CLEAN] * len(chunk_files), chunk_files


def _garbage():
    pdf_pages = [{"file_name": f, "page_label": None, "text": GARBAGE * 200} for f in PAGES]
    chunk_files = [f for f in PAGES for _ in range(5540 // 3 + 1)][:5540]
    return pdf_pages, [GARBAGE] * 5540, chunk_files


def _by_name(results):
    return {r["name"]: r for r in results}


def test_known_good_shape_passes_every_check():
    results = _by_name(checks.content_checks(*_good(), PAGES))
    assert all(r["passed"] for r in results.values()), {k: r["metric"] for k, r in results.items()}
    assert results["chunks_per_page"]["metric"] == pytest.approx(558 / 344, abs=0.001)


def test_a_5540_chunk_garbage_run_fails_and_blocks():
    results = _by_name(checks.content_checks(*_garbage(), PAGES))
    for name in ("pdf_reader_used", "no_raw_pdf_markers", "bad_char_share", "chunks_per_page", "pages_with_text"):
        assert results[name]["passed"] is False, name
        assert results[name]["action"] == "block"
    assert results["chunks_per_page"]["metric"] == pytest.approx(5540 / 344, abs=0.01)
    assert len(checks.blocking_failures(list(results.values()))) == 5


def test_a_pdf_that_opens_but_yields_no_text_fails_pages_with_text():
    pdf_pages, chunks, files = _good()
    for p in pdf_pages:
        if p["file_name"] == "fg22-5.pdf":
            p["text"] = "   "
    r = _by_name(checks.content_checks(pdf_pages, chunks, files, PAGES))["pages_with_text"]
    assert r["passed"] is False and r["metric"] == pytest.approx(223 / 344, abs=0.001)


def test_file_coverage_only_warns():
    pdf_pages, chunks, files = _good()
    files = [f for f in files if f != "ps22-9.pdf"]
    results = checks.content_checks(pdf_pages, chunks[: len(files)], files, PAGES)
    cov = _by_name(results)["file_coverage"]
    assert cov["passed"] is False and cov["action"] == "warn" and cov["metric"]["missing"] == ["ps22-9.pdf"]
    assert "file_coverage" not in [r["name"] for r in checks.blocking_failures(results)]


def test_bad_char_share_counts_replacement_characters():
    assert checks.check_bad_char_share(["ab\ufffd\ufffd"])["passed"] is False
    assert checks.check_bad_char_share(["plain text with a non-breaking\xa0space" * 50])["passed"] is True


def test_smoke_retrieval():
    ok = [{"question": "q", "expected_file": "fg22-5.pdf", "top": [("ps22-9.pdf", 0.7), ("fg22-5.pdf", 0.65)]}]
    low = [{"question": "q", "expected_file": "fg22-5.pdf", "top": [("fg22-5.pdf", 0.59)]}]
    wrong = [{"question": "q", "expected_file": "fg22-5.pdf", "top": [("ps22-9.pdf", 0.9)]}]
    assert checks.check_smoke_retrieval(ok)["passed"] is True
    assert checks.check_smoke_retrieval(low)["passed"] is False
    assert checks.check_smoke_retrieval(wrong)["passed"] is False
    assert checks.check_smoke_retrieval(None)["passed"] is None


def test_thresholds_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "INGEST_CHUNKS_PER_PAGE_MAX", 1.0)
    assert checks.check_chunks_per_page(558, 344)["passed"] is False


def _garbage_documents():
    return [Document(text=GARBAGE * 3000, metadata={"file_name": f}) for f in PAGES]


class _ChromaMustNotBeTouched:
    def __init__(self, *a, **k):
        raise AssertionError("Chroma was opened although a blocking check failed")


def test_build_index_blocks_before_embedding_and_leaves_chroma_untouched(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, "source_files", lambda d: [])
    monkeypatch.setattr(ingest, "load_documents", lambda d: _garbage_documents())
    monkeypatch.setattr(ingest, "true_page_counts", lambda files: dict(PAGES))
    monkeypatch.setattr(ingest.chromadb, "PersistentClient", _ChromaMustNotBeTouched)
    monkeypatch.setattr(ingest, "HuggingFaceEmbedding", _ChromaMustNotBeTouched)
    audit.start_run("unit test")
    with pytest.raises(ingest.IngestionChecksFailed):
        ingest.build_index(tmp_path, "regulatory_corpus")
    audit.end_run("blocked")
    events = [json.loads(line) for p in config.LOG_DIR.rglob("*-*.jsonl") for line in p.read_text(encoding="utf-8").splitlines()]
    failed = {e["data"]["name"] for e in events if e["event"] == "check" and e["data"]["passed"] is False}
    # chunks_per_page depends on how much text the fake documents hold; the
    # 5,540-chunk test above covers it. These fail regardless of length.
    assert {"pdf_reader_used", "no_raw_pdf_markers", "bad_char_share", "pages_with_text"} <= failed


def test_allow_failed_checks_is_logged_as_an_override():
    audit.start_run("unit test", overrides=["allow_failed_checks"])
    failing = [{"name": "chunks_per_page", "passed": False, "action": "block"}]
    ingest._gate(failing, True, "regulatory_corpus", "before embedding")  # does not raise
    with pytest.raises(ingest.IngestionChecksFailed):
        ingest._gate(failing, False, "regulatory_corpus", "before embedding")
    audit.end_run()
    events = [json.loads(line) for p in config.LOG_DIR.rglob("*-*.jsonl") for line in p.read_text(encoding="utf-8").splitlines()]
    [override] = [e for e in events if e["event"] == "override"]
    assert override["level"] == "warn" and override["data"]["failed_blocking_checks"] == ["chunks_per_page"]
    assert events[0]["data"]["overrides"] == ["allow_failed_checks"]


def test_cli_returns_1_and_indexes_the_run_as_blocked(monkeypatch):
    def blocked(*a, **k):
        raise ingest.IngestionChecksFailed("Blocking ingestion checks failed: ['chunks_per_page']")

    monkeypatch.setattr(ingest, "build_index", blocked)
    assert ingest.main([]) == 1
    [idx] = [json.loads(line) for line in (config.LOG_DIR / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert idx["status"] == "blocked" and idx["command"] == "ingest build"

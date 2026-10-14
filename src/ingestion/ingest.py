import argparse
import logging
import time
from collections import Counter
from pathlib import Path

import chromadb
from llama_index.core import Settings, SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from src.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBED_MODEL_NAME,
    INGEST_SMOKE_QUERIES,
    INGEST_SMOKE_TOP_K,
    INTERNAL_POLICY_COLLECTION_NAME,
    INTERNAL_POLICY_CORPUS_DIR,
    REGULATORY_CORPUS_DIR,
)
from src.ingestion import checks
from src.monitoring import audit

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_EXTS = [".pdf", ".txt"]


class IngestionChecksFailed(RuntimeError):
    """A blocking sanity check failed; the live collection was left unchanged."""


def load_documents(corpus_dir: Path):
    if not any(corpus_dir.glob(f"*{ext}") for ext in SUPPORTED_EXTS):
        raise FileNotFoundError(f"No supported documents ({SUPPORTED_EXTS}) found in {corpus_dir}")
    reader = SimpleDirectoryReader(input_dir=str(corpus_dir), required_exts=SUPPORTED_EXTS)
    return reader.load_data()


def source_files(corpus_dir: Path) -> list[Path]:
    return sorted(p for ext in SUPPORTED_EXTS for p in corpus_dir.glob(f"*{ext}"))


def true_page_counts(files: list[Path]) -> dict[str, int]:
    """Page count per PDF read with pypdf, independently of the ingestion reader; 1 per non-PDF file."""
    from pypdf import PdfReader

    counts = {}
    for f in files:
        counts[f.name] = len(PdfReader(str(f)).pages) if f.suffix.lower() == ".pdf" else 1
    return counts


def _log_checks(results: list[dict], collection_name: str) -> None:
    for r in results:
        audit.check("ingestion", r["name"], r["passed"], metric=r["metric"], threshold=r["threshold"],
                    action=r["action"], data={"collection": collection_name, **r["data"]})


def _gate(results: list[dict], allow_failed_checks: bool, collection_name: str, phase: str) -> None:
    failed = checks.blocking_failures(results)
    if not failed:
        return
    names = [r["name"] for r in failed]
    if allow_failed_checks:
        audit.event("ingestion", "override", level="warn", data={
            "phase": phase, "collection": collection_name, "failed_blocking_checks": names,
            "note": "--allow-failed-checks given: continuing despite failed blocking checks"})
        logger.warning("Blocking checks FAILED but --allow-failed-checks was given: %s", names)
        return
    raise IngestionChecksFailed(
        f"Blocking ingestion checks failed ({phase}): {names}. The live collection "
        f"'{collection_name}' was not changed. See the audit log for details."
    )


def smoke_results(index: VectorStoreIndex, collection_name: str) -> list[dict] | None:
    questions = INGEST_SMOKE_QUERIES.get(collection_name)
    if not questions:
        return None
    retriever = index.as_retriever(similarity_top_k=INGEST_SMOKE_TOP_K)
    out = []
    for question, expected in questions:
        nodes = retriever.retrieve(question)
        out.append({"question": question, "expected_file": expected,
                    "top": [(n.metadata.get("file_name"), round(n.score or 0.0, 4)) for n in nodes]})
    return out


def build_index(
    corpus_dir: Path = REGULATORY_CORPUS_DIR,
    collection_name: str = CHROMA_COLLECTION_NAME,
    allow_failed_checks: bool = False,
) -> VectorStoreIndex:
    """
    Parse, check, embed into a staging collection, smoke-test, then swap it in.
    A failed blocking check raises IngestionChecksFailed and leaves the live
    collection untouched, unless allow_failed_checks (logged as an override).
    """
    files = source_files(corpus_dir)
    audit.event("ingestion", "start", data={"corpus_dir": corpus_dir, "collection": collection_name,
                                             "files": [f.name for f in files]})
    t0 = time.time()
    documents = load_documents(corpus_dir)
    pages_per_file = true_page_counts(files)
    docs_per_file = Counter(d.metadata.get("file_name") for d in documents)
    for f in files:
        audit.event("ingestion", "success", data={
            "step": "file_loaded", "file": f.name, "bytes": f.stat().st_size,
            "sha256": _file_sha256(f),
            "true_pages": pages_per_file[f.name], "page_records": docs_per_file.get(f.name, 0)})
    logger.info("Loaded %d source document(s), %d page-document(s)", len(docs_per_file), len(documents))

    splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    nodes = splitter.get_nodes_from_documents(documents)
    pdf_pages = [
        {"file_name": d.metadata.get("file_name"), "page_label": d.metadata.get("page_label"), "text": d.text}
        for d in documents if str(d.metadata.get("file_name", "")).lower().endswith(".pdf")
    ]
    results = checks.content_checks(
        pdf_pages, [n.get_content() for n in nodes], [n.metadata.get("file_name") for n in nodes], pages_per_file)
    _log_checks(results, collection_name)
    _gate(results, allow_failed_checks, collection_name, "before embedding")

    Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    staging_name = f"{collection_name}__staging"
    try:
        client.delete_collection(staging_name)  # leftover from an interrupted run
    except Exception:
        pass
    staging = client.create_collection(staging_name)
    try:
        storage_context = StorageContext.from_defaults(vector_store=ChromaVectorStore(chroma_collection=staging))
        index = VectorStoreIndex(nodes, storage_context=storage_context, show_progress=True)
        smoke = checks.check_smoke_retrieval(smoke_results(index, collection_name))
        _log_checks([smoke], collection_name)
        _gate([smoke], allow_failed_checks, collection_name, "after embedding")
    except Exception:
        client.delete_collection(staging_name)
        raise

    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    staging.modify(name=collection_name)
    live = client.get_collection(collection_name)
    audit.event("ingestion", "success", duration_ms=int((time.time() - t0) * 1000), data={
        "step": "collection_swapped", "collection": collection_name, "chunks": live.count(),
        "persist_dir": CHROMA_PERSIST_DIR})
    logger.info("Indexed %d chunks into Chroma collection '%s' at %s", live.count(), collection_name,
                CHROMA_PERSIST_DIR)
    return index


def _file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_existing(corpus_dir: Path = REGULATORY_CORPUS_DIR,
                   collection_name: str = CHROMA_COLLECTION_NAME) -> list[dict]:
    """
    Read-only: run every check against the live collection's stored chunks.
    Nothing is written to Chroma. Page records are rebuilt from stored chunks
    (one per labelled page; one per unlabelled chunk), so this approximates
    the pre-embedding checks rather than repeating them exactly.
    """
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    got = client.get_collection(collection_name).get(include=["documents", "metadatas"])
    texts, metas = got["documents"], got["metadatas"]
    files = [m.get("file_name") for m in metas]
    pages: dict[tuple, list[str]] = {}
    unlabelled = []
    for t, m in zip(texts, metas):
        if not str(m.get("file_name", "")).lower().endswith(".pdf"):
            continue
        if m.get("page_label") is None:
            unlabelled.append({"file_name": m.get("file_name"), "page_label": None, "text": t})
        else:
            pages.setdefault((m["file_name"], m["page_label"]), []).append(t)
    pdf_pages = [{"file_name": f, "page_label": p, "text": " ".join(ts)} for (f, p), ts in pages.items()] + unlabelled
    results = checks.content_checks(pdf_pages, texts, files, true_page_counts(source_files(corpus_dir)))
    Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    index = VectorStoreIndex.from_vector_store(
        ChromaVectorStore(chroma_collection=client.get_collection(collection_name)))
    results.append(checks.check_smoke_retrieval(smoke_results(index, collection_name)))
    for r in results:
        r["data"]["method"] = "stored_chunks"
    _log_checks(results, collection_name)
    return results


def build_internal_policy_index(allow_failed_checks: bool = False) -> VectorStoreIndex:
    return build_index(
        corpus_dir=INTERNAL_POLICY_CORPUS_DIR,
        collection_name=INTERNAL_POLICY_COLLECTION_NAME,
        allow_failed_checks=allow_failed_checks,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build a Chroma collection, gated by sanity checks.")
    p.add_argument("--internal-policy", action="store_true", help="Build the internal policy collection.")
    p.add_argument("--check-only", action="store_true",
                   help="Run the checks read-only against the existing collection; build nothing.")
    p.add_argument("--allow-failed-checks", action="store_true",
                   help="Swap the collection in even if blocking checks fail (logged as an override).")
    args = p.parse_args(argv)
    corpus_dir = INTERNAL_POLICY_CORPUS_DIR if args.internal_policy else REGULATORY_CORPUS_DIR
    collection = INTERNAL_POLICY_COLLECTION_NAME if args.internal_policy else CHROMA_COLLECTION_NAME
    command = "ingest " + ("check-only" if args.check_only else "build")
    audit.start_run(command, settings={"collection": collection, "corpus_dir": str(corpus_dir)},
                    overrides=["allow_failed_checks"] if args.allow_failed_checks else None)
    try:
        if args.check_only:
            results = check_existing(corpus_dir, collection)
            for r in results:
                print(f"{'PASS' if r['passed'] else ('N/A ' if r['passed'] is None else 'FAIL')}  "
                      f"{r['name']}: {r['metric']} (threshold {r['threshold']}, {r['action']})")
            failed = checks.blocking_failures(results)
            audit.end_run("checks_failed" if failed else "completed")
            return 1 if failed else 0
        build_index(corpus_dir, collection, allow_failed_checks=args.allow_failed_checks)
        audit.end_run("completed")
        return 0
    except IngestionChecksFailed as exc:
        logger.error(str(exc))
        audit.event("ingestion", "error", level="error", data={"error": str(exc)})
        audit.end_run("blocked")
        return 1
    except Exception as exc:
        audit.event("ingestion", "error", level="error", data={"error": repr(exc)})
        audit.end_run("failed")
        raise


if __name__ == "__main__":
    raise SystemExit(main())

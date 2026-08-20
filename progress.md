# Progress Log

Read this file first, every session. Update it last, every session.
Newest entry at the top.

---

## Session 2 — 2026-08-20
**Status:** P1-01 done and tested end-to-end. Regulatory corpus loaded,
chunked, embedded, and indexed in Chroma.

**Done:**
- Corpus sourced (by user, not me — off-limits dir): FCA Handbook PRIN 2A
  (Consumer Duty, 62 pages), FG22/5 Consumer Duty guidance (121 pages),
  PS22/9 Consumer Duty policy statement (161 pages) — 344 pages total,
  all real Consumer Duty regulatory text.
- Built `src/config.py` (shared Chroma path/collection name/embed model
  settings — needed by both ingestion now and retrieval next session, so
  centralizing it now avoids the two disagreeing later) and
  `src/ingestion/ingest.py`: loads PDFs via LlamaIndex `SimpleDirectoryReader`,
  splits with `SentenceSplitter` (chunk_size=512, overlap=50), embeds with
  a local HuggingFace model (`BAAI/bge-small-en-v1.5` — chosen so the
  project stays "local, no external infra" per ARCHITECTURE.md; no OpenAI
  key needed, only ANTHROPIC_API_KEY), and persists into Chroma at
  `./chroma_db`. Rebuilds the collection fresh each run (idempotent).
- Hit and fixed two real bugs along the way, not just "ran without error":
  1. One source PDF (fg22-5.pdf) is AES-encrypted — pypdf needs the
     `cryptography` package installed to open it at all, even read-only.
  2. Bigger one: `SimpleDirectoryReader` silently falls back to reading
     **raw PDF bytes as text** if `llama-index-readers-file` isn't
     installed — no error, no warning that looks fatal, just garbage
     chunks (`'%PDF-1.4\n...'`). First ingestion run "succeeded" (5540
     chunks indexed) but every chunk was binary garbage. Caught by
     actually inspecting sample chunk text, not just checking exit code.
     Installed `llama-index-readers-file`, reran — real text, 558 sane
     chunks.
- Verified end-to-end for real: sample chunks contain actual Consumer
  Duty text (checked manually), all 3 source files represented in the
  558 chunks proportional to page count, and — most importantly — ran
  real semantic retrieval queries ("price and value outcome requirements",
  "how should firms treat vulnerable customers", etc.) against the
  embedded index and confirmed top results are genuinely on-topic with
  correct source attribution and similarity scores 0.65-0.74.
- Wrote this validation up as `tests/test_ingestion.py` (5 tests, all
  passing): source-file coverage, no raw-PDF-byte contamination, and
  parametrized retrieval-relevance checks against known queries.
- Marked P1-01 `passes: true` in feature_list.json.

**Next:**
- P1-02: build the query engine on top of this index — grounded answers
  with cited sources for test questions. `index.as_retriever()` already
  proven to work well (see tests/test_ingestion.py); P1-02 adds the LLM
  synthesis + citation layer on top, in `src/retrieval/`.

**Known issues:**
- None blocking. `chroma_db/` is gitignored (correct — it's a rebuildable
  artifact, not source); anyone picking up this repo needs to run
  `python -m src.ingestion.ingest` once before P1-02's query engine will
  have anything to retrieve from.
- Embedding is CPU-only and takes ~2 min for the current 558-chunk corpus
  on this machine. Fine at this scale; would need a GPU or batching
  strategy if the corpus grows substantially (e.g. full FCA Handbook).

**Notes:**
- Corpus is Consumer-Duty-specific right now (not the full FCA Handbook/PRA
  rulebook). That's fine for demonstrating the pipeline; broadening the
  corpus later is just a matter of dropping more PDFs in
  data/regulatory_corpus/ and rerunning ingestion — no code changes needed.

---

## Session 1 — 2026-08-20
**Status:** P0-01 done and tested end-to-end. `init.sh` now runs cleanly on
Windows (Git Bash).

**Done:**
- Fixed `init.sh`: it assumed a POSIX venv layout (`.venv/bin/activate`),
  which doesn't exist on Windows (`.venv/Scripts/activate`) — added a
  layout check. Also switched `pip install --upgrade pip` to
  `python -m pip install --upgrade pip` (bare `pip.exe` can't overwrite
  itself while running on Windows). venv now created with `py -3.11`
  explicitly rather than whatever `python3` resolves to, since a
  pre-existing .venv had been created against Python 3.14 and newer
  Python versions risk missing wheels for compiled deps (chromadb/
  onnxruntime).
- Found and fixed a real dependency-resolution bug: `ragas` (floor-pinned
  `>=0.1.0`) resolves to 0.4.3, which unconditionally imports
  `langchain_community.chat_models.vertexai` — a module removed from
  `langchain-community` in its 0.4.x line. Pinned `langchain-community<0.4.0`
  in requirements.txt to fix (ragas itself declares no upper bound on it).
- Verified end-to-end: `pip install -r requirements.txt` completes clean,
  all key packages import (anthropic, llama_index.core, chromadb, pydantic,
  streamlit, pypdf, ragas, pandas, pytest), `.env` created from
  `.env.example`, `python -m pytest tests/` runs (0 tests collected — no
  test files exist yet, expected).
- Marked P0-01 `passes: true` in feature_list.json.

**Next:**
- Phase 1 (P1-01): source FCA Handbook / PRA rulebook PDFs into
  `data/regulatory_corpus/` (still empty), then build ingestion —
  chunk/embed/index into Chroma.

**Known issues:**
- None blocking. Note for later: `ragas`/`langchain-community` pin above is
  a workaround for an upstream break, not a real version requirement —
  revisit if ragas ships a fix or drops the langchain_community dependency.

**Notes:**
- Regulatory corpus not yet sourced — need FCA Handbook / PRA rulebook PDFs
  in data/regulatory_corpus/ before Phase 1 can start for real.

---

## Session 0 — [DATE]
**Status:** Repo initialized. Scaffolding created (CLAUDE.md, feature_list.json,
ARCHITECTURE.md, folder structure). No code written yet.

**Done:**
- Repo structure created
- CLAUDE.md, feature_list.json, progress.md, ARCHITECTURE.md committed

**Next:**
- Phase 0 (P0-01): confirm dependencies, get init.sh running cleanly
- Phase 1 (P1-01, P1-02): ingest regulatory corpus, get basic retrieval working

**Known issues:**
- None yet — nothing built.

**Notes:**
- Regulatory corpus not yet sourced — need FCA Handbook / PRA rulebook PDFs
  in data/regulatory_corpus/ before Phase 1 can start for real.

# Progress Log

Read this file first, every session. Update it last, every session.
Newest entry at the top.

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

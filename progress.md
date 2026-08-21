# Progress Log

Read this file first, every session. Update it last, every session.
Newest entry at the top.

---

## Session 4 — 2026-08-20
**Status:** P2-01 done and tested end-to-end. Intake Agent extracts
structured loan-agreement fields via a Pydantic schema.

**Done:**
- Created 3 synthetic UK consumer loan agreements in
  `data/synthetic_docs/` (clearly labeled fictional at the top of each
  file, fictional company numbers/addresses/names throughout), each
  isolating exactly one deliberate issue so later phases can test
  precisely:
  - `loan_agreement_1.txt` (Northfield Consumer Finance / Daniel Osei):
    fee disclosure buried in a "General Provisions" clause, referenced
    only as "administration and arrangement charges... as set out in the
    Lender's standard tariff of charges" — no amount ever stated in the
    agreement. Has a proper vulnerable-customer clause, so this document
    tests *only* the fee-disclosure issue.
  - `loan_agreement_2.txt` (Bridgeport Lending Group / Rebecca Ashworth):
    clear, prominent fee disclosure (£150 arrangement fee, dedicated
    clause), but no vulnerable-customer identification/support process
    at all — just a generic customer-service contact clause. Tests
    *only* the vulnerable-customer gap.
  - `loan_agreement_3.txt` (Thornebury Finance / Marcus Chen): the
    control — clear fee disclosure (£200, dedicated clause) and an
    explicit vulnerable-customer clause (identification, tailored
    support options, staff training, debt-advice signposting). Written
    to the same length/style as the other two, not conspicuously
    "extra good".
  All three otherwise read as normal, professionally-drafted agreements
  (parties, loan details, repayment, interest, early repayment, default,
  data protection, governing law) — the planted issues require reading
  the document, not keyword spotting.
- Built `src/agent/schemas.py` (`LoanAgreementFields`: lender_name,
  borrower_name, loan_amount, apr, term_months, repayment_schedule,
  fees, key_clauses — `fees` and `repayment_schedule` are free text, not
  forced into a numeric field, specifically so the model can faithfully
  report "no amount stated, only referenced via X" instead of being
  forced to invent a number) and `src/agent/intake.py`
  (`IntakeAgent`/`extract_fields`), using the `instructor` library
  (`instructor.from_anthropic`) for schema-validated structured output
  from Claude via tool calling, rather than hand-rolling JSON-schema
  tool-use glue. `instructor` was already present as a transitive dep of
  ragas but is now pinned directly in requirements.txt since we depend
  on it ourselves.
- Tested extraction end-to-end against the real Claude API on all 3
  documents, checked field-by-field against the source text — not just
  "it ran": lender/borrower names, loan amount, APR, term, and repayment
  instalment figures all matched exactly for all 3 docs. Critically,
  extraction correctly preserved the deliberate distinctions rather than
  smoothing them over: doc1's `fees` field describes the vague tariff
  reference with no invented number, doc2/doc3's `fees` fields contain
  their exact stated amounts (£150 / £200), doc2's `key_clauses` contain
  no vulnerable-customer mention (correctly, since none exists in the
  source), and doc1/doc3's do.
- Wrote this up as `tests/test_intake.py` (7 tests, all passing, real API
  calls, auto-skips without ANTHROPIC_API_KEY): per-document core-field
  checks plus two cross-document checks that specifically verify the
  fee-vagueness and vulnerable-customer distinctions survived extraction
  intact.
- Full suite: `python -m pytest tests/` → 16 passed (5 ingestion + 4
  query engine + 7 intake).
- Marked P2-01 `passes: true` in feature_list.json.

**Next:**
- P3-01: single agent loop — receive a document, extract fields (P2-01,
  done), retrieve relevant regulation (P1-02, done), return a first-pass
  answer. This is the first point where intake + retrieval get wired
  together, but still no compliance-check/flagging logic yet — that's
  explicitly P4-01/P4-02, later.

**Known issues:**
- None blocking. Compliance-check comparison (does the extracted fee
  disclosure / vulnerable-customer clause actually violate the Consumer
  Duty) is deliberately NOT built yet — that's Phase 4. The 3 synthetic
  docs are designed for that phase but nothing in P2-01 evaluates them
  against the regulatory corpus.

**Notes:**
- None.

---

## Session 3 — 2026-08-20
**Status:** P1-02 done and tested end-to-end. Query engine returns grounded,
cited answers over the indexed Consumer Duty corpus.

**Done:**
- Built `src/retrieval/query_engine.py`: `QueryEngine.query(question)` runs
  retrieval via the same LlamaIndex/Chroma setup as ingestion (top-5,
  matching embed model), builds a numbered context block from the
  retrieved chunks, and calls the Anthropic SDK directly (not a
  llama-index LLM integration package — after hitting two llama-index
  integration bugs in P1-01, going straight to the Anthropic SDK for the
  reasoning half keeps one fewer layer that can silently misbehave, and
  maps cleanly onto CLAUDE.md's stack description: LlamaIndex for
  RAG/indexing, Anthropic SDK for reasoning). System prompt requires the
  model to answer only from the numbered context, cite chunk numbers
  inline (`[1]`, `[2]`...), and return a fixed refusal string when the
  context doesn't support an answer — no outside knowledge, no guessing.
  Result is a Pydantic `QueryResult` (answer + structured `SourceCitation`
  list: file name, similarity score, excerpt) rather than a bare string,
  so P2+ has a stable shape to build on.
- Model is Claude Sonnet 5 (`ANTHROPIC_MODEL`, configurable via `.env`,
  defaults to `claude-sonnet-5`).
- Tested with real questions end-to-end against the real Claude API
  (not mocked): "What are the four outcomes firms must deliver under the
  Consumer Duty?" → correct 4-outcome answer, cited fg22-5.pdf. "How
  should firms treat vulnerable customers?" → detailed grounded answer
  citing all 3 source docs with proper per-claim inline markers. Off-topic
  control question ("What is the capital of France?") → correctly refused
  with the fixed no-answer message instead of hallucinating, and its
  retrieval similarity scores were visibly lower (0.36-0.39) than the
  on-topic questions (0.65-0.70) — useful signal for P6's confidence work.
- Wrote this up as `tests/test_query_engine.py` (4 tests, all passing,
  real API calls — skipped automatically if ANTHROPIC_API_KEY isn't set,
  so the suite doesn't hard-fail on a machine without a key).
- Full suite: `python -m pytest tests/` → 9 passed (5 ingestion + 4 query
  engine).
- Marked P1-02 `passes: true` in feature_list.json.

**Next:**
- Phase 2 (P2-01): Intake Agent — extract structured fields from an
  uploaded document using a Pydantic schema. This is a different job from
  the query engine (structured extraction from a target document, not
  Q&A over the regulatory corpus) — the query engine built here will
  likely be a tool the later orchestrating agent calls, not something
  P2-01 needs to change.

**Known issues:**
- None blocking. Retrieval `similarity_top_k` is fixed at 5
  (`QUERY_SIMILARITY_TOP_K` in src/config.py) — no evaluation yet of
  whether that's the right k (that's P8-02, recall@k against a labelled
  test set).
- Corpus is still Consumer-Duty-only (see P1-01 note) — query engine
  will just say "not enough information" for anything outside that scope,
  which is correct behavior, not a bug, but worth remembering when
  demoing.

**Notes:**
- User pasted a real ANTHROPIC_API_KEY directly into the chat during this
  session (I'd asked them to add it to .env directly to avoid this).
  Wrote it straight to .env, never echoed it in any command output. Worth
  a gentle reminder next time this comes up, not a big deal.

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

# Banking Compliance & Customer Intelligence Agent

A RAG + MCP + agentic system that reviews banking documents and customer
queries against regulatory guidance (FCA/PRA), flags compliance issues
with a confidence score, and routes uncertain or high-risk cases to human
review.

**Status:** Phase 1 (RAG core — ingestion + query engine) and P2-01
(Intake Agent structured extraction) are built and tested end-to-end. See
`progress.md` for full session-by-session detail and `feature_list.json`
for the complete phase checklist.

## What this demonstrates
- **RAG**: retrieval over a real regulatory corpus (FCA Handbook, PRA
  rulebook), with retrieval quality evaluated (recall@k), not assumed.
- **MCP**: a custom MCP server exposing regulation lookup, mock
  account/transaction lookup, and policy rulebook tools — used because
  these are genuinely separate data domains, not because MCP is trendy.
- **Agentic design**: one orchestrating agent + a deterministic validation
  layer + a human approval gate, not an unjustified multi-agent swarm.
- **Uncertainty handling**: every output carries a confidence score
  grounded in retrieval quality; low-confidence cases are abstained on
  and routed to a human, not guessed at.
- **Evaluation**: labelled test set, faithfulness/hallucination scoring,
  prompt variant comparison.
- **Deployment & monitoring**: Dockerized, deployed, every run logged with
  a dashboard showing failure/flag rates over time.
- **Judgement**: see `ARCHITECTURE.md` for documented trade-offs (why RAG
  over fine-tuning, why MCP over plain function calls, why one agent over
  five) and a business impact model (time saved, false escalation cost).

## What's actually built so far
- **RAG pipeline** over 3 real FCA Consumer Duty documents (344 pages
  total: FCA Handbook PRIN 2A, FG22/5 guidance, PS22/9 policy statement),
  chunked and embedded locally (`BAAI/bge-small-en-v1.5`, no external API
  needed for retrieval) and indexed into Chroma.
- **Grounded, cited query engine** (`src/retrieval/query_engine.py`):
  answers natural-language questions using only the retrieved context,
  cites source chunks inline, and correctly *refuses* to answer
  off-topic questions instead of hallucinating — verified with a
  deliberately off-topic control question, which triggered the fixed
  refusal message and showed visibly lower retrieval similarity scores
  than genuine Consumer Duty questions.
- **Intake Agent** (`src/agent/intake.py`): extracts structured fields
  from loan agreements into a Pydantic schema (`LoanAgreementFields`),
  validated via the `instructor` library's Claude tool-calling
  integration rather than free-form JSON parsing.
- **3 purpose-built synthetic test documents** (`data/synthetic_docs/`):
  one with a buried/vague fee disclosure, one missing a vulnerable-
  customer identification/support process, and one fully compliant
  control — written so that catching the planted issues requires
  actually reading the document against the regulatory corpus, not
  keyword spotting.
- **16 passing automated tests** (`tests/`) covering ingestion, retrieval
  relevance, query engine groundedness, and extraction correctness
  against known source text — including a real bug caught and fixed
  along the way: `SimpleDirectoryReader` was silently reading raw PDF
  bytes as text (not parsing them) because a required dependency wasn't
  installed, producing thousands of "successfully indexed" chunks that
  were actually binary garbage. Caught by inspecting actual chunk
  content, not by trusting a clean exit code.

## What's still to come
- **Phase 3** — single agent loop wiring intake (P2-01) and retrieval
  (P1-02) together into a first-pass answer.
- **Phase 4** — orchestrating Compliance Agent + deterministic validation
  layer: the actual compliance-check logic (comparing extracted document
  fields against retrieved regulation and producing flagged issues).
- **Phase 5** — MCP tools layer: regulation lookup, mock account/
  transaction lookup, and policy rulebook query as separate tools.
- **Phase 6** — confidence scoring grounded in retrieval quality, with
  abstention/human-review routing below a threshold.
- **Phase 7** — human-in-the-loop approval gate for flagged issues.
- **Phase 8** — evaluation harness: labelled test set, recall@k,
  faithfulness/hallucination rate, prompt variant comparison.
- **Phase 9** — monitoring: every run logged, dashboard of failure/flag
  rates and latency.
- **Phase 10** — Dockerization and deployment.
- **Phase 11** — business impact model and final documentation polish.

## Stack
Claude API (Anthropic SDK) · LlamaIndex · ChromaDB · `BAAI/bge-small-en-v1.5`
(local embeddings) · Pydantic + `instructor` (validated structured
extraction) · Streamlit · MCP · Ragas

## Setup
```bash
bash init.sh
# then add your ANTHROPIC_API_KEY to .env (copied from .env.example)

python -m src.ingestion.ingest   # builds the Chroma index from data/regulatory_corpus/
python -m pytest tests/          # runs the full test suite (16 tests)
```
The Streamlit UI (`streamlit run src/app.py`) isn't built yet — that
lands in a later phase (see "What's still to come" above).

## Project structure
See `ARCHITECTURE.md` for the full design and data flow diagram.

## Honest scope note
This is a portfolio project, not a production banking system. Data is
public regulatory text plus synthetic documents/queries — no real
customer data is used anywhere. Where a real deployment would need
additional work (scale, security review, access control depth), that is
noted explicitly rather than implied.

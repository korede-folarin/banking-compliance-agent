# Banking Compliance & Customer Intelligence Agent

Reads a loan agreement, checks it against real UK financial regulation, and
tells you where it falls short — citing exactly which regulatory text it's
relying on, and refusing to guess when it isn't sure.

## Why this needs to exist

Compliance review of consumer credit documents is still mostly manual:
someone reads the agreement, reads the relevant FCA guidance, and judges
whether the two line up. That's slow, and it's inconsistent — two
reviewers can reasonably disagree, and the same reviewer can miss the same
kind of issue twice.

The obvious shortcut — point an LLM at the document and ask "is this
compliant?" — creates a worse problem than it solves. A model that isn't
grounded in the actual regulatory text will confidently answer regardless
of whether it actually knows, and a *confident wrong answer about
regulatory compliance* is a genuinely dangerous failure mode in a
regulated industry, not a quirky bug. The core design problem this project
is about is making the "I don't know" case work as reliably as the "yes,
compliant" case.

## What it does right now

Right now the system does two of the three steps a compliance review
needs, end to end:

1. **It reads the regulation.** The FCA's Consumer Duty corpus (the
   Handbook's PRIN 2A, the FG22/5 guidance, and the PS22/9 policy
   statement — 344 pages) is chunked, embedded, and indexed, and a query
   engine can answer natural-language questions about it with inline
   citations back to the source text.
2. **It reads the loan agreement.** An Intake Agent pulls structured
   fields out of a loan document — lender, borrower, amount, APR, term,
   repayment schedule, fees, and other notable clauses — into a validated
   schema, rather than leaving them as unstructured prose.
3. **It will compare the two.** Actually checking whether what the
   document says is compliant with what the regulation requires — the
   step that turns this from two separate tools into a compliance
   agent — is the next phase, not yet built. See "What's still to come."

## How I know it actually works

Four things happened during development that are better told as what
happened than summarized as a feature list:

**It said "I don't know" instead of making something up.** I asked the
query engine an off-topic control question — "What is the capital of
France?" — against an index that only contains Consumer Duty regulation.
It didn't answer. It returned the fixed refusal message, and the
underlying retrieval similarity scores for that question (0.36–0.39) were
visibly lower than for genuine Consumer Duty questions (0.65–0.70) — a
real, measurable signal, not just a prompt instruction the model happened
to follow that one time.

**It reported a vague fee as vague, not as a number.** One of the three
synthetic test loan agreements deliberately buries its fee disclosure —
it only references "the Lender's standard tariff of charges" in a general
provisions clause, with no amount ever stated anywhere in the document.
Fed to the Intake Agent, it didn't invent a figure to fill the field. It
reported that the fee is referenced but never quantified. The other two
test documents state exact fees (£150, £200) in dedicated clauses, and
those were extracted as exact figures — so the difference in the output
reflects a real difference in the source text, not extraction noise.

**It reported a missing clause as missing, not filled it in.** A second
synthetic test document has no vulnerable-customer identification or
support process at all — just a generic customer-service phone number.
The Intake Agent's extracted clause list for that document contains no
mention of vulnerability, correctly, because there's nothing there to
find. The other two test documents do have explicit vulnerable-customer
provisions, and those were extracted correctly too.

**A "successful" run was actually silently broken.** The first ingestion
run reported success — 5,540 chunks indexed, no errors — but a missing
dependency (`llama-index-readers-file`) meant the PDF reader had silently
fallen back to treating raw PDF bytes as plain text. Every chunk was
binary garbage (`'%PDF-1.4\n...'`), and nothing about the exit code or
the logs said so. It was only caught by opening a few chunks and actually
reading them. Installing the missing dependency and re-running produced
558 real, readable chunks. Nothing after that point trusts a clean exit
code as proof of correctness — checking actual content became a habit for
the rest of the build.

## What this does and doesn't prove

The 16 automated tests behind these results are real — they hit the
actual Claude API and the actual indexed corpus, not mocks — but they
prove correctness on a small set of known, controlled cases: 3 real
regulatory documents and 3 hand-written synthetic loan agreements with
known ground truth. That's enough to catch real bugs (see the PDF-bytes
story above) and to demonstrate the intended behavior clearly. It is
**not** the same as evidence about how well this generalizes to a wider
regulatory corpus or to arbitrary real-world documents. That's a
separate, deliberately deferred piece of work — a labelled test set,
retrieval recall@k, and a measured faithfulness/hallucination rate — and
it's Phase 8, not done yet.

## What's still to come
- **Phase 3** — wire the Intake Agent and the query engine together into
  a single first-pass loop.
- **Phase 4** — the actual compliance-check logic: an orchestrating agent
  that reasons over extracted terms against retrieved regulation and
  produces a flagged-issues list, plus a deterministic (non-LLM)
  validation layer on top of it.
- **Phase 5** — an MCP tools layer (regulation lookup, mock account/
  transaction lookup, policy rulebook query) as separate tools.
- **Phase 6** — confidence scoring grounded in retrieval quality, with
  abstention/human-review routing below a threshold.
- **Phase 7** — a human-in-the-loop approval gate for flagged issues.
- **Phase 8** — the evaluation harness described above.
- **Phase 9** — monitoring: every run logged, a dashboard of failure/flag
  rates and latency.
- **Phase 10** — Dockerization and deployment.
- **Phase 11** — a business impact model and final documentation polish.

## On the architecture doc
`ARCHITECTURE.md` isn't a diagram kept for its own sake — it's where each
non-obvious build decision gets written down at the time it's made,
including what was rejected and why: RAG over fine-tuning, MCP over plain
function calls, one orchestrating agent over a five-agent swarm, a static
API key over cloud identity federation (and specifically why that's the
right call for local development but wouldn't be for a production
deployment). Read it for the reasoning behind the shape of the system,
not just the shape itself.

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

## Honest scope note
This is a portfolio project, not a production banking system. Data is
public regulatory text plus synthetic documents/queries — no real
customer data is used anywhere. Where a real deployment would need
additional work (scale, security review, access control depth), that is
noted explicitly rather than implied.

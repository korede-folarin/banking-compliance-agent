# Banking Compliance & Customer Intelligence Agent

Reads a loan agreement, checks it against real UK financial regulation (the
FCA Consumer Duty), and reports where it falls short, citing the regulatory
text each finding relies on. It routes uncertain or flagged cases to human
review instead of guessing.

## Why this needs to exist

Compliance review of consumer credit documents is still mostly manual:
someone reads the agreement, reads the relevant FCA guidance, and judges
whether the two line up. That's slow, and it's inconsistent: two
reviewers can reasonably disagree, and the same reviewer can miss the same
kind of issue twice.

The obvious shortcut is pointing an LLM at the document and asking "is this
compliant?". That creates a worse problem than it solves. A model that isn't
grounded in the actual regulatory text will answer confidently whether or
not it knows, and a *confident wrong answer about regulatory compliance* is a
dangerous failure mode in a regulated industry. The core design problem here
is making the "I don't know" case work as reliably as the "compliant" case.

## What it does (as built, 2026-10-13)

The evaluated system is a **fixed workflow**. The code calls each step in
order; the model does not choose tools or steps. For one loan agreement:

1. **Extraction.** One structured LLM call extracts the loan terms (lender,
   borrower, amount, APR, term, repayment schedule, fees) plus one field per
   Consumer Duty outcome. A field the document doesn't address is recorded
   as "Not addressed in this document.", never left blank.
2. **Retrieval.** One query per outcome against the indexed FCA corpus:
   - the corpus is PRIN 2A, FG22/5 and PS22/9: 344 pages, 558 chunks;
   - embeddings are local (`BAAI/bge-small-en-v1.5`), stored in Chroma;
   - top 5 chunks per query.
3. **Judgment.** One structured LLM call per outcome. It sees the full
   document, its extracted field and the 5 retrieved chunks, and returns:
   - a status: compliant, potentially non-compliant, or insufficient
     evidence;
   - reasoning;
   - the excerpts it cites;
   - claims with verbatim quotes.
4. **Deterministic validation (no LLM).**
   - **Confidence** is the minimum retrieval similarity of the cited
     excerpts, never the model's own self-report.
   - **Below 0.65,** the status becomes `insufficient_evidence`.
   - **Any non-compliant or insufficient outcome** sets
     `needs_human_review`.

Entry points: `python -m src.agent.compliance <document>` for one
document, and `python -m src.evaluation.run_eval main` for the evaluation
pass.

**MCP is built, but not on the evaluated path.** `src/mcp_server/` is a
real MCP server with three tools, called over stdio:
- regulation lookup;
- mock account lookup;
- internal policy query.

One added method (`ComplianceAgent.judge_price_and_value_with_mcp_context`)
calls all three, and only tests call that method. In it, **the code chooses
which tools to call and with what arguments**, and the model only reads the
results. It is not agentic tool use. An agentic version, where the model
chooses its tools inside a bounded loop, is designed in
`docs/agent_tool_use_design.md` and is the next build.

## Results (full pass, 15 documents × 3 runs)

**Judge accuracy** (judge verdict, before the confidence override;
positive = non-compliant):

| Outcome | Accuracy | False positives | False negatives | Abstained |
|---|---|---|---|---|
| Price and value | 0.978 | 1 | 0 | 0 |
| Consumer support | 0.933 | 3 | 0 | 0 |
| Products and services | 1.000 | 0 | 0 | 0 |
| Consumer understanding | 0.907 | 4 | 0 | 2 |

**The confidence score does not separate right from wrong verdicts in this
pass.** The mean confidence of correct and incorrect verdicts differs by at
most 0.0123 per outcome. At the 0.65 threshold, half the correct verdicts are
overridden to `insufficient_evidence`, and 62.5% of the incorrect ones are
caught. Those caught cases are routed to review, which is the safety
property; the threshold is not a correctness detector.

**Run-to-run agreement.** In 52 of 60 document-outcome pairs, all 3 runs
gave the same verdict, and none of those verdicts was wrong. All 8 wrong
verdicts, and both abstentions, are in the 8 pairs where the runs
disagreed. On these 15 synthetic documents, disagreement between runs
marked every error. See `docs/eval_agreement_eval_raw_main_pass_v2.md`.

**Could any category skip human review? Not on this evidence.** No
outcome qualifies for auto-approval at a 1%, 2% or 5% missed-issue
target, under any gate:
- one run above 0.65;
- all 3 runs compliant;
- both of those together.

No missed issue was seen. But with at most 13 approved documents per
outcome, the 95% upper bound stays at 20.6% or more. Showing 5% with zero
misses would take 59 approved documents, and showing 1% would take 299.
Auto-approval therefore stays off. See
`docs/eval_calibration_eval_raw_main_pass_v2.md`.

**Claim checks.** Every regulatory claim was checked twice:
- **Quote location (deterministic).** 540 of 542 cited quotes were found
  in the excerpt they named.
  - **The splice rule:** 27 of those are "..."-spliced quotes. They count
    as found when every part appears in the excerpt in the quote's order
    (rule B, 2026-10-20). The agent's validator uses the same rule.
  - **Under the earlier strict rule** the count was 513:
    `docs/eval_raw_main_pass_v2_claim_judgments_checks_rule_b_report.md`
    against the original report.
- **A narrow LLM check, run per claim.** It returned yes for 484 of 536
  claims, partially for 52, and no for none.

Full detail is in `docs/eval_raw_main_pass_v2_summary.json` and
`docs/eval_raw_main_pass_v2_claim_judgments_checks_report.md`.

## Agentic tool loop: live results (2026-10-24)

The model chooses its own MCP tools inside a bounded loop. A
deterministic layer checks every call and every quote. It was run live on
19 new documents × 3 runs, and on the 15 baseline documents × 1 run, for
about $9. The full results are in `docs/eval_results_v2.md`.

**Tool calling.**
- **Required calls:** every required call was made (regulation, account
  and policy), with the right customer number every time.
- **Unnecessary calls:** 10, all on two documents from other lenders. The
  model looked up an account or a policy that didn't apply, and the
  validation layer flagged all 10.

**Escalation.**
- **50 of 57 decisions correct.** All 7 errors were on held-out documents
  whose right answer was "cannot determine".
- **In 6 of the 7, the agent said "no escalation" instead.**

**Compliance verdicts vs the baseline,** on the same 15 documents:
- **Consumer understanding is worse:** 0.533 accuracy against 0.907, and
  **2 missed breaches**, where the baseline had none.
- **On the new set,** all 4 of the agent's missed breaches are also in
  consumer understanding.
- **Price and value and consumer support:** no errors, but more
  abstentions.
- **This does not replace the baseline.**

**Its errors repeat.** 12 of the agent's 13 wrong verdicts were the same in
every run, so disagreement between runs, which caught every baseline
error, does not catch the agent's.

**Since then, code decides first.** These rules were added after the live
run, and are tested offline:
- **A document that isn't a credit agreement** gets no model call.
- **Another lender's agreement** is offered only the regulation search.
- **The cases that can't be decided are set to "cannot determine" by
  rule:** no lender named, no customer number, no account record, or an
  account in another person's name. Each goes to a reviewer.

These rules prevent all 10 unnecessary calls and all 7 escalation errors
seen in the live run. They were written after seeing those held-out
failures, so they have not yet been tested on unseen documents.

## What went wrong during the build, and what changed

**A "successful" ingestion run was silently broken.** The first ingestion
reported 5,540 chunks and no error. A missing dependency
(`llama-index-readers-file`) had made the PDF reader fall back to reading
raw PDF bytes as text, so every chunk was binary garbage (`'%PDF-1.4\n...'`).
- **How it was found:** by opening sample chunks and reading them.
- **The records:** that run was not logged. The only records are the
  session note in `progress.md` and commit `cb3a7dd`.
- **The second bug, found at the same time:** one PDF (FG22/5) is
  encrypted and needed the `cryptography` package to open at all.
- **The fix:** both dependencies installed, and a re-run produced 558 real
  chunks.
- **The guard since 2026-10-13:** ingestion runs content checks before
  embedding (PDF reader used, no raw-PDF markers, bad characters, chunks
  per page, pages with text) and a retrieval smoke test, and replaces the
  live index only if they pass.

**Parallel tool calls broke structured output.** Two runs failed with HTTP
400s because the model returned several tool calls at once. Structured
calls now force a single tool call (`disable_parallel_tool_use`), and there
have been no failures since.

**Known limitation, not fixed:** in the full pass, 49 judge calls came back
with their arguments wrapped in a literal placeholder key
(`$PARAMETER_NAME`, `$PARAMETER_VALUE`). All recovered on an automatic
retry. The details are in ARCHITECTURE.md.

## What this does and doesn't prove

**The test suite has 289 tests.** 249 run offline. 40 are live tests that
call the Claude API and are skipped without a key.

The evaluation covers 15 synthetic loan agreements with planted, known
defects, against a Consumer-Duty-only corpus. That catches real bugs and
measures the pipeline on controlled cases. It is **not** evidence about
arbitrary real-world agreements or a wider regulatory corpus.
- **No CONC:** the consumer credit sourcebook, which holds the
  affordability and arrears rules, is not indexed.
- **No affordability judgment:** the project doesn't attempt one.

## Human review (P7-01)

`streamlit run src/app.py` opens the review queue. Auto-approval is off,
so every case is in it: baseline results now, and the agent's once they
have run. For each item (the four outcomes, plus escalation for agent
cases), the reviewer sees:
- the system's verdict, confidence and the reasons it was flagged;
- each claim with its quote and the full passage it came from.

The reviewer then **confirms** the verdict or **overrides** it. An
override needs a written reason. A case can be marked resolved only when
every item has an explicit decision and a reviewer is named. Decisions
are append-only (`./reviews/`, gitignored) and logged to the audit log.
The rules are enforced in `src/review/store.py`, not just on screen.

## Not built yet

- **Monitoring dashboard (P9-02).** Audit logging (P9-01) is built and
  tested offline, but not yet verified on a live run.
- **Deployment and business framing:** Docker and deployment (P10); the
  business impact model (P11).

## On the architecture doc

`ARCHITECTURE.md` records each non-obvious decision when it was made,
including what was rejected and why:
- RAG over fine-tuning;
- one workflow plus a deterministic validation layer, over a multi-agent
  swarm;
- MCP for separate data domains;
- a static API key over cloud identity federation, for local development.

Its "As built" section describes the system as the code runs it.

## Stack

Claude API (Anthropic SDK) · `instructor` + Pydantic (validated structured
output) · LlamaIndex · ChromaDB · `BAAI/bge-small-en-v1.5` (local
embeddings) · MCP (`mcp` 1.29.0, side path).

## Setup

```bash
bash init.sh
```

Then add your `ANTHROPIC_API_KEY` to `.env`, copied from `.env.example`.

```bash
python -m src.ingestion.ingest
```

This builds the Chroma index, gated by the sanity checks. Add
`--check-only` to check the existing index without rebuilding it.

```bash
python -m pytest tests/
```

The live tests run only when an API key is set.

## Honest scope note

This is a portfolio project, not a production banking system. Data is
public regulatory text plus synthetic documents and accounts; no real
customer data is used anywhere. Where a real deployment would need more
(scale, security review, access control), that is stated rather than
implied.

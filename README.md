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

## What it does (as built, 2026-10-24)

There are two paths, and both end in a human review queue.

1. **A fixed workflow produces the compliance verdicts.** It is the
   baseline, and it was evaluated first.
2. **An agentic loop decides vulnerable-customer escalation.** The model
   chooses its own tools over MCP.

**Code runs before both.** A deterministic gate decides everything it can
from the document itself (see "Agentic tool loop" below and
`docs/architecture/`).

**The fixed workflow.** The code calls each step in order; the model does
not choose tools or steps. For one loan agreement:

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

**The agentic loop** (`src/agent/tool_agent.py`) gives Claude three MCP
tools over stdio (`src/mcp_server/agent_server.py`):
- regulation search, one per outcome;
- the customer's account;
- Northbridge's internal escalation policy.

The model chooses which to call and with what arguments, within 8 calls
and 6 turns. It then submits an assessment that cites numbered evidence. A
deterministic layer checks every call, quote, citation and trigger against
the account data. The agent also gives its own four outcome verdicts,
which is how it was compared with the fixed workflow on the same
documents.

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

## Diagrams

- `docs/architecture/system_flow.md`: how a document flows through the
  code gate, the fixed workflow and the agentic loop, into review and the
  audit log.
- `docs/architecture/escalation_gate.md`: which escalation cases code
  decides, and which the model decides.

## Business case

`docs/business_model.md` covers three scenarios. With auto-approval off,
the value is **reviewer time saved per agreement**, net of time lost to
false alarms.

**The numbers:**
- **Net saving:** 1.3, 8.7 or 20.7 minutes per agreement.
- **Model cost:** about $0.11 per run.

**Where the inputs come from:**
- **Measured:** false alarms (8 in 45 baseline runs) and model cost.
- **Sourced:** salaries.
- **Assumed:** review time and the share of it saved, because no public
  benchmark exists. The conservative case shows no business case. The
  document ends with the pilot that would measure the real number.

## Monitoring and Docker

**Dashboard.** `streamlit run src/app.py`, then open **Dashboard** in the
sidebar. It has two tabs, for two audiences.

**Compliance overview,** in plain language:
- how many agreements were reviewed;
- how many have a possible breach, and how many a person must look at
  closely;
- what was found under each Consumer Duty outcome;
- how reliable the system was on the test agreements: real problems
  caught, missed and false alarms;
- vulnerable customers to escalate;
- what reviewers decided.

It can switch between the AI agent and the fixed workflow, and is built
from the saved results, so it also works in the hosted demo.

**System health,** for the technical team: failure rate, flagged rate,
latency and cost per day, from the audit log. Where no log exists, it
reads a committed summary of it (`docs/monitoring_snapshot.json`, refreshed
with `dashboard.write_snapshot()`).

**Docker.** The image serves the review app and dashboard, and needs no API
key:

```bash
docker build -t compliance-review .
```

```bash
docker run --rm -p 127.0.0.1:8510:8501 -v "${PWD}/reviews:/app/reviews" -v "${PWD}/logs:/app/logs" compliance-review
```

## Decisions and trade-offs

Each row is a choice made during the build, what was rejected, and the
evidence behind it. The decisions are recorded as they were made in
`ARCHITECTURE.md`.

| Decision | Chosen | Rejected | Why, and what the evidence showed |
|---|---|---|---|
| Grounding | RAG over the FCA texts | Fine-tuning | Every finding must cite text a reviewer can check, and regulation changes. 540 of 542 cited quotes were found in the passage they named. |
| Who decides the steps | Fixed workflow for the verdicts; agentic loop only for escalation; code before both | One agent choosing everything | Live, the agent called every required tool, but was worse than the fixed workflow on one outcome (0.533 vs 0.907). The agent's 7 escalation errors and 10 wasted calls were all decidable by code, so code now decides them. |
| Number of agents | One, plus a deterministic validation layer | A multi-agent swarm | No boundary needed separate agents. The checks that matter (quotes, citations, account facts) are plain code, which is cheaper and auditable. |
| Tools | MCP server: regulation, accounts, policy | Plain function calls | Three separate data domains with different owners. The agent discovers them through `list_tools` and calls them over stdio. |
| Confidence | Retrieval similarity, reported only | The model's own confidence; a 0.65 cut-off that replaces verdicts | Mean confidence of right and wrong verdicts differed by at most 0.0123. The cut-off acted as an on/off switch by category, so it no longer replaces any verdict. |
| Skipping review | Auto-approval off: every case goes to a person | Auto-approve "easy" categories | Zero misses on at most 13 approvals still bounds the miss rate at 20.6% (95%). A 5% claim would need 59 approved documents. |
| Ambiguous cases | `cannot_determine` is set by rule and always reviewed | Let the model decide | Live, in 6 of 7 such cases the model said "no escalation", which is the risky direction. |
| Quote checking | Exact, normalised, fuzzy, or "..."-spliced with every part 3+ words and in order | Exact only; or parts in any order | Exact matching wrongly rejected 27 real quotes. Requiring order keeps the reviewer's reading intact. |
| Spending | A hard `--max-usd` cap on every paid command | Trust the estimate | The full live evaluation ran under a $12 cap and cost about $9. |
| Vector store | Chroma, local | A managed vector database | No infrastructure for a 558-chunk corpus. It would need revisiting at production scale. |
| API key | A static key in `.env`, never committed | Cloud identity federation | Local development has no cloud identity to federate. A production deployment would use short-lived tokens. |

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

**The test suite has 294 tests.** 254 run offline. 40 are live tests that
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
so every case is in it: 117 cases (45 baseline, and 72 from the agent's
live runs). For each item (the four outcomes, plus escalation for agent
cases), the reviewer sees:
- the system's verdict, confidence and the reasons it was flagged;
- each claim with its quote and the full passage it came from.

The reviewer then **confirms** the verdict or **overrides** it. An
override needs a written reason. A case can be marked resolved only when
every item has an explicit decision and a reviewer is named. Decisions
are append-only (`./reviews/`, gitignored) and logged to the audit log.
The rules are enforced in `src/review/store.py`, not just on screen.

## If a bank ran this: what it would add

The review screen shows the right core loop for a regulated setting:
- every case reaches a person;
- each verdict comes with its quotes and the full regulation text;
- an override needs a reason;
- nothing resolves until every item is decided;
- every decision is in an append-only log.

It is still a reviewer workbench prototype. A bank's version would add the
following, roughly in order of importance.

| Gap today | What a bank needs |
|---|---|
| The reviewer name is free text | Single sign-on identity (e.g. Entra ID or Okta): the name comes from the login and cannot be typed |
| One person decides and resolves | **Four-eyes (maker-checker):** a second reviewer approves every override and every resolution of a flagged case |
| No roles | Role-based access: reviewer, approver, read-only auditor; and segregation of duties |
| Override reasons are free text | Standard reason codes plus free text, so overrides can be counted and fed back to model monitoring |
| A flat queue | Assignment, priority (escalations first), case age and SLA timers, and a backlog view |
| A local append-only file | A tamper-evident store (write-once storage or a hash-chained database), retention set to the firm's record-keeping policy, and export for audits and the regulator |
| Synthetic data | Real customer data: masking of personal data on screen, a log of who viewed which case, and data-protection controls |
| Technical dashboard only | Management information: override rate per outcome (a model-quality signal), reviewer agreement, SLA breaches, and volume |
| Model details only in the logs | Model risk governance: model, prompt and corpus version shown on every case and frozen for each release, with change control |
| Runs on a laptop | Hosted inside the bank's network, not publicly reachable, with high availability and alerting |

None of these change how the model works. They are the controls a bank
puts around any decision tool.

## Open items

- **P8-04, prompt variants:** a scored comparison of two prompt versions
  for price and value. It needs a small paid run.
- **P10-02, public demo:** ready to deploy to Streamlit Community Cloud
  (`src/requirements.txt` holds the light dependencies; set
  `DEMO_MODE=1`). It needs the owner's account.

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
embeddings) · MCP (`mcp` 1.29.0, the agentic loop's tools) · Streamlit
(review screen and dashboard) · Docker.

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

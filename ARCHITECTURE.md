# Architecture — Banking Compliance & Customer Intelligence Agent

## Purpose
A RAG + MCP + agentic system that reviews banking documents (loan
agreements, compliance queries) against regulatory guidance (FCA/PRA),
flags issues with a confidence score, and routes uncertain or high-risk
cases to human review. Built to demonstrate: RAG, agentic workflows,
MCP/tool design, evaluation, deployment, monitoring, and — critically —
judgement (documented trade-offs, uncertainty handling, business framing).

## Data flow

```
COMPANY DATA
  -> FCA/PRA regulatory corpus + synthetic customer queries/complaints
  -> indexed via RAG (LlamaIndex + Chroma)

CUSTOMER/BUSINESS QUESTION
  -> e.g. "Is this loan clause compliant?"
  -> natural language in

MCP LAYER
  -> custom MCP server exposing: regulation lookup, mock account/
     transaction lookup, policy rulebook query
  -> justification: these are three genuinely separate data domains that,
     in a real bank, would be owned by different teams/systems with
     different access controls. MCP standardizes access across that
     boundary. If this project only ever needed one tool, plain function
     calling would be used instead — MCP is not used for its own sake.

AGENT (single orchestrator, not a swarm)
  -> Compliance Agent: intake, retrieval via MCP tools, reasoning
  -> Deterministic validation layer: rule-based checks + confidence
     scoring (not another LLM call — this is intentional, see trade-offs)
  -> Human approval gate for flagged/low-confidence cases

EVALUATION
  -> labelled test set, retrieval recall@k, faithfulness/hallucination
     rate, task success rate, prompt variant comparison

DEPLOYMENT
  -> Dockerized, deployed to Render, live demo link

MONITORING
  -> every run logged (query, tools called, output, confidence, flag
     status), dashboard shows failure rate / flagged rate / latency
```

## Agent design decision
Originally scoped as 5 separate agents (Intake, Retrieval, Compliance,
Self-Check, Report). Collapsed to **one orchestrating agent + a
deterministic validation layer** after review — multiple LLM agents for
this task added cost and latency without a clear boundary justification.
If a genuine reason emerges during build (e.g. retrieval needs different
context/tool access than reasoning), split deliberately and document why
here, in this file, at the time it happens.

## Uncertainty handling (required, not optional)
- Every extraction and every compliance check returns a confidence score.
- Confidence is grounded in retrieval quality (e.g. vector similarity score
  of the best-matching regulation), not the model's self-reported
  confidence alone.
- Below an explicit threshold, the agent does not answer — it abstains and
  routes to human review with a stated reason ("insufficient regulatory
  match", "conflicting clauses found").
- UI must show: confidence %, evidence used, auto-resolved vs escalated tag.

## Compliance-check field provenance
`LoanAgreementFields` (src/agent/schemas.py) has four fields that map 1:1
onto the Consumer Duty's four outcomes — `vulnerable_customer_provision`
(Consumer Support), `fair_value_justification` (Price and Value),
`target_market_suitability_statement` (Products and Services), and
`key_terms_summary_provision` (Consumer Understanding). These were not
chosen from general knowledge of what a loan agreement "should" contain,
and arriving at them was a two-step process, not a single pass.

**Step 1 — validation of a candidate list.** Starting from a plausible
example list, each candidate was checked against the actual indexed
corpus (via `src/retrieval/query_engine.py`): does querying for it return
a detailed, specific, citable answer, or a thin/refused one? Four
categories came back detailed and well-grounded (similarity scores
~0.65-0.74). Two — cooling-off/cancellation rights, and detailed
complaints-handling procedure — were dropped: cancellation is only ever
mentioned in passing as a complaints metric, and complaints/arrears
content only cross-references DISP/CONC rulebook rules that aren't part
of this corpus.

**Step 2 — open-ended discovery, run separately** to check for
categories that were never on the candidate list in the first place (a
validation pass can only confirm or reject what it's told to look for).
Five broad, open-ended queries were run — "what does this corpus cover
beyond X, Y, Z", "what's the overall topic breakdown", "what credit-
specific obligations exist beyond what's already covered" — followed by
2 targeted confirmation queries on the most promising lead the discovery
pass surfaced. The most concrete-looking candidate was a duty-wide
"avoid foreseeable harm" principle, illustrated in the corpus with a
credit-specific example (escalating balances / token payments in the
second-charge lending market). It didn't survive a direct, precisely-
worded confirmation query — the query engine returned "does not contain
enough information" rather than a confident, cited answer, despite
retrieving topically adjacent chunks (0.63-0.65 similarity). That's the
same refusal behavior the query engine uses elsewhere when it isn't
grounded (see README's "how I know it actually works"), and here it's
the evidence that this candidate was a narrow illustrative aside within
the Price and Value discussion, not a standalone, well-established
obligation. Separately, "foreseeable harm" as a general principle *is*
well-grounded (a direct query about it, not tied to arrears
specifically, returned a long, confident, well-cited answer) — but it's
a cross-cutting lens that touches product design, withdrawal, ongoing
support, and behavioural bias all at once, not something with a single
bounded clause type a document would have or lack. Assessing it means
judging the whole document holistically against a principle, which is
compliance *reasoning* — explicitly Phase 4's job, not something an
extraction field can check. The remaining discovery candidates
(distribution-chain information sharing, communication timing/testing,
"acting in good faith") were either firm-internal processes that
wouldn't appear in a customer-facing contract, or restatements of the
four fields already covered from a different angle.

**Result: no new field was added.** That's a genuine finding, not a
shortcut — the four categories represent this corpus's substantive,
loan-agreement-relevant, checkable coverage, and that claim is now
backed by both validating a candidate list *and* an open-ended search
for what wasn't on it, not validation alone. "Foreseeable harm" is worth
carrying forward as a reasoning lens for Phase 4's orchestrating
Compliance Agent, even though it isn't a Phase 2/3 extraction field.

Each of these fields is required (not optional) and typed `str | None`
specifically so the model cannot silently drop a field it has nothing to
report for — the Intake Agent is instructed to write the literal string
"Not addressed in this document." rather than omit the key or return
null, so absence is always an explicit, visible statement rather than a
gap that looks like a bug.

**Residual risk:** this is a checklist grounded in one particular
regulatory corpus, not a general-purpose compliance detector. It reduces
but does not eliminate the risk of missing a genuinely novel clause type
that falls outside these four categories, or outside what this
Consumer-Duty-only corpus happens to cover (e.g. it would currently say
nothing useful about a PRA prudential requirement, or about a consumer
credit issue the Consumer Duty corpus doesn't substantively address, the
same way it doesn't for cancellation rights). Closing that gap over time
is what the Phase 8 evaluation set is for — a labelled test set is the
right tool for surfacing categories the schema is currently blind to,
not something a fixed field list can guarantee on its own.

## Decision trade-offs (fill in as built — this is the judgement section)
| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| RAG vs fine-tuning | RAG | Fine-tuning | Auditability — traceable sources required for compliance; cheaper to update as regulation changes |
| MCP vs plain function calling | MCP | Plain functions | Three genuinely separate tool/data domains with different real-world ownership |
| Single orchestrating agent vs multi-agent | Single + validation layer | 5-agent swarm | Lower cost/latency; no clear boundary justified multiple LLM calls |
| Vector store | Chroma (local) | Managed vector DB | Zero infra cost/setup for a portfolio-scale corpus; document if this wouldn't scale to production volume |
| API authentication | Static API key in `.env` (gitignored) | Identity federation (short-lived tokens via AWS/GCP IAM, Azure, or GitHub Actions OIDC) | Local dev on a personal machine has no cloud/CI platform to federate identity through, so a static key is the correct approach at this stage. A real production deployment on AWS/GCP/Azure would eliminate the static key entirely — the cloud provider issues short-lived tokens automatically, nothing to store or rotate manually, and tokens expire in minutes even if exposed. Documented here as the production-hardening step this project intentionally does not implement, given its local-dev scope. |

*(Add rows as new decisions are made during the build.)*

## Business sizing (fill in during Phase 11)
- Estimated manual review time per document today
- Auto-resolve rate under conservative / moderate / optimistic scenarios
- False escalation cost (agent over-flags -> wasted human review time)
- Net estimated time/cost saved per scenario

## Evaluation approach
- Small hand-labelled test set (queries + expected retrieval sources +
  expected flag outcome)
- Metrics: retrieval recall@k, faithfulness (does the answer match cited
  evidence), task success rate, false positive/negative flag rate
- At least 2 prompt variants compared with scores, not just one prompt
  assumed to be correct

## Explicitly out of scope (for this project)
- Multimodal / image-based document verification (KYC photo/ID checks) —
  noted as a future extension, not built here.
- Kafka / PyFlink / Spark / Delta Lake / Databricks — belongs to the
  separate, larger data-engineering platform project, not this one.
- LangGraph — using Claude's own agent loop + MCP directly; revisit only
  if orchestration complexity genuinely requires it.

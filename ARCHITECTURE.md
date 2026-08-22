# Architecture: Banking Compliance & Customer Intelligence Agent

## Purpose
A RAG + MCP + agentic system that reviews banking documents (loan
agreements, compliance queries) against regulatory guidance (FCA/PRA),
flags issues with a confidence score, and routes uncertain or high-risk
cases to human review. Built to demonstrate: RAG, agentic workflows,
MCP/tool design, evaluation, deployment, monitoring, and, critically,
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
     calling would be used instead; MCP is not used for its own sake.

AGENT (single orchestrator, not a swarm)
  -> Compliance Agent: intake, retrieval via MCP tools, reasoning
  -> Deterministic validation layer: rule-based checks + confidence
     scoring (not another LLM call; this is intentional, see trade-offs)
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
deterministic validation layer** after review. Multiple LLM agents for
this task added cost and latency without a clear boundary justification.
If a genuine reason emerges during build (e.g. retrieval needs different
context/tool access than reasoning), split deliberately and document why
here, in this file, at the time it happens.

## Uncertainty handling (required, not optional)
- Every extraction and every compliance check returns a confidence score.
- Confidence is grounded in retrieval quality (e.g. vector similarity score
  of the best-matching regulation), not the model's self-reported
  confidence alone.
- Below an explicit threshold, the agent does not answer; it abstains and
  routes to human review with a stated reason ("insufficient regulatory
  match", "conflicting clauses found").
- UI must show: confidence %, evidence used, auto-resolved vs escalated tag.

## Compliance-check field provenance
`LoanAgreementFields` (`src/agent/schemas.py`) has four fields that map
1:1 onto the Consumer Duty's four outcomes: `vulnerable_customer_provision`
(Consumer Support), `fair_value_justification` (Price and Value),
`target_market_suitability_statement` (Products and Services), and
`key_terms_summary_provision` (Consumer Understanding).

These were not chosen from general knowledge of what a loan agreement
"should" contain. Arriving at them was a two-step process, not a single
pass.

### Step 1: Validate a candidate list
Starting from a plausible example list, each candidate was checked
against the actual indexed corpus (via `src/retrieval/query_engine.py`):
does querying for it return a detailed, specific, citable answer, or a
thin/refused one?

Four categories came back detailed and well-grounded (similarity scores
~0.65-0.74). Two were dropped: cooling-off/cancellation rights, and
detailed complaints-handling procedure. Cancellation is only ever
mentioned in passing as a complaints metric, and complaints/arrears
content only cross-references DISP/CONC rulebook rules that aren't part
of this corpus.

### Step 2: Search for what wasn't on the list
A validation pass can only confirm or reject what it's told to look
for. So a second, open-ended pass was run separately, to check for
categories that were never on the candidate list in the first place.

Five broad, open-ended queries were run: "what does this corpus cover
beyond X, Y, Z", "what's the overall topic breakdown", "what
credit-specific obligations exist beyond what's already covered." These
were followed by 2 targeted confirmation queries on the most promising
lead the discovery pass surfaced.

The most concrete-looking candidate was a duty-wide "avoid foreseeable
harm" principle, illustrated in the corpus with a credit-specific
example (escalating balances / token payments in the second-charge
lending market). It didn't survive a direct, precisely-worded
confirmation query: the query engine returned "does not contain enough
information" rather than a confident, cited answer, despite retrieving
topically adjacent chunks (0.63-0.65 similarity). That's the same
refusal behavior the query engine uses elsewhere when it isn't grounded
(see README's "how I know it actually works"), and here it's the
evidence that this candidate was a narrow illustrative aside within the
Price and Value discussion, not a standalone, well-established
obligation.

Separately, "foreseeable harm" as a general principle *is* well-grounded
(a direct query about it, not tied to arrears specifically, returned a
long, confident, well-cited answer). But it's a cross-cutting lens that
touches product design, withdrawal, ongoing support, and behavioural
bias all at once, not something with a single bounded clause type a
document would have or lack. Assessing it means judging the whole
document holistically against a principle, which is compliance
*reasoning*: explicitly Phase 4's job, not something an extraction field
can check.

The remaining discovery candidates (distribution-chain information
sharing, communication timing/testing, "acting in good faith") were
either firm-internal processes that wouldn't appear in a
customer-facing contract, or restatements of the four fields already
covered from a different angle.

### Result
No new field was added. That's a genuine finding, not a shortcut. The
four categories represent this corpus's substantive,
loan-agreement-relevant, checkable coverage, and that claim is now
backed by both validating a candidate list *and* an open-ended search
for what wasn't on it, not validation alone. "Foreseeable harm" is
worth carrying forward as a reasoning lens for Phase 4's orchestrating
Compliance Agent, even though it isn't a Phase 2/3 extraction field.

Each of these fields is required (not optional) and typed `str | None`,
specifically so the model cannot silently drop a field it has nothing
to report for. The Intake Agent is instructed to write the literal
string "Not addressed in this document." rather than omit the key or
return null, so absence is always an explicit, visible statement rather
than a gap that looks like a bug.

### Residual risk
This is a checklist grounded in one particular regulatory corpus, not a
general-purpose compliance detector. It reduces but does not eliminate
the risk of missing a genuinely novel clause type that falls outside
these four categories, or outside what this Consumer-Duty-only corpus
happens to cover (e.g. it would currently say nothing useful about a
PRA prudential requirement, or about a consumer credit issue the
Consumer Duty corpus doesn't substantively address, the same way it
doesn't for cancellation rights). Closing that gap over time is what
the Phase 8 evaluation set is for. A labelled test set is the right
tool for surfacing categories the schema is currently blind to, not
something a fixed field list can guarantee on its own.

## Confidence threshold vs. LLM judgment
P4-01 (the Compliance Agent, `src/agent/compliance.py`) produces a
per-outcome `status` (`compliant` / `potentially_non_compliant` /
`insufficient_evidence`) from LLM reasoning alone, with no numeric
confidence attached. P4-02 (the deterministic validation layer, same
file) computes confidence separately: the **minimum** retrieval
similarity score among the sources that judgment actually cited, not an
average, and not anything the LLM reports. Minimum was chosen because a
judgment resting on one weakly-matched citation shouldn't count as
well-supported just because its other citations are strong; averaging
would let a weak link hide behind stronger ones. If confidence falls
below `CONFIDENCE_THRESHOLD` (0.65, from `.env`/`src/config.py`), the
outcome's status is overridden to `insufficient_evidence` regardless of
what the LLM concluded, and the original LLM verdict is preserved
alongside it as `llm_status` for auditability.

Testing this against the 3 synthetic documents
(`tests/test_compliance.py`) surfaced a real, honest finding, not a
bug: **the 0.65 threshold has never actually been validated against
evaluation data. It's just the number that shipped in `.env.example`
from the start.** For the control document (`loan_agreement_3.txt`,
written to be compliant on all 4 outcomes), the LLM's own judgment
(`llm_status`) is correctly `compliant` across all 4, proving P4-01's
reasoning works, which is the actual point of having a control. But 2
of those 4 outcomes retrieve sources with similarity just under 0.65
for this document (price_and_value: 0.634; consumer_understanding:
0.614), so P4-02 downgrades them to `insufficient_evidence`, and
`needs_human_review` stays `True` even for a document with zero
non-compliance findings. Switching the aggregation from minimum to
average doesn't change this: both come out below 0.65 either way (0.636
and 0.623 respectively), so this isn't an artifact of which aggregation
was chosen; retrieval similarity for these two outcome/question
framings against this corpus is genuinely below 0.65 for this document,
independent of how the citations are combined.

The same boundary effect shows up on docs 1 and 2 too, not just the
control. There, it's a second, distinct source of variance on top of
retrieval scores being close to 0.65: **which of the 5 retrieved
candidate sources the LLM actually cites in `cited_sources` isn't
perfectly stable between calls**, even though retrieval itself is
deterministic (same query, same embeddings, same corpus). Confidence is
computed from whichever subset gets cited, so a judgment sitting right
at the boundary can flip status between runs purely from that citation
selection, not from any change in retrieval quality. Observed directly:
doc2's `consumer_support` outcome (its one deliberately planted issue)
measured at confidence 0.651 in one run and 0.629 in another,
straddling 0.65 both times. `tests/test_compliance.py` reflects this
honestly: it asserts the stable, semantic signal (`llm_status`, and
`needs_human_review`, which is `True` under either post-threshold
outcome) for docs 1 and 2's primary findings, rather than
hard-asserting the exact post-threshold `status` string for an outcome
known to sit on the boundary.

The same borderline retrieval quality also shows up one layer up, in
the LLM's own `llm_status` judgment (P4-01) itself, not just in P4-02's
threshold. Here the finding is more serious than "occasionally
cautious." Five live samples of the control document's `price_and_value`
judgment, same document, same code, same corpus, produced: `compliant`,
`compliant`, `insufficient_evidence`, **`potentially_non_compliant`**,
`compliant`. That fourth sample isn't cautious hedging: it's a real, if
infrequent (~1 in 5 in this sample), false accusation against a
document written to be genuinely compliant. It traces to the same root
cause as the threshold-boundary effect above (retrieval for this
outcome/corpus combination sits in a genuinely ambiguous 0.61-0.68
range), but manifests one layer earlier: with only borderline-relevant
excerpts to reason from, the model's own verdict becomes unstable, not
just its confidence.

Critically, this instability is not uniform across outcomes.
`consumer_support` and `products_and_services` retrieve consistently
strongly (~0.68-0.71 similarity) across every document tested, and have
never, across every sample collected building this feature, produced a
false `potentially_non_compliant` verdict. `price_and_value` and
`consumer_understanding` consistently retrieve weaker (~0.61-0.68) and
are the only two outcomes where this has been observed.
`tests/test_compliance.py` reflects this precisely rather than
asserting a blanket claim the evidence doesn't support: "never falsely
flags the control" is only asserted for the two consistently
strongly-grounded outcomes, not all four.

What *has* held reliably across every single run, for every document,
regardless of which outcome or how it was judged: `needs_human_review`
is `True` whenever retrieval grounding is weak. The system never
silently auto-approves; it always routes the uncertain case to a human.
That's the safety property CLAUDE.md actually requires ("if confidence
is low, route to human review — do not guess"), and it holds. What
doesn't hold, currently, is the stronger claim that P4-01's reasoning
itself is free of occasional false accusations on weakly-grounded
outcomes. That's a real, open limitation, not a documentation nicety,
and it's a priority candidate for Phase 8: better retrieval (more
candidates, a stronger embedding model, or corpus additions covering
Price and Value / Consumer Understanding more deeply) or
evaluation-driven prompt refinement, not something to paper over by
loosening tests further. Properly tuning `CONFIDENCE_THRESHOLD` against
real evaluation data (recall@k, a labelled test set) is Phase 8's job,
not something to adjust ad hoc now just to make a test pass.

A follow-up diagnostic looked directly at what `price_and_value`
retrieves for the control document, and compared it against
`consumer_support`'s retrieval for the same document, to understand why
the two behave so differently. `consumer_support`'s top-5 chunks were
uniformly on-topic: all from the dedicated Consumer Support chapter, all
speaking directly to the thing being judged. `price_and_value`'s top-5
mixed two genuinely relevant general-principle chunks with three that
pull in specific worked examples for other product types: buy-now-pay-
later default-fee stacking, an SME business-current-account opacity
example, a mortgage escalating-balance harm scenario, and
distributor-chain guidance for multi-party lending. None of those
resemble the plain fixed-rate personal loan under review. The corpus
clearly has real Price and Value content (the two relevant chunks prove
that); the retrieval mechanism just surfaces more topical noise for this
outcome, because that chapter interleaves general rules with detailed,
scenario-specific illustrations more heavily than the Consumer Support
chapter does. That gives Phase 8 a concrete, testable lead rather than
an unexplained false-accusation rate: separating example/illustration
text from general-principle text at chunk boundaries, increasing
`top_k` with reranking to filter out scenario-mismatched examples, or
rewording the question to reduce keyword overlap with the example
paragraphs.

## Decision trade-offs (fill in as built; this is the judgement section)
| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| RAG vs fine-tuning | RAG | Fine-tuning | Auditability: traceable sources required for compliance; cheaper to update as regulation changes |
| MCP vs plain function calling | MCP | Plain functions | Three genuinely separate tool/data domains with different real-world ownership |
| Single orchestrating agent vs multi-agent | Single + validation layer | 5-agent swarm | Lower cost/latency; no clear boundary justified multiple LLM calls |
| Vector store | Chroma (local) | Managed vector DB | Zero infra cost/setup for a portfolio-scale corpus; document if this wouldn't scale to production volume |
| API authentication | Static API key in `.env` (gitignored) | Identity federation (short-lived tokens via AWS/GCP IAM, Azure, or GitHub Actions OIDC) | Local dev on a personal machine has no cloud/CI platform to federate identity through, so a static key is the correct approach at this stage. A real production deployment on AWS/GCP/Azure would eliminate the static key entirely: the cloud provider issues short-lived tokens automatically, nothing to store or rotate manually, and tokens expire in minutes even if exposed. Documented here as the production-hardening step this project intentionally does not implement, given its local-dev scope. |

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
- Multimodal / image-based document verification (KYC photo/ID checks):
  noted as a future extension, not built here.
- Kafka / PyFlink / Spark / Delta Lake / Databricks: belongs to the
  separate, larger data-engineering platform project, not this one.
- LangGraph: using Claude's own agent loop + MCP directly; revisit only
  if orchestration complexity genuinely requires it.

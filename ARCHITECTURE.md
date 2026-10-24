# Architecture: Banking Compliance & Customer Intelligence Agent

## Purpose
A RAG system with a deterministic validation layer that reviews loan
agreements against FCA Consumer Duty guidance, flags issues with a
confidence score grounded in retrieval, and routes uncertain or flagged
cases to human review. An MCP tools layer exists alongside it. Agentic tool
use, where the model chooses MCP tools, is designed and is the next build.
Built to demonstrate RAG, tool and MCP design, evaluation and monitoring,
and, critically, judgement: documented trade-offs, uncertainty handling
and business framing.

## As built (2026-10-13, commit `7f63d32` plus uncommitted Session 27 changes)

The evaluated path is a **fixed workflow**. The code calls each step in
order; the model does not choose tools or steps. Every line below names the
file that does it.

```
loan agreement text
  -> 1. Extraction: src/agent/intake.py extract_fields (1 LLM call, instructor, single forced tool)
  -> 2. Retrieval x4, one per Consumer Duty outcome:
        src/agent/first_pass.py FirstPassAgent.run -> src/retrieval/query_engine.py QueryEngine.query
        (local Chroma "regulatory_corpus", 558 chunks, bge-small-en-v1.5, top 5;
         plus 1 LLM synthesis call per query whose answer the judge does NOT use)
  -> 3. Judgment x4: src/agent/compliance.py ComplianceAgent.evaluate
        (full document + that outcome's field + 5 whole chunks; 1 LLM call each)
  -> 4. Deterministic validation: compliance.build_compliance_report
        (confidence = min similarity of cited chunks; < 0.65 -> insufficient_evidence;
         needs_human_review if any outcome is non-compliant or insufficient)
  -> ComplianceReport
```

- **Entry points:** `python -m src.evaluation.run_eval main` (the
  evaluation pass) and `python -m src.agent.compliance <doc>`.
- **Review screen (P7-01, 2026-10-15):** `streamlit run src/app.py`. See
  "Human review" below.
- **Audit logging:** every stage logs to `LOG_DIR` when a run is started
  (see "Audit logging" below).

**Side paths, not on the evaluated path:**
- **MCP:** the server is `src/mcp_server/server.py` (`lookup_regulation`,
  `lookup_account`, `query_policy`) and the stdio client is
  `src/mcp_server/client.py`. Its only caller is
  `ComplianceAgent.judge_price_and_value_with_mcp_context`, and only tests
  call that. The code chooses all three tools and their arguments; the
  model reads the results and never chooses a tool. See "MCP tools layer"
  below.
- **Extraction confidence:** `src/agent/uncertainty.py` is called by tests
  only.

**Not built:**
- the monitoring dashboard (P9-02);
- Docker and deployment (P10);
- a live run of the agentic tool loop: it is built and tested offline (see "Agentic tool loop");
- CONC, which is deferred.

## Original data-flow plan (August 2026; kept as the plan, not as built)

The block below is the original plan. Where it differs from the code, the
"As built" section above is correct:
- **No customer queries or complaints:** there are no synthetic customer
  queries or complaints. The input is a loan agreement, not a
  natural-language question.
- **MCP isn't on the evaluated path,** and retrieval doesn't go through
  MCP tools.
- **Planned, not built:** deployment and the monitoring dashboard. The
  human approval gate was built later (P7-01, see "Human review").

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

## Uncertainty handling (Phase 6)
The requirement is: every extraction and every compliance check returns
a confidence score, grounded in retrieval/evidence quality rather than
the model's self-report, with an explicit threshold below which the
agent abstains and routes to human review. Before building anything new
for Phase 6, what P4-02 already did was checked against this
requirement honestly, field by field, against `feature_list.json`'s
P6-01/P6-02 wording, rather than assumed satisfied.

**What P4-02 already covered:** compliance judgments. Confidence there
is the minimum retrieval similarity among a judgment's cited sources,
never the LLM's self-report, with a deterministic override to
`insufficient_evidence` below `CONFIDENCE_THRESHOLD` and
`needs_human_review` set accordingly. This part of P6-01/P6-02 was
already done, not re-built.

**What was genuinely missing, and closed:**

1. **Extraction (P2-01) had no confidence signal at all.** A bad
   extraction (a mis-read APR, an invented fee figure) could silently
   feed into a compliance judgment that looked confident but was built
   on shaky input, with nothing anywhere flagging it. Closed by
   `src/agent/uncertainty.py`: `extract_fields_with_confidence()` wraps
   the existing `extract_fields()` (unchanged) and adds a deterministic,
   non-LLM-self-reported grounding check per field. Extraction has no
   retrieval step of its own to derive a score from, so the check is
   deliberately not one-size-fits-all; it's three strategies chosen per
   field type, based on what empirical testing showed actually works:
   - **Numeric fields** (`loan_amount`, `apr`, `term_months`): does the
     value appear as a number in the source document. Binary, exact,
     validated against all 3 synthetic documents' real extracted values.
   - **Name fields** (`lender_name`, `borrower_name`): case-insensitive
     substring match in the source document. Also binary and exact.
   - **Free-text clause fields** (`fees`, `repayment_schedule`, and the
     four Consumer-Duty-outcome fields): embedding similarity between
     the extracted value and the source document's sentence-level
     chunks (same embedding model, `BAAI/bge-small-en-v1.5`, used
     everywhere else in this project), continuous, thresholded against
     `CONFIDENCE_THRESHOLD` like everything else.

   The three-way split exists because a single embedding-similarity
   check across all fields was tried first and empirically failed for
   short fields: correct, real `borrower_name`/`lender_name` values
   scored 0.43-0.51 similarity against document sentences containing
   them, indistinguishable from or *lower than* a deliberately
   fabricated free-text field's score (0.55-0.67) in the same test. A
   short 2-3 word name and a full sentence containing it just don't
   embed as similarly as two comparable sentences do; a uniform
   threshold would have flagged every correct name on every document as
   unreliable. Names and numbers get exact matching instead, which is
   both more appropriate for proper nouns/figures (no paraphrasing
   expected) and empirically reliable (validated against all 9 real
   numeric values across the 3 synthetic documents). The embedding
   approach, once scoped to the fields it actually suits, does
   discriminate well: a deliberately fabricated fee/vulnerability clause
   scored 0.55-0.67 against a correct extraction's 0.80-0.92 on the same
   document.

2. **The query engine's refusal was purely LLM self-report, not
   deterministic.** It computes real similarity scores for every
   retrieved source and had never checked them against anything; the
   decision to say "I don't know" was entirely up to the model following
   a prompt instruction. This directly contradicted the "not the model's
   self-reported confidence alone" requirement above, quietly, since
   P1-02. `QueryResult` now carries `confidence` (minimum similarity
   among sources actually cited inline via `[n]` markers in the answer,
   same "minimum, not average" reasoning as the compliance layer) and
   `needs_human_review`.

   Enforcing this as a hard override, the same way P4-02 enforces it for
   compliance judgments, was implemented and tested, then deliberately
   reverted after empirically causing a real regression: the plainly
   answerable, on-topic question "What is the price and value outcome?"
   (answered by source content literally titled "The price and value
   outcome") got refused, because its cited sources' similarity scores
   (0.55-0.60) sit below `CONFIDENCE_THRESHOLD`. That's the same
   untuned-threshold issue already documented below for compliance,
   showing up somewhere more visible: a previously-reliable,
   general-purpose capability. The signal is exposed, computed the same
   way everywhere, so a caller can act on it; it is deliberately not
   force-enforced on the query engine while the threshold itself remains
   unvalidated. This is a documented, evidence-based scope decision, not
   an oversight, see `tests/test_query_engine.py::
   test_confidence_is_deterministically_computed_from_cited_sources`.

**On "a single, consistent mechanism":** the signal is now computed the
same way (same embedding model or similarity source, same
`CONFIDENCE_THRESHOLD` constant, same `needs_human_review` naming)
across extraction, query engine, and compliance. Whether it's *enforced*
as a hard override differs by design, not oversight: compliance enforces
it (P4-02, already tested and caveated), extraction enforces it (new,
`needs_human_review` reflects a real override-equivalent decision since
there's no existing answer to preserve), and the query engine exposes it
without enforcing it, for the reason above. *(Note, 2026-10-13:
`extract_fields_with_confidence` is called only by tests. The evaluated
path calls `extract_fields` directly, so in the running system extraction
confidence is neither computed nor enforced.)* Full enforcement everywhere
is contingent on Phase 8 actually validating `CONFIDENCE_THRESHOLD`
against real data, not something to force now for the sake of
appearing uniform.

**UI display** ("confidence %, evidence used, auto-resolved vs escalated
tag") is Phase 7's job, not Phase 6's: the data these fields need
(`confidence`, `sources`/`cited_sources`, `needs_human_review`) now
exists in structured form on every relevant result object. The review
screen built in Phase 7 (`streamlit run src/app.py`, see "Human review")
displays the confidence, flags and evidence. It shows no
auto-resolved tag, because auto-approval is disabled.

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
false `potentially_non_compliant` verdict. *(Superseded, 2026-10-13: the
full v2 pass, with 15 documents x 3 runs, has 3 false
`potentially_non_compliant` verdicts on `consumer_support`. Only
`products_and_services` has none. See
`docs/eval_raw_main_pass_v2_summary.json`.)* `price_and_value` and
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

## MCP tools layer (Phase 5)
Before building this, the justification in the Data flow section above
("three genuinely separate data domains... owned by different teams/
systems with different access controls") was re-checked, not assumed.
It still holds, and building the internal policy tool made it concrete
rather than asserted:

- **Regulation lookup** wraps the existing `src/retrieval/query_engine.py`
  against the public FCA corpus. In a real bank this is external,
  published data, likely sourced from a GRC (governance/risk/compliance)
  system.
- **Account lookup** is mock customer account data: status, products,
  payment-history flags and notes. There are no transactions. In a real
  bank this sits in the core banking system, is actual customer PII, and
  is access-controlled per customer, nothing like the other two domains.
- **Policy query** is Northbridge Consumer Lending's internal
  underwriting and escalation policy (`data/internal_policy/`,
  synthetic, distinct from the public FCA corpus). In a real bank this
  is an internal, employee-only knowledge base, owned by Risk/
  Underwriting, not Compliance and not Core Banking.

The concrete proof this isn't just an asserted three-way split: asked
the *identical* fee-disclosure question of both the regulation tool and
the policy tool (`tests/test_mcp_tools.py::
test_policy_and_regulation_tools_give_genuinely_different_answers`).
The public regulation answer stays at the level of a general "fair
value" principle. The internal policy answer is concrete and stricter:
a fee referenced only via a separate "tariff of charges" is a
disclosure defect requiring an Underwriting Manager referral before
approval, full stop, a specific internal rule with no equivalent in the
public FCA text. Two tools returning genuinely different, non-
overlapping information for the same question is what makes "separate
domains" a real design fact, not a diagram label.

**Implementation.** `src/mcp_server/server.py` is a `FastMCP` server
(the `mcp` SDK, pinned to `1.29.0`; its `2.0.0` release restructured the
server/client API in a way not yet documented well enough to build
against reliably) exposing three tools: `lookup_regulation`,
`lookup_account`, `query_policy`. The internal policy tool reuses the
same ingestion (`src/ingestion/ingest.py`) and retrieval
(`src/retrieval/query_engine.py`) code as the regulation tool, both
generalized to take a `corpus_dir`/`collection_name` parameter instead
of being hardcoded to the regulatory corpus, rather than duplicating a
second RAG pipeline for two short internal documents. The mock account
tool (`src/mcp_server/mock_accounts.py`) is a small JSON file
(`data/mock_accounts/accounts.json`), no database, exactly as scoped.
`src/mcp_server/client.py` spawns the server as a subprocess and talks
to it over stdio (the standard MCP transport), so tool calls genuinely
cross a process boundary rather than being direct Python calls dressed
up as MCP.

**Where MCP is actually wired in.** `ComplianceAgent.evaluate()` (P4-01,
already tested end-to-end against all 3 synthetic documents) was left
untouched by Phase 5. It changed later, for its own reason: item #4 gave
the judge the full document text. rewriting its whole four-outcome pipeline to route through
MCP would have meant touching already-passing, already-audited code for
no functional gain. Instead,
`ComplianceAgent.judge_price_and_value_with_mcp_context()` is a new,
additive method demonstrating genuine multi-tool MCP use for one real
scenario: judging the Price and Value outcome enriched with the
borrower's mock account payment history and Northbridge's internal fee-
disclosure standard, alongside the same public-regulation question the
baseline pipeline already asks. Tested (`tests/test_compliance_mcp.py`)
against `loan_agreement_1.txt` (the vague-fee document) and confirmed,
not assumed, that the output differs meaningfully from the baseline:
the enriched judgment cites both a public regulation source and an
internal policy source, and its reasoning references the borrower's
missed-payment history, content the baseline pipeline has no access to
and never mentions. This is deliberately scoped as one real
demonstration of the wiring working, not a claim that every outcome
now routes through MCP.

**What P5-04 does and does not show (note, 2026-10-13).** P5-04 ("Agent
calls all three MCP tools correctly during a real run") is about the
protocol:
- the tools are called through a real MCP client session over stdio, not
  as direct Python calls;
- the run that exercised it is a live test, not the evaluation pass.

**The calls are fixed in code.** `compliance.py` calls all three tools, in
a fixed order, with arguments it builds itself; `list_tools` is never
called; the model sees only the results, pasted into its prompt. So P5-04
is not "the agent uses tools". In standard agentic tool use, the model
sees the tool descriptions and decides which tool to call and with what
arguments. That is designed in `docs/agent_tool_use_design.md` and is not
built.

## Groundedness cross-check (P8-05)
New scope, added after Phase 8's original evaluation plan (recall@k,
per-outcome accuracy/FP/FN, `CONFIDENCE_THRESHOLD` validation — all already
covered above and in `docs/eval_results.md`). This is a second, independent
check on the Compliance Agent's *reasoning text itself*: not "is the
confidence score high enough" (P4-02, already covered), but "does the
reasoning's actual content match what the cited evidence says." Tracked as
`feature_list.json`'s P8-05, not folded into an existing Phase 8 subtask,
because it checks something none of P8-01 through P8-04 check: text-level
faithfulness of the reasoning, not the correctness of the final status
label.

**The inherent tradeoff this is built around.** There is no single
mechanical method that both tolerates legitimate paraphrasing and reliably
catches unsupported overreach, and this project does not claim to have
found one:

- A purely mechanical, embedding-similarity check (reuse of the same local
  model, `BAAI/bge-small-en-v1.5`, used everywhere else in this project) is
  cheap, deterministic, and *tolerant of paraphrasing* — a reasoning
  sentence that restates a source's meaning in different words still scores
  high. But that same tolerance is exactly what makes it unable to catch
  *overreach*: a sentence that takes a source's general principle and
  extends it into a specific, unsupported claim can still embed close to
  that source, because embedding similarity measures topical/semantic
  closeness, not whether a specific factual assertion is actually licensed
  by the text.
- A narrow, per-claim LLM check ("does this specific claim appear, in
  substance, in this source text — yes/no/partially") is better positioned
  to catch that kind of overreach, because it's actually asked to reason
  about entailment for one isolated claim, not just measure similarity. But
  it introduces exactly the failure mode the mechanical signal doesn't
  have: it's an LLM judgment, capable of being miscalibrated, inconsistent
  between claims, or itself too strict/lenient about what counts as
  "supported."

Neither weakness is fixed by using more of the same method (a bigger
embedding model still can't distinguish paraphrase from overreach by
construction; more LLM claim-checks still inherit LLM judgment variance).
That's why this feature compares two *independently-failing* signals
against each other rather than picking one and trusting it:

- **Signal 1 (mechanical)**: maximum cosine similarity between a
  judgment's full reasoning text and any single retrieved source excerpt.
  Documented explicitly, per this design: **high similarity is weak
  positive evidence, not proof of correctness** (the reasoning merely
  resembles something it was shown); **low similarity is a stronger red
  flag** (the reasoning doesn't resemble anything it was shown at all,
  which is harder to explain away as legitimate paraphrasing).
- **Signal 2 (narrow LLM claim-check)**: reasoning is split into
  individual claims by a mechanical, non-LLM step (regex sentence
  splitting — not an LLM extraction call, to keep this step as close to
  mechanical as possible), then each claim gets its own narrow LLM call
  asking only whether that one claim is supported by the source text.
  Deliberately scoped per-claim, not one holistic "is this grounded"
  question, to keep it closer to fact-checking than open-ended quality
  assessment.
- **Comparison, not trust in either alone**: cases where the two signals
  agree (high similarity + all claims supported, or low similarity + a
  flagged claim) are lower priority — two independently-failing methods
  landing on the same answer is modestly reassuring. Cases where they
  **disagree** are the actual output of interest: disagreement between two
  signals with different, uncorrelated failure modes is more informative
  than either signal's own confidence, and gets flagged for human review
  rather than resolved automatically by either signal.

**This is this project's own applied methodology, not a technique drawn
from established literature.** Two sources were reviewed while designing
this (Bandi et al. 2025's survey of agentic-AI evaluation approaches, and
the HAL evaluation-infrastructure paper); neither describes a settled,
validated technique for exactly this problem (cross-checking an LLM
reasoning agent's grounding against retrieved evidence via two
independently-failing signals compared against each other). This is stated
plainly so the method is not overstated as more validated than it is: it's
a reasonable, documented engineering response to a real tradeoff, built and
reasoned about for this specific project, not a peer-reviewed or
industry-standard evaluation protocol.

**Scope and results**: see `docs/eval_groundedness.md` for the actual run
(51 in-scope judgments, 192 Signal-2 claim-check calls, agreement/
disagreement counts and specific disagreement cases) and its own scope
caveat (checked against the full retrieved source set, not a verified
cited-only subset — see "Evaluation notes" below for why).

**Scope rule corrected (Session 24).** P8-05 excluded every
`insufficient_evidence` judgment, on the premise that such judgments cite
nothing. The data contradicts that premise: all 31 Phase 8
`insufficient_evidence` judgments cite sources (9 of them at run 0), and so
did both in the Session 23 pilot. `groundedness.py` now decides scope per
judgment from what it actually cited (`cites_anything`: raw citations, else
resolved citations, else Phase 8's `cited_source_count`). Only judgments
that cite nothing are excluded, and the exclusions are printed.
`--p8-05-scope` restores the original status-based rule, so P8-05's
published 51-judgment scope stays reproducible. Under the new rule the
Phase 8 run-0 scope would be 60.

**Superseded for the full pass: Signal 2 is not re-run (Session 26
decision).** For claim-level faithfulness, the comprehensive 15-document,
3-run pass relies on the structured-claim verifier (P8-06, next section).
Only `groundedness.py plan` is run, which costs nothing and still gives
Signal 1. `groundedness.py run`, P8-05's regex sentence-splitter plus a
per-sentence LLM check, is not re-run at scale. The pilot evidence for this:
- **P8-05's Signal 2 never produced a usable result.** It returned zero
  `clean` judgments on the Phase 8 data (51 judgments) and on the Session
  23 pilot (14). Its "flagged" verdicts are dominated by a category error
  documented in `docs/eval_groundedness.md`: sentences about the loan
  document, or asserting an absence, are checked against regulatory text
  they can never appear in.
- **P8-06 gives a more precise and actionable signal.** Each claim arrives
  already typed (document fact, regulatory requirement, absence) with a
  verbatim quote. The quote is checked mechanically against its named
  excerpt, then an LLM check sees only that excerpt. In the Session 23 and
  25 pilots every `partially` verdict could be traced to a specific claim
  and quote: first to truncation, which was fixed in Session 25, then to
  specific overreach.
- **Signal 2 would also have been the most expensive step.** About 920
  calls at about 2,700 input tokens each (all 5 whole chunks per call),
  for the least precise signal.

`groundedness.py run` still works and can be run on any main-pass file
later if wanted. This is a scope decision for the full pass, not a removal.

## Structured-claim verification (P8-06)
Replaces P8-05's Signal 2 Part A (the regex sentence splitter). P8-05 found
that splitting free-text reasoning into sentences produced claims of mixed
kinds (statements about the loan document, statements about the
regulation, and absence statements) that were then all checked against
regulatory text only. Instead of recovering claim types after the fact,
the judgment now declares them.

**Schema change.** `OutcomeJudgment` (`src/agent/compliance.py`) gains three
fields, appended *after* the existing `status`, `reasoning` and
`cited_sources` so the verdict is generated before the claims are
itemised. The existing prompt text, existing field descriptions and field
order are unchanged. The new descriptions are short and neutral: they say
what to record, not how to decide status.
- `document_facts`: `{claim, verbatim_quote}`, quote copied from the loan
  agreement text the judge was shown.
- `regulatory_requirements`: `{claim, sources: [{excerpt_number,
  verbatim_quote}]}`. One requirement per claim wherever possible; several
  sources only for a synthesis that cannot be split. Short quotes (one
  sentence or clause).
- `absences`: `{claim, kind, explanation}`, `kind` exactly
  `absent_from_document` or `absent_from_retrieved_regulation`.

`max_tokens` for the judgment call was raised from 1024 to 4096 because
the quote fields make the output longer and a truncated tool call fails
schema validation. This is a call parameter, not a prompt or schema change.

**Why verbatim quotes allow non-LLM checking.** A paraphrased claim can
only be compared with its source by a model (or by embedding similarity,
which measures topical closeness, not support). A verbatim quote is a
string: whether it occurs in a given text is a deterministic question.
Asking the generator to attach a quote to each claim turns "does the
evidence say this" into two parts: "is the quoted text really in the named
source" (mechanical: substring and fuzzy matching) and "does the quoted
text support the claim" (still a judgment). The first part, which covers
fabricated or misattributed quotes, needs no LLM.

**Verifier** (`src/evaluation/claim_verification.py`). Every result is
logged; no step is gated on a threshold.
- `document_facts`: normalised substring match of the quote against the
  full loan document text only. Not against the extracted field text the
  judge was shown: that text is a paraphrase, so a quote missing from it
  says nothing about whether the claim is true.
- `regulatory_requirements`, per source: text is normalised (lowercase,
  whitespace collapsed, punctuation stripped, PDF hyphenation and
  apostrophe artefacts undone), then matched as exact, normalised, or
  fuzzy (in-order word match, cutoff 0.9, best score always logged).
  Search order and `quote_location`: the named excerpt as shown to the
  judge (`named_chunk`), the judgment's other retrieved excerpts
  (`other_retrieved_chunk`), the full text of every corpus chunk
  (`corpus_not_retrieved`, with a flag when the chunk was retrieved but
  the quote lies past the excerpt the judge saw: 300 characters for
  Phase 8 rows; the whole chunk since Session 25), else
  `not_found`. Also logged: embedding similarity between the claim and
  each named excerpt (every score plus the minimum, not an average),
  `source_count`, and whether each named excerpt is in `cited_sources`.
  Then every claim, with no gating, gets one narrow LLM check that sees
  only the claim and the text of its named excerpts (no excerpt labels, no
  reasoning) and returns yes / partially / no plus the supporting sentence
  copied from the chunk. A failed quote match does not mark a claim as
  failed; the quote result, similarity scores and LLM verdict are logged
  side by side and their disagreements reported.
- `absences`: `absent_from_document` is checked against the extracted
  field(s) for that outcome (is the field the "Not addressed in this
  document." sentinel), with the nearest document chunk logged for a
  reader. `absent_from_retrieved_regulation` is marked
  `needs_human_review`, not verified.
- Comparison and status are not mechanically checked.

**Signal 1 change.** Signal 1 (reasoning-vs-chunk embedding similarity) is
now computed against the judgment's logged cited chunks only, per chunk,
with minimum and mean reported and no pass/fail threshold
(`src.evaluation.groundedness.compute_signal1_cited`). The P8-05 numbers
in `docs/eval_groundedness.md` predate citation logging and were computed
against the full retrieved set; see that file's correction.

**Limits, stated plainly.**
- The generator chooses the buckets. A claim about the regulation filed
  as a document fact, or an overreaching claim filed as an absence, is
  checked by the wrong method, and nothing here detects the misfiling.
- The excerpt labels are self-reported. The quote search tells us where
  the quote actually is, but the claim-to-excerpt pairing is the
  generator's own.
- Shared model bias remains: the narrow claim check uses the same model
  family as the generator, so shared blind spots are not independent
  errors.
- The new field descriptions are extra context in the tool schema and may
  slightly affect judgments, even though they come after the verdict and
  say nothing about how to decide it. The pilot compares status against
  the cached Phase 8 run-0 status to make any such shift visible, but with
  run-to-run variance already documented, a difference is not proof of
  cause.
- A multi-source claim can pass every quote check and still go beyond its
  sources: each quote can be real while the synthesis across them is not
  supported by any one of them.
- A found quote shows only that the quoted text exists where it was said
  to be. Write-ups should say a claim is "supported by the cited chunk"
  (when the checks agree), never that it is "derived from" it.

**This is this project's own method**, built for this pipeline. It is not
a published or validated evaluation protocol, and is not presented as one.

**Known limitations found in the Session 23 real pilot** (documented, not
changed in code):
- **The judge can quote the extraction instead of the document.** For
  `loan_agreement_12` / consumer_understanding the judge gave the
  `document_facts` quote `"Not addressed in this document."`. That is the
  extractor's sentinel value, which appears in the extracted statement but
  not in the agreement. This happened even though, since item #4, the judge
  sees the full document. The quote check reports it correctly as not
  found in the document. It is a real miss, not a checker error. But a
  reader should know a `document_facts` "not found" can mean "quoted the
  extracted statement", not only "invented a quote". With the extracted
  statement still in the judge's message, this can recur.
- **The `absent_from_document` check is coarse for multi-field outcomes.**
  It labels an absence `extracted_field_marked_not_addressed` if ANY of
  the outcome's extracted fields is the sentinel. Price and Value has two
  (`fees`, `fair_value_justification`). In the pilot, a claim that "no
  specific amount for ... charges is stated" (about `fees`) got that label
  because `fair_value_justification` was the sentinel, while `fees` itself
  was not. The label records a fact about the outcome's fields, not
  confirmation of the specific claimed absence. Read it as "an extracted
  field for this outcome is marked not addressed", nothing more.
- **Resolved 2026-10-20 by rule B (user decisions 2026-10-20 and
  2026-10-24):** a "..."-spliced quote is now matched as `spliced` when it
  meets two conditions (`claim_verification.match_quote`):
  - **every part has at least 3 words;** a shorter part fails the splice,
    because it is too short to show where it came from;
  - **every part is in the text, in the quote's order,** as whole words
    after normalising.
  - The agent's `quote_in` calls the same function, so both systems use
    one rule. Before, the agent allowed parts in any order.
  - `claim_verification rescore` (no API) re-scored the full pass into
    `..._checks_rule_b_results.jsonl` and `..._report.md`. 27 quotes moved
    from `not_found` to `named_chunk/spliced`, nothing else changed, and the
    original files are kept.

  The original note follows.
- **Spliced quotes can read as `not_found`** (found in the Session 25
  re-pilot). The judge sometimes joins two non-adjacent passages of the same
  excerpt with "...". Both parts are verbatim in the chunk, but the joined
  string is not contiguous text. The in-order word match then scores below
  its 0.9 "fuzzy" cut-off (0.87 in the one live case), and the quote is
  labelled `not_found` although nothing was invented. A `not_found` with a
  high best fuzzy score should be read with this in mind. The cut-off was
  not lowered: it would also admit genuinely altered quotes.
- **Placeholder quotes recur.** In the Session 25 re-pilot the judge again
  gave `"Not addressed in this document."` as a `document_facts` quote,
  twice (see the first limitation above).

**Excerpt length: the whole chunk, since Session 25 (pilot finding 2).**
In the Session 23 pilot the judge saw only the first 300 characters of each
retrieved chunk. 18 of 39 regulatory quotes ended exactly at that cut-off,
some mid-word, and the judge's claims went beyond text it never saw. The
claim checker's `partially` verdicts on those were accurate relative to
the visible text. So `query_engine.SOURCE_EXCERPT_CHARS` is now `None`: the
judge, and the claim checker, see each retrieved chunk in full. This
roughly doubles the judge's input (measured on the pilot: about 2,300 to
about 4,600 tokens per call).
- **Comparability.** This is a second change to the judge's input, after
  item #4, so post-Session-25 judgments are not comparable to the Session
  23 pilot's either, let alone Phase 8.
- **Every row records its own length.** Each main-pass, variant and
  ingested row records `source_excerpt_chars` (`null` = whole chunk). Rows
  without it (Phase 8, the Session 23 pilot) were judged with 300
  characters.
- **Replay is pinned.** Every retrieval replay of a recorded row
  (`groundedness.reconstruct_sources`, `claim_verification.replay_sources`
  in the `plan` spot check and the `judge` fallback) uses that row's length
  via `query_engine.excerpt_chars_for`, never the current setting. So
  Phase 8 replay stays exactly 300 characters, verified on real data: the
  spot check still reproduces Phase 8's and the pilot's cached sources 5/5.
- **The re-pilot confirmed the effect.** In the Session 25 re-pilot (2
  documents), 0 of 28 regulatory quotes ended at their excerpt's end, and
  every saved excerpt equalled its full corpus chunk.

Pilot: run for real in Session 23 (4 documents, run 0) on a separate main
pass (`docs/eval_raw_main_pass_pilot.jsonl`). Its own judgments were
ingested and checked: claim-check report
`docs/eval_raw_main_pass_pilot_claim_judgments_checks_report.md`, raw facts
only. The pilot validated the mechanism. It is not the comprehensive
re-run, and its results are not comparable to Phase 8 (item #4).

## Human review (P7-01, built and tested offline 2026-10-15)
"Flagged issues require explicit human approval before marked resolved."

**The files:**
- `src/review/cases.py` turns baseline and agent rows into one case shape:
  one case per (document, run). The items are the four outcomes, plus
  escalation for agent cases. Each item carries the verdict, confidence,
  reasoning, flags, and claims with their quotes and full passages.
  Labels are never shown.
- `src/review/store.py` enforces the rules:
  - a reviewer must be named;
  - an item is either `confirm`ed or `override`n, and an override needs an
    allowed, different verdict and a written reason;
  - a case can be `resolve`d only when every item has a decision;
  - nothing changes after resolution;
  - the history is append-only and the latest decision per item counts.

  Decisions go to `REVIEW_DIR/decisions.jsonl` (`./reviews/`, gitignored
  because it holds names) and to the audit log, without the reviewer's
  name.
- `src/app.py` (Streamlit) only displays and passes decisions through,
  with the queue, case view, decision controls, resolve and history.
  Dry-run rows can be shown, labelled as rehearsal.

**Tests:** `tests/test_review.py` (13) cover the rules on the store, plus
the screen end to end with Streamlit's offline `AppTest`: no decision
without a reviewer, an override without a reason is refused, resolve only
appears once everything is decided, and a resolved case leaves the Open
queue.

**Startup:** starting the audit run no longer imports the query engine
(and the ML stack) just to read one setting, so the app loads in seconds.

## Agentic tool loop (built 2026-10-14; run live 2026-10-24; gate added 2026-10-24)

**The gate: code decides first (user decisions 2026-10-24, after the live run).** The live run
showed two failures that need no judgment to prevent. All 10 unnecessary calls were account or policy
lookups on other lenders' agreements. 6 of the 7 escalation errors said `no_escalation` where the
answer was `cannot_determine`. Both are now decided by code, from the document and the lookup result:

| Document | Model called | Tools offered | Escalation |
|---|---|---|---|
| Not a credit agreement | **no** (0 model and 0 tool calls) | none | `not_applicable` |
| Another lender | yes | regulation search only | `not_applicable` |
| No lender named | yes | regulation search only | `cannot_determine` |
| Northbridge, no customer number | yes | regulation search and policy | `cannot_determine` |
| Northbridge, account not found or not looked up | yes | all | `cannot_determine` |
| Northbridge, account in another person's name | yes | all | `cannot_determine` |
| Northbridge, matching account | yes | all | **the model decides** |

How it is enforced:
- `escalation_gate` and `account_gate` in `agent_validation.py` decide; `tool_agent._loop` applies the
  gate before the first model call.
- A tool outside the offered set never reaches the MCP server: the model gets an error result.
- The model is told the pre-check.
- `cannot_determine` always adds a review reason naming the rule. Where the rule overrode the model,
  that is a review reason too, and the model's own decision is kept as `llm_decision`.

**Honest limits:**
- The rules were written after seeing the held-out failures (v2_d13, d14, d18). The held-out set is no
  longer held out for escalation.
- The live numbers in `docs/eval_results_v2.md` are from before the gate.
- The offline dry run on all 19 documents shows the rules fire on exactly the 6 documents labelled
  `cannot_determine` or `not_applicable`, and on none of the 13 the model must decide.
- A live re-run of those documents is what would show the effect on real model output.

The original design, as built on 2026-10-14, follows.
Design and decisions: `docs/agent_tool_use_design.md`. The fixed workflow
above is unchanged and stays the baseline.

**How it connects.**
- **The tools.** `src/mcp_server/agent_server.py` is a separate MCP server
  with three tools that return raw evidence, with no model call inside:
  - `search_regulation(query)`: the FCA corpus;
  - `get_account(customer_id)`: the v2 accounts, by customer number only,
    with `found: false` when there's no record;
  - `search_policy(query)`: Northbridge's internal policy.

  The P5 server (`server.py`) is untouched.
- **The loop.** `src/agent/tool_agent.py` starts the server over stdio and
  takes the tools from its `list_tools`. It passes them to the model with
  `tool_choice: auto`, plus a local `submit_assessment` output tool. The
  **model chooses** which tools to call, with what arguments, and in what
  order. Parallel calls are allowed, with all results returned in one
  message.
- **Evidence.** Every returned passage or record is numbered (E1, E2, …),
  and the model must cite those numbers.
- **Output.** `src/agent/agent_schemas.py` defines what the model submits:
  - document scope;
  - the four outcome judgments;
  - escalation, with exact policy quotes and dated note quotes.

**Enforced in code during the run:**
- **Limits** (`src/config.py`): 8 tool calls in total; `search_regulation`
  at most 4, one per Consumer Duty outcome, each call naming its outcome in
  a required `outcome` argument; the other tools at most 3 each; 6 turns.
  Hitting one stops the run; every outcome becomes `insufficient_evidence`
  and the case goes to review.
- **Repeats:** an identical repeated call returns the cached result and
  still counts.
- **Malformed calls:** arguments wrapped in `$PARAMETER…` are not
  executed.
- **Invalid submissions:** returned to the model with the schema error.

**Validated after the run** (`src/agent/agent_validation.py`,
deterministic):
1. **Necessary calls, from the document's own facts.** Regulation search is
   needed for any credit agreement. Policy search is needed for every
   Northbridge agreement. An account lookup, with the document's own
   customer number, is needed when the agreement has one. A missing
   necessary call routes the case to review.
2. **Unnecessary calls, flagged and counted:**
   - account or policy calls for another lender's agreement, or account
     calls when no lender is named;
   - any call for a document that isn't a credit agreement;
   - a second account lookup, or a lookup of another customer;
   - any repeated call.
3. **Outcomes only from their own cited passages.** Every regulatory quote
   must be in the exact passage it names, and that passage must be in the
   outcome's own citations. A cited regulation passage must come from that
   outcome's **own** search, and each outcome must have had one. A decided
   outcome needs at least one such quote and at least one cited regulation
   passage. Otherwise it is
   **forced to `insufficient_evidence`**. "..."-spliced quotes are checked
   part by part. Confidence is the minimum similarity of the cited
   passages, against the 0.65 threshold.
4. **Escalation:**
   - the decision must fit the document: `not_applicable` for another
     lender or a non-agreement, `cannot_determine` with no lender or
     customer;
   - a decision must quote the procedure, and each quote must be in the
     policy passage it names;
   - trigger 2.1(a) must match "2+ missed payments in the trailing 12
     months", and 2.1(b) "an open hardship marker";
   - 2.1(c) needs a quoted note that is in the record and dated inside the
     window. "Recent" means the 12 months before the review date (user decision, 2026-10-14; the agent is told it),
     because the procedure doesn't define it;
   - an in-window bereavement, separation or health note that 2.1(c)
     doesn't claim is flagged.

**Fixtures v2:**
- **Data:** `data/fixtures_v2/` (19 documents, 18 accounts), built by
  `build_fixtures.py` with seed 20261013.
- **Labels:** in `tests/fixtures/eval_set_v2.json`. The agent never sees
  them.
- **Checks:** `python -m src.evaluation.fixtures_v2_check` checks the set
  and writes `docs/fixtures_v2_coverage.md` and `docs/fixtures_v2_labels.md`
  before any run:
  - every customer number resolves or is a declared mismatch;
  - every coverage cell has a positive and a negative;
  - the blind-read leak check, fairness and policy echo.

**Two evaluation sets** (`--set`):
- **v2** (default): the 19 fixture documents with accounts. It tests
  escalation and tool use.
- **v1**: the 15 hand-written baseline documents (decision 2026-10-14).
  They come from other lenders and have no customer numbers, so escalation
  should be `not_applicable` and account and policy calls are unnecessary.
  Their outcome results are reported next to the baseline's full pass on
  the same documents.
  - **Labels:** `tests/fixtures/eval_set_v1_agent.json` and
    `docs/agent_v1_labels.md`, written by `agent_eval labels-v1` from the
    baseline's own ground truth before any run.

**One server per evaluation run.** `ToolAgent.run_many` sends every document
through one MCP server, which loads the embedding model once. Each document
is still its own run: its own messages, evidence numbers, call counts,
limits and cache. One document's failure doesn't end the batch.

**Lender reading.** The lender counts as "not stated" only when the party
clause names no one ("The Lender" or a blank placeholder); any named lender
is read as named. The first rule required "Ltd", "plc" and similar, and
misread two v1 lenders ("Bridgeport Lending Group", "Elmsworth Credit
Union") as not stated. Found before any run.

**Evaluation:** `python -m src.evaluation.agent_eval` has these commands:
- `plan`: free;
- `run`: API;
- `claimcheck`: API, using the same checker as the baseline;
- `score`: free;
- `labels-v1`: free.

**Tests (offline):**
- `tests/test_tool_agent.py` (24): scripted model and fake MCP session,
  covering every rule above.
- `tests/test_tool_agent_mcp_integration.py` (2): scripted model, but the
  real MCP server subprocess, the real local index and the real accounts.
- `tests/test_agent_eval.py` (3): scoring.

**Two bugs the integration test caught, both fixed:**
- **The server's error output went to an unread pipe.** It now goes to
  `LOG_DIR/agent_server_stderr.log`. A pipe nobody reads can fill and
  block the server.
- **On Windows, loading the embedding model inside the first tool call
  hung.** The server froze before the model started loading. The same load
  works from a shell, a plain subprocess, and a console-less subprocess.
  The server now loads the model and both indexes before it starts
  serving (`agent_server.warm_up`), and every tool call then returns at
  once.

**No auto-approval; confidence is reported, not applied (decision 2026-10-14).**
`AGENT_AUTO_APPROVAL_ENABLED = False`, so every agent case goes to a human, each with `review_reasons`.
The agent's verdict is replaced only by the quote and citation rules. Confidence (minimum similarity of
the cited passages) is reported, with a flag for "below the uncalibrated 0.65 reference", but never
changes a verdict. Why: in the baseline, one 0.65 threshold acted as an on/off switch by category. 0%
of compliant price-and-value and consumer-understanding verdicts passed it; 100% of consumer-support
and products-and-services verdicts did, including all 3 wrong consumer-support verdicts. On today's
data, no category can meet a risk target, because 0 misses across 15 documents bounds nothing useful.
Auto-approval returns only after a per-category gate is calibrated on the design split against a
stated risk target and frozen before held-out testing. The baseline pipeline is unchanged.

**Known limits:**
- an outcome may cite only regulation passages from its own search. This
  rules out "off-copy" support but also legitimate reuse of a passage found
  for another outcome, which then has to come back through that outcome's
  own search;
- 2.1(c) is checked only by quote, date and a word list, not by meaning;
- the fixtures are template-generated, with two wordings per clause.

## Audit logging (built offline 2026-10-13; not yet run end to end)
The standard, with the decisions behind it, is in
`docs/audit_logging_design.md`.

**What exists:**
- **Logging module:** `src/monitoring/audit.py`. One JSON line per event,
  one file per run (`LOG_DIR/<date>/<run_id>.jsonl`, default `./logs/`,
  gitignored), plus `LOG_DIR/index.jsonl` with one line per run.
- **Off until a run starts:** an entry point starts a run, so library
  use and tests write nothing. The entry points that start one:
  - `run_eval main`, `python -m src.ingestion.ingest` and `python -m
    src.agent.compliance`;
  - `agent_eval run` and `claimcheck`;
  - since 2026-10-20, the other paid evaluation commands:
    `claim_verification judge` and `check`, `groundedness run`, and
    `negative_control run`. Each logs a completeness check (calls or rows
    saved against those planned), and is recorded as `failed` if it
    crashes (`audit.logged_run`; `tests/test_eval_audit.py`).
  - Zero-cost commands (plan, summary, report, ingest) are not logged.
- **Tests never write to `LOG_DIR`:** `tests/conftest.py` sends their
  runs to a temp directory.
- **Run header:** commit, a dirty-tree flag, allowlisted settings, corpus
  chunk count, package versions and any overrides. Each main-pass row
  gains `run_id`, linking it to its log.
- **Stage events:** `src/monitoring/pipeline_events.py` logs extraction,
  retrieval, judgment and validation. Checks are logged whether they pass
  or fail, and none changes a result.
- **Model calls:** every model request and every instructor retry is
  logged through the existing observe-only hooks in
  `src/agent/retry_log.py`; the query engine logs its synthesis call
  directly. The old `*_retries.jsonl` file is still written as before.
- **Redaction:** no keys, and no dump of the environment. Paths are
  relative or `<USER_HOME>`; documents and chunks are logged as hashes and
  IDs. Prompt text is written only with `--log-payloads`. All logs are
  kept: there is no pruning.

**Ingestion is gated.** `src/ingestion/ingest.py` runs the content checks
in `src/ingestion/checks.py` on the parsed pages and chunks before
anything is embedded:
- the PDF reader was used;
- no raw-PDF markers;
- bad characters under 1%;
- 0.5–5 chunks per page;
- at least 90% of pages yield text;
- file coverage, which warns only.

It then embeds into a staging collection and runs a 3-question retrieval
smoke test. It swaps the staging collection in only if every blocking
check passed.
- **On a failed blocking check:** the live collection stays unchanged
  and the command exits 1, unless `--allow-failed-checks` is given. An
  override is logged at `warn` and recorded in the run header.
- **Thresholds:** in `src/config.py`.
- **Read-only mode:** `--check-only` runs every check against the live
  collection without building anything. The current index passes all 7
  checks: 0.022% bad characters, 1.62 chunks per page, 344/344 pages with
  text, smoke test 3/3.

The checks would have flagged the 5,540-chunk run: the offline tests feed
them chunks shaped like it. That run itself was not reproduced.

## Decision trade-offs (fill in as built; this is the judgement section)
| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| RAG vs fine-tuning | RAG | Fine-tuning | Auditability: traceable sources required for compliance; cheaper to update as regulation changes |
| MCP vs plain function calling | MCP for the three tool domains | Plain functions | Three genuinely separate tool/data domains with different real-world ownership. **As built:** the evaluated path calls the query engine directly (a plain function call); MCP is used only by a test-only side path (see "As built") |
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

## Evaluation notes

**Citation-logging fix (forward-looking, does not affect existing eval
data).** `src.agent.compliance.validate_outcome` (P4-02) now logs each
judgment's full resolved cited-source objects — index, file name,
similarity score, chunk text, via `logger.info`, `json.dumps`'d for
machine-parseability — not just how many sources were cited.
`src.evaluation.run_eval`'s `main` subcommand's per-outcome record now
similarly persists the full `cited_sources` list (in addition to the
existing `cited_source_count`) for any future run. **This fix is in place
for future evaluation runs only.** The current Phase 8 main pass data
(`docs/eval_raw_main_pass.jsonl`, 405 calls, Session 13) predates it and
was never backfilled — it recorded `cited_source_count` as a bare integer,
not which of the retrieved sources were actually cited. That is the
specific, structural reason `docs/eval_groundedness.md`'s P8-05 check is
scoped against each judgment's *full retrieved context* (typically 5
sources) rather than a verified cited-only subset: the cited-only subset
was never recorded for this dataset, and can't be reconstructed after the
fact (unlike the retrieved-sources list itself, which is reconstructable
by replaying deterministic retrieval — see `src/evaluation/groundedness.py`'s
module docstring).

**On finding gaps like this one, going forward.** This citation-logging
gap is treated as one instance of a general pattern likely to recur: as
evaluation and analysis work continues, it's expected that other
not-originally-scoped gaps in what the harness records will surface
(this session's gap was discovered by trying to build the P8-05
groundedness check against data that turned out not to carry what was
needed). The deliberate policy, going forward: **fix each such gap in the
code as it's found and document it here, but do not re-run the expensive
405-call main pass every time.** Re-running incrementally, once per
discovered gap, would repeatedly pay the full API cost while the build is
still actively changing and more gaps are still likely to surface. Instead,
accumulate fixes (this session's citation logging is the first) and do
**one comprehensive re-run once the build reaches a stable point** — not
before. This trades slightly stale interim eval data (already flagged with
its own caveats, as above) for not re-paying a 405-call pass multiple
times over the course of ongoing build work. Tracked in `progress.md` each
time a new gap/fix is added, so the eventual comprehensive re-run has a
clear checklist of what it needs to validate, rather than being decided on
an ad hoc basis when it happens.

**Deferred-changes checklist for the comprehensive re-run** (as of Session
16). *(Note, 2026-10-13: every item has since been built, and the
comprehensive re-run has run: 45/45 rows, 2026-10-07. The "State" column
is kept as a record of the checklist. Item 2's "no real judgment yet" and
item 5's "not run" are out of date: the Session 23 pilot and the full pass
both ran. Item 20's 300 characters became `None` (whole chunk) in Session
25.)*

| # | Change | State | Why it waits for the re-run |
|---|---|---|---|
| 1 | Citation logging (full cited-source objects) | In code | Existing Phase 8 data predates it; not backfilled |
| 2 | `OutcomeJudgment` structured-claim fields (P8-06) | In code, tested offline only | No real judgment has produced them yet |
| 3 | `run_eval.py main` persisting the structured-claim fields | **Built, tested offline (Session 21).** Each outcome record now has `judgment`: the full `OutcomeJudgment` (`judgments[key].model_dump()`), taken from the judge's output directly rather than via `ValidatedOutcome`. Tests: `tests/test_main_pass_record.py`. Originally: | `ValidatedOutcome` doesn't carry them; needed so the verifier can run on the re-run's output |
| 4 | Judge sees the full loan document text, not only the extracted statement | **Built, tested offline (Session 22).** `compliance.build_judgment_user_message` adds the full document text to the judge's user message, alongside the extracted statement; the system prompt is unchanged. `ComplianceAgent.evaluate()` now requires `document_text`, and every caller passes it. Not like-for-like with Phase 8 (see below). The MCP price_and_value path is unchanged. Tests: `tests/test_rerun_final_batch.py`. Originally: | Changes the judgment's user message (see below) |
| 5 | P8-06 pilot (16 judgment calls + one claim check per regulatory claim) | Built, **not run** | Would test a judgment input that #4 is about to change |
| 6 | Save every retrieved source per outcome (not just cited ones), including node IDs, for every run | **Built, tested offline (Session 21).** Each outcome record has `retrieved_sources` (all retrieved excerpts as shown to the judge). `SourceCitation` gained optional `node_id`, filled by `QueryEngine.query`. Tests: `tests/test_main_pass_record.py`. Originally: | The verifier's `named_chunk` / `other_retrieved_chunk` tiers, claims naming an uncited excerpt, and `corpus_chunk_was_retrieved` all need the full retrieved set; only run 0 can rebuild it by replay |
| 7 | Save extracted fields for every run, not just run 0 | **Built, tested offline (Session 21).** `_cached_fields` is written for every run. `_cached_price_and_value_context` stays run-0-only on purpose (`variants` takes the last row per document, so caching it every run would switch P8-04's input to run 2). Tests: `tests/test_main_pass_record.py`. Originally: | Extraction is a fresh, non-deterministic LLM call per run, so runs 1 and 2 can't be replayed without saved fields; `absent_from_document` checks also read them |
| 8 | Save the structured-claim fields (`document_facts`, `regulatory_requirements`, `absences`) in the main-pass record for every run | **Built, tested offline (Session 21).** Same change as #3; the record is built for every run, and the tests check runs 0, 1 and 2. Tests: `tests/test_main_pass_record.py`. Originally: | Same underlying work as #3, stated explicitly as per-run: without it no run has anything for P8-06 to verify |
| 9 | Save the raw judgment `cited_sources` list before excerpt resolution drops out-of-range entries | **Built, tested offline (Session 21).** Each outcome record has `cited_sources_raw` (the judge's excerpt numbers, unresolved) next to the resolved `cited_sources`. Tests: `tests/test_main_pass_record.py`. Originally: | Only resolved citations are saved today; an out-of-range excerpt number the judge cited is lost |
| 10 | Update `groundedness.py` and `claim_verification.py` to read main-pass records for all three runs | **Built, tested offline (Session 22).** `groundedness.build_scope` covers every run, using saved `retrieved_sources` when present, replay from that run's `_cached_fields` otherwise, and skipping (with a printed note) rows with neither; on the Phase 8 data it still yields P8-05's 51 run-0 judgments. `claim_verification`: rows keyed by `(doc_id, run_idx)`; `judge --runs`; a new zero-cost `ingest` copies a main pass's own judgments (any run) into a judgments file; `--judgments` on every subcommand; claim-check keys include the run. Tests: `tests/test_rerun_final_batch.py`. Originally: | `build_scope` skips `run_idx != 0` and requires `_cached_fields`; `claim_verification.py` reads its own pilot file and gets inputs from run 0 plus replay |
| 11 | **MOST SERIOUS ITEM: silent no-op risk, not just missing data.** Give the re-run a new output path, or archive `docs/eval_raw_main_pass.jsonl` first | **Built, tested offline (Session 17).** New-path option chosen: `main` writes to `docs/eval_raw_main_pass_v2.jsonl` by default (or `--output`), refuses the Phase 8 file, resumes against its own output only, writes errors next to it, and prints a WARNING listing every skipped pair (plus a "NO API calls" warning if all are skipped). Tests: `tests/test_run_eval_main_output.py`. Readers (`summary`, `variants`, ...) still point at the Phase 8 file: that is item 13 | `run_eval.py main` resumes by skipping every `(doc_id, run_idx)` pair already in that file. All 45 pairs are there. A re-run would print "Resuming: 45 ... skipping those", make zero calls and write nothing, and everything downstream would keep reading the old Phase 8 rows. A partial re-run would mix new-schema and old rows in one file |
| 12 | Make P8-04 `variants` records save reasoning, raw and resolved cited sources, retrieved sources and the structured-claim fields | **Built, tested offline (Session 22).** Variant rows now carry every per-outcome field `main` saves, plus the fields used and the main-pass input name. `variants` builds its message with the same function as the production judge, so Variant A is the production prompt and message. Tests: `tests/test_rerun_final_batch.py`. Originally: | Its record saves only `llm_status`, `status`, `confidence` and `cited_source_count`: the same count-only pattern citation logging fixed for `main`. Needed if P8-04 runs in the final batch and its judgments should be checkable |
| 13 | Point every reader at the re-run's output, or archive `docs/eval_summary.json` too | **Built, tested offline (Session 18).** Point-every-reader option chosen: `summary`, `variants`, `groundedness.py` (`plan`, `run`) and `claim_verification.py` (`plan`, `judge`) take `--input`, default to `docs/eval_raw_main_pass_v2.jsonl` via the shared `run_eval.resolve_main_input`, and read the Phase 8 file only when given it explicitly. `summary` writes `<input stem>_summary.json` next to its input and refuses any input whose derived name would be `docs/eval_summary.json`. Tests: `tests/test_eval_readers_input.py` | `summary`, `variants`, `groundedness.py` and `claim_verification.py` all hardcode `docs/eval_raw_main_pass.jsonl`. If #11 is fixed with a new path, all four must be updated or they silently keep reading Phase 8 data. If #11 is fixed by archiving, `summary` then overwrites `docs/eval_summary.json`, which `eval_results.md` cites, so it must be archived as well |
| 14 | Give `variants` a skip check and run identity | **Built, tested offline (Session 22).** Output is `<input stem>_variants.jsonl` next to the main-pass input (or `--output`), so each variant file belongs to one pass and `summary` reads the matching one; main-pass files are refused. Existing `(doc, variant, run)` rows are skipped with a WARNING listing each, plus "NO API calls" if all are skipped. Tests: `tests/test_rerun_final_batch.py`. Originally: | `docs/eval_raw_variant_pass.jsonl` is append-only. Running `variants` twice duplicates every row, and `summary` scores them all together |
| 15 | Flag partial runs | **Built, tested offline (Session 22).** `summary` checks rows against documents x runs (runs inferred, or `--expected-runs`) and all 4 outcomes per row, reports duplicates and the input's errors file, and checks variant rows the same way. Shortfalls print `WARNING (incomplete pass)` and add `completeness_warnings` to the summary; a complete pass is silent and unchanged (Phase 8 still reproduces `eval_summary.json`). Tests: `tests/test_rerun_final_batch.py`. Originally: | Failed `(doc, run)` pairs go to the errors file and the batch continues. `summary` never checks the row count against the expected 45, so a few silent failures would give results on, say, 43/45 rows with no warning. The errors file also accumulates across invocations |
| 16 | Stop a pilot re-run from silently skipping documents | **Built, tested offline (Session 22).** `judge` (and `ingest`) skip `(doc, run)` pairs already in the judgments file with a WARNING listing each, plus "NO API calls" when nothing is left. Tests: `tests/test_rerun_final_batch.py`. Originally: | `claim_verification judge` skips any document already in `docs/eval_claim_pilot_judgments.jsonl`, the same pattern as #11. The file doesn't exist yet, but once it does, a second pilot run (e.g. after #4) would silently skip the documents judged before |
| 17 | Stop `claim_verification check` overwriting its outputs | **Built, tested offline (Session 20).** `--output` names an append-only claim-check store (default `docs/eval_claim_pilot_checks.jsonl`); `<store stem>_results.jsonl` and `<store stem>_report.md` are derived from it and rewritten in full each run, deliberately: they are pure views of (judgments file + whole store), rebuilt from every recorded judgment, not just `--docs`, so nothing is dropped. Judgments with unchecked claims are listed in the report, not tabulated. The judgments file is refused as a store. Tests: `tests/test_claim_check_store.py`. Originally: | It rewrites `docs/eval_claim_pilot_checks.jsonl` and `docs/eval_claim_verification_pilot.md` in full on every run. A second run replaces earlier results; a run limited with `--docs` keeps only that subset and drops the other documents' results |
| 18 | Give `claim_verification check` resume and incremental saving | **Built, tested offline (Session 20).** Each result is appended to the store as it returns; a re-run skips claims already stored (keyed by doc, outcome, claim index and claim text) with a WARNING listing each, plus a "NO API calls" warning if all are skipped. `plan` reports the remaining count. Tests: `tests/test_claim_check_store.py`. Originally: | No resume, and all results are held in memory until the end. A crash partway through loses every completed, already-paid-for claim check, and a re-run pays for all of them again |
| 19 | Stop `groundedness.py run` overwriting `docs/eval_groundedness.md` | **Built, tested offline (Session 19).** `run` writes to `--output`, default `docs/eval_groundedness_<input stem>.md` (e.g. `eval_groundedness_eval_raw_main_pass_v2.md`), and refuses `docs/eval_groundedness.md` by absolute or relative path. The output path is resolved before any input is read or API call made. Tests: `tests/test_groundedness_output.py` | It rewrites the file in full, which would erase the hand-written "Observed limitation" section and the Signal 1 correction. Already noted in progress.md's "Known issues", but not previously on this checklist |
| 20 | Stop hardcoding the 300-character excerpt length | **Built, tested offline (Session 20).** `src/retrieval/query_engine.py` defines `SOURCE_EXCERPT_CHARS = 300` and uses it; `groundedness.py` and `claim_verification.py` read `query_engine.SOURCE_EXCERPT_CHARS` at call time (no local copy), so changing it there changes all three. Tests: `tests/test_excerpt_length_single_source.py`. Originally: | `groundedness.py` (`node.text[:300]`) and `claim_verification.py` (`EXCERPT_CHARS = 300`) each copy the query engine's truncation instead of importing it. If that length ever changes, rebuilt sources would silently stop matching what the judge actually saw. Item #6 removes the need for this, since saved sources replace replay |

**The final re-run needs a new output path, or the old
`docs/eval_raw_main_pass.jsonl` archived first (item 11), or it will
silently do nothing.**

**This is the fourth and final completeness pass. Items 1-20 are the
complete checklist before the comprehensive re-run, and all 20 must be in
place before it runs. No further completeness passes will be run; building
starts now.** Items 6-10 came from a read-only check of what the Phase
8 log records per run. Only run 0 has `_cached_fields` and
`_cached_price_and_value_context`; no run records which excerpts were
retrieved; and the analysis code is hard-wired to run 0. Citation logging
(#1) alone would give every run only the new cited-chunk Signal 1. Running
the re-run with any of 6-10 missing would again limit groundedness
checking to run 0, or remove it entirely, and would mean paying for the
405-call pass a second time. This is the reason for the batching policy
above. Items 11 and 12 came from a later end-to-end read of `compliance.py`,
`run_eval.py`, `groundedness.py` and `claim_verification.py`. Items 13-16
came from a third pass over how the re-run is invoked, where its output
goes, and what reads that output afterwards. Items 17-20 came from a
fourth pass over the same four files.

Notes for the re-run (smaller points, not blocking groundedness checking
itself):
- **No record of which settings produced a row.** Rows store no model ID
  (`ANTHROPIC_MODEL` comes from `.env`), timestamp or prompt version. Item
  #4 changes the judge's input, so rows should ideally be tagged with the
  configuration that produced them. This includes `CONFIDENCE_THRESHOLD`
  (also from `.env`), which decides the post-threshold `status`.
  `load_dotenv()` does not override variables already set in the shell, so
  a stray shell variable would take effect without any sign.
- **One failed call loses all 4 outcomes for that run.** A failure in any
  of the 4 judgment calls sends the whole `(doc, run)` to the errors file.
  The larger structured output makes validation failures somewhat more
  likely than in Phase 8, which could leave holes in a 405-call pass.
- **Hardcoded top-k.** `groundedness.py` and `claim_verification.py` pass
  `similarity_top_k=5` directly instead of using
  `QUERY_SIMILARITY_TOP_K`. They agree today. Item #6 (saving retrieved
  sources) removes the need for replay, and with it this risk.
- **Corpus re-ingestion risk, before and after the re-run.** The
  verifier's corpus tier reads chunk text live from Chroma. If the corpus
  is re-ingested between the re-run and the analysis, node IDs saved under
  item #6 may no longer match. Re-ingesting *before* the re-run is also a
  risk. `chroma_db/` is gitignored, and ingest deletes and rebuilds the
  collection with fresh node IDs, so the Phase 8 index can't be restored.
  Retrieval would change versus Phase 8 and confound every other change.
  Nothing re-ingests automatically (checked: `init.sh`, tests, MCP code).
  Only re-ingest if that is deliberately intended, and record it if done.
- **OneDrive sync.** The repo is inside a OneDrive-synced folder. A
  long-running append to the JSONL output, and Chroma's SQLite file, could
  be locked or split into conflict copies by sync during the run. Before
  starting, pause OneDrive sync for the duration of the re-run, or move
  output outside the synced folder.
- **A crash mid-write breaks resume.** A truncated last line in a JSONL
  file makes `json.loads` fail on the next read. This fails loudly, not
  silently. Recovery step: fix or delete the truncated last line by hand,
  then re-invoke.

**Known limitation: placeholder-wrapped judge tool calls (Session 26). No
fix applied.** In the full 15-document, 3-run pass, all 49 logged
judge-call retries had the same cause:
- **The failure.** The model's single `OutcomeJudgment` tool call arrived
  with its arguments wrapped in literal placeholder keys (`$PARAMETER_NAME`
  33, `$PARAMETER_VALUE` 14, `$PARAMETER_VALUE_PLACEHOLDER` 1,
  `$PARAMETER_name` 1), so every real field was missing and validation
  failed.
- **What it wasn't.** All 49 had `stop_reason: tool_use` and exactly one
  tool call, so this is neither truncation (instructor does not retry
  truncation anyway) nor parallel tool use (already prevented by
  `disable_parallel_tool_use`).
- **Shape.** 30 were short stubs; 19 were complete judgments nested inside
  the wrapper.
- **Spread and outcome.** It affected all four outcomes and no extraction
  call. All 49 recovered on re-ask: 46 on attempt 2, 3 on attempt 3; none
  became a hard failure.
- **Cost.** 49 extra judge calls (about 15%) on top of the 288 nominal in
  that resume. In total the main pass used 492 requests.
- **Not fixed.** One option is unwrapping a single placeholder key whose
  value is a complete, valid judgment, which would save the 19 full-wrapper
  retries. It was considered and not applied: it means accepting a
  malformed envelope, and it would not help the stub cases. Records:
  `docs/eval_raw_main_pass_v2_retries.jsonl`, from the observe-only hooks
  in `src/agent/retry_log.py`.
- **Not reflected in the judgments.** A retried judgment is the model's
  re-asked answer, not its first one, but every saved judgment passed the
  same schema. Nothing in the saved rows marks which judgments were
  retried; the retry log does.
- This is the same family as Session 13's single malformed generation
  (parameter-tag text bleeding into a field).

**Evaluation outputs added in Session 26.**
- `groundedness.py plan` now saves per-judgment Signal 1 to
  `<input stem>_signal1.jsonl`: P8-05's max over the retrieved set, plus the
  cited-chunk per-chunk scores with min and mean, no threshold. It refuses
  the input itself and the protected Phase 8 files.
- `claim_verification check` writes observe-only retry records to
  `<store stem>_retries.jsonl`.

**All 20 items are now built and tested offline (Sessions 17-22).** *(Done
since: the Session 23 pilot and the full 15-document, 3-run pass, completed
2026-10-07, ran with their call counts approved first. Results are in
`docs/eval_raw_main_pass_v2_summary.json` and the claim-check report.)*

**Item #4 breaks comparability with Phase 8, deliberately.** Since Session
22 the judge's user message includes the full loan agreement text (see
`compliance.build_judgment_user_message`). Judgments produced after this
point are therefore **not directly comparable to the cached Phase 8 run-0
statuses**, or to any Phase 8 result: a status that differs could reflect
the new input rather than run-to-run variance or a real change in
reasoning. This is exactly why #4 was batched for the final re-run rather
than run earlier. Changing the judge's input mid-way would have left the
project with a mix of old-input and new-input results and no clean baseline
under either. Any comparison with Phase 8 (the pilot report's "reference
status" table included) must be read as old input vs. new input, not as a
like-for-like re-measurement.

**Why #4 existed.** Before Session 22 the judge was shown only the extracted
field text for each outcome, never the loan document itself. That text is
sometimes a paraphrase (`LoanAgreementFields` allows "quote or closely
paraphrase"). A `document_facts` verbatim quote can therefore only come
from the paraphrase, and a quote-vs-document miss can reflect how the
extraction was worded rather than a wrong or invented claim. Until the
judge sees the document, the `document_facts` check can't really verify
anything. Checking quotes against the extracted text instead was
considered and rejected. A paraphrase can't reliably contain an exact
quote, so a miss against it is uninformative. Because #4 changes what the
judge sees, it may also shift judgments. That's one more reason to
measure it once, in the comprehensive re-run, rather than in a pilot that
would immediately be out of date.

**What is built and tested offline (P8-06).** The schema fields, the
verifier (`src/evaluation/claim_verification.py`, including `ingest` for a
main pass's own judgments since item #10), and cited-chunk Signal 1.
The quote normaliser and matcher were tested against real corpus text.
A hand-built judgment exercised every bucket, search tier and report
section. Retrieval replay reproduced the cached run-0 sources for all 4
pilot documents. *(Since then, the verifier has run on real judgments:
the Session 23 and 25 pilots, and the full pass's 536 claims, 2026-10-08.)*

## Explicitly out of scope (for this project)
- Multimodal / image-based document verification (KYC photo/ID checks):
  noted as a future extension, not built here.
- Kafka / PyFlink / Spark / Delta Lake / Databricks: belongs to the
  separate, larger data-engineering platform project, not this one.
- LangGraph: the plan is a hand-written loop over the Claude API with MCP
  tools (`docs/agent_tool_use_design.md`); there is no agent loop yet.
  Revisit LangGraph only if orchestration complexity genuinely requires
  it.

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
without enforcing it, for the reason above. Full enforcement everywhere
is contingent on Phase 8 actually validating `CONFIDENCE_THRESHOLD`
against real data, not something to force now for the sake of
appearing uniform.

**UI display** ("confidence %, evidence used, auto-resolved vs escalated
tag") is Phase 7's job, not Phase 6's: the data these fields need
(`confidence`, `sources`/`cited_sources`, `needs_human_review`) now
exists in structured form on every relevant result object, but no UI
exists yet to display it (`streamlit run src/app.py` isn't built).

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
- **Account lookup** is mock customer/transaction data. In a real bank
  this sits in the core banking system, is actual customer PII, and is
  access-controlled per customer, nothing like the other two domains.
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
already tested end-to-end against all 3 synthetic documents) is
untouched: rewriting its whole four-outcome pipeline to route through
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
  the quote lies past the 300-character excerpt the judge saw), else
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

Pilot: built, not yet run; deferred to the comprehensive re-run (see
"Evaluation notes" below). When run, it writes raw facts only to
`docs/eval_claim_verification_pilot.md`.

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
16):

| # | Change | State | Why it waits for the re-run |
|---|---|---|---|
| 1 | Citation logging (full cited-source objects) | In code | Existing Phase 8 data predates it; not backfilled |
| 2 | `OutcomeJudgment` structured-claim fields (P8-06) | In code, tested offline only | No real judgment has produced them yet |
| 3 | `run_eval.py main` persisting the structured-claim fields | **Not built** | `ValidatedOutcome` doesn't carry them; needed so the verifier can run on the re-run's output |
| 4 | Judge sees the full loan document text, not only the extracted statement | **Not built** | Changes the judgment's user message (see below) |
| 5 | P8-06 pilot (16 judgment calls + one claim check per regulatory claim) | Built, **not run** | Would test a judgment input that #4 is about to change |
| 6 | Save every retrieved source per outcome (not just cited ones), including node IDs, for every run | **Not built** | The verifier's `named_chunk` / `other_retrieved_chunk` tiers, claims naming an uncited excerpt, and `corpus_chunk_was_retrieved` all need the full retrieved set; only run 0 can rebuild it by replay |
| 7 | Save extracted fields for every run, not just run 0 | **Not built** | Extraction is a fresh, non-deterministic LLM call per run, so runs 1 and 2 can't be replayed without saved fields; `absent_from_document` checks also read them |
| 8 | Save the structured-claim fields (`document_facts`, `regulatory_requirements`, `absences`) in the main-pass record for every run | **Not built** | Same underlying work as #3, stated explicitly as per-run: without it no run has anything for P8-06 to verify |
| 9 | Save the raw judgment `cited_sources` list before excerpt resolution drops out-of-range entries | **Not built** | Only resolved citations are saved today; an out-of-range excerpt number the judge cited is lost |
| 10 | Update `groundedness.py` and `claim_verification.py` to read main-pass records for all three runs | **Not built** | `build_scope` skips `run_idx != 0` and requires `_cached_fields`; `claim_verification.py` reads its own pilot file and gets inputs from run 0 plus replay |
| 11 | **MOST SERIOUS ITEM: silent no-op risk, not just missing data.** Give the re-run a new output path, or archive `docs/eval_raw_main_pass.jsonl` first | **Built, tested offline (Session 17).** New-path option chosen: `main` writes to `docs/eval_raw_main_pass_v2.jsonl` by default (or `--output`), refuses the Phase 8 file, resumes against its own output only, writes errors next to it, and prints a WARNING listing every skipped pair (plus a "NO API calls" warning if all are skipped). Tests: `tests/test_run_eval_main_output.py`. Readers (`summary`, `variants`, ...) still point at the Phase 8 file: that is item 13 | `run_eval.py main` resumes by skipping every `(doc_id, run_idx)` pair already in that file. All 45 pairs are there. A re-run would print "Resuming: 45 ... skipping those", make zero calls and write nothing, and everything downstream would keep reading the old Phase 8 rows. A partial re-run would mix new-schema and old rows in one file |
| 12 | Make P8-04 `variants` records save reasoning, raw and resolved cited sources, retrieved sources and the structured-claim fields | **Not built** | Its record saves only `llm_status`, `status`, `confidence` and `cited_source_count`: the same count-only pattern citation logging fixed for `main`. Needed if P8-04 runs in the final batch and its judgments should be checkable |
| 13 | Point every reader at the re-run's output, or archive `docs/eval_summary.json` too | **Built, tested offline (Session 18).** Point-every-reader option chosen: `summary`, `variants`, `groundedness.py` (`plan`, `run`) and `claim_verification.py` (`plan`, `judge`) take `--input`, default to `docs/eval_raw_main_pass_v2.jsonl` via the shared `run_eval.resolve_main_input`, and read the Phase 8 file only when given it explicitly. `summary` writes `<input stem>_summary.json` next to its input and refuses any input whose derived name would be `docs/eval_summary.json`. Tests: `tests/test_eval_readers_input.py` | `summary`, `variants`, `groundedness.py` and `claim_verification.py` all hardcode `docs/eval_raw_main_pass.jsonl`. If #11 is fixed with a new path, all four must be updated or they silently keep reading Phase 8 data. If #11 is fixed by archiving, `summary` then overwrites `docs/eval_summary.json`, which `eval_results.md` cites, so it must be archived as well |
| 14 | Give `variants` a skip check and run identity | **Not built** | `docs/eval_raw_variant_pass.jsonl` is append-only. Running `variants` twice duplicates every row, and `summary` scores them all together |
| 15 | Flag partial runs | **Not built** | Failed `(doc, run)` pairs go to the errors file and the batch continues. `summary` never checks the row count against the expected 45, so a few silent failures would give results on, say, 43/45 rows with no warning. The errors file also accumulates across invocations |
| 16 | Stop a pilot re-run from silently skipping documents | **Not built** | `claim_verification judge` skips any document already in `docs/eval_claim_pilot_judgments.jsonl`, the same pattern as #11. The file doesn't exist yet, but once it does, a second pilot run (e.g. after #4) would silently skip the documents judged before |
| 17 | Stop `claim_verification check` overwriting its outputs | **Not built** | It rewrites `docs/eval_claim_pilot_checks.jsonl` and `docs/eval_claim_verification_pilot.md` in full on every run. A second run replaces earlier results; a run limited with `--docs` keeps only that subset and drops the other documents' results |
| 18 | Give `claim_verification check` resume and incremental saving | **Not built** | No resume, and all results are held in memory until the end. A crash partway through loses every completed, already-paid-for claim check, and a re-run pays for all of them again |
| 19 | Stop `groundedness.py run` overwriting `docs/eval_groundedness.md` | **Built, tested offline (Session 19).** `run` writes to `--output`, default `docs/eval_groundedness_<input stem>.md` (e.g. `eval_groundedness_eval_raw_main_pass_v2.md`), and refuses `docs/eval_groundedness.md` by absolute or relative path. The output path is resolved before any input is read or API call made. Tests: `tests/test_groundedness_output.py` | It rewrites the file in full, which would erase the hand-written "Observed limitation" section and the Signal 1 correction. Already noted in progress.md's "Known issues", but not previously on this checklist |
| 20 | Stop hardcoding the 300-character excerpt length | **Not built** | `groundedness.py` (`node.text[:300]`) and `claim_verification.py` (`EXCERPT_CHARS = 300`) each copy the query engine's truncation instead of importing it. If that length ever changes, rebuilt sources would silently stop matching what the judge actually saw. Item #6 removes the need for this, since saved sources replace replay |

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

**Why #4 exists.** The judge is currently shown only the extracted field
text for each outcome, never the loan document itself. That text is
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
verifier (`src/evaluation/claim_verification.py`), and cited-chunk Signal 1.
The quote normaliser and matcher were tested against real corpus text.
A hand-built judgment exercised every bucket, search tier and report
section. Retrieval replay reproduced the cached run-0 sources for all 4
pilot documents. No verifier result on a real model judgment exists yet.

## Explicitly out of scope (for this project)
- Multimodal / image-based document verification (KYC photo/ID checks):
  noted as a future extension, not built here.
- Kafka / PyFlink / Spark / Delta Lake / Databricks: belongs to the
  separate, larger data-engineering platform project, not this one.
- LangGraph: using Claude's own agent loop + MCP directly; revisit only
  if orchestration complexity genuinely requires it.

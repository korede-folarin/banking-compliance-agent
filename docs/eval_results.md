# Phase 8 Evaluation Results

Generated from a real, fully-executed evaluation pass — not estimated. See
`src/evaluation/run_eval.py` for the harness and `tests/fixtures/eval_set.py`
for ground truth. Raw data: `docs/eval_raw_main_pass.jsonl` (405 total API
calls: 45 doc/run combinations × 9 calls each — 1 extraction + 4
retrieval-synthesis + 4 compliance-judgment calls), `docs/eval_recall_at_k.json`
(retrieval only, zero API cost), `docs/eval_summary.json` (computed metrics,
zero API cost, reproducible via `python -m src.evaluation.run_eval summary`).

## Methodology

- **15 labelled documents** (`loan_agreement_1` through `_15`), each with a
  human-assigned ground-truth label (`compliant` / `non_compliant`) per
  Consumer Duty outcome. 12 carry one deliberately planted issue in exactly
  one of the 4 outcomes; 3 are all-compliant controls (one in a
  deliberately different plain-language house style, to test generalization
  beyond one document register).
- **3 runs per document** (`--n-runs 3`) through the full pipeline
  (`FirstPassAgent` → `ComplianceAgent` → deterministic validation), to
  observe run-to-run variance rather than treat a single sample as
  representative — the same reasoning that made Session 8's 5-sample manual
  estimate too small to trust.
- **45 total (document, run) samples** per outcome (15 docs × 3 runs).
- **Scoring convention**: `insufficient_evidence` (from either the LLM's own
  judgment or the deterministic confidence-threshold override) is scored as
  an **abstention**, excluded from accuracy/FP/FN denominators and reported
  separately as an abstention rate. This mirrors the system's own design —
  an abstention routes to human review rather than asserting a possibly-wrong
  answer, so it is not a "wrong answer," but it is also not a resolved one.
- Two views are reported for every outcome: **`llm_status`** (the raw
  `ComplianceAgent` judgment, before any confidence check) and
  **`post_threshold_status`** (after `CONFIDENCE_THRESHOLD = 0.65` is
  applied — status forced to `insufficient_evidence` if confidence, the
  minimum retrieval similarity among cited sources, falls below it).
- One real run-time bug surfaced and was fixed mid-pass: a single generation
  (out of 405 calls) produced a malformed tool-call response that
  `instructor`'s own retry loop could not recover from (4 internal retries,
  each reproducing the same malformed structure) and crashed the whole
  batch job after 12/45 samples. Rather than re-run the entire pass and
  risk hitting it again, `run_eval.py`'s `main` subcommand was made
  resumable (skips `(doc_id, run_idx)` pairs already recorded) and resilient
  (a per-run failure is now logged to `docs/eval_raw_main_pass_errors.jsonl`
  and the batch continues, instead of aborting). The resumed run completed
  all remaining 33 samples cleanly with 0 further failures — this appears to
  have been a rare, non-deterministic model-output quirk on that specific
  input, not a reproducible defect in this codebase, but the harness is now
  robust to it either way.

## Per-outcome accuracy, false positive rate, false negative rate

Raw LLM judgment (`llm_status`), before the confidence threshold:

| Outcome | n (scored) | Accuracy | FP rate | FN rate | Abstention rate |
|---|---|---|---|---|---|
| price_and_value | 22 / 45 | 95.5% | 8.3% (1/12) | 0.0% (0/10) | 51.1% |
| consumer_support | 43 / 45 | 100.0% | 0.0% (0/31) | 0.0% (0/12) | 4.4% |
| products_and_services | 39 / 45 | 97.4% | 0.0% (0/33) | 16.7% (1/6) | 13.3% |
| consumer_understanding | 45 / 45 | 97.8% | 2.6% (1/39) | 0.0% (0/6) | 0.0% |

*(FP rate = false positives / all ground-truth-compliant scored samples. FN
rate = false negatives / all ground-truth-non_compliant scored samples.
Denominators differ from n because they split by ground truth.)*

**`consumer_support` is fully reliable across this evaluation**: 0 false
positives and 0 false negatives across all 45 samples, confirming Session
8/9's original finding on a far larger sample — every planted vulnerable-
customer issue (docs 2, 7, 8, 9) was caught 3/3 runs, no control document
was ever wrongly flagged.

**`products_and_services` produced the one real false negative in this
entire evaluation**: `loan_agreement_11` run 1 (of its 3 runs) judged
`compliant` when ground truth is `non_compliant`. Doc 11's planted issue is
a target-market statement that describes a *mismatched* market (flexible
revolving credit) for what is actually a fixed-term, fixed-instalment loan
— a subtler issue than an outright missing statement (which doc 10 catches
3/3 runs). The miss's own reasoning text confirms the failure mode: it
restates the document's stated target market ("flexible, revolving credit
for fluctuating short-term cash flow needs") and judges it against the
*general* Products and Services principle, without ever cross-checking it
against the loan's own actual structure (fixed-term, fixed-instalment) —
a comparison the retrieved regulatory excerpts alone can't supply, since
that check requires the document's own other extracted fields, not more
regulation. This is an architectural gap (the judgment call for one outcome
doesn't have access to the extracted fields for a different outcome), not a
retrieval or prompt-wording problem, and not caught by the confidence
threshold either (see below).

**`price_and_value` and `consumer_understanding` are the two weaker
outcomes**, exactly as diagnosed in Sessions 8/9, but now with hard numbers
instead of a small-sample impression — see the dedicated section below.

## Effect of the 0.65 confidence threshold

| Outcome | Pre-threshold abstention | Post-threshold abstention | FP/FN caught by threshold |
|---|---|---|---|
| price_and_value | 51.1% | 91.1% | Yes (the 1 FP) |
| consumer_support | 4.4% | 13.3% | N/A (none to catch) |
| products_and_services | 13.3% | 13.3% (unchanged) | **No** — the 1 FN survives |
| consumer_understanding | 0.0% | **100.0%** | Yes (the 1 FP) |

`confidence_by_correctness` (mean confidence, correct vs. incorrect
judgments) explains why the threshold behaves so differently per outcome:

| Outcome | Correct-judgment mean confidence | vs. threshold 0.65 |
|---|---|---|
| price_and_value | 0.644 (n=21) | just below |
| consumer_understanding | 0.622 (n=44) | below |
| consumer_support | 0.674 (n=43) | above |
| products_and_services | 0.683 (n=38) | above |

For `price_and_value` and `consumer_understanding`, correct judgments
average *below* the 0.65 threshold — the threshold cannot distinguish a
correct judgment from an incorrect one for these two outcomes because both
cluster in roughly the same similarity range, well below where
`consumer_support`/`products_and_services`' correct judgments sit. This
directly confirms Session 8/9's root-cause finding: for these two outcomes,
the corpus's retrieved top-5 chunks consistently mix genuinely relevant
text with worked examples for other product types, capping retrieval
similarity for on-topic content regardless of whether the LLM's eventual
judgment happens to be right.

**`consumer_understanding` is the most striking case**: pre-threshold, it
is the *best*-performing outcome by accuracy (97.8%, 0% abstention — the
LLM never once said `insufficient_evidence` itself). Applying the 0.65
threshold discards **100% of these judgments**, including all 44 correct
ones, to catch its single error. The threshold doesn't make
`consumer_understanding` safer; it makes it silent — every document, right
or wrong, gets routed to human review, which is functionally equivalent to
not running the check at all.

## Updated price_and_value instability read

Session 8's finding was a **~1-in-5 (20%) false-accusation rate**, from 5
manual runs against a single control document. This evaluation replaces
that with a real number from 33 independent samples (11 documents whose
`price_and_value` ground truth is `compliant`, × 3 runs each):

- **1 false accusation out of 33 compliant-ground-truth samples (3.0%)**,
  or 1/12 (8.3%) among the samples where the LLM actually committed to a
  verdict rather than abstaining (21/33 of the compliant samples abstained
  as `insufficient_evidence` — a safe, if frequent, non-answer).
- The one false accusation recurred on the *same document* Session 8 first
  flagged it on: `loan_agreement_3` (the original control), run 0 of 3.
  Its reasoning is not an arbitrary hallucination — it noted the
  document's fair-value clause explicitly scopes its assessment to the
  arrangement fee and interest only, excluding default/arrears charges,
  while the retrieved excerpt says firms must consider "all interest, fees
  and charges a consumer may incur." That is a defensible, if arguably
  over-strict, reading of genuinely ambiguous scope language — closer to a
  strict-interpretation disagreement than a fabrication.
- A second, distinct false accusation appeared on `consumer_understanding`
  (not `price_and_value`) for `loan_agreement_6` run 0 — also a plausible,
  if strict, reading (the document's key-facts summary states most core
  terms but the fee is disclosed as a range, and the excerpt calls for
  disclosing "the total expected price").
- **0 false negatives on `price_and_value`** across all 12 non-compliant
  samples where the LLM committed to a verdict — every planted
  `price_and_value` issue that got a confident answer was caught correctly;
  the only imperfect coverage was on `loan_agreement_5` (the
  self-contradicting fee clause — "no fees charged" vs. a stated £220 fee
  elsewhere), caught confidently in only 1 of 3 runs, abstaining
  (`insufficient_evidence`) the other 2 — a safe miss, not a wrong one.

**Revised conclusion**: the true false-accusation rate (~3-8%, depending on
denominator) is meaningfully lower than the earlier ~20% estimate, which
was always flagged as low-confidence given its n=5 sample size. The
underlying root cause Session 8/9 diagnosed (retrieval noise from
mismatched worked examples) is confirmed and now precisely quantified via
the confidence-score analysis above, rather than just inferred from
instability. The failure mode observed in both real false-accusation cases
is consistently a *defensible strict reading of ambiguous evidence*, not
random hallucination — worth keeping in mind if `price_and_value`'s prompt
is tuned later (P8-04).

## Does this validate or invalidate `CONFIDENCE_THRESHOLD = 0.65`?

**Neither uniformly — it is well-calibrated for 2 of the 4 outcomes and
actively counterproductive for the other 2.**

- **Validated for `consumer_support` and `products_and_services`**: correct
  judgments average comfortably above 0.65 (0.674, 0.683), so the threshold
  adds a modest, low-cost extra abstention margin (4.4%→13.3% and
  unchanged at 13.3% respectively) without discarding much real signal.
  Its one blind spot is real, though: `products_and_services`' single false
  negative (`loan_agreement_11`) sits at confidence 0.662 — above 0.65 —
  so the threshold does **not** catch it. A global threshold tuned to this
  outcome's distribution would need to sit above 0.662 to catch this
  specific miss, which would push its abstention rate up considerably.
- **Invalidated for `price_and_value` and `consumer_understanding`**:
  correct-judgment confidence sits at or below 0.65 for both (0.644, 0.622),
  so the threshold cannot separate signal from noise here — it discards
  91% and 100% of judgments respectively, including the overwhelming
  majority that were correct. For `consumer_understanding` specifically,
  the threshold converts a 97.8%-accurate, 0%-abstention check into one
  that never gives a usable answer.
- The threshold-sweep data (`eval_summary.json`) shows the underlying
  cliff clearly across *all* outcomes combined: 0% of correct judgments
  are overridden at threshold ≤ 0.60, but 44.5% are overridden at 0.65 and
  99.3% at 0.70 — confidence scores in this corpus cluster tightly in the
  0.60-0.70 band, so there is no threshold in that range that cleanly
  separates correct from incorrect without also discarding a large share
  of correct judgments for at least some outcomes.

**This is evidence for an outcome-specific threshold, not a single global
one** — the same conclusion Session 8/9 anticipated but couldn't validate
without real data. A single global `CONFIDENCE_THRESHOLD` cannot be both
"catches products_and_services' one miss" and "doesn't silence
consumer_understanding entirely" at the same time, because the two
outcomes' correct-judgment confidence distributions don't overlap the same
way relative to any single cutoff. This is a finding to act on in a future
session, not something changed in this one — 0.65 is left as-is here,
since changing it is a design decision the evaluation informs but doesn't
by itself authorize.

## Retrieval recall@k (P8-02, unchanged from prior session, included for reference)

| Outcome | recall@1 | @2 | @3 | @5 | @10 |
|---|---|---|---|---|---|
| price_and_value | 0.0 | 0.25 | 0.25 | 0.75 | 1.0 |
| consumer_support | 0.0 | 0.5 | 0.5 | 1.0 | 1.0 |
| products_and_services | 0.0 | 0.0 | 0.25 | 0.5 | 1.0 |
| consumer_understanding | 0.33 | 0.67 | 0.67 | 0.67 | 1.0 |

Notably, `products_and_services` has the weakest recall@k of the 4 outcomes
at the production `k=5` (0.5), yet its confidence-score and
accuracy/FP/FN numbers in this pass are among the best. Recall@k measures
whether the truly relevant chunk is retrieved at all; confidence measures
the similarity score of whatever the LLM actually cited. The two can and do
diverge — weak recall doesn't necessarily translate into weak downstream
confidence if the chunks the LLM ends up citing (even if not the single
"most relevant" one by the recall@k ground truth) still score reasonably
well. This is worth remembering before assuming recall@k alone predicts
downstream judgment reliability.

## P8-03 scope note

This project's practically relevant "hallucination" is a compliance
judgment asserting a violation the document doesn't actually have —
exactly what the false-positive rate above measures per outcome (an
agent-invented non-compliance finding, contradicted by ground truth). The
false-negative rate is the mirror case: a real violation the agent failed
to surface. Together, per-outcome accuracy/FP-rate/FN-rate against 45
human-labelled samples is this evaluation's answer to P8-03, in place of a
separate Ragas/LLM-as-judge groundedness score — the FP/FN analysis above
directly answers the question that matters here ("does the agent invent or
miss compliance findings"), and doing so against real ground truth is a
stronger check than a groundedness-only metric would have been on its own.

## Not run this session

- **P8-04 (prompt variant comparison)**: the harness's `variants`
  subcommand and Variant B system prompt (targeting the diagnosed
  worked-example mismatch) are built and ready, reusing this pass's cached
  `price_and_value` first-pass context — no new extraction/retrieval calls
  needed, only the judgment call itself repeated per variant. Not run in
  this session; a natural next step given the price_and_value findings
  above.

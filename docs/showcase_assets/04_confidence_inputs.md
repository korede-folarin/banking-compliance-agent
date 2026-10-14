# Asset 4: confidence inputs

All loan documents, borrowers and lenders referred to here are synthetic (data/synthetic_docs/). Regulatory text is from the FCA corpus in data/regulatory_corpus/.

## What feeds the confidence score

`src/agent/compliance.py` `compute_confidence` / `validate_outcome`:
- **One input:** the retrieval similarity score of each source the judge cited (cosine similarity between the retrieval query and the chunk, from the vector store).
- **Aggregation:** the minimum over cited sources; 0.0 if none cited.
- **Rule:** if confidence < 0.65, the status is replaced by `insufficient_evidence`.

Not inputs: the judge's own status or reasoning, claim-to-chunk similarity (Signal 1), the quote check, the LLM claim check, and extraction confidence (`src/agent/uncertainty.py`, which is not called by the main path).

## Five judgments from the full pass

| Doc / run / outcome | Ground truth | Judge status | Correct? | Cited similarities | Confidence (min) | Final status |
|---|---|---|---|---|---|---|
| loan_agreement_1 / 1 / price_and_value | non_compliant | potentially_non_compliant | yes | 0.6853, 0.6760, 0.6753 | 0.6753 | potentially_non_compliant |
| loan_agreement_4 / 0 / price_and_value | non_compliant | potentially_non_compliant | yes | 0.6400, 0.6420, 0.6349 | 0.6349 | insufficient_evidence |
| loan_agreement_13 / 1 / consumer_support | compliant | compliant | yes | 0.7044, 0.6997 | 0.6997 | compliant |
| loan_agreement_13 / 2 / consumer_support | compliant | potentially_non_compliant | no | 0.7044, 0.7038, 0.7030, 0.6995 | 0.6995 | potentially_non_compliant |
| loan_agreement_11 / 1 / price_and_value | compliant | potentially_non_compliant | no | 0.6539, 0.6453, 0.6444 | 0.6444 | insufficient_evidence |

## Across all 45 runs (from `eval_raw_main_pass_v2_summary.json`)

| Outcome | Correct: mean confidence (n) | Incorrect: mean confidence (n) |
|---|---|---|
| price_and_value | 0.6408 (44) | 0.6444 (1) |
| consumer_support | 0.6803 (42) | 0.6926 (3) |
| products_and_services | 0.6796 (45) | none (0) |
| consumer_understanding | 0.6237 (39) | 0.6198 (4) |

| Threshold | Correct judgments overridden | Incorrect judgments caught |
|---|---|---|
| 0.5 | 0.000 | 0.000 |
| 0.55 | 0.000 | 0.000 |
| 0.6 | 0.000 | 0.000 |
| 0.65 | 0.500 | 0.625 |
| 0.7 | 1.000 | 1.000 |
| 0.75 | 1.000 | 1.000 |
| 0.8 | 1.000 | 1.000 |

## What the score does and does not separate (facts from the tables above)

- It separates judgments by how closely the cited chunks matched the retrieval query. Below 0.65 the judgment is withheld and routed to review.
- It does not separate correct from incorrect judgments in this pass: per outcome, the mean confidence of correct and incorrect judgments differs by at most 0.0123.
- Rows 3 and 4 are the same document and outcome: confidence 0.6997 (correct) and 0.6995 (incorrect). Both pass the threshold.
- Row 2 is correct and is overridden (0.6349). Row 5 is incorrect and is overridden (0.6444).
- At 0.65, 0.5 of correct judgments are overridden and 0.625 of incorrect judgments are caught.

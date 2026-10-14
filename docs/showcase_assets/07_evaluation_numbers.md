# Asset 7: evaluation numbers (full pass v2)

All loan documents, borrowers and lenders referred to here are synthetic (data/synthetic_docs/). Regulatory text is from the FCA corpus in data/regulatory_corpus/.

Source: `docs/eval_raw_main_pass_v2_summary.json`. Runs: 45 (15 documents x 3). Completeness warnings recorded in the file: ['main pass: 2 failure(s) logged in eval_raw_main_pass_v2_errors.jsonl'].

Positive class = non-compliant. `llm_status` = the judge's verdict; `post_threshold_status` = after the confidence override. Abstain = `insufficient_evidence`.

| Outcome | Stage | n | TP | TN | FP | FN | Abstain | Accuracy (excl. abstain) | FPR | FNR | Abstention rate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| price_and_value | llm_status | 45 | 12 | 32 | 1 | 0 | 0 | 0.978 | 0.030 | 0.000 | 0.000 |
| price_and_value | post_threshold_status | 45 | 3 | 0 | 0 | 0 | 42 | 1.000 | n/a | 0.000 | 0.933 |
| consumer_support | llm_status | 45 | 12 | 30 | 3 | 0 | 0 | 0.933 | 0.091 | 0.000 | 0.000 |
| consumer_support | post_threshold_status | 45 | 7 | 30 | 3 | 0 | 5 | 0.925 | 0.091 | 0.000 | 0.111 |
| products_and_services | llm_status | 45 | 6 | 39 | 0 | 0 | 0 | 1.000 | 0.000 | 0.000 | 0.000 |
| products_and_services | post_threshold_status | 45 | 6 | 39 | 0 | 0 | 0 | 1.000 | 0.000 | 0.000 | 0.000 |
| consumer_understanding | llm_status | 45 | 6 | 33 | 4 | 0 | 2 | 0.907 | 0.108 | 0.000 | 0.044 |
| consumer_understanding | post_threshold_status | 45 | 0 | 0 | 0 | 0 | 45 | n/a | n/a | n/a | 1.000 |

## Recall@k (retrieval)

| Query set | @1 | @2 | @3 | @5 | @10 |
|---|---|---|---|---|---|
| price_and_value | 0.000 | 0.250 | 0.250 | 0.750 | 1.000 |
| consumer_support | 0.000 | 0.500 | 0.500 | 1.000 | 1.000 |
| products_and_services | 0.000 | 0.000 | 0.250 | 0.500 | 1.000 |
| consumer_understanding | 0.333 | 0.667 | 0.667 | 0.667 | 1.000 |
| off_topic_control | 0 | 0 | 0 | 0 | 0 |

Confidence by correctness and the threshold sweep are in `04_confidence_inputs.md`.

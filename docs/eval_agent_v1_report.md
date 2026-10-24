# Agentic tool loop: evaluation on fixtures v2

Input: `docs/eval_agent_v1.jsonl` (15 runs; 0 failed runs logged; 143 claim checks). Labels: `tests/fixtures/eval_set_v2.json`, written before any run. Counts and rates only.

## Agent vs baseline on the same v1 documents

Baseline: the fixed pipeline's full pass (`docs/eval_raw_main_pass_v2.jsonl`). Same documents and ground truth; the two systems differ in more than one way (see ARCHITECTURE.md), so a difference reflects the whole design, not one variable.

Runs differ between the two systems, so compare the rates: accuracy = (TP+TN)/(TP+TN+FP+FN), abstention = Abstain/runs.

| Outcome | Stage | System | Runs | TP | TN | FP | FN | Abstain | Accuracy (excl. abstain) | Abstention |
|---|---|---|---|---|---|---|---|---|---|---|
| price_and_value | llm | agent | 15 | 2 | 11 | 0 | 0 | 2 | 1.000 | 0.133 |
| price_and_value | llm | baseline | 45 | 12 | 32 | 1 | 0 | 0 | 0.978 | 0.000 |
| price_and_value | post | agent | 15 | 2 | 11 | 0 | 0 | 2 | 1.000 | 0.133 |
| price_and_value | post | baseline | 45 | 3 | 0 | 0 | 0 | 42 | 1.000 | 0.933 |
| consumer_support | llm | agent | 15 | 2 | 10 | 0 | 0 | 3 | 1.000 | 0.200 |
| consumer_support | llm | baseline | 45 | 12 | 30 | 3 | 0 | 0 | 0.933 | 0.000 |
| consumer_support | post | agent | 15 | 2 | 10 | 0 | 0 | 3 | 1.000 | 0.200 |
| consumer_support | post | baseline | 45 | 7 | 30 | 3 | 0 | 5 | 0.925 | 0.111 |
| products_and_services | llm | agent | 15 | 1 | 10 | 3 | 0 | 1 | 0.786 | 0.067 |
| products_and_services | llm | baseline | 45 | 6 | 39 | 0 | 0 | 0 | 1.000 | 0.000 |
| products_and_services | post | agent | 15 | 1 | 10 | 3 | 0 | 1 | 0.786 | 0.067 |
| products_and_services | post | baseline | 45 | 6 | 39 | 0 | 0 | 0 | 1.000 | 0.000 |
| consumer_understanding | llm | agent | 15 | 0 | 8 | 5 | 2 | 0 | 0.533 | 0.000 |
| consumer_understanding | llm | baseline | 45 | 6 | 33 | 4 | 0 | 2 | 0.907 | 0.044 |
| consumer_understanding | post | agent | 15 | 0 | 8 | 5 | 2 | 0 | 0.533 | 0.000 |
| consumer_understanding | post | baseline | 45 | 0 | 0 | 0 | 0 | 45 | n/a | 1.000 |

## Signal 1: reasoning vs the passages it cites

Cosine similarity (local embeddings, zero API cost) between each outcome's reasoning and each regulation or policy passage it cites; per judgment, the lowest. The same ruler as the baseline (`groundedness.compute_signal1_cited`). No threshold: a coarse topical signal, not proof of support.

| Outcome | System | Judgments | Median of lowest | Lowest |
|---|---|---|---|---|
| price_and_value | agent | 15 | 0.7436 | 0.6753 |
| price_and_value | baseline | 45 | 0.7931 | 0.7574 |
| consumer_support | agent | 15 | 0.7413 | 0.6956 |
| consumer_support | baseline | 45 | 0.8121 | 0.74 |
| products_and_services | agent | 15 | 0.7283 | 0.6707 |
| products_and_services | baseline | 45 | 0.797 | 0.7659 |
| consumer_understanding | agent | 15 | 0.6893 | 0.617 |
| consumer_understanding | baseline | 45 | 0.7508 | 0.6521 |

## overall

### Tool calling

| Tool | Required runs | Called when required | Correct argument | Unnecessary-call runs | Called when unnecessary | Total calls |
|---|---|---|---|---|---|---|
| search_regulation | 15 | 15 | - | 0 | 0 | 60 |
| get_account | 0 | 0 | - | 15 | 0 | 0 |
| search_policy | 0 | 0 | - | 15 | 0 | 0 |

Regulation searched for all 4 outcomes (one search each): 15 / 15 runs; by outcome: price_and_value 15, consumer_support 15, products_and_services 15, consumer_understanding 15.

Runs: 15; tool calls: 60; unnecessary calls (validation layer): 0 in 0 runs; runs stopped by a limit: 0; model turns: 30.

### Outcomes

Positive = non-compliant. `llm` = the agent's verdict; `post` = after the validation layer's quote and citation rules. Auto-approval is disabled: every case goes to a human. Confidence is reported against the uncalibrated 0.65 reference but never replaces a verdict.

Forced by rule: verdicts replaced with insufficient_evidence because a quote or citation rule failed. Below 0.65: outcomes whose confidence is under the reference value (reported only).

| Outcome | Stage | TP | TN | FP | FN | Abstain | Forced by rule | Below 0.65 (reported only) |
|---|---|---|---|---|---|---|---|---|
| price_and_value | llm | 2 | 11 | 0 | 0 | 2 | - | - |
| price_and_value | post | 2 | 11 | 0 | 0 | 2 | 0 | 9 |
| consumer_support | llm | 2 | 10 | 0 | 0 | 3 | - | - |
| consumer_support | post | 2 | 10 | 0 | 0 | 3 | 0 | 12 |
| products_and_services | llm | 1 | 10 | 3 | 0 | 1 | - | - |
| products_and_services | post | 1 | 10 | 3 | 0 | 1 | 0 | 5 |
| consumer_understanding | llm | 0 | 8 | 5 | 2 | 0 | - | - |
| consumer_understanding | post | 0 | 8 | 5 | 2 | 0 | 0 | 10 |

### Escalation

Decision correct: 15 / 15.
- expected not_applicable: 15 / 15 correct
- triggers exactly right when escalating: 0 / 0
- discrepancy reported when expected: 0 / 0

### Groundedness

- outcomes whose every regulatory quote is in the passage it names: 60 / 60
- escalation decisions whose every policy quote is in the policy passage it names: 0 / 0
- narrow claim check: yes 130, partially 12, no 1; claims naming no returned passage (not sent): 0

### Validation checks failed

- none

## Per document (overall)

- **loan_agreement_1** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support o), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_10** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_11** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support c), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_12** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "target market), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_13** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "target market), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_14** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "target market), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_15** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_2** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support o), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "consumer und) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_3** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "supporting custome), search_regulation({"outcome": "products_and_services", "query": "target market), search_regulation({"outcome": "consumer_understanding", "query": "clear commun) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_4** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "target market), search_regulation({"outcome": "consumer_understanding", "query": "clear commun) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_5** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value fees and), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_6** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value fees cha), search_regulation({"outcome": "consumer_support", "query": "customer support v), search_regulation({"outcome": "products_and_services", "query": "target market), search_regulation({"outcome": "consumer_understanding", "query": "clear commun) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_7** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support o), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_8** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support o), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "consumer und) -> escalation `not_applicable` (expected `not_applicable`)
- **loan_agreement_9** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "target market), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`)

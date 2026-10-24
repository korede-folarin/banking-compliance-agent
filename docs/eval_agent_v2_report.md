# Agentic tool loop: evaluation on fixtures v2

Input: `docs/eval_agent_v2.jsonl` (57 runs; 0 failed runs logged; 160 claim checks). Labels: `tests/fixtures/eval_set_v2.json`, written before any run. Counts and rates only.

## Signal 1: reasoning vs the passages it cites

Cosine similarity (local embeddings, zero API cost) between each outcome's reasoning and each regulation or policy passage it cites; per judgment, the lowest. The same ruler as the baseline (`groundedness.compute_signal1_cited`). No threshold: a coarse topical signal, not proof of support.

| Outcome | System | Judgments | Median of lowest | Lowest |
|---|---|---|---|---|
| price_and_value | agent | 54 | 0.7356 | 0.6189 |
| consumer_support | agent | 54 | 0.7206 | 0.6289 |
| products_and_services | agent | 54 | 0.6908 | 0.5906 |
| consumer_understanding | agent | 54 | 0.685 | 0.5879 |

## Run-to-run agreement

Pairs (document, outcome) where every run gave the same verdict: 71, with 12 wrong verdicts. Pairs where runs disagreed: 5, with 1 wrong verdicts and 6 abstentions. Full table: `docs/eval_agreement_eval_agent_v2.md`.

## overall

### Tool calling

| Tool | Required runs | Called when required | Correct argument | Unnecessary-call runs | Called when unnecessary | Total calls |
|---|---|---|---|---|---|---|
| search_regulation | 54 | 54 | - | 3 | 0 | 216 |
| get_account | 45 | 45 | 45 | 12 | 6 | 51 |
| search_policy | 48 | 48 | - | 9 | 4 | 52 |

Regulation searched for all 4 outcomes (one search each): 54 / 54 runs; by outcome: price_and_value 54, consumer_support 54, products_and_services 54, consumer_understanding 54.

Runs: 57; tool calls: 319; unnecessary calls (validation layer): 10 in 6 runs; runs stopped by a limit: 0; model turns: 112.

### Outcomes

Positive = non-compliant. `llm` = the agent's verdict; `post` = after the validation layer's quote and citation rules. Auto-approval is disabled: every case goes to a human. Confidence is reported against the uncalibrated 0.65 reference but never replaces a verdict.

Forced by rule: verdicts replaced with insufficient_evidence because a quote or citation rule failed. Below 0.65: outcomes whose confidence is under the reference value (reported only).

| Outcome | Stage | TP | TN | FP | FN | Abstain | Forced by rule | Below 0.65 (reported only) |
|---|---|---|---|---|---|---|---|---|
| price_and_value | llm | 9 | 44 | 0 | 0 | 1 | - | - |
| price_and_value | post | 8 | 43 | 0 | 0 | 3 | 2 | 23 |
| consumer_support | llm | 1 | 42 | 0 | 0 | 11 | - | - |
| consumer_support | post | 1 | 42 | 0 | 0 | 11 | 0 | 46 |
| products_and_services | llm | 0 | 48 | 0 | 0 | 6 | - | - |
| products_and_services | post | 0 | 48 | 0 | 0 | 6 | 0 | 18 |
| consumer_understanding | llm | 1 | 37 | 9 | 4 | 3 | - | - |
| consumer_understanding | post | 1 | 37 | 8 | 4 | 4 | 1 | 38 |

### Escalation

Decision correct: 50 / 57.
- expected escalate: 18 / 18 correct
- expected no_escalation: 21 / 21 correct
- expected cannot_determine: 5 / 12 correct
- expected not_applicable: 6 / 6 correct
- triggers exactly right when escalating: 18 / 18
- discrepancy reported when expected: 6 / 6

### Groundedness

- outcomes whose every regulatory quote is in the passage it names: 212 / 216
- escalation decisions whose every policy quote is in the policy passage it names: 45 / 45
- narrow claim check: yes 145, partially 14, no 1; claims naming no returned passage (not sent): 0

### Validation checks failed

- escalation_decision_fits_document: 4
- no_unnecessary_calls: 6
- quotes_in_named_passages: 4
- regulation_from_own_search: 1

## design

### Tool calling

| Tool | Required runs | Called when required | Correct argument | Unnecessary-call runs | Called when unnecessary | Total calls |
|---|---|---|---|---|---|---|
| search_regulation | 27 | 27 | - | 3 | 0 | 108 |
| get_account | 21 | 21 | 21 | 9 | 3 | 24 |
| search_policy | 24 | 24 | - | 6 | 1 | 25 |

Regulation searched for all 4 outcomes (one search each): 27 / 27 runs; by outcome: price_and_value 27, consumer_support 27, products_and_services 27, consumer_understanding 27.

Runs: 30; tool calls: 157; unnecessary calls (validation layer): 4 in 3 runs; runs stopped by a limit: 0; model turns: 58.

### Outcomes

Positive = non-compliant. `llm` = the agent's verdict; `post` = after the validation layer's quote and citation rules. Auto-approval is disabled: every case goes to a human. Confidence is reported against the uncalibrated 0.65 reference but never replaces a verdict.

Forced by rule: verdicts replaced with insufficient_evidence because a quote or citation rule failed. Below 0.65: outcomes whose confidence is under the reference value (reported only).

| Outcome | Stage | TP | TN | FP | FN | Abstain | Forced by rule | Below 0.65 (reported only) |
|---|---|---|---|---|---|---|---|---|
| price_and_value | llm | 6 | 21 | 0 | 0 | 0 | - | - |
| price_and_value | post | 6 | 21 | 0 | 0 | 0 | 0 | 13 |
| consumer_support | llm | 1 | 21 | 0 | 0 | 5 | - | - |
| consumer_support | post | 1 | 21 | 0 | 0 | 5 | 0 | 24 |
| products_and_services | llm | 0 | 24 | 0 | 0 | 3 | - | - |
| products_and_services | post | 0 | 24 | 0 | 0 | 3 | 0 | 11 |
| consumer_understanding | llm | 0 | 18 | 6 | 3 | 0 | - | - |
| consumer_understanding | post | 0 | 18 | 5 | 3 | 1 | 1 | 23 |

### Escalation

Decision correct: 30 / 30.
- expected escalate: 9 / 9 correct
- expected no_escalation: 12 / 12 correct
- expected cannot_determine: 3 / 3 correct
- expected not_applicable: 6 / 6 correct
- triggers exactly right when escalating: 9 / 9
- discrepancy reported when expected: 0 / 0

### Groundedness

- outcomes whose every regulatory quote is in the passage it names: 106 / 108
- escalation decisions whose every policy quote is in the policy passage it names: 21 / 21
- narrow claim check: yes 68, partially 10, no 0; claims naming no returned passage (not sent): 0

### Validation checks failed

- no_unnecessary_calls: 3
- quotes_in_named_passages: 2

## heldout

### Tool calling

| Tool | Required runs | Called when required | Correct argument | Unnecessary-call runs | Called when unnecessary | Total calls |
|---|---|---|---|---|---|---|
| search_regulation | 27 | 27 | - | 0 | 0 | 108 |
| get_account | 24 | 24 | 24 | 3 | 3 | 27 |
| search_policy | 24 | 24 | - | 3 | 3 | 27 |

Regulation searched for all 4 outcomes (one search each): 27 / 27 runs; by outcome: price_and_value 27, consumer_support 27, products_and_services 27, consumer_understanding 27.

Runs: 27; tool calls: 162; unnecessary calls (validation layer): 6 in 3 runs; runs stopped by a limit: 0; model turns: 54.

### Outcomes

Positive = non-compliant. `llm` = the agent's verdict; `post` = after the validation layer's quote and citation rules. Auto-approval is disabled: every case goes to a human. Confidence is reported against the uncalibrated 0.65 reference but never replaces a verdict.

Forced by rule: verdicts replaced with insufficient_evidence because a quote or citation rule failed. Below 0.65: outcomes whose confidence is under the reference value (reported only).

| Outcome | Stage | TP | TN | FP | FN | Abstain | Forced by rule | Below 0.65 (reported only) |
|---|---|---|---|---|---|---|---|---|
| price_and_value | llm | 3 | 23 | 0 | 0 | 1 | - | - |
| price_and_value | post | 2 | 22 | 0 | 0 | 3 | 2 | 10 |
| consumer_support | llm | 0 | 21 | 0 | 0 | 6 | - | - |
| consumer_support | post | 0 | 21 | 0 | 0 | 6 | 0 | 22 |
| products_and_services | llm | 0 | 24 | 0 | 0 | 3 | - | - |
| products_and_services | post | 0 | 24 | 0 | 0 | 3 | 0 | 7 |
| consumer_understanding | llm | 1 | 19 | 3 | 1 | 3 | - | - |
| consumer_understanding | post | 1 | 19 | 3 | 1 | 3 | 0 | 15 |

### Escalation

Decision correct: 20 / 27.
- expected escalate: 9 / 9 correct
- expected no_escalation: 9 / 9 correct
- expected cannot_determine: 2 / 9 correct
- triggers exactly right when escalating: 9 / 9
- discrepancy reported when expected: 6 / 6

### Groundedness

- outcomes whose every regulatory quote is in the passage it names: 106 / 108
- escalation decisions whose every policy quote is in the policy passage it names: 24 / 24
- narrow claim check: yes 77, partially 4, no 1; claims naming no returned passage (not sent): 0

### Validation checks failed

- escalation_decision_fits_document: 4
- no_unnecessary_calls: 3
- quotes_in_named_passages: 2
- regulation_from_own_search: 1

## Per document (overall)

- **v2_d01** run 0: search_regulation({"outcome": "price_and_value", "query": "fees charged at len), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "clear commun), get_account({"customer_id": "CUST-89997"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `escalate` (expected `escalate`)
- **v2_d01** run 1: search_regulation({"outcome": "price_and_value", "query": "fair value fees cha), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "clear commun), get_account({"customer_id": "CUST-89997"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `escalate` (expected `escalate`)
- **v2_d01** run 2: get_account({"customer_id": "CUST-89997"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fees charges must b), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "fees and cha) -> escalation `escalate` (expected `escalate`)
- **v2_d02** run 0: get_account({"customer_id": "CUST-69917"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `escalate` (expected `escalate`)
- **v2_d02** run 1: get_account({"customer_id": "CUST-69917"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "clear commun) -> escalation `escalate` (expected `escalate`)
- **v2_d02** run 2: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-69917"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `escalate` (expected `escalate`)
- **v2_d03** run 0: get_account({"customer_id": "CUST-35345"}), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `escalate` (expected `escalate`)
- **v2_d03** run 1: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-35345"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `escalate` (expected `escalate`)
- **v2_d03** run 2: get_account({"customer_id": "CUST-35345"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `escalate` (expected `escalate`)
- **v2_d04** run 0: get_account({"customer_id": "CUST-85351"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `escalate` (expected `escalate`)
- **v2_d04** run 1: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-85351"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `escalate` (expected `escalate`)
- **v2_d04** run 2: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support v), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-85351"}), search_policy({"query": "vulnerable customer escalation triggers"}) -> escalation `escalate` (expected `escalate`)
- **v2_d05** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-52981"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `escalate` (expected `escalate`)
- **v2_d05** run 1: get_account({"customer_id": "CUST-52981"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `escalate` (expected `escalate`)
- **v2_d05** run 2: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-52981"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `escalate` (expected `escalate`)
- **v2_d06** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-72079"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `escalate` (expected `escalate`)
- **v2_d06** run 1: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-72079"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `escalate` (expected `escalate`)
- **v2_d06** run 2: get_account({"customer_id": "CUST-72079"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `escalate` (expected `escalate`)
- **v2_d07** run 0: get_account({"customer_id": "CUST-22711"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d07** run 1: get_account({"customer_id": "CUST-22711"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d07** run 2: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support o), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-22711"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d08** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-64391"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d08** run 1: get_account({"customer_id": "CUST-64391"}), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "supporting custome), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d08** run 2: get_account({"customer_id": "CUST-64391"}), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d09** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-91642"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d09** run 1: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-91642"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d09** run 2: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-91642"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d10** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-91039"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d10** run 1: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-91039"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d10** run 2: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support o), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-91039"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d11** run 0: get_account({"customer_id": "CUST-87899"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fees charged must b), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "clear commun) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d11** run 1: get_account({"customer_id": "CUST-87899"}), search_regulation({"outcome": "price_and_value", "query": "fees must be clear ), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), search_policy({"query": "vulnerable customer escalation triggers"}) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d11** run 2: search_regulation({"outcome": "price_and_value", "query": "fair value fees cha), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-87899"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d12** run 0: get_account({"customer_id": "CUST-16999"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d12** run 1: get_account({"customer_id": "CUST-16999"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d12** run 2: get_account({"customer_id": "CUST-16999"}), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "supporting custome), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d13** run 0: search_regulation({"outcome": "price_and_value", "query": "fees charged must r), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-41065"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `cannot_determine` (expected `cannot_determine`)
- **v2_d13** run 1: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "clear commun), get_account({"customer_id": "CUST-41065"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `cannot_determine` (expected `cannot_determine`)
- **v2_d13** run 2: search_regulation({"outcome": "price_and_value", "query": "fees and charges mu), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-41065"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `not_applicable` (expected `cannot_determine`)
- **v2_d14** run 0: get_account({"customer_id": "CUST-86954"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support o), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `no_escalation` (expected `cannot_determine`)
- **v2_d14** run 1: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support o), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-86954"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `cannot_determine`)
- **v2_d14** run 2: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "clear commun), get_account({"customer_id": "CUST-86954"}), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `cannot_determine`)
- **v2_d15** run 0: get_account({"customer_id": "CUST-19654"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d15** run 1: get_account({"customer_id": "CUST-19654"}), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d15** run 2: get_account({"customer_id": "CUST-19654"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `no_escalation` (expected `no_escalation`)
- **v2_d16** run 0: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `cannot_determine` (expected `cannot_determine`)
- **v2_d16** run 1: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "supporting custome), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `cannot_determine` (expected `cannot_determine`)
- **v2_d16** run 2: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), search_policy({"query": "vulnerable customer escalation procedure triggers) -> escalation `cannot_determine` (expected `cannot_determine`)
- **v2_d17** run 0: get_account({"customer_id": "CUST-38997"}), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`); unnecessary: no account lookup is needed for this document
- **v2_d17** run 1: get_account({"customer_id": "CUST-38997"}), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support c), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`); unnecessary: no account lookup is needed for this document
- **v2_d17** run 2: get_account({"customer_id": "CUST-38997"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "customer support o), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `not_applicable` (expected `not_applicable`); unnecessary: no account lookup is needed for this document; Northbridge policy does not apply to this document
- **v2_d18** run 0: get_account({"customer_id": "CUST-85253"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "supporting custome), search_regulation({"outcome": "products_and_services", "query": "products and ), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `no_escalation` (expected `cannot_determine`); unnecessary: no account lookup is needed for this document; Northbridge policy does not apply to this document
- **v2_d18** run 1: get_account({"customer_id": "CUST-85253"}), search_policy({"query": "vulnerable customer escalation procedure triggers), search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "product desig), search_regulation({"outcome": "consumer_understanding", "query": "communicatio) -> escalation `no_escalation` (expected `cannot_determine`); unnecessary: no account lookup is needed for this document; Northbridge policy does not apply to this document
- **v2_d18** run 2: search_regulation({"outcome": "price_and_value", "query": "fair value assessme), search_regulation({"outcome": "consumer_support", "query": "support for custom), search_regulation({"outcome": "products_and_services", "query": "products desi), search_regulation({"outcome": "consumer_understanding", "query": "communicatio), get_account({"customer_id": "CUST-85253"}), search_policy({"query": "vulnerable customer escalation triggers"}) -> escalation `no_escalation` (expected `cannot_determine`); unnecessary: no account lookup is needed for this document; Northbridge policy does not apply to this document
- **v2_d19** run 0: no calls -> escalation `not_applicable` (expected `not_applicable`)
- **v2_d19** run 1: no calls -> escalation `not_applicable` (expected `not_applicable`)
- **v2_d19** run 2: no calls -> escalation `not_applicable` (expected `not_applicable`)

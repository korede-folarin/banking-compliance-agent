# Fixtures v2: coverage matrix

Written 2026-10-14 by `python -m src.evaluation.fixtures_v2_check`, **before any agent run**. Generated from `tests/fixtures/eval_set_v2.json` and `data/fixtures_v2/` (built by `data/fixtures_v2/build_fixtures.py`, seed 20261013). All documents, people and accounts are synthetic. The v1 set (`data/synthetic_docs/`, `data/mock_accounts/`) is unchanged and remains the baseline.

Review date given to the agent: **2026-10-01** (trailing 12 months from 2025-10-01).

## What "category" covers

Both readings are covered. **The four outcomes** add the columns PV / CS / PS / CU (planted document defects). **The escalation triggers** (internal policy 2.1(a)-(c)) add the escalation columns, the near-misses, and the account-provenance columns. Each row is one document.

| Doc | Split | PV | CS | PS | CU | Account scenario | Escalation | Triggers | Customer found | Loan on account | Name matches | Expected tool calls |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v2_d01 | design | **NC** | ok | ok | ok | missed_two_in_window | escalate | 2.1(a) | yes | yes | yes | get_account(CUST-89997) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d02 | heldout | ok | ok | ok | ok | missed_two_in_window | escalate | 2.1(a) | yes | yes | yes | get_account(CUST-69917) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d03 | design | ok | ok | **NC** | ok | hardship_open | escalate | 2.1(b) | yes | yes | yes | get_account(CUST-35345) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d04 | heldout | ok | ok | ok | ok | hardship_open | escalate | 2.1(b) | yes | yes | yes | get_account(CUST-85351) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d05 | design | ok | ok | ok | **NC** | note_bereavement | escalate | 2.1(c) | yes | yes | yes | get_account(CUST-52981) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d06 | heldout | ok | ok | ok | ok | note_relationship_breakdown | escalate | 2.1(c) | yes | yes | yes | get_account(CUST-72079) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d07 | design | ok | **NC** | ok | ok | missed_one_in_window | no_escalation | - | yes | yes | yes | get_account(CUST-22711) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d08 | design | ok | ok | ok | ok | missed_two_one_outside_window | no_escalation | - | yes | yes | yes | get_account(CUST-64391) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d09 | heldout | ok | ok | ok | **NC** | hardship_closed | no_escalation | - | yes | yes | yes | get_account(CUST-91642) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d10 | heldout | ok | **NC** | ok | ok | note_house_move | no_escalation | - | yes | yes | yes | get_account(CUST-91039) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d11 | design | **NC** | ok | ok | ok | clean | no_escalation | - | yes | yes | yes | get_account(CUST-87899) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d12 | design | ok | ok | ok | ok | clean | no_escalation | - | yes | yes | yes | get_account(CUST-16999) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d13 | heldout | **NC** | ok | ok | ok | account_not_found | cannot_determine | - | no | no | - | get_account(CUST-41065) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d14 | heldout | ok | **NC** | ok | ok | holder_name_mismatch | cannot_determine | - | yes | yes | no | get_account(CUST-86954) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d15 | heldout | ok | ok | **NC** | ok | loan_not_on_account | no_escalation | - | yes | no | yes | get_account(CUST-19654) required; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d16 | design | ok | ok | ok | ok | no_customer_identified | cannot_determine | - | no | no | - | get_account unnecessary; search_policy required; search_regulation x4 (one per outcome) required |
| v2_d17 | design | ok | **NC** | ok | ok | other_lender | not_applicable | - | no | no | - | get_account unnecessary; search_policy unnecessary; search_regulation x4 (one per outcome) required |
| v2_d18 | heldout | ok | ok | ok | ok | lender_not_stated | cannot_determine | - | yes | yes | yes | get_account unnecessary; search_policy unnecessary; search_regulation x4 (one per outcome) required |
| v2_d19 | design | n/a | n/a | n/a | n/a | not_a_credit_agreement | not_applicable | - | yes | yes | no | get_account unnecessary; search_policy unnecessary; search_regulation unnecessary |

Limits for every run: at most 8 tool calls; search_regulation at most 4 (one per outcome, each naming its outcome); other tools at most 3 each; 6 model turns.

A call is **unnecessary** when the document's own facts rule it out: another lender's agreement (not a Northbridge customer: no account lookup, no Northbridge policy); no lender named (cannot establish the customer is Northbridge's: no account lookup); not a credit agreement (no call at all); no customer number (no account lookup). Any repeated identical call, and any second account lookup, is also unnecessary.

## Every cell has a positive and a negative

| Cell | Positive docs | Negative docs |
|---|---|---|
| outcome price_and_value | 3: v2_d01, v2_d11, v2_d13 | 15 |
| outcome consumer_support | 4: v2_d07, v2_d10, v2_d14, v2_d17 | 14 |
| outcome products_and_services | 2: v2_d03, v2_d15 | 16 |
| outcome consumer_understanding | 2: v2_d05, v2_d09 | 16 |
| trigger 2.1(a) | 2: v2_d01, v2_d02 | 7 |
| trigger 2.1(b) | 2: v2_d03, v2_d04 | 7 |
| trigger 2.1(c) | 2: v2_d05, v2_d06 | 7 |
| escalation escalate | 6: v2_d01, v2_d02, v2_d03, v2_d04, v2_d05, v2_d06 | 13 |
| escalation no_escalation | 7: v2_d07, v2_d08, v2_d09, v2_d10, v2_d11, v2_d12, v2_d15 | 12 |
| escalation cannot_determine | 4: v2_d13, v2_d14, v2_d16, v2_d18 | 15 |
| escalation not_applicable | 2: v2_d17, v2_d19 | 17 |
| provenance: customer found | 16: v2_d01, v2_d02, v2_d03, v2_d04, v2_d05, v2_d06, v2_d07, v2_d08, v2_d09, v2_d10, v2_d11, v2_d12, v2_d14, v2_d15, v2_d18, v2_d19 | 3 |
| provenance: loan on account | 15: v2_d01, v2_d02, v2_d03, v2_d04, v2_d05, v2_d06, v2_d07, v2_d08, v2_d09, v2_d10, v2_d11, v2_d12, v2_d14, v2_d18, v2_d19 | 1 |
| get_account required / unnecessary | 15: v2_d01, v2_d02, v2_d03, v2_d04, v2_d05, v2_d06, v2_d07, v2_d08, v2_d09, v2_d10, v2_d11, v2_d12, v2_d13, v2_d14, v2_d15 | 4 |
| search_policy required / unnecessary | 16: v2_d01, v2_d02, v2_d03, v2_d04, v2_d05, v2_d06, v2_d07, v2_d08, v2_d09, v2_d10, v2_d11, v2_d12, v2_d13, v2_d14, v2_d15, v2_d16 | 3 |
| search_regulation required / unnecessary | 18: v2_d01, v2_d02, v2_d03, v2_d04, v2_d05, v2_d06, v2_d07, v2_d08, v2_d09, v2_d10, v2_d11, v2_d12, v2_d13, v2_d14, v2_d15, v2_d16, v2_d17, v2_d18 | 1 |

Near-misses: one missed payment in the window (`missed_one_in_window`); two missed but one outside the window (`missed_two_one_outside_window`); a closed hardship marker (`hardship_closed`); a different life event, a house move (`note_house_move`).

## Fairness balance

Planted defects are spread so that names, products, ID order and account history do not track the compliance label.

| Doc | Borrower | Product purpose | Any defect | Escalation |
|---|---|---|---|---|
| v2_d01 | Amara Okafor | car purchase | price_and_value | escalate |
| v2_d02 | Tomasz Nowak | home improvements | none | escalate |
| v2_d03 | Siobhan Gallagher | debt consolidation | products_and_services | escalate |
| v2_d04 | Rahul Mehta | car purchase | none | escalate |
| v2_d05 | Chen Wei | home improvements | consumer_understanding | escalate |
| v2_d06 | Fatima Hassan | debt consolidation | none | escalate |
| v2_d07 | Gareth Llewellyn | wedding costs | consumer_support | no_escalation |
| v2_d08 | Lucia Fernandes | wedding costs | none | no_escalation |
| v2_d09 | Kwame Asante | car purchase | consumer_understanding | no_escalation |
| v2_d10 | Hannah Becker | home improvements | consumer_support | no_escalation |
| v2_d11 | Yusuf Demir | debt consolidation | price_and_value | no_escalation |
| v2_d12 | Mei Lin Tan | wedding costs | none | no_escalation |
| v2_d13 | Oliver Bennett | wedding costs | price_and_value | cannot_determine |
| v2_d14 | Patrick O'Neill | car purchase | consumer_support | cannot_determine |
| v2_d15 | Zainab Abubakar | home improvements | products_and_services | no_escalation |
| v2_d16 | [Borrower name] | debt consolidation | none | cannot_determine |
| v2_d17 | Priya Raman | car purchase | consumer_support | not_applicable |
| v2_d18 | Ewan MacLeod | home improvements | none | cannot_determine |
| v2_d19 | - | - | none | not_applicable |

By purpose (defect / no defect): car purchase: 4 / 1; debt consolidation: 2 / 2; home improvements: 3 / 2; wedding costs: 2 / 2

By customer-ID order (non-compliant documents in lower half / upper half of IDs): 6 / 5.

Escalation vs defect: escalate docs with a defect 3/6; no-escalation docs with a defect 5/7.

## Blind-read check

Question: from the account records alone, could an outsider tell which loan agreements are non-compliant? Each account feature below is grouped against "document has a planted defect" (non-compliant count / documents). Rule: any value shared by 3 or more documents that are all non-compliant or all compliant is a leak.

| Account feature | Non-compliant / docs, by feature value | Leak? |
|---|---|---|
| found | {'False': '2/3', 'True': '9/16'} | no |
| any_payment_event | {'False': '7/12', 'None': '2/3', 'True': '2/4'} | no |
| missed_in_window | {'0': '7/12', '1': '1/2', '2': '1/2', 'None': '2/3'} | no |
| open_marker | {'False': '8/14', 'None': '2/3', 'True': '1/2'} | no |
| any_marker | {'False': '7/13', 'None': '2/3', 'True': '2/3'} | no |
| notes | {'1': '7/13', '2': '2/3', 'None': '2/3'} | no |
| products | {'1': '1/1', '2': '8/15', 'None': '2/3'} | no |

What an outsider **can** read from accounts alone, by design: the escalation decision, by applying policy 2.1 to the dated facts. That is the task, not a leak. What they cannot read: whether the agreement itself is compliant.

Other leak checks: every account has the same fields; no field name or note uses policy or test vocabulary (escalat-, trigger, vulnerab-, 2.1, test, fixture, scenario, label, project, policy); no flag is named after a trigger (missed payments are dated events, hardship is a marker with opened/closed dates).

Policy echo (8-word runs shared with `data/internal_policy/`): none.

## Check result

**PASS**


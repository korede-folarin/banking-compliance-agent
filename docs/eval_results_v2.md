# Evaluation results: baseline and agentic tool loop (2026-10-24)

Facts only. Every number below comes from a file in `docs/`, named in each section. Model:
`claude-sonnet-5`. Labels were written before any run. All documents and accounts are synthetic.

## What was run

| System | Documents | Runs | Output |
|---|---|---|---|
| Baseline (fixed workflow) | 15 (v1) | 3 each, 45 | `eval_raw_main_pass_v2.jsonl` (7 Oct) |
| Agent (model chooses MCP tools) | 15 (v1, same as baseline) | 1 each, 15 | `eval_agent_v1.jsonl` |
| Agent | 19 (v2: 10 design, 9 held-out) | 3 each, 57 | `eval_agent_v2.jsonl` |

Live agent spend on 24 Oct, estimated from logged tokens: ~$8.97 of a $12.00 approved cap, as follows.

| Item | Spend |
|---|---|
| Pilot (3 runs) | $0.32 |
| v1 (15 runs) | $1.94 |
| v2 run 0 (16 runs) | $1.65 |
| v2 runs 1–2 (38 runs) | $3.79 |
| Claim checks (305 claims) | $1.16 |
| Negative control (30 calls) | $0.11 |

Every paid command ran under a hard `--max-usd` cap.

## 1. Tool calling (agent, v2, 57 runs; `eval_agent_v2_report.md`)

The model chose its own tools. The deterministic validation layer judged each call.

| Tool | Required in | Called when required | Correct argument | Not needed in | Called anyway |
|---|---|---|---|---|---|
| search_regulation | 54 runs | 54 | 54/54 searched all 4 outcomes, one search each | 3 | 0 |
| get_account | 45 | 45 | 45 (the document's customer number) | 12 | 6 |
| search_policy | 48 | 48 | n/a | 9 | 4 |

- **Required calls:** 100% made, with 100% correct customer numbers.
- **Unnecessary calls:** 10, in 6 runs, all on two non-Northbridge documents:
  - v2_d17: 3 runs;
  - v2_d18: 3 runs, held-out.

  The model looked up an account or the Northbridge policy that did not apply. The validation layer flagged every one.
- **Limits:** 0 runs stopped by a limit. 112 model turns over 57 runs.
- **v1 (15 runs):** 4 regulation searches in every run, and 0 unnecessary calls.

## 2. Escalation (agent, v2)

| Expected | Correct |
|---|---|
| escalate | 18 / 18, with triggers exactly right in 18 / 18 |
| no_escalation | 21 / 21 |
| not_applicable | 6 / 6 |
| cannot_determine | 5 / 12 |
| **all** | **50 / 57** |

**Discrepancy reported when expected:** 6 / 6.

**All 7 escalation errors are on held-out documents labelled `cannot_determine`:**
- v2_d14: `no_escalation` in 3 of 3 runs;
- v2_d18: `no_escalation` in 3 of 3 runs;
- v2_d13: `not_applicable` in 1 of 3 runs.

In 6 of the 7, the agent decided "no escalation" where the right answer was "cannot determine". **The design split: 30 / 30. Held-out: 20 / 27.**

## 3. Compliance verdicts: agent vs baseline on the same 15 v1 documents (`eval_agent_v1_report.md`)

Judge verdict before any override. Accuracy excludes abstentions. Positive = non-compliant.

| Outcome | System | Runs | FP | FN | Abstain | Accuracy |
|---|---|---|---|---|---|---|
| Price and value | agent | 15 | 0 | 0 | 2 | 1.000 |
| | baseline | 45 | 1 | 0 | 0 | 0.978 |
| Consumer support | agent | 15 | 0 | 0 | 3 | 1.000 |
| | baseline | 45 | 3 | 0 | 0 | 0.933 |
| Products and services | agent | 15 | 3 | 0 | 1 | 0.786 |
| | baseline | 45 | 0 | 0 | 0 | 1.000 |
| Consumer understanding | agent | 15 | 5 | **2** | 0 | 0.533 |
| | baseline | 45 | 4 | 0 | 2 | 0.907 |

- **Missed breaches:**
  - **The agent missed 2 real breaches (consumer understanding).** The baseline missed none.
  - **On v2, the agent missed 4 consumer-understanding breaches** in 57 runs. Every agent false negative is in consumer understanding.
- **Abstention:** the agent abstains more on price and value and consumer support (13–20% vs 0%).
- **Comparing the two:** the agent has 1 run per document here and the baseline 3, so compare rates. The systems differ in more than one way (tools, prompts, evidence format), so a difference reflects the whole design, not one variable.

## 4. Groundedness

**Quote location (deterministic; splice rule B):**
- **Agent, v2:** 212 / 216 outcomes had every regulatory quote in the passage named, and 45 / 45 escalations had every policy quote in the policy passage.
- **Agent, v1:** 60 / 60 outcomes.
- **Baseline:** 540 / 542 quotes (`..._checks_rule_b_report.md`).

**Narrow per-claim LLM check (run 0):**

| | Claims | yes | partially | no |
|---|---|---|---|---|
| Agent v2 | 160 | 145 | 14 | 1 |
| Agent v1 | 143 | 130 | 12 | 1 |
| Baseline | 536 | 484 | 52 | 0 |

**Signal 1** (embedding similarity of reasoning to cited passages, lowest per judgment; no threshold). The agent's medians are 0.69–0.74 on v1, against the baseline's 0.75–0.81 on the same documents. It is a coarse topical signal, not proof of support.

## 5. Run-to-run agreement

| System | Pairs agreeing | Wrong in agreeing pairs | Wrong in disagreeing pairs |
|---|---|---|---|
| Baseline (v1, 60 pairs) | 52 | 0 | 8 |
| Agent (v2, 76 pairs) | 71 | 12 | 1 |

**For the baseline,** every error was where runs disagreed. **For the agent, 12 of 13 errors are repeated in every run.** These are the consumer-understanding false positives and false negatives. Disagreement between runs flags the baseline's errors; **it does not flag the agent's.** Files: `eval_agreement_eval_raw_main_pass_v2.md`, `eval_agreement_eval_agent_v2.md`.

## 6. Checking the checker: negative control (`negative_control_report.md`)

| Group (10 pairs each) | Required | Result |
|---|---|---|
| Claim vs unrelated passage | `no` ≥ 10 | 9 `no`, 1 `partially`: **FAIL** |
| Claim vs neighbouring passage | `no` ≥ 7 | 10 `no`: PASS |
| Claim vs its own passage | `yes` ≥ 9 | 10 `yes`: PASS |

- **The checker said `yes` to no wrong passage.** With the deterministic quote check added (the combined gate), all three groups pass.
- **The criteria were written before the run** (`negative_control_criteria.md`).

## 7. Calibration (`eval_calibration_eval_raw_main_pass_v2.md`)

On the baseline, no outcome qualifies to skip human review at a 1%, 2% or 5% missed-issue target:
- the bound is 20.6% or more with at most 13 approvals;
- 59 / 149 / 299 approved documents with zero misses would be needed.

The agent's missed breaches above make this stricter, not looser. Auto-approval stays off.

## What this does not show

- **Synthetic data:** 34 documents with planted defects, which is not evidence about real agreements.
- **Agent v1 has one run per document.**
- **Escalation is checked** against synthetic accounts and one internal policy.

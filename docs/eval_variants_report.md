# Prompt variant comparison: price and value (P8-04, 2026-10-24)

Source: `docs/eval_raw_main_pass_v2_variants.jsonl` (`python -m src.evaluation.run_eval variants --n-runs 1`).
This was 30 judge calls: 15 v1 documents × 2 prompts × 1 run. It reuses each document's cached first
pass (extraction and retrieval), so only the prompt differs.

| Variant | What it asks |
|---|---|
| A_production | The production judging prompt, unchanged |
| B_scenario_match | Additionally: check whether each regulation excerpt is about the same kind of product and scenario (a fixed-rate personal loan) before treating it as a requirement; prefer `insufficient_evidence` when it is not. It aims at false alarms from excerpts about other products. |

## Result

The judge's verdict, before the 0.65 confidence override. Positive = non-compliant.

| Variant | TP | TN | FP | FN | Abstain | Accuracy |
|---|---|---|---|---|---|---|
| A_production | 4 | 11 | 0 | 0 | 0 | 1.000 |
| B_scenario_match | 4 | 11 | 0 | 0 | 0 | 1.000 |

**Same verdict on all 15 documents.** Confidence matched to within 0.008. After the 0.65 override,
B kept one more correct `potentially_non_compliant` (loan_agreement_5: confidence 0.651 against A's
0.646), but that is the threshold's on/off behaviour, not the prompt.

## What this does and doesn't show

- **On these 15 documents, the variant made no difference.** There was nothing for it to fix: the
  production prompt made no false alarms on price and value in this run. In the full pass it made 1
  false alarm in 45 runs.
- **With one run per variant, a difference would need to be large to show.** This result cannot rule
  out a small effect.
- **The production prompt stays as it is.** The extra instruction adds length without a measured
  benefit.
- **Cost:** the variants command does not open an audit run, so its spend was not logged. At the
  measured cost of similar judge calls it is roughly $1.

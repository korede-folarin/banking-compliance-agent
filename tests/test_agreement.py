"""Run-to-run agreement (P8-10): offline, on hand-built rows and on the saved main pass (read only)."""

from src.evaluation import agreement
from src.evaluation.run_eval import MAIN_PASS_PATH
from tests.fixtures.eval_set import OUTCOME_KEYS

PNC, C, IE = "potentially_non_compliant", "compliant", "insufficient_evidence"


def _rows(verdicts_by_run, labels):
    """verdicts_by_run[run][doc] -> one status applied to every outcome; labels[doc] -> label."""
    return [{"doc_id": doc, "run_idx": run, "ground_truth": {k: labels[doc] for k in OUTCOME_KEYS},
             "outcomes": {k: {"llm_status": status} for k in OUTCOME_KEYS}}
            for run, by_doc in enumerate(verdicts_by_run) for doc, status in by_doc.items()]


def test_agreement_counts_wrong_and_abstained_by_group():
    rows = _rows([{"a": C, "b": PNC, "c": C}, {"a": C, "b": PNC, "c": IE}, {"a": C, "b": PNC, "c": PNC}],
                 {"a": "compliant", "b": "non_compliant", "c": "compliant"})
    pairs = agreement.pair_table(rows)
    s = agreement.summarise(pairs)
    assert s["agree"] == {"pairs": 8, "verdicts": 24, "wrong": 0, "abstained": 0}
    assert s["disagree"] == {"pairs": 4, "verdicts": 12, "wrong": 4, "abstained": 4}
    assert s["disagree_majority_correct"] == 0  # one of each verdict: no single majority
    assert s["agree_wrong_upper_95"] == round(3 / 8, 4)


def test_agreeing_runs_on_a_wrong_verdict_are_counted():
    rows = _rows([{"a": PNC}, {"a": PNC}, {"a": PNC}], {"a": "compliant"})
    s = agreement.summarise(agreement.pair_table(rows))
    assert s["agree_wrong_pairs"] == 4 and s["agree"]["wrong"] == 12 and s["agree_wrong_upper_95"] is None


def test_saved_main_pass_numbers(tmp_path):
    out = tmp_path / "agreement.md"
    agreement.main(["--input", str(MAIN_PASS_PATH.with_name("eval_raw_main_pass_v2.jsonl")), "--output", str(out)])
    text = out.read_text(encoding="utf-8")
    assert "| Runs agree | 52 | 156 | 0 | 0 |" in text
    assert "| Runs disagree | 8 | 24 | 8 | 2 |" in text
    assert "correct in 7 of 8" in text

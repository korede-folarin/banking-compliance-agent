"""Calibration report (P8-11): the bound, the gates, and the saved main pass (read only)."""

import pytest

from src.evaluation import calibration
from src.evaluation.run_eval import MAIN_PASS_PATH
from tests.fixtures.eval_set import OUTCOME_KEYS


def test_upper_bound_matches_known_values():
    assert calibration.upper_bound(0, 15) == pytest.approx(0.1810, abs=1e-4)
    assert calibration.upper_bound(1, 20) == pytest.approx(0.2161, abs=1e-3)  # exact Clopper-Pearson
    assert calibration.upper_bound(0, 0) is None
    assert [calibration.docs_needed(t) for t in (0.01, 0.02, 0.05)] == [299, 149, 59]


def _row(doc, run, status, conf, label):
    return {"doc_id": doc, "run_idx": run, "ground_truth": {k: label for k in OUTCOME_KEYS},
            "outcomes": {k: {"llm_status": status, "confidence": conf} for k in OUTCOME_KEYS}}


def test_gates_count_missed_issues_and_never_approve_a_flag():
    rows = [_row("a", i, "compliant", 0.9, "non_compliant") for i in range(3)]          # missed issue
    rows += [_row("b", i, "compliant", 0.5, "compliant") for i in range(3)]             # low confidence
    rows += [_row("c", i, "potentially_non_compliant", 0.9, "compliant") for i in range(3)]  # flag: never approved
    rows += [_row("d", 0, "compliant", 0.9, "compliant"), _row("d", 1, "compliant", 0.9, "compliant"),
             _row("d", 2, "insufficient_evidence", 0.9, "compliant")]                   # runs disagree
    r = calibration.gate_counts(rows, threshold=0.65)["price_and_value"]
    assert (r["three_runs_agree"]["approved"], r["three_runs_agree"]["missed"]) == (2, 1)  # a, b
    assert (r["three_runs_conf"]["approved"], r["three_runs_conf"]["missed"]) == (1, 1)    # a
    assert (r["one_run_conf"]["approved"], r["one_run_conf"]["missed"]) == (1, 1)          # worst run: a only
    assert r["three_runs_agree"]["qualifies"] == {0.01: False, 0.02: False, 0.05: False}


def test_saved_main_pass_no_category_qualifies(tmp_path):
    out = tmp_path / "calibration.md"
    calibration.main(["--input", str(MAIN_PASS_PATH.with_name("eval_raw_main_pass_v2.jsonl")), "--output", str(out)])
    text = out.read_text(encoding="utf-8")
    for t in ("1%", "2%", "5%"):
        assert f"**Target {t}:** no category qualifies under any gate." in text
    assert "| products_and_services | 15 (2) | three_runs_agree | 13 | 0 | 20.6% |" in text

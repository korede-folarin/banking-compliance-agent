"""
Offline tests for deferred-checklist item 11 (ARCHITECTURE.md "Evaluation
notes"): `run_eval.py main` must write a new pass to a new file by default,
never touch the Phase 8 data, resume against the NEW file only, and warn
loudly about anything it skips.

No API calls and no model loading: FirstPassAgent, ComplianceAgent and
build_compliance_report are replaced with fakes, and the Phase 8 / v2 paths
are pointed at temporary files. The real docs/eval_raw_main_pass.jsonl is
hashed before and after to prove it is untouched.
"""

import argparse
import hashlib
import json

import pytest

from src.evaluation import run_eval
from tests.fixtures.eval_set import EVAL_DOCUMENTS, OUTCOME_KEYS

REAL_PHASE8_PATH = run_eval.MAIN_PASS_PATH
TEST_DOCS = EVAL_DOCUMENTS[:2]
N_RUNS = 2
ALL_PAIRS = {(d["id"], r) for d in TEST_DOCS for r in range(N_RUNS)}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_rows(path, pairs, marker):
    path.write_text(
        "".join(json.dumps({"doc_id": d, "run_idx": r, "marker": marker}) + "\n" for d, r in sorted(pairs)),
        encoding="utf-8",
    )


class _Dumpable:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return self._data


class _FakeOutcome:
    llm_status = "compliant"
    status = "compliant"
    confidence = 0.7
    reasoning = "fake reasoning"
    cited_sources = [_Dumpable({"index": 1, "file_name": "fake.pdf", "similarity_score": 0.7, "text_excerpt": "x"})]


class _FakeReport:
    needs_human_review = False

    def __init__(self):
        for key in OUTCOME_KEYS:
            setattr(self, key, _FakeOutcome())


class _FakeFirstPass:
    price_and_value_context = _Dumpable({"sources": []})
    document_fields = _Dumpable({"fake": True})


@pytest.fixture(scope="module", autouse=True)
def real_phase8_file_untouched():
    before = _sha256(REAL_PHASE8_PATH)
    yield
    assert _sha256(REAL_PHASE8_PATH) == before, "the real Phase 8 main-pass file was modified"


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    calls = {"n": 0, "fail_on": set()}

    class FakeFirstPassAgent:
        def run(self, text):
            calls["n"] += 1
            return _FakeFirstPass()

    class FakeComplianceAgent:
        def evaluate(self, first_pass):
            return {}

    def fake_report(first_pass, judgments):
        return _FakeReport()

    phase8 = tmp_path / "phase8_main_pass.jsonl"
    _write_rows(phase8, ALL_PAIRS, "phase8")  # like the real file: every pair already present
    monkeypatch.setattr(run_eval, "MAIN_PASS_PATH", phase8)
    monkeypatch.setattr(run_eval, "MAIN_PASS_ERRORS_PATH", tmp_path / "phase8_main_pass_errors.jsonl")
    monkeypatch.setattr(run_eval, "MAIN_PASS_V2_PATH", tmp_path / "main_pass_v2.jsonl")
    monkeypatch.setattr(run_eval, "EVAL_DOCUMENTS", TEST_DOCS)
    monkeypatch.setattr(run_eval, "FirstPassAgent", FakeFirstPassAgent)
    monkeypatch.setattr(run_eval, "ComplianceAgent", FakeComplianceAgent)
    monkeypatch.setattr(run_eval, "build_compliance_report", fake_report)
    return {"calls": calls, "phase8": phase8, "v2": tmp_path / "main_pass_v2.jsonl", "tmp": tmp_path}


def _run_main(output=None):
    run_eval.cmd_main(argparse.Namespace(n_runs=N_RUNS, output=output))


def test_real_default_output_is_new_file_not_phase8():
    assert run_eval.MAIN_PASS_V2_PATH.name == "eval_raw_main_pass_v2.jsonl"
    assert run_eval.MAIN_PASS_V2_PATH != run_eval.MAIN_PASS_PATH
    output_path, errors_path = run_eval._resolve_main_output(None)
    assert output_path == run_eval.MAIN_PASS_V2_PATH
    assert errors_path.name == "eval_raw_main_pass_v2_errors.jsonl"


@pytest.mark.parametrize("given", [str(REAL_PHASE8_PATH), "docs/eval_raw_main_pass.jsonl"])
def test_writing_to_phase8_file_is_refused(given, monkeypatch):
    monkeypatch.chdir(REAL_PHASE8_PATH.parent.parent)
    with pytest.raises(SystemExit, match="Refusing"):
        run_eval._resolve_main_output(given)


def test_fresh_run_uses_new_file_and_ignores_phase8_rows(fake_env, capsys):
    phase8_before = _sha256(fake_env["phase8"])
    _run_main()
    out = capsys.readouterr().out

    assert fake_env["calls"]["n"] == len(ALL_PAIRS)  # nothing skipped despite Phase 8 having every pair
    rows = _rows(fake_env["v2"])
    assert {(r["doc_id"], r["run_idx"]) for r in rows} == ALL_PAIRS
    assert len(rows) == len(ALL_PAIRS)
    assert _sha256(fake_env["phase8"]) == phase8_before
    assert "WARNING" not in out
    assert str(fake_env["v2"]) in out


def test_resume_is_against_new_file_and_skips_are_announced(fake_env, capsys):
    already = {(TEST_DOCS[0]["id"], 0)}
    _write_rows(fake_env["v2"], already, "earlier_v2_run")
    _run_main()
    out = capsys.readouterr().out

    assert fake_env["calls"]["n"] == len(ALL_PAIRS) - 1
    rows = _rows(fake_env["v2"])
    assert len(rows) == len(ALL_PAIRS)  # no duplicate for the skipped pair
    assert {(r["doc_id"], r["run_idx"]) for r in rows} == ALL_PAIRS
    assert "WARNING" in out and "1 of the 4" in out
    assert f"{TEST_DOCS[0]['id']} run 0" in out
    assert "NO API calls" not in out


def test_every_pair_present_warns_that_nothing_will_run(fake_env, capsys):
    _write_rows(fake_env["v2"], ALL_PAIRS, "earlier_v2_run")
    before = _sha256(fake_env["v2"])
    _run_main()
    out = capsys.readouterr().out

    assert fake_env["calls"]["n"] == 0
    assert _sha256(fake_env["v2"]) == before
    assert "4 of the 4" in out and "NO API calls" in out


def test_failures_are_logged_next_to_the_output_file(fake_env, monkeypatch):
    class FailingFirstPassAgent:
        def run(self, text):
            raise RuntimeError("simulated malformed generation")

    monkeypatch.setattr(run_eval, "FirstPassAgent", FailingFirstPassAgent)
    _run_main()

    errors = _rows(fake_env["tmp"] / "main_pass_v2_errors.jsonl")
    assert {(e["doc_id"], e["run_idx"]) for e in errors} == ALL_PAIRS
    assert not (fake_env["tmp"] / "phase8_main_pass_errors.jsonl").exists()
    assert not fake_env["v2"].exists()


def test_explicit_output_path_is_honoured(fake_env):
    custom = fake_env["tmp"] / "custom_pass.jsonl"
    _run_main(output=str(custom))
    assert len(_rows(custom)) == len(ALL_PAIRS)
    assert not fake_env["v2"].exists()

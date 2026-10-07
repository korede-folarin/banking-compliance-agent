"""
Offline tests for deferred-checklist item 13 (ARCHITECTURE.md "Evaluation
notes"): every main-pass reader (`run_eval summary`, `run_eval variants`,
groundedness.py, claim_verification.py) defaults to the file `run_eval main`
now writes (docs/eval_raw_main_pass_v2.jsonl), can still read the Phase 8
file when given it explicitly with --input, and `summary` never overwrites
the Phase 8 docs/eval_summary.json.

No API calls, no Chroma queries, no model loading: LLM clients, retrievers
and agents are faked, and every write goes to a temp directory. The real
Phase 8 main-pass file and docs/eval_summary.json are hashed before and
after, and docs/ is checked for new files.
"""

import argparse
import hashlib
import json
import shutil
import sys

import pytest

from src.agent.compliance import OutcomeJudgment
from src.evaluation import claim_verification as cv
from src.evaluation import groundedness
from src.evaluation import run_eval
from tests.fixtures.eval_set import EVAL_DOCUMENTS, OUTCOME_KEYS

REAL_PHASE8_PATH = run_eval.MAIN_PASS_PATH
REAL_SUMMARY_PATH = run_eval.SUMMARY_PATH
REAL_V2_PATH = run_eval.MAIN_PASS_V2_PATH
DOCS_DIR = run_eval.DOCS_OUT_DIR


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture(scope="module", autouse=True)
def phase8_files_untouched():
    phase8_before = _sha256(REAL_PHASE8_PATH)
    summary_before = _sha256(REAL_SUMMARY_PATH)
    docs_before = sorted(p.name for p in DOCS_DIR.iterdir())
    yield
    assert _sha256(REAL_PHASE8_PATH) == phase8_before, "Phase 8 main-pass file was modified"
    assert _sha256(REAL_SUMMARY_PATH) == summary_before, "Phase 8 eval_summary.json was modified"
    assert sorted(p.name for p in DOCS_DIR.iterdir()) == docs_before, "a file was created or removed in docs/"


@pytest.fixture
def v2_file(tmp_path, monkeypatch):
    """Point the v2 default at a temp file (resolve_main_input reads it at call time)."""
    path = tmp_path / "eval_raw_main_pass_v2.jsonl"
    monkeypatch.setattr(run_eval, "MAIN_PASS_V2_PATH", path)
    return path


def _v2_rows_marked():
    """Phase 8 run-0 rows with every cached excerpt and status replaced by v2 markers."""
    rows = []
    for r in _rows(REAL_PHASE8_PATH):
        if r["run_idx"] != 0:
            continue
        r = json.loads(json.dumps(r))
        for s in r["_cached_price_and_value_context"]["sources"]:
            s["text_excerpt"] = f"V2-MARKER-{r['doc_id']}-{s['index']}"
        for o in r["outcomes"].values():
            o["llm_status"] = "insufficient_evidence"
            o["status"] = "insufficient_evidence"
        rows.append(r)
    return rows


# --- defaults: every reader's CLI resolves to the v2 path ---

@pytest.mark.parametrize(
    "module, argv, func_name",
    [
        (run_eval, ["run_eval", "summary"], "cmd_summary"),
        (run_eval, ["run_eval", "variants"], "cmd_variants"),
        (groundedness, ["groundedness", "plan"], "cmd_plan"),
        (groundedness, ["groundedness", "run"], "cmd_run"),
        (cv, ["claim_verification", "plan"], "cmd_plan"),
        (cv, ["claim_verification", "judge"], "cmd_judge"),
    ],
)
def test_each_reader_defaults_to_v2_path(module, argv, func_name, monkeypatch):
    captured = {}
    monkeypatch.setattr(module, func_name, lambda args: captured.setdefault("args", args))
    monkeypatch.setattr(sys, "argv", argv)
    module.main()
    assert captured["args"].input is None
    assert run_eval.resolve_main_input(captured["args"].input) == REAL_V2_PATH
    assert REAL_V2_PATH.name == "eval_raw_main_pass_v2.jsonl"


@pytest.mark.parametrize(
    "module, argv, func_name",
    [
        (run_eval, ["run_eval", "summary"], "cmd_summary"),
        (run_eval, ["run_eval", "variants"], "cmd_variants"),
        (groundedness, ["groundedness", "run"], "cmd_run"),
        (cv, ["claim_verification", "judge"], "cmd_judge"),
    ],
)
def test_each_reader_accepts_explicit_phase8_input(module, argv, func_name, monkeypatch):
    captured = {}
    monkeypatch.setattr(module, func_name, lambda args: captured.setdefault("args", args))
    monkeypatch.setattr(sys, "argv", argv + ["--input", "docs/eval_raw_main_pass.jsonl"])
    module.main()
    assert run_eval.resolve_main_input(captured["args"].input).name == REAL_PHASE8_PATH.name


# --- summary ---

def test_summary_output_path_is_derived_and_never_the_phase8_summary():
    assert run_eval._summary_output_for(REAL_V2_PATH) == DOCS_DIR / "eval_raw_main_pass_v2_summary.json"
    phase8_out = run_eval._summary_output_for(REAL_PHASE8_PATH)
    assert phase8_out == DOCS_DIR / "eval_raw_main_pass_summary.json"
    assert phase8_out != REAL_SUMMARY_PATH
    with pytest.raises(SystemExit, match="Refusing"):
        run_eval._summary_output_for(DOCS_DIR / "eval.jsonl")  # would derive docs/eval_summary.json


def test_summary_on_v2_input_writes_new_distinct_file(v2_file, capsys):
    rows = [r for r in _rows(REAL_PHASE8_PATH) if r["run_idx"] == 0][:3]
    _write_rows(v2_file, rows)
    run_eval.cmd_summary(argparse.Namespace(input=None))

    out_path = v2_file.with_name("eval_raw_main_pass_v2_summary.json")
    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8"))["n_main_runs"] == 3
    assert str(v2_file) in capsys.readouterr().out


def test_summary_on_explicit_phase8_data_reproduces_existing_summary(tmp_path):
    # Copy, so the derived output lands in tmp_path rather than docs/.
    phase8_copy = tmp_path / REAL_PHASE8_PATH.name
    shutil.copyfile(REAL_PHASE8_PATH, phase8_copy)
    run_eval.cmd_summary(argparse.Namespace(input=str(phase8_copy)))

    produced = json.loads((tmp_path / "eval_raw_main_pass_summary.json").read_text(encoding="utf-8"))
    assert produced == json.loads(REAL_SUMMARY_PATH.read_text(encoding="utf-8"))


# --- variants (fake LLM client) ---

class _FakeInstructorClient:
    def __init__(self):
        self.user_messages = []
        self.messages = self

    def create(self, **kwargs):
        self.user_messages.append(kwargs["messages"][0]["content"])
        return OutcomeJudgment(
            status="compliant", reasoning="fake", cited_sources=[1],
            document_facts=[], regulatory_requirements=[], absences=[],
        )


@pytest.fixture
def fake_llm(monkeypatch):
    import anthropic
    import instructor

    client = _FakeInstructorClient()
    monkeypatch.setattr(instructor, "from_anthropic", lambda *_a, **_k: client)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *_a, **_k: None)
    return client


def test_variants_reads_explicit_phase8_file(fake_llm, tmp_path, monkeypatch):
    run_eval.cmd_variants(
        argparse.Namespace(n_runs=1, input=str(REAL_PHASE8_PATH), output=str(tmp_path / "variants.jsonl"))
    )

    assert len(fake_llm.user_messages) == len(EVAL_DOCUMENTS) * len(run_eval.VARIANTS)
    joined = "\n".join(fake_llm.user_messages)
    for r in _rows(REAL_PHASE8_PATH):
        if r["run_idx"] == 0:
            assert r["_cached_price_and_value_context"]["sources"][0]["text_excerpt"] in joined
    assert "V2-MARKER" not in joined


def test_variants_defaults_to_v2_file(fake_llm, v2_file, tmp_path, monkeypatch):
    _write_rows(v2_file, _v2_rows_marked())
    run_eval.cmd_variants(argparse.Namespace(n_runs=1, input=None, output=str(tmp_path / "variants.jsonl")))

    joined = "\n".join(fake_llm.user_messages)
    assert "V2-MARKER-loan_agreement_1-1" in joined
    phase8_excerpt = next(
        r for r in _rows(REAL_PHASE8_PATH) if r["run_idx"] == 0
    )["_cached_price_and_value_context"]["sources"][0]["text_excerpt"]
    assert phase8_excerpt not in joined


# --- groundedness.py (build_scope faked: no Chroma, no embeddings) ---

@pytest.fixture
def captured_scope_input(monkeypatch):
    captured = {}

    def fake_build_scope(main_records, **_kwargs):
        captured["records"] = main_records
        return []

    monkeypatch.setattr(groundedness, "build_scope", fake_build_scope)
    monkeypatch.setattr(
        groundedness, "_write_report", lambda scope, output_path: captured.setdefault("report_written", output_path)
    )
    return captured


def test_groundedness_plan_reads_explicit_phase8_file_unchanged(captured_scope_input, tmp_path):
    # Session 26: `plan` saves Signal 1 next to its input by default; keep it out of docs/.
    groundedness.cmd_plan(argparse.Namespace(input=str(REAL_PHASE8_PATH), signal1_output=str(tmp_path / "s1.jsonl")))
    assert captured_scope_input["records"] == _rows(REAL_PHASE8_PATH)


def test_groundedness_plan_and_run_default_to_v2(captured_scope_input, v2_file, fake_llm):
    v2_rows = _v2_rows_marked()[:2]
    _write_rows(v2_file, v2_rows)
    groundedness.cmd_plan(argparse.Namespace(input=None))
    assert captured_scope_input["records"] == v2_rows

    captured_scope_input.clear()
    groundedness.cmd_run(argparse.Namespace(input=None, output=None))
    assert captured_scope_input["records"] == v2_rows
    assert fake_llm.user_messages == []  # empty scope: no claim checks


def test_groundedness_missing_v2_file_fails_loudly(v2_file):
    with pytest.raises(SystemExit):
        groundedness.cmd_plan(argparse.Namespace(input=None))


# --- claim_verification.py (retriever and judge faked) ---

class _FakeNode:
    def __init__(self, i):
        self.node = type("N", (), {"node_id": f"fake-node-{i}"})()
        self.metadata = {"file_name": "fake.pdf"}
        self.score = 0.7
        self.text = f"fake regulatory excerpt {i}"


class _FakeIndex:
    def as_retriever(self, similarity_top_k):
        return self

    def retrieve(self, question):
        return [_FakeNode(i) for i in range(1, 6)]


class _FakeComplianceAgent:
    def evaluate(self, first_pass, document_text):
        return {
            k: OutcomeJudgment(
                status="compliant", reasoning="fake", cited_sources=[1],
                document_facts=[], regulatory_requirements=[], absences=[],
            )
            for k in OUTCOME_KEYS
        }


@pytest.fixture
def fake_pilot(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "load_index", lambda: _FakeIndex())
    monkeypatch.setattr(cv, "ComplianceAgent", _FakeComplianceAgent)
    monkeypatch.setattr(cv, "PILOT_JUDGMENTS_PATH", tmp_path / "pilot_judgments.jsonl")
    return tmp_path / "pilot_judgments.jsonl"


def test_claim_verification_cached_run_reads_explicit_phase8_file():
    row = cv._cached_run("loan_agreement_1", 0, REAL_PHASE8_PATH)
    expected = next(r for r in _rows(REAL_PHASE8_PATH) if r["doc_id"] == "loan_agreement_1" and r["run_idx"] == 0)
    assert row == expected


def test_claim_verification_judge_explicit_phase8(fake_pilot):
    cv.cmd_judge(argparse.Namespace(docs=["loan_agreement_1"], input=str(REAL_PHASE8_PATH)))
    row = _rows(fake_pilot)[0]
    phase8 = cv._cached_run("loan_agreement_1", 0, REAL_PHASE8_PATH)
    assert row["main_pass_input"] == REAL_PHASE8_PATH.name
    assert row["fields"] == phase8["_cached_fields"]
    for k in OUTCOME_KEYS:
        assert row["outcomes"][k]["reference_llm_status"] == phase8["outcomes"][k]["llm_status"]


def test_claim_verification_judge_defaults_to_v2(fake_pilot, v2_file):
    _write_rows(v2_file, _v2_rows_marked())
    cv.cmd_judge(argparse.Namespace(docs=["loan_agreement_1"], input=None))
    row = _rows(fake_pilot)[0]
    assert row["main_pass_input"] == v2_file.name
    assert all(row["outcomes"][k]["reference_llm_status"] == "insufficient_evidence" for k in OUTCOME_KEYS)

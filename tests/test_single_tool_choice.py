"""
Offline tests for the Session 26 parallel-tool-call fix: every instructor
structured call (judge, MCP judge, extraction, variants, claim check,
groundedness check) passes `tool_choice` forcing its own response model's
tool with `disable_parallel_tool_use: True`, and instructor sends that
`tool_choice` to the API unchanged.

No API calls: each call site runs against a fake client that records the
keyword arguments it was given (the MCP tools are faked too). Instructor's
real Anthropic request preparation is exercised, but nothing is sent. The
real Phase 8 file is only read; protected files are hashed before and after,
and docs/ is checked for new files.
"""

import argparse
import hashlib
import json
from types import SimpleNamespace

import pytest

from src.agent import compliance, intake
from src.agent.compliance import OutcomeJudgment
from src.agent.first_pass import FirstPassResult
from src.agent.schemas import LoanAgreementFields
from src.agent.structured_output import single_tool_choice
from src.evaluation import claim_verification as cv
from src.evaluation import groundedness, run_eval
from src.retrieval.query_engine import QueryResult, SourceCitation
from tests.fixtures.eval_set import EVAL_DOCUMENTS, OUTCOME_KEYS

PROTECTED = [run_eval.MAIN_PASS_PATH, run_eval.SUMMARY_PATH, run_eval.DOCS_OUT_DIR / "eval_groundedness.md"]
PHASE8_RUN0 = [
    r for r in (json.loads(line) for line in run_eval.MAIN_PASS_PATH.read_text(encoding="utf-8").splitlines() if line.strip())
    if r["run_idx"] == 0
]
FIELDS = LoanAgreementFields(**PHASE8_RUN0[0]["_cached_fields"])


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def protected_files_untouched():
    before = {p: _sha256(p) for p in PROTECTED}
    docs_before = sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir())
    yield
    assert {p: _sha256(p) for p in PROTECTED} == before
    assert sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir()) == docs_before


class _Recorder:
    """Fake instructor client: records every create() call's kwargs, returns a valid instance."""

    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        model = kwargs["response_model"]
        if model is OutcomeJudgment:
            return OutcomeJudgment(status="compliant", reasoning="r", cited_sources=[1],
                                   document_facts=[], regulatory_requirements=[], absences=[])
        if model is LoanAgreementFields:
            return FIELDS
        if model is cv.ClaimCheck:
            return cv.ClaimCheck(verdict="yes", supporting_sentence="")
        return SimpleNamespace(verdict="yes")  # groundedness's local ClaimVerdict


def _assert_single_tool(call):
    name = call["response_model"].__name__
    assert call["tool_choice"] == {"type": "tool", "name": name, "disable_parallel_tool_use": True}


def test_helper_shape():
    assert single_tool_choice(OutcomeJudgment) == {
        "type": "tool", "name": "OutcomeJudgment", "disable_parallel_tool_use": True,
    }


def test_instructor_sends_our_tool_choice_unchanged():
    # The real instructor Anthropic TOOLS-mode request preparation, no network.
    from instructor.v2.providers.anthropic.handlers import AnthropicToolsHandler

    for model in (OutcomeJudgment, LoanAgreementFields, cv.ClaimCheck):
        _, prepared = AnthropicToolsHandler().prepare_request(
            model, {"messages": [{"role": "user", "content": "x"}], "tool_choice": single_tool_choice(model)},
        )
        assert prepared["tool_choice"] == single_tool_choice(model)
        assert [t["name"] for t in prepared["tools"]] == [model.__name__]  # tool_choice names a real tool


def _first_pass():
    ctx = {
        f"{k}_context": QueryResult(
            question="q", answer="a", confidence=0.7, needs_human_review=False,
            sources=[SourceCitation(index=1, file_name="f.pdf", similarity_score=0.7, text_excerpt="t")],
        )
        for k in OUTCOME_KEYS
    }
    return FirstPassResult(document_fields=FIELDS, **ctx)


def test_judge_calls_carry_the_setting():
    agent = compliance.ComplianceAgent.__new__(compliance.ComplianceAgent)
    agent._client = _Recorder()
    agent.evaluate(_first_pass(), "full document text")
    assert len(agent._client.calls) == 4
    for call in agent._client.calls:
        _assert_single_tool(call)


def test_mcp_judge_call_carries_the_setting(monkeypatch):
    qr = QueryResult(question="q", answer="a", confidence=0.7, needs_human_review=False,
                     sources=[SourceCitation(index=1, file_name="f.pdf", similarity_score=0.7, text_excerpt="t")])
    monkeypatch.setattr(compliance, "call_tools", lambda calls: [json.dumps({"found": False}), qr.model_dump_json(), qr.model_dump_json()])
    agent = compliance.ComplianceAgent.__new__(compliance.ComplianceAgent)
    agent._client = _Recorder()
    agent.judge_price_and_value_with_mcp_context(FIELDS, "Nobody")
    assert len(agent._client.calls) == 1
    _assert_single_tool(agent._client.calls[0])


def test_extraction_call_carries_the_setting():
    agent = intake.IntakeAgent.__new__(intake.IntakeAgent)
    agent._client = _Recorder()
    agent.extract("loan agreement text")
    _assert_single_tool(agent._client.calls[0])
    assert agent._client.calls[0]["response_model"] is LoanAgreementFields


def test_variants_calls_carry_the_setting(monkeypatch, tmp_path):
    import anthropic
    import instructor

    rec = _Recorder()
    monkeypatch.setattr(instructor, "from_anthropic", lambda *_a, **_k: rec)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *_a, **_k: None)
    v2 = tmp_path / "pass.jsonl"
    v2.write_text("".join(json.dumps(r) + "\n" for r in PHASE8_RUN0), encoding="utf-8")
    run_eval.cmd_variants(argparse.Namespace(n_runs=1, input=str(v2), output=str(tmp_path / "v.jsonl")))
    assert len(rec.calls) == len(EVAL_DOCUMENTS) * len(run_eval.VARIANTS)
    for call in rec.calls:
        _assert_single_tool(call)


def test_claim_check_call_carries_the_setting():
    rec = _Recorder()
    cv._check_claim(rec, "a claim", ["chunk text"])
    _assert_single_tool(rec.calls[0])
    assert rec.calls[0]["response_model"] is cv.ClaimCheck


def test_groundedness_check_call_carries_the_setting():
    rec = _Recorder()
    groundedness.check_claim(rec, "a claim", "source text")
    _assert_single_tool(rec.calls[0])
    assert rec.calls[0]["response_model"].__name__ == "ClaimVerdict"


def test_no_structured_call_is_left_without_it():
    # Every `response_model=` in src/ is followed by the tool_choice line.
    from pathlib import Path

    src = Path(run_eval.__file__).resolve().parent.parent
    for path in src.rglob("*.py"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "response_model=" in line and line.strip().startswith("response_model="):
                assert "tool_choice=single_tool_choice(" in lines[i + 1], f"{path.name}:{i + 1}"

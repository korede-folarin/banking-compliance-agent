"""
The paid evaluation commands leave an audit record (docs/audit_logging_design.md):
claim_verification check, groundedness run and negative_control run each write
a run header, a completeness check, and an end event with their status, plus
one line in index.jsonl. A command that crashes is recorded as failed.

No API calls: the LLM client is faked and every file lives in a temp
directory (conftest sends audit logs there too).
"""

import argparse
import json

import pytest

from src import config
from src.evaluation import claim_verification as cv
from src.evaluation import groundedness as gr
from src.evaluation import negative_control as nc
from tests.test_claim_check_store import TOTAL_CLAIMS, _FakeClient, env  # noqa: F401  (env is a fixture)


def _index():
    path = config.LOG_DIR / "index.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _events(entry):
    path = config.LOG_DIR / entry["log"]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _check_event(events, name):
    return next(e["data"] for e in events if e["event"] == "check" and e["data"]["name"] == name)


def test_claim_check_run_is_logged(env):  # noqa: F811
    cv.cmd_check(argparse.Namespace(docs=None, output=None))
    [entry] = _index()
    assert entry["command"] == "claim_verification check" and entry["status"] == "completed"
    events = _events(entry)
    assert events[0]["event"] == "start" and events[-1]["event"] == "end"
    check = _check_event(events, "claim_checks_complete")
    assert check["passed"] is True and check["metric"] == f"{TOTAL_CLAIMS}/{TOTAL_CLAIMS}"


def test_claim_check_crash_is_logged_as_failed(env):  # noqa: F811
    env["state"]["client"] = _FakeClient(crash_on=3)
    with pytest.raises(RuntimeError):
        cv.cmd_check(argparse.Namespace(docs=None, output=None))
    [entry] = _index()
    assert entry["status"] == "failed"


def test_groundedness_run_is_logged(tmp_path, monkeypatch):
    import anthropic
    import instructor

    class _Verdicts:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            return kwargs["response_model"](verdict="yes")

    scope = [{"doc_id": "loan_agreement_1", "run_idx": 0, "outcome": "price_and_value", "signal1": 0.8,
              "llm_status": "compliant", "reasoning": "r", "claims": ["claim a", "claim b"],
              "sources": [{"text_excerpt": "text"}]}]
    monkeypatch.setattr(gr, "_load_main_records", lambda args: [])
    monkeypatch.setattr(gr, "build_scope", lambda records, p8_05_scope=False: scope)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *_a, **_k: None)
    monkeypatch.setattr(instructor, "from_anthropic", lambda *_a, **_k: _Verdicts())
    gr.cmd_run(argparse.Namespace(input=None, output=str(tmp_path / "report.md"), p8_05_scope=False))
    [entry] = _index()
    assert entry["command"] == "groundedness run" and entry["status"] == "completed"
    assert _check_event(_events(entry), "claim_checks_complete")["metric"] == "2/2"


def test_negative_control_run_is_logged(tmp_path, monkeypatch):
    import anthropic
    import instructor

    pairs = tmp_path / "pairs.jsonl"
    pairs.write_text("".join(json.dumps({"pair_id": f"p{i}", "group": "positive", "doc_id": "loan_agreement_1",
                                         "run_idx": 0, "outcome": "price_and_value", "claim": "c",
                                         "chunk_text": "t"}) + "\n" for i in range(3)), encoding="utf-8")
    monkeypatch.setattr(anthropic, "Anthropic", lambda *_a, **_k: None)
    monkeypatch.setattr(instructor, "from_anthropic", lambda *_a, **_k: _FakeClient())
    nc.cmd_run(argparse.Namespace(pairs=str(pairs), output=str(tmp_path / "nc_results.jsonl")))
    [entry] = _index()
    assert entry["command"] == "negative_control run" and entry["status"] == "completed"
    events = _events(entry)
    assert _check_event(events, "pairs_complete")["metric"] == "3/3"
    assert all(e.get("doc_id") is None for e in events if e["event"] in ("start", "end"))

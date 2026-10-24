"""The --max-usd budget guard on the paid agent_eval commands. Offline: fake clients, temp files."""

import argparse
import json
from types import SimpleNamespace as NS

import pytest

from src.evaluation import agent_eval
from src.monitoring import audit


def _ns(**kw):
    base = {"set": "v2", "output": None, "n_runs": 1, "split": None, "docs": None, "log_payloads": False,
            "dry_run": False, "max_usd": None, "runs": None, "count_only": False}
    return argparse.Namespace(**{**base, **kw})


def test_signal1_uses_cited_regulation_and_policy_passages_only(monkeypatch):
    seen = []
    monkeypatch.setattr("src.evaluation.groundedness.compute_signal1_cited",
                        lambda reasoning, cited: seen.append([c["index"] for c in cited]) or
                        {"per_chunk": [], "min": 0.7, "mean": 0.7})
    evidence = [{"number": 1, "kind": "regulation", "text": "a"}, {"number": 2, "kind": "account", "text": "b"},
                {"number": 3, "kind": "policy", "text": "c"}]
    outcomes = {o: {"llm_status": "compliant", "judgment": {"reasoning": "r", "cited_sources": [1, 2, 3]}}
                for o in agent_eval.OUTCOMES}
    outcomes["consumer_support"]["judgment"]["cited_sources"] = []  # nothing cited: skipped
    rows = agent_eval.signal1_rows([{"doc_id": "d", "run_idx": 0, "evidence": evidence, "outcomes": outcomes}])
    assert len(rows) == 3 and seen == [[1, 3]] * 3
    assert agent_eval.signal1_summary(rows)["price_and_value"] == {"n": 1, "median_min": 0.7, "lowest": 0.7}


def test_run_refuses_without_a_cap(tmp_path):
    with pytest.raises(SystemExit, match="--max-usd"):
        agent_eval.cmd_run(_ns(output=str(tmp_path / "rows.jsonl")))


def test_run_stops_before_passing_the_cap(tmp_path, monkeypatch):
    """Each fake run costs $0.30; cap $1.00: after 3 runs ($0.90), $0.90 + $0.35 worst > $1.00, so it stops."""
    calls = []

    class FakeAgent:
        def __init__(self, *a, **k):
            pass

        def run_many(self, items, before, after):
            for key, _text in items:
                before(key)
                calls.append(key)
                audit._run["tokens"]["output"] += 30_000  # 30k output tokens at $10/M = $0.30
                after(key, {"tool_calls": [], "escalation": None, "stop": {"reason": None}}, None)

    monkeypatch.setattr("src.agent.tool_agent.ToolAgent", FakeAgent)
    monkeypatch.setattr(agent_eval.config, "ANTHROPIC_MODEL", "claude-sonnet-5")
    out = tmp_path / "rows.jsonl"
    agent_eval.cmd_run(_ns(output=str(out), docs=["v2_d01", "v2_d02", "v2_d03", "v2_d04"], max_usd=1.0))
    assert len(calls) == 3
    assert len(out.read_text(encoding="utf-8").splitlines()) == 3


def test_run_creates_a_missing_output_folder_before_any_paid_call(tmp_path, monkeypatch):
    """2026-10-24: a live run into a folder that did not exist lost its paid result at the write."""
    class FakeAgent:
        def __init__(self, *a, **k):
            pass

        def run_many(self, items, before, after):
            for key, _text in items:
                before(key)
                after(key, {"tool_calls": [], "escalation": None, "stop": {"reason": None}}, None)

    monkeypatch.setattr("src.agent.tool_agent.ToolAgent", FakeAgent)
    out = tmp_path / "new" / "nested" / "rows.jsonl"
    agent_eval.cmd_run(_ns(output=str(out), docs=["v2_d01"], max_usd=1.0))
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1


def test_claimcheck_count_only_and_cap(tmp_path, monkeypatch):
    out = tmp_path / "rows.jsonl"
    evidence = [{"number": 1, "kind": "regulation", "text": "Firms must act."}]
    req = {"claim": "Firms must act.", "sources": [{"excerpt_number": 1, "verbatim_quote": "Firms must act"}]}
    outcomes = {o: {"status": "compliant", "judgment": {"regulatory_requirements": [req] * 3}} for o in agent_eval.OUTCOMES}
    out.write_text(json.dumps({"doc_id": "v2_d01", "run_idx": 0, "evidence": evidence, "outcomes": outcomes}) + "\n",
                   encoding="utf-8")

    with pytest.raises(SystemExit, match="--max-usd"):
        agent_eval.cmd_claimcheck(_ns(output=str(out)))
    agent_eval.cmd_claimcheck(_ns(output=str(out), count_only=True))  # no client, no error
    store = tmp_path / "rows_claimchecks.jsonl"
    assert not store.exists()

    class FakeClient:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            audit._run["tokens"]["output"] += 1_000  # $0.01 each
            return kwargs["response_model"](verdict="yes", supporting_sentence="Firms must act.")

    import anthropic
    import instructor
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: None)
    monkeypatch.setattr(instructor, "from_anthropic", lambda *a, **k: FakeClient())
    monkeypatch.setattr(agent_eval.config, "ANTHROPIC_MODEL", "claude-sonnet-5")
    agent_eval.cmd_claimcheck(_ns(output=str(out), max_usd=0.05))  # 12 claims; stops when spent + $0.02 > $0.05
    assert len(store.read_text(encoding="utf-8").splitlines()) == 4

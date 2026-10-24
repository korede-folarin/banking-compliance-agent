"""Monitoring dashboard (P9-02): numbers from a hand-built audit log, and the page renders offline."""

import json
from pathlib import Path

from src.monitoring import dashboard


def _write_run(base: Path, run_id, command, status, started, ended, events, cost=0.0, argv=()):
    log = f"2026-10-24/{run_id}.jsonl"
    (base / "2026-10-24").mkdir(parents=True, exist_ok=True)
    header = {"stage": "run", "event": "start", "ts": started, "data": {"argv": list(argv)}}
    (base / log).write_text("".join(json.dumps(e) + "\n" for e in [header, *events]), encoding="utf-8")
    with open(base / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"run_id": run_id, "command": command, "status": status, "started": started,
                            "ended": ended, "log": log, "levels": {}, "failed_checks": [],
                            "estimated_cost_usd": cost}) + "\n")


def _agent(doc, start, end, reasons):
    return [{"stage": "agent", "event": "start", "ts": start, "doc_id": doc, "run_idx": 0},
            {"stage": "agent", "event": "end", "ts": end, "doc_id": doc, "run_idx": 0,
             "data": {"needs_human_review": True, "review_reasons": reasons}}]


def _log(base):
    _write_run(base, "a", "agent_eval run", "completed", "2026-10-24T10:00:00Z", "2026-10-24T10:05:00Z",
               _agent("d1", "2026-10-24T10:00:00Z", "2026-10-24T10:01:00Z", ["auto-approval disabled: x"])
               + _agent("d2", "2026-10-24T10:01:00Z", "2026-10-24T10:03:00Z",
                        ["auto-approval disabled: x", "escalation: cannot_determine"])
               + [{"stage": "evaluation", "event": "error", "ts": "2026-10-24T10:04:00Z", "doc_id": "d3", "run_idx": 0}],
               cost=0.5)
    _write_run(base, "b", "agent_eval run", "completed", "2026-10-24T11:00:00Z", "2026-10-24T11:00:10Z",
               _agent("d1", "2026-10-24T11:00:00Z", "2026-10-24T11:00:01Z", []), argv=("run", "--dry-run"))
    _write_run(base, "c", "claimcheck", "budget_stop", "2026-10-24T12:00:00Z", "2026-10-24T12:00:30Z", [], cost=0.2)


def test_rates_latency_and_cost_from_the_log(tmp_path):
    _log(tmp_path)
    commands, docs = dashboard.load(tmp_path)
    [day] = dashboard.by_day(commands, docs)  # the dry run is left out by default
    assert day["commands"] == 2 and day["command_failure_rate"] == 0.5  # budget_stop is not "completed"
    assert day["agent_documents"] == 3 and day["document_failure_rate"] == round(1 / 3, 4)
    assert day["flagged_rate"] == 1.0 and day["flagged_beyond_policy_rate"] == 0.5
    assert day["median_latency_s"] == 90.0 and day["cost_usd"] == 0.7
    [with_dry] = dashboard.by_day(commands, docs, include_rehearsal=True)
    assert with_dry["commands"] == 3 and with_dry["agent_documents"] == 4


def test_page_renders_offline(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from src import config

    _log(tmp_path)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "REVIEW_DIR", tmp_path / "reviews")
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "src" / "pages" / "1_Dashboard.py"))
    at.run(timeout=60)
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Compliance overview", "System health"]
    values = {m.label: m.value for m in at.metric}
    assert values["Agent document runs"] == "3" and values["Document failure rate"] == "33.3%"
    assert values["Loan agreements reviewed"] == "34"  # the AI agent's results in docs/: 19 + 15 agreements


def test_snapshot_is_used_when_there_is_no_log(tmp_path, monkeypatch):
    _log(tmp_path / "real")
    snap = tmp_path / "snapshot.json"
    monkeypatch.setattr(dashboard, "SNAPSHOT", snap)
    dashboard.write_snapshot(snap, tmp_path / "real")
    commands, docs, taken = dashboard.load_or_snapshot(tmp_path / "empty")
    assert len(commands) == 3 and len(docs) == 4 and taken == "2026-10-24T12:00:00Z"
    assert dashboard.load_or_snapshot(tmp_path / "real")[2] is None  # a live log wins


def test_overview_matches_the_published_results():
    from src.monitoring import overview

    agent = overview.summary("AI agent (chooses its own tools)")
    assert (agent["agreements"], agent["missed"], agent["false_alarms"]) == (34, 6, 17)
    assert agent["escalation_right"] == (65, 72)
    base = overview.summary("Fixed workflow (baseline)")
    assert (base["caught"], base["real_problems"], base["missed"], base["false_alarms"]) == (36, 36, 0, 8)

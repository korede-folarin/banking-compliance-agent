"""
Audit log (docs/audit_logging_design.md): off by default, envelope and run
header, checks logged when they pass, redaction, the docs/ guard, LLM-call
accounting, payloads only behind the flag, and the instructor hooks.
Offline: no API calls, no Chroma, no embedding model.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import config
from src.agent import retry_log
from src.monitoring import audit


def _events(run_id=None):
    files = [p for p in config.LOG_DIR.rglob("*.jsonl") if p.name != "index.jsonl" and "_payloads" not in p.name]
    rows = [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if run_id is None or r["run_id"] == run_id]


def _index():
    path = config.LOG_DIR / "index.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _fake_response(input_tokens=1000, output_tokens=200, tool="OutcomeJudgment"):
    return SimpleNamespace(
        model="claude-sonnet-5", id="msg_1", stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0),
        content=[SimpleNamespace(type="tool_use", name=tool)],
    )


def test_logging_is_off_until_a_run_starts():
    audit.event("judgment", "success", data={"x": 1})
    audit.check("judgment", "c", False, action="block")
    audit.llm_call("judgment", "judge", _fake_response())
    assert not config.LOG_DIR.exists() or not any(config.LOG_DIR.rglob("*"))


def test_run_header_end_event_and_index():
    rid = audit.start_run("unit test", settings={"n_runs": 1})
    audit.end_run("completed")
    events = _events(rid)
    header, end = events[0], events[-1]
    assert (header["stage"], header["event"], header["schema_version"]) == ("run", "start", 1)
    d = header["data"]
    for key in ("git_commit", "git_dirty", "settings", "settings_sha256", "versions", "overrides", "log_payloads"):
        assert key in d
    assert d["settings"]["ANTHROPIC_MODEL"] == config.ANTHROPIC_MODEL
    assert d["settings"]["n_runs"] == 1
    assert "ANTHROPIC_API_KEY" not in json.dumps(header)  # allowlist only; the environment is never dumped
    assert (end["event"], end["data"]["status"]) == ("end", "completed")
    [idx] = _index()
    assert idx["run_id"] == rid and idx["status"] == "completed"
    assert idx["log"].endswith(f"{rid}.jsonl") and "\\" not in idx["log"]


def test_every_event_has_the_envelope_and_context():
    rid = audit.start_run("unit test")
    audit.set_context(doc_id="loan_agreement_1", run_idx=0)
    audit.event("judgment", "success", outcome="price_and_value", duration_ms=5, data={"status": "compliant"})
    audit.end_run()
    e = [x for x in _events(rid) if x["stage"] == "judgment"][0]
    for key in ("schema_version", "ts", "run_id", "stage", "event", "level", "component", "data"):
        assert key in e
    assert (e["doc_id"], e["run_idx"], e["outcome"], e["duration_ms"]) == ("loan_agreement_1", 0, "price_and_value", 5)
    assert e["ts"].endswith("Z")
    assert e["component"].startswith("tests/test_audit_log.py:")


def test_checks_are_logged_when_they_pass_and_failures_are_levelled_by_action():
    rid = audit.start_run("unit test")
    audit.check("ingestion", "passes", True, metric=1, threshold=1, action="block")
    audit.check("ingestion", "warns", False, metric=0, threshold=1, action="warn")
    audit.check("ingestion", "blocks", False, metric=0, threshold=1, action="block")
    audit.check("ingestion", "n_a", None, action="block")
    audit.end_run()
    checks = {e["data"]["name"]: e for e in _events(rid) if e["event"] == "check"}
    assert set(checks) == {"passes", "warns", "blocks", "n_a"}
    assert checks["passes"]["level"] == "info" and checks["passes"]["data"]["action"] == "none"
    assert checks["warns"]["level"] == "warn"
    assert checks["blocks"]["level"] == "error" and checks["blocks"]["data"]["action"] == "block"
    assert checks["n_a"]["level"] == "info" and checks["n_a"]["data"]["passed"] is None
    assert _index()[0]["failed_checks"] == ["warns", "blocks"]


def test_redaction_of_paths_and_secret_markers():
    home = str(Path.home())
    repo_file = str(config.PROJECT_ROOT / "docs" / "x.md")
    assert audit.redact({"p": [home + "\\eval_runs\\a.log"]}) == {"p": ["<USER_HOME>\\eval_runs\\a.log"]}
    assert audit.redact(repo_file).replace("\\", "/") == "docs/x.md"
    rid = audit.start_run("unit test")
    audit.event("run", "note", data={"leak": "sk-ant-abc123"})
    audit.end_run()
    text = "\n".join(json.dumps(e) for e in _events(rid))
    assert "sk-ant" not in text
    assert any(e["event"] == "redaction" for e in _events(rid))


def test_refuses_to_log_inside_docs():
    with pytest.raises(ValueError):
        audit.start_run("unit test", log_dir=config.PROJECT_ROOT / "docs" / "logs")
    assert not audit.active()


def test_llm_calls_are_counted_hashed_and_costed():
    rid = audit.start_run("unit test")
    kwargs = {"system": "S", "messages": [{"role": "user", "content": "hello"}]}
    audit.llm_call("judgment", "judge", _fake_response(1_000_000, 100_000), kwargs=kwargs, attempt=1)
    audit.end_run()
    [call] = [e for e in _events(rid) if e["event"] == "llm_call"]
    assert call["data"]["tokens"]["input"] == 1_000_000 and call["data"]["tool_names"] == ["OutcomeJudgment"]
    assert call["data"]["prompt_sha256"] == audit.prompt_hash(kwargs)
    assert "hello" not in json.dumps(call)  # prompt text is not logged by default
    end = _events(rid)[-1]["data"]
    assert end["llm_calls"] == 1 and end["estimated_cost_usd"] == pytest.approx(2.0 + 1.0)
    assert not list(config.LOG_DIR.rglob("*_payloads.jsonl"))


def test_payloads_only_with_the_flag():
    audit.start_run("unit test", log_payloads=True)
    audit.llm_call("judgment", "judge", _fake_response(), kwargs={"messages": [{"role": "user", "content": "hello"}]})
    audit.end_run()
    [payloads] = list(config.LOG_DIR.rglob("*_payloads.jsonl"))
    assert "hello" in payloads.read_text(encoding="utf-8")


def test_a_logging_failure_never_raises(tmp_path):
    audit.start_run("unit test")
    audit._run["path"] = tmp_path  # a directory: every write fails
    audit.event("run", "note")
    audit.end_run()


class _HookClient:
    def __init__(self):
        self.hooks = {}

    def on(self, name, fn):
        self.hooks[name] = fn


def test_instructor_hooks_log_each_attempt_and_retry():
    client = retry_log.attach(_HookClient(), "judge")
    rid = audit.start_run("unit test")
    h = client.hooks
    h["completion:kwargs"](messages=[{"role": "user", "content": "a"}])
    h["completion:response"](_fake_response())
    h["parse:error"](ValueError("bad"), attempt_number=1, is_last_attempt=False)
    h["completion:kwargs"](messages=[{"role": "user", "content": "a"}])
    h["completion:response"](_fake_response())
    h["completion:kwargs"](messages=[{"role": "user", "content": "b"}])  # next call starts again at 1
    h["completion:response"](_fake_response())
    audit.end_run()
    events = _events(rid)
    assert [e["data"]["attempt"] for e in events if e["event"] == "llm_call"] == [1, 2, 1]
    [retry] = [e for e in events if e["event"] == "retry"]
    assert retry["stage"] == "judgment" and retry["level"] == "warn" and retry["data"]["error_type"] == "ValueError"


def test_instructor_hooks_write_nothing_without_a_run():
    client = retry_log.attach(_HookClient(), "extraction")
    client.hooks["completion:kwargs"](messages=[])
    client.hooks["completion:response"](_fake_response())
    client.hooks["parse:error"](ValueError("bad"), attempt_number=1, is_last_attempt=True)
    assert not config.LOG_DIR.exists() or not any(config.LOG_DIR.rglob("*"))

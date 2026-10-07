"""
Offline tests for observe-only retry-cause logging (src/agent/retry_log.py).

The central test drives instructor's REAL retry loop: the Anthropic client's
`messages.create` is replaced by a local fake that returns a response which
fails validation, then a valid one. The same calls are made with and without
logging attached, and everything sent to the API and returned is compared:
attaching the hooks must change nothing but the log file. No network calls.
"""

import argparse
import json

import instructor
import pytest
from instructor.v2.core.errors import IncompleteOutputException
from anthropic import Anthropic
from anthropic.types import Message, ToolUseBlock, Usage

from src.agent import retry_log
from src.agent.structured_output import single_tool_choice
from src.evaluation import run_eval
from src.evaluation.claim_verification import ClaimCheck


@pytest.fixture(autouse=True)
def logging_off_between_tests():
    retry_log.set_path(None)
    retry_log.set_context()
    yield
    retry_log.set_path(None)
    retry_log.set_context()


def _message(i, verdict, stop_reason="tool_use"):
    return Message(
        id=f"msg_{i}", type="message", role="assistant", model="claude-test",
        content=[ToolUseBlock(id=f"toolu_{i}", type="tool_use", name="ClaimCheck",
                              input={"verdict": verdict, "supporting_sentence": "s"})],
        stop_reason=stop_reason, stop_sequence=None, usage=Usage(input_tokens=100, output_tokens=42),
    )


def _client(responses, sent):
    raw = Anthropic(api_key="offline-test-not-a-real-key")

    def fake_create(*args, **kwargs):
        sent.append(json.dumps(kwargs, sort_keys=True, default=str))
        return responses.pop(0)

    raw.messages.create = fake_create  # no network: instructor calls this
    return instructor.from_anthropic(raw)


def _call(client):
    return client.messages.create(
        model="claude-test", max_tokens=512, system="sys",
        messages=[{"role": "user", "content": "claim"}],
        response_model=ClaimCheck, tool_choice=single_tool_choice(ClaimCheck),
    )


def test_logging_observes_only_same_requests_same_result(tmp_path):
    # Without logging.
    sent_plain = []
    plain = _client([_message(1, "maybe"), _message(2, "yes")], sent_plain)
    result_plain = _call(plain)

    # With logging attached and switched on.
    log = tmp_path / "retries.jsonl"
    retry_log.set_path(log)
    retry_log.set_context(doc_id="loan_agreement_1", run_idx=2)
    sent_logged = []
    logged = retry_log.attach(_client([_message(1, "maybe"), _message(2, "yes")], sent_logged), "claim_check")
    result_logged = _call(logged)

    assert len(sent_plain) == len(sent_logged) == 2  # one retry each
    assert sent_plain == sent_logged  # byte-identical requests, incl. the re-ask
    # Compare field values: instructor attaches its raw response as a private attribute.
    assert result_plain.model_dump() == result_logged.model_dump() == {"verdict": "yes", "supporting_sentence": "s"}

    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1  # one failed attempt, one record
    r = records[0]
    assert r["call_site"] == "claim_check" and r["doc_id"] == "loan_agreement_1" and r["run_idx"] == 2
    assert r["attempt_number"] == 1
    assert r["error_type"] == "ValidationError" and "verdict" in r["error"]
    assert r["stop_reason"] == "tool_use" and r["output_tokens"] == 42
    assert r["content_block_types"] == ["tool_use"] and r["tool_use_count"] == 1 and r["tool_names"] == ["ClaimCheck"]


def test_truncated_response_is_not_retried_and_behaves_the_same_with_logging(tmp_path):
    # Learned from this test: instructor does NOT retry a response cut off at
    # max_tokens; it raises IncompleteOutputException at once, before any
    # parse error. So truncation cannot be what drives the silent retries, and
    # a truncated judgment surfaces as a hard failure (main's errors file),
    # not in the retry log.
    for attach_logging in (False, True):
        log = tmp_path / f"retries_{attach_logging}.jsonl"
        retry_log.set_path(log if attach_logging else None)
        sent = []
        client = _client([_message(1, "maybe", stop_reason="max_tokens"), _message(2, "yes")], sent)
        if attach_logging:
            client = retry_log.attach(client, "judge")
        with pytest.raises(IncompleteOutputException):
            _call(client)
        assert len(sent) == 1  # no re-ask
        assert not log.exists()  # nothing to log: no parse error was emitted


def test_logging_is_off_unless_a_path_is_set(tmp_path):
    client = retry_log.attach(_client([_message(1, "maybe"), _message(2, "yes")], []), "claim_check")
    _call(client)
    assert list(tmp_path.iterdir()) == []


def test_a_failing_log_write_never_affects_the_call(tmp_path):
    retry_log.set_path(tmp_path)  # a directory: open() for append fails
    sent = []
    client = retry_log.attach(_client([_message(1, "maybe"), _message(2, "yes")], sent), "claim_check")
    assert _call(client).model_dump() == {"verdict": "yes", "supporting_sentence": "s"}
    assert len(sent) == 2


def test_attach_leaves_objects_without_hooks_alone():
    marker = object()
    assert retry_log.attach(marker, "x") is marker


def test_main_turns_logging_on_next_to_its_output_and_labels_runs(tmp_path, monkeypatch):
    seen = []

    class FakeFirstPassAgent:
        def run(self, text):
            seen.append(dict(retry_log._context))
            raise RuntimeError("stop here; only the logging setup is under test")

    monkeypatch.setattr(run_eval, "FirstPassAgent", FakeFirstPassAgent)
    monkeypatch.setattr(run_eval, "ComplianceAgent", lambda: None)
    out = tmp_path / "pass.jsonl"
    run_eval.cmd_main(argparse.Namespace(n_runs=2, output=str(out), docs=["loan_agreement_1"]))
    assert retry_log._path == tmp_path / "pass_retries.jsonl"
    assert seen == [{"doc_id": "loan_agreement_1", "run_idx": 0}, {"doc_id": "loan_agreement_1", "run_idx": 1}]

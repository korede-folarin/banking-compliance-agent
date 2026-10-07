"""
Offline tests for two Session 26 gap fixes (no API calls):

1. `groundedness plan` saves per-judgment Signal 1 (P8-05's max over the
   retrieved set, and the cited-chunk per-chunk scores with min and mean)
   to <input stem>_signal1.jsonl next to its input, refusing the input
   itself and the protected Phase 8 files.
2. `claim_verification check` writes observe-only retry-cause records to
   <store stem>_retries.jsonl. Checked by running `check` through a REAL
   instructor client (its `messages.create` replaced by a local fake that
   makes the first claim check fail validation once), with and without the
   hooks, and comparing every request sent and every stored result.

Protected docs/ files are hashed before and after, and docs/ is checked for
new files.
"""

import argparse
import hashlib
import json

import pytest
from anthropic import Anthropic
from anthropic.types import Message, ToolUseBlock, Usage

from src.agent import retry_log
from src.evaluation import claim_verification as cv
from src.evaluation import groundedness, run_eval
from tests.fixtures.eval_set import OUTCOME_KEYS
from tests.test_claim_check_store import _judgment_row

PROTECTED = [
    run_eval.MAIN_PASS_PATH, run_eval.SUMMARY_PATH, groundedness.GROUNDEDNESS_OUT_PATH,
    run_eval.DOCS_OUT_DIR / "eval_raw_main_pass_v2.jsonl",
]
PHASE8_ROWS = [json.loads(line) for line in run_eval.MAIN_PASS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module", autouse=True)
def protected_files_untouched():
    before = {p: _sha256(p) for p in PROTECTED}
    docs_before = sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir())
    yield
    assert {p: _sha256(p) for p in PROTECTED} == before
    assert sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir()) == docs_before, "a file was created or removed in docs/"


@pytest.fixture(autouse=True)
def retry_logging_reset():
    retry_log.set_path(None)
    retry_log.set_context()
    yield
    retry_log.set_path(None)
    retry_log.set_context()


# ------------------------------------------------- gap 1: Signal 1 file ---

def _main_row(doc_id, run_idx):
    src = [{"index": i, "node_id": f"n{i}", "file_name": "f.pdf", "similarity_score": 0.7, "text_excerpt": f"text {i}."}
           for i in range(1, 6)]
    outcomes = {
        k: {"llm_status": "compliant", "status": "compliant", "confidence": 0.7, "reasoning": f"{k} reasoning sentence here.",
            "cited_source_count": 2, "cited_sources": src[:2], "cited_sources_raw": [1, 2], "retrieved_sources": src}
        for k in OUTCOME_KEYS
    }
    return {"doc_id": doc_id, "run_idx": run_idx, "ground_truth": {k: "compliant" for k in OUTCOME_KEYS},
            "outcomes": outcomes, "_cached_fields": PHASE8_ROWS[0]["_cached_fields"]}


@pytest.fixture
def fake_signal1(monkeypatch):
    monkeypatch.setattr(groundedness, "compute_signal1", lambda reasoning, sources: 0.81)
    monkeypatch.setattr(groundedness, "compute_signal1_cited", lambda reasoning, cited: {
        "per_chunk": [{"index": s["index"], "score": 0.7 + s["index"] / 100} for s in cited],
        "min": 0.71, "mean": 0.715,
    })

    def _no_replay(*a, **k):
        raise AssertionError("no replay expected")

    monkeypatch.setattr(groundedness, "load_index", _no_replay)


def test_signal1_default_path_is_derived_from_the_input():
    assert groundedness._resolve_signal1_output(None, run_eval.MAIN_PASS_V2_PATH) == (
        run_eval.DOCS_OUT_DIR / "eval_raw_main_pass_v2_signal1.jsonl"
    )


@pytest.mark.parametrize("given", [
    str(run_eval.MAIN_PASS_PATH), "docs/eval_raw_main_pass.jsonl", str(run_eval.SUMMARY_PATH),
    "docs/eval_groundedness.md", str(run_eval.MAIN_PASS_V2_PATH),  # the input itself
])
def test_signal1_refuses_the_input_and_protected_files(given, monkeypatch):
    monkeypatch.chdir(run_eval.DOCS_OUT_DIR.parent)
    with pytest.raises(SystemExit, match="Refusing to write Signal 1"):
        groundedness._resolve_signal1_output(given, run_eval.MAIN_PASS_V2_PATH)


def test_plan_saves_per_judgment_signal1(fake_signal1, tmp_path, capsys):
    src = tmp_path / "pass.jsonl"
    src.write_text("".join(json.dumps(_main_row("loan_agreement_1", i)) + "\n" for i in range(2)), encoding="utf-8")
    groundedness.cmd_plan(argparse.Namespace(input=str(src)))

    out = tmp_path / "pass_signal1.jsonl"
    rows = _rows(out)
    assert len(rows) == 2 * len(OUTCOME_KEYS)
    assert {(r["doc_id"], r["run_idx"], r["outcome"]) for r in rows} == {
        ("loan_agreement_1", i, k) for i in range(2) for k in OUTCOME_KEYS
    }
    r = rows[0]
    assert r["signal1_full_retrieved_max"] == 0.81
    assert r["signal1_cited"] == {"per_chunk": [{"index": 1, "score": 0.71}, {"index": 2, "score": 0.72}],
                                  "min": 0.71, "mean": 0.715}
    assert r["scope_rule"] == groundedness.SCOPE_RULE_CITES and r["llm_status"] == "compliant"
    assert str(out) in capsys.readouterr().out

    groundedness.cmd_plan(argparse.Namespace(input=str(src)))  # its own derived file is simply rewritten
    assert _rows(out) == rows


def test_refused_signal1_path_does_no_work(monkeypatch):
    called = []
    monkeypatch.setattr(groundedness, "build_scope", lambda *a, **k: called.append(1) or [])
    monkeypatch.chdir(run_eval.DOCS_OUT_DIR.parent)
    with pytest.raises(SystemExit, match="Refusing"):
        groundedness.cmd_plan(argparse.Namespace(input=None, signal1_output="docs/eval_summary.json"))
    assert called == []


# ------------------------------------------ gap 2: check's retry logging ---

def _msg(i, verdict):
    return Message(
        id=f"msg_{i}", type="message", role="assistant", model="claude-test",
        content=[ToolUseBlock(id=f"toolu_{i}", type="tool_use", name="ClaimCheck",
                              input={"verdict": verdict, "supporting_sentence": ""})],
        stop_reason="tool_use", stop_sequence=None, usage=Usage(input_tokens=50, output_tokens=20),
    )


def _run_check(tmp_path, monkeypatch, with_hooks):
    import instructor

    tmp_path.mkdir(parents=True, exist_ok=True)
    judgments = tmp_path / "judgments.jsonl"
    judgments.write_text(json.dumps(_judgment_row("loan_agreement_1", PHASE8_ROWS)) + "\n", encoding="utf-8")
    monkeypatch.setattr(cv, "PILOT_JUDGMENTS_PATH", judgments)
    monkeypatch.setattr(cv, "PILOT_CHECKS_PATH", tmp_path / "checks.jsonl")
    monkeypatch.setattr(cv, "load_corpus", lambda: [])
    monkeypatch.setattr(cv, "_embed", lambda text: [float(len(text) % 7 + 1), 1.0, 0.5])
    monkeypatch.setattr(cv, "compute_signal1_cited", lambda reasoning, cited: {"per_chunk": [], "min": None, "mean": None})
    if not with_hooks:
        monkeypatch.setattr(retry_log, "attach", lambda client, call_site: client)

    sent, n = [], {"calls": 0}

    def fake_create(*args, **kwargs):
        sent.append(json.dumps(kwargs, sort_keys=True, default=str))
        n["calls"] += 1
        return _msg(n["calls"], "maybe" if n["calls"] == 1 else "yes")  # first check fails validation once

    real_from_anthropic = instructor.from_anthropic

    def offline_from_anthropic(_ignored_client, *a, **k):
        # A real instructor client around an offline Anthropic client: the
        # retry loop and hooks are real, only messages.create is local.
        raw = Anthropic(api_key="offline-test-not-a-real-key")
        raw.messages.create = fake_create  # no network
        return real_from_anthropic(raw, *a, **k)

    monkeypatch.setattr(instructor, "from_anthropic", offline_from_anthropic)
    cv.cmd_check(argparse.Namespace(docs=None, runs=None, judgments=None, output=None))
    return sent, _rows(tmp_path / "checks.jsonl"), tmp_path / "checks_retries.jsonl"


def test_check_retry_logging_only_observes(tmp_path, monkeypatch):
    sent_plain, store_plain, retries_plain = _run_check(tmp_path / "plain", monkeypatch, with_hooks=False)
    monkeypatch.undo()
    sent_logged, store_logged, retries_logged = _run_check(tmp_path / "logged", monkeypatch, with_hooks=True)

    n_claims = len(OUTCOME_KEYS) * 2  # _judgment_row: 2 regulatory claims per outcome
    assert len(sent_plain) == len(sent_logged) == n_claims + 1  # one retry each
    assert sent_plain == sent_logged  # identical requests, including the re-ask
    assert store_plain == store_logged  # identical stored results
    assert not retries_plain.exists()

    records = _rows(retries_logged)
    assert len(records) == 1
    r = records[0]
    assert r["call_site"] == "claim_check" and r["error_type"] == "ValidationError" and "verdict" in r["error"]
    assert (r["doc_id"], r["run_idx"], r["outcome"], r["claim_index"]) == ("loan_agreement_1", 0, "price_and_value", 0)
    assert r["tool_use_count"] == 1 and r["stop_reason"] == "tool_use"


def test_check_prints_and_derives_its_retry_log_path(tmp_path, monkeypatch, capsys):
    _run_check(tmp_path, monkeypatch, with_hooks=True)
    assert f"Retry log: {tmp_path / 'checks_retries.jsonl'}" in capsys.readouterr().out

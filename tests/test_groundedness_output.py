"""
Offline tests for deferred-checklist item 19 (ARCHITECTURE.md "Evaluation
notes"): `groundedness.py run` writes its report to a filename derived from
its input (docs/eval_groundedness_<input stem>.md) or to --output, and
refuses to write docs/eval_groundedness.md, which holds the Phase 8 P8-05
results plus hand-written sections the script does not regenerate.

No API calls, no Chroma queries, no model loading: build_scope and the LLM
client are faked, and every report that is written goes to a temp
directory. The real docs/eval_groundedness.md is hashed before and after,
its hand-written sections are checked to be present and unchanged, and
docs/ is checked for new files.
"""

import argparse
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from src.evaluation import groundedness
from src.evaluation import run_eval

REAL_REPORT_PATH = groundedness.GROUNDEDNESS_OUT_PATH
DOCS_DIR = groundedness.DOCS_OUT_DIR

# Opening lines of the two hand-written sections that `run` never generates.
HAND_WRITTEN_MARKERS = [
    "**Correction: what Signal 1 measures in this run.**",
    "## Observed limitation: what's actually driving \"flagged\"",
]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hand_written_sections(text):
    """Each hand-written section from its marker up to the next '## ' heading."""
    sections = {}
    for marker in HAND_WRITTEN_MARKERS:
        start = text.index(marker)
        end = text.find("\n## ", start + len(marker))
        sections[marker] = text[start : end if end != -1 else len(text)]
    return sections


@pytest.fixture(scope="module", autouse=True)
def phase8_report_untouched():
    text_before = REAL_REPORT_PATH.read_text(encoding="utf-8")
    hash_before = _sha256(REAL_REPORT_PATH)
    sections_before = _hand_written_sections(text_before)
    docs_before = sorted(p.name for p in DOCS_DIR.iterdir())
    yield
    assert _sha256(REAL_REPORT_PATH) == hash_before, "docs/eval_groundedness.md was modified"
    assert _hand_written_sections(REAL_REPORT_PATH.read_text(encoding="utf-8")) == sections_before
    assert sorted(p.name for p in DOCS_DIR.iterdir()) == docs_before, "a file was created or removed in docs/"


def test_hand_written_sections_exist_in_phase8_report():
    # Guards the fixture above: if a marker were missing, the section check
    # would not be checking anything.
    text = REAL_REPORT_PATH.read_text(encoding="utf-8")
    for marker in HAND_WRITTEN_MARKERS:
        assert marker in text


# --- output path resolution ---

def test_default_output_is_derived_from_input_not_phase8_report():
    v2 = groundedness._resolve_report_output(None, run_eval.MAIN_PASS_V2_PATH)
    assert v2 == DOCS_DIR / "eval_groundedness_eval_raw_main_pass_v2.md"
    phase8 = groundedness._resolve_report_output(None, run_eval.MAIN_PASS_PATH)
    assert phase8 == DOCS_DIR / "eval_groundedness_eval_raw_main_pass.md"
    assert REAL_REPORT_PATH not in (v2, phase8)


@pytest.mark.parametrize("given", [str(REAL_REPORT_PATH), "docs/eval_groundedness.md"])
def test_explicit_phase8_report_output_is_refused(given, monkeypatch):
    monkeypatch.chdir(DOCS_DIR.parent)
    with pytest.raises(SystemExit, match="Refusing to write the groundedness report"):
        groundedness._resolve_report_output(given, run_eval.MAIN_PASS_V2_PATH)


def test_cli_accepts_output_flag(monkeypatch):
    captured = {}
    monkeypatch.setattr(groundedness, "cmd_run", lambda args: captured.setdefault("args", args))
    monkeypatch.setattr(sys, "argv", ["groundedness", "run", "--output", "x.md"])
    groundedness.main()
    assert captured["args"].output == "x.md"


# --- cmd_run end to end, faked ---

class _FakeClient:
    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(verdict="yes")


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    import anthropic
    import instructor

    client = _FakeClient()
    monkeypatch.setattr(instructor, "from_anthropic", lambda *_a, **_k: client)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *_a, **_k: None)

    scope_calls = {"n": 0}

    def fake_build_scope(main_records):
        scope_calls["n"] += 1
        return [
            {
                "doc_id": "loan_agreement_1",
                "outcome": "price_and_value",
                "ground_truth": "non_compliant",
                "llm_status": "potentially_non_compliant",
                "reasoning": "fake reasoning",
                "sources": [{"text_excerpt": "fake excerpt"}],
                "signal1": 0.8,
                "claims": ["fake claim one is long enough", "fake claim two is long enough"],
            }
        ]

    monkeypatch.setattr(groundedness, "build_scope", fake_build_scope)
    v2 = tmp_path / "eval_raw_main_pass_v2.jsonl"
    v2.write_text(json.dumps({"doc_id": "loan_agreement_1", "run_idx": 0}) + "\n", encoding="utf-8")
    monkeypatch.setattr(run_eval, "MAIN_PASS_V2_PATH", v2)
    return {"client": client, "scope_calls": scope_calls, "tmp": tmp_path}


def test_run_with_phase8_report_output_is_refused_before_any_work(fake_run, monkeypatch):
    monkeypatch.chdir(DOCS_DIR.parent)
    with pytest.raises(SystemExit, match="Refusing"):
        groundedness.cmd_run(argparse.Namespace(input=None, output="docs/eval_groundedness.md"))
    assert fake_run["scope_calls"]["n"] == 0
    assert fake_run["client"].calls == 0


def test_run_writes_to_explicit_output(fake_run, capsys):
    out = fake_run["tmp"] / "report.md"
    groundedness.cmd_run(argparse.Namespace(input=None, output=str(out)))

    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Groundedness / Faithfulness Cross-Check (P8-05)")
    assert "loan_agreement_1 | price_and_value" in text
    assert fake_run["client"].calls == 2
    assert str(out) in capsys.readouterr().out


def test_run_default_output_is_derived_filename(fake_run, monkeypatch):
    monkeypatch.setattr(groundedness, "DOCS_OUT_DIR", fake_run["tmp"])  # keep the write out of docs/
    groundedness.cmd_run(argparse.Namespace(input=None, output=None))
    assert (fake_run["tmp"] / "eval_groundedness_eval_raw_main_pass_v2.md").exists()

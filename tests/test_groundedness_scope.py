"""
Offline tests for the Session 24 groundedness scope fix (pilot finding 4):
a judgment is in scope when it cites at least one source, whatever its
status. P8-05 excluded every `insufficient_evidence` judgment on the premise
that such judgments cite nothing, which both the Phase 8 data and the
Session 23 pilot contradict. `--p8-05-scope` keeps the original rule
available, so P8-05's published scope stays reproducible.

No API calls, no Chroma, no embedding model. The real Phase 8 and pilot
files are only read; protected files are hashed before and after, and docs/
is checked for new files.
"""

import argparse
import hashlib
import json
import sys

import pytest

from src.evaluation import groundedness
from src.evaluation import run_eval
from tests.fixtures.eval_set import OUTCOME_KEYS

PILOT_PATH = run_eval.DOCS_OUT_DIR / "eval_raw_main_pass_pilot.jsonl"
REAL_FIELDS = next(
    json.loads(line)["_cached_fields"]
    for line in run_eval.MAIN_PASS_PATH.read_text(encoding="utf-8").splitlines()
    if line.strip() and json.loads(line)["run_idx"] == 0
)
PROTECTED = [run_eval.MAIN_PASS_PATH, run_eval.SUMMARY_PATH, run_eval.DOCS_OUT_DIR / "eval_groundedness.md"]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def protected_files_untouched():
    before = {p: _sha256(p) for p in PROTECTED}
    docs_before = sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir())
    yield
    assert {p: _sha256(p) for p in PROTECTED} == before
    assert sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir()) == docs_before


@pytest.fixture
def no_embeddings(monkeypatch):
    monkeypatch.setattr(groundedness, "compute_signal1", lambda reasoning, sources: 0.5)
    monkeypatch.setattr(groundedness, "compute_signal1_cited", lambda reasoning, cited: {"per_chunk": [], "min": None, "mean": None})

    def _no_replay(*a, **k):
        raise AssertionError("no replay expected: rows carry retrieved_sources")

    monkeypatch.setattr(groundedness, "load_index", _no_replay)


def _row(statuses_and_raw):
    """One new-format main-pass row; statuses_and_raw maps outcome -> (llm_status, cited_sources_raw)."""
    src = [{"index": i, "node_id": f"n{i}", "file_name": "f.pdf", "similarity_score": 0.7, "text_excerpt": f"text {i}."}
           for i in range(1, 6)]
    outcomes = {}
    for k in OUTCOME_KEYS:
        status, raw = statuses_and_raw[k]
        outcomes[k] = {"llm_status": status, "status": status, "confidence": 0.7, "reasoning": f"{k} reasoning text here.",
                       "cited_source_count": len(raw), "cited_sources": [src[i - 1] for i in raw if 1 <= i <= 5],
                       "cited_sources_raw": raw, "retrieved_sources": src}
    return {"doc_id": "loan_agreement_1", "run_idx": 0, "ground_truth": {k: "compliant" for k in OUTCOME_KEYS},
            "outcomes": outcomes, "_cached_fields": REAL_FIELDS}


def test_cites_anything_reads_what_each_row_format_recorded():
    assert groundedness.cites_anything({"cited_sources_raw": [3]})
    assert not groundedness.cites_anything({"cited_sources_raw": []})
    assert groundedness.cites_anything({"cited_sources_raw": [9], "cited_sources": []})  # raw wins: out-of-range still a citation
    assert groundedness.cites_anything({"cited_sources": [{"index": 1}]})  # citation-logging rows
    assert groundedness.cites_anything({"cited_source_count": 2})  # Phase 8 rows
    assert not groundedness.cites_anything({"cited_source_count": 0})


def test_insufficient_evidence_with_citations_is_in_scope_and_uncited_is_excluded(no_embeddings, capsys):
    row = _row({
        "price_and_value": ("insufficient_evidence", [1, 3]),
        "consumer_support": ("insufficient_evidence", []),
        "products_and_services": ("compliant", [2]),
        "consumer_understanding": ("compliant", []),
    })
    scope = groundedness.build_scope([row])
    out = capsys.readouterr().out
    assert sorted(j["outcome"] for j in scope) == ["price_and_value", "products_and_services"]
    assert all(j["scope_rule"] == groundedness.SCOPE_RULE_CITES for j in scope)
    assert "2 judgment(s) excluded because they cite no sources" in out
    assert "consumer_support (insufficient_evidence)" in out and "consumer_understanding (compliant)" in out


def test_p8_05_scope_flag_restores_status_based_exclusion(no_embeddings, capsys):
    row = _row({
        "price_and_value": ("insufficient_evidence", [1, 3]),
        "consumer_support": ("insufficient_evidence", []),
        "products_and_services": ("compliant", [2]),
        "consumer_understanding": ("compliant", []),
    })
    scope = groundedness.build_scope([row], p8_05_scope=True)
    assert sorted(j["outcome"] for j in scope) == ["consumer_understanding", "products_and_services"]
    assert "excluded by status (--p8-05-scope)" in capsys.readouterr().out


@pytest.mark.skipif(not PILOT_PATH.exists(), reason="Session 23 pilot output not present")
def test_real_pilot_insufficient_judgments_with_citations_are_now_in_scope(no_embeddings):
    rows = [json.loads(line) for line in PILOT_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    default = groundedness.build_scope(rows)
    legacy = groundedness.build_scope(rows, p8_05_scope=True)
    assert len(legacy) == 14  # what the Session 23 groundedness run covered
    assert len(default) == 16  # + loan_agreement_1 and _12 consumer_support
    added = {(j["doc_id"], j["outcome"]) for j in default} - {(j["doc_id"], j["outcome"]) for j in legacy}
    assert added == {("loan_agreement_1", "consumer_support"), ("loan_agreement_12", "consumer_support")}


def test_cli_flag_reaches_build_scope(monkeypatch, tmp_path):
    seen = {}

    def fake_build_scope(main_records, p8_05_scope=False):
        seen["p8_05_scope"] = p8_05_scope
        return []

    monkeypatch.setattr(groundedness, "build_scope", fake_build_scope)
    src = tmp_path / "pass.jsonl"
    src.write_text(json.dumps({"doc_id": "loan_agreement_1", "run_idx": 0}) + "\n", encoding="utf-8")
    for argv, expected in ((["groundedness", "plan", "--input", str(src)], False),
                           (["groundedness", "plan", "--input", str(src), "--p8-05-scope"], True)):
        monkeypatch.setattr(sys, "argv", argv)
        groundedness.main()
        assert seen["p8_05_scope"] is expected

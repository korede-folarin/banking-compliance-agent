"""
Offline tests for deferred-checklist items 17 and 18 (ARCHITECTURE.md
"Evaluation notes"), both in `claim_verification check`:

- Item 17: a second run, or a run limited with --docs, must not lose or
  overwrite earlier results. The append-only claim-check store holds the
  paid-for results; <store>_results.jsonl and <store>_report.md are rebuilt
  from every recorded judgment plus the whole store.
- Item 18: each claim-check result is saved the moment it comes back, a
  crash keeps every completed result, and a re-run skips already-checked
  claims and says so.

No API calls, no Chroma, no embedding model: the LLM client, corpus and
embeddings are faked, and all files live in a temp directory. The pilot
judgments are built from the Phase 8 cached run-0 fields (read only). The
real Phase 8 files are hashed before and after, and docs/ is checked for new
files.
"""

import argparse
import hashlib
import json

import pytest

from src.evaluation import claim_verification as cv
from src.evaluation import run_eval
from tests.fixtures.eval_set import OUTCOME_KEYS

DOCS = ["loan_agreement_1", "loan_agreement_2"]
CLAIMS_PER_OUTCOME = 2
TOTAL_CLAIMS = len(DOCS) * len(OUTCOME_KEYS) * CLAIMS_PER_OUTCOME  # 16
PROTECTED = [run_eval.MAIN_PASS_PATH, run_eval.SUMMARY_PATH, cv.DOCS_OUT_DIR / "eval_groundedness.md"]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module", autouse=True)
def real_files_untouched():
    before = {p: _sha256(p) for p in PROTECTED}
    docs_before = sorted(p.name for p in cv.DOCS_OUT_DIR.iterdir())
    yield
    assert {p: _sha256(p) for p in PROTECTED} == before
    assert sorted(p.name for p in cv.DOCS_OUT_DIR.iterdir()) == docs_before, "a file was created or removed in docs/"


def _fake_sources():
    return [
        {"index": i, "node_id": f"n{i}", "file_name": "fake.pdf", "similarity_score": 0.7,
         "text_excerpt": f"Fake regulatory excerpt number {i} says firms must do thing {i}."}
        for i in range(1, 6)
    ]


def _judgment_row(doc_id, phase8_rows):
    cached = next(r for r in phase8_rows if r["doc_id"] == doc_id and r["run_idx"] == 0)
    sources = _fake_sources()
    outcomes = {}
    for k in OUTCOME_KEYS:
        reqs = [
            {"claim": f"{doc_id} {k} claim {i}",
             "sources": [{"excerpt_number": i + 1, "verbatim_quote": f"firms must do thing {i + 1}"}]}
            for i in range(CLAIMS_PER_OUTCOME)
        ]
        outcomes[k] = {
            "judgment": {"status": "compliant", "reasoning": "fake", "cited_sources": [1],
                         "document_facts": [], "regulatory_requirements": reqs, "absences": []},
            "validated_status": "compliant", "confidence": 0.7,
            "resolved_cited_sources": [sources[0]], "sources": sources,
            "reference_llm_status": "compliant", "reference_status": "compliant",
        }
    return {"doc_id": doc_id, "run_idx": 0, "main_pass_input": "eval_raw_main_pass.jsonl",
            "ground_truth": cached["ground_truth"], "fields": cached["_cached_fields"], "outcomes": outcomes}


class _FakeClient:
    """Returns a verdict per call; can crash on a given call; can check the store before answering."""

    def __init__(self, crash_on=None, store_path=None):
        self.calls = 0
        self.crash_on = crash_on
        self.store_path = store_path
        self.store_lines_seen = []
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        if self.store_path is not None:
            self.store_lines_seen.append(len(_rows(self.store_path)))
        if self.crash_on is not None and self.calls == self.crash_on:
            raise RuntimeError("simulated crash mid-run")
        return cv.ClaimCheck(verdict="yes", supporting_sentence="")


@pytest.fixture
def env(tmp_path, monkeypatch):
    import anthropic
    import instructor

    phase8_rows = _rows(run_eval.MAIN_PASS_PATH)
    judgments = tmp_path / "pilot_judgments.jsonl"
    judgments.write_text("".join(json.dumps(_judgment_row(d, phase8_rows)) + "\n" for d in DOCS), encoding="utf-8")
    store = tmp_path / "pilot_checks.jsonl"

    monkeypatch.setattr(cv, "PILOT_JUDGMENTS_PATH", judgments)
    monkeypatch.setattr(cv, "PILOT_CHECKS_PATH", store)
    monkeypatch.setattr(cv, "load_corpus", lambda: [])
    monkeypatch.setattr(cv, "_embed", lambda text: [float(len(text) % 7 + 1), 1.0, 0.5])
    monkeypatch.setattr(cv, "compute_signal1_cited", lambda reasoning, cited: {"per_chunk": [], "min": None, "mean": None})
    monkeypatch.setattr(anthropic, "Anthropic", lambda *_a, **_k: None)

    state = {"client": _FakeClient()}
    monkeypatch.setattr(instructor, "from_anthropic", lambda *_a, **_k: state["client"])
    return {
        "state": state,
        "store": store,
        "results": tmp_path / "pilot_checks_results.jsonl",
        "report": tmp_path / "pilot_checks_report.md",
    }


def _check(docs=None):
    cv.cmd_check(argparse.Namespace(docs=docs, output=None))


def _llm_checks_by_doc(results_path):
    out = {}
    for r in _rows(results_path):
        out.setdefault(r["doc_id"], []).extend(q["llm_check"] for q in r["regulatory_requirements"])
    return out


# --- item 17 ---

def test_item17_default_paths_are_derived_from_the_store():
    store, results, report = cv._resolve_check_outputs(None)
    assert store == cv.DOCS_OUT_DIR / "eval_claim_pilot_checks.jsonl"
    assert results == cv.DOCS_OUT_DIR / "eval_claim_pilot_checks_results.jsonl"
    assert report == cv.DOCS_OUT_DIR / "eval_claim_pilot_checks_report.md"
    with pytest.raises(SystemExit, match="Refusing"):
        cv._resolve_check_outputs(str(cv.PILOT_JUDGMENTS_PATH))


def test_item17_second_run_keeps_every_result(env, capsys):
    _check()
    assert env["state"]["client"].calls == TOTAL_CLAIMS
    first_store = env["store"].read_text(encoding="utf-8")

    env["state"]["client"] = _FakeClient()
    _check()
    out = capsys.readouterr().out
    assert env["state"]["client"].calls == 0
    assert env["store"].read_text(encoding="utf-8") == first_store  # store untouched, no duplicates
    checks = _llm_checks_by_doc(env["results"])
    assert set(checks) == set(DOCS) and all(c is not None for cs in checks.values() for c in cs)
    report = env["report"].read_text(encoding="utf-8")
    assert "2 documents (loan_agreement_1, loan_agreement_2)" in report
    assert "not yet fully claim-checked" not in report
    assert "NO API calls" in out


def test_item17_docs_limited_runs_never_drop_other_documents(env):
    _check(["loan_agreement_1"])
    assert env["state"]["client"].calls == TOTAL_CLAIMS // 2
    checks = _llm_checks_by_doc(env["results"])
    assert all(c is not None for c in checks["loan_agreement_1"])
    assert all(c is None for c in checks["loan_agreement_2"])  # present, not dropped, just unchecked
    report = env["report"].read_text(encoding="utf-8")
    assert "1 documents (loan_agreement_1)" in report
    assert "loan_agreement_2 run 0 / price_and_value: 2 of 2 regulatory claims unchecked" in report

    env["state"]["client"] = _FakeClient()
    _check(["loan_agreement_2"])
    assert env["state"]["client"].calls == TOTAL_CLAIMS // 2
    checks = _llm_checks_by_doc(env["results"])
    assert all(c is not None for cs in checks.values() for c in cs)  # doc 1's results survived
    assert "2 documents (loan_agreement_1, loan_agreement_2)" in env["report"].read_text(encoding="utf-8")

    env["state"]["client"] = _FakeClient()
    _check(["loan_agreement_1"])  # re-running doc 1 alone must not drop doc 2
    assert env["state"]["client"].calls == 0
    assert all(c is not None for cs in _llm_checks_by_doc(env["results"]).values() for c in cs)
    assert len(_rows(env["store"])) == TOTAL_CLAIMS


# --- item 18 ---

def test_item18_each_result_is_saved_before_the_next_call(env):
    env["state"]["client"] = _FakeClient(store_path=env["store"])
    _check()
    # Before call n, the store already holds the n-1 results before it.
    assert env["state"]["client"].store_lines_seen == list(range(TOTAL_CLAIMS))


def test_item18_crash_keeps_completed_results_and_resume_skips_them(env, capsys):
    env["state"]["client"] = _FakeClient(crash_on=6)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _check()
    saved = _rows(env["store"])
    assert len(saved) == 5  # every completed, paid-for check survived the crash
    capsys.readouterr()

    env["state"]["client"] = _FakeClient()
    _check()
    out = capsys.readouterr().out
    assert env["state"]["client"].calls == TOTAL_CLAIMS - 5
    assert f"5 of the {TOTAL_CLAIMS} requested claims. These will be SKIPPED" in out
    for rec in saved:
        assert f"{rec['doc_id']} run {rec['run_idx']} {rec['outcome']} claim #{rec['claim_index']}" in out
    keys = [cv._store_key(r) for r in _rows(env["store"])]
    assert len(keys) == TOTAL_CLAIMS and len(set(keys)) == TOTAL_CLAIMS  # nothing re-checked, no duplicates
    assert "NO API calls" not in out


def test_item18_plan_count_excludes_already_checked_claims(env, monkeypatch, capsys):
    class _FakeIndex:
        def as_retriever(self, similarity_top_k):
            return self

        def retrieve(self, question):
            return []

    env["state"]["client"] = _FakeClient(crash_on=6)
    with pytest.raises(RuntimeError):
        _check()
    capsys.readouterr()

    monkeypatch.setattr(cv, "load_index", lambda: _FakeIndex())
    cv.cmd_plan(argparse.Namespace(docs=DOCS, input=str(run_eval.MAIN_PASS_PATH), output=None))
    out = capsys.readouterr().out
    assert f"exactly {TOTAL_CLAIMS - 5} claim-check calls (5 of {TOTAL_CLAIMS} already in" in out

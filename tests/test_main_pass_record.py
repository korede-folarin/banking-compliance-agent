"""
Offline tests for deferred-checklist items 3/8, 6, 7 and 9 (ARCHITECTURE.md
"Evaluation notes"): what `run_eval.py main` saves in each record, for every
run, not just run 0.

- Items 3/8: the full OutcomeJudgment, including the P8-06 structured-claim
  fields (document_facts, regulatory_requirements, absences).
- Item 6: every retrieved source per outcome (cited or not), with node IDs.
- Item 7: the extracted fields (`_cached_fields`) for every run.
- Item 9: the raw judgment cited_sources list next to the resolved one, so an
  out-of-range excerpt number is visible rather than silently dropped.

No API calls, no Chroma, no embedding model. Only the two LLM-backed agents
are faked. FirstPassResult, QueryResult, SourceCitation, OutcomeJudgment and
the real deterministic build_compliance_report (P4-02) are used as-is, so
citation resolution really runs. Extraction differs on every run, like the
real non-deterministic call. The real Phase 8 main-pass file and
docs/eval_summary.json are hashed before and after, and docs/ is checked
for new files.
"""

import argparse
import hashlib
import json
from types import SimpleNamespace

import pytest

from src.agent.compliance import OutcomeJudgment
from src.agent.first_pass import FirstPassResult
from src.agent.schemas import LoanAgreementFields
from src.evaluation import run_eval
from src.retrieval import query_engine
from src.retrieval.query_engine import QueryResult, SourceCitation
from tests.fixtures.eval_set import EVAL_DOCUMENTS, OUTCOME_KEYS

TEST_DOCS = EVAL_DOCUMENTS[:2]
N_RUNS = 3
OUT_OF_RANGE = 9  # only excerpts 1-5 are retrieved
CONTEXT_FIELDS = {
    "price_and_value": "price_and_value_context",
    "consumer_support": "consumer_support_context",
    "products_and_services": "products_and_services_context",
    "consumer_understanding": "consumer_understanding_context",
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module", autouse=True)
def phase8_files_untouched():
    protected = [run_eval.MAIN_PASS_PATH, run_eval.SUMMARY_PATH]
    before = {p: _sha256(p) for p in protected}
    docs_before = sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir())
    yield
    assert {p: _sha256(p) for p in protected} == before, "a Phase 8 file was modified"
    assert sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir()) == docs_before, "a file was created or removed in docs/"


def _base_fields():
    row = next(r for r in _rows(run_eval.MAIN_PASS_PATH) if r["run_idx"] == 0)
    return row["_cached_fields"]


def _sources(doc_id, outcome, run):
    return [
        SourceCitation(
            index=i, file_name="fake.pdf", similarity_score=0.7,
            text_excerpt=f"{doc_id} {outcome} run {run} excerpt {i}", node_id=f"{doc_id}-{outcome}-r{run}-node{i}",
        )
        for i in range(1, 6)
    ]


def _judgment(doc_id, outcome, run):
    return OutcomeJudgment(
        status="compliant",
        reasoning=f"{doc_id} {outcome} run {run} reasoning",
        # price_and_value cites an excerpt number that does not exist (item 9).
        cited_sources=[1, OUT_OF_RANGE] if outcome == "price_and_value" else [1, 2],
        document_facts=[{"claim": f"{doc_id} fact run {run}", "verbatim_quote": "quoted document text"}],
        regulatory_requirements=[{
            "claim": f"{doc_id} {outcome} requirement run {run}",
            "sources": [{"excerpt_number": 1, "verbatim_quote": "q1"}, {"excerpt_number": 2, "verbatim_quote": "q2"}],
        }],
        absences=[{"claim": "nothing on x", "kind": "absent_from_retrieved_regulation", "explanation": "looked for x"}],
    )


@pytest.fixture
def main_rows(tmp_path, monkeypatch):
    """Runs `main` over 2 docs x 3 runs into a temp v2 file; returns (rows, expected)."""
    base = _base_fields()
    expected = {"fields": {}, "judgments": {}, "sources": {}}
    state = {"doc": None, "run": {}}

    class FakeFirstPassAgent:
        def run(self, text):
            doc_id = next(d["id"] for d in TEST_DOCS if run_eval._load_doc_text(d["file"]) == text)
            run = state["run"].get(doc_id, 0)
            state["run"][doc_id] = run + 1
            state["doc"] = (doc_id, run)
            fields = LoanAgreementFields(**{**base, "fees": f"{doc_id} fees as extracted on run {run}"})
            expected["fields"][(doc_id, run)] = fields.model_dump()
            contexts = {}
            for k in OUTCOME_KEYS:
                srcs = _sources(doc_id, k, run)
                expected["sources"][(doc_id, run, k)] = [s.model_dump() for s in srcs]
                contexts[CONTEXT_FIELDS[k]] = QueryResult(
                    question="q", answer="a", sources=srcs, confidence=0.7, needs_human_review=False
                )
            return FirstPassResult(document_fields=fields, **contexts)

    class FakeComplianceAgent:
        def evaluate(self, first_pass, document_text):
            doc_id, run = state["doc"]
            js = {k: _judgment(doc_id, k, run) for k in OUTCOME_KEYS}
            for k, j in js.items():
                expected["judgments"][(doc_id, run, k)] = j.model_dump()
            return js

    out = tmp_path / "eval_raw_main_pass_v2.jsonl"
    monkeypatch.setattr(run_eval, "MAIN_PASS_V2_PATH", out)
    monkeypatch.setattr(run_eval, "EVAL_DOCUMENTS", TEST_DOCS)
    monkeypatch.setattr(run_eval, "FirstPassAgent", FakeFirstPassAgent)
    monkeypatch.setattr(run_eval, "ComplianceAgent", FakeComplianceAgent)
    run_eval.cmd_main(argparse.Namespace(n_runs=N_RUNS, output=None))
    rows = _rows(out)
    assert sorted((r["doc_id"], r["run_idx"]) for r in rows) == sorted(
        (d["id"], r) for d in TEST_DOCS for r in range(N_RUNS)
    )
    return rows, expected, out


# --- items 3/8 ---

def test_items_3_8_full_judgment_saved_for_every_run(main_rows):
    rows, expected, _ = main_rows
    for r in rows:
        for k in OUTCOME_KEYS:
            saved = r["outcomes"][k]["judgment"]
            assert saved == expected["judgments"][(r["doc_id"], r["run_idx"], k)]
            assert OutcomeJudgment.model_validate(saved).model_dump() == saved  # round-trips
            assert saved["document_facts"] and saved["regulatory_requirements"] and saved["absences"]
            assert len(saved["regulatory_requirements"][0]["sources"]) == 2
    assert {r["run_idx"] for r in rows} == {0, 1, 2}


def test_items_3_8_existing_summary_fields_still_present_for_readers(main_rows, tmp_path):
    rows, _, out = main_rows
    for r in rows:
        for k in OUTCOME_KEYS:
            o = r["outcomes"][k]
            assert {"llm_status", "status", "confidence", "cited_source_count", "cited_sources", "reasoning"} <= set(o)
    run_eval.cmd_summary(argparse.Namespace(input=str(out)))  # the existing reader still works on new records
    summary = json.loads(out.with_name("eval_raw_main_pass_v2_summary.json").read_text(encoding="utf-8"))
    assert summary["n_main_runs"] == len(rows)


# --- item 6 ---

def test_item6_full_retrieved_set_with_node_ids_saved_for_every_run(main_rows):
    rows, expected, _ = main_rows
    for r in rows:
        for k in OUTCOME_KEYS:
            o = r["outcomes"][k]
            retrieved = o["retrieved_sources"]
            assert retrieved == expected["sources"][(r["doc_id"], r["run_idx"], k)]
            assert [s["index"] for s in retrieved] == [1, 2, 3, 4, 5]
            assert all(s["node_id"] for s in retrieved)
            cited = {s["index"] for s in o["cited_sources"]}
            assert {s["index"] for s in retrieved} - cited  # uncited sources are saved too


def test_item6_query_engine_records_node_ids():
    class _Node:
        def __init__(self, i):
            self.node = SimpleNamespace(node_id=f"chroma-node-{i}")
            self.metadata = {"file_name": "fake.pdf"}
            self.score = 0.7
            self.text = "text"

    engine = query_engine.QueryEngine.__new__(query_engine.QueryEngine)  # no index/model loading
    engine._retriever = SimpleNamespace(retrieve=lambda q: [_Node(i) for i in range(1, 4)])
    engine._client = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(content=[SimpleNamespace(type="text", text="a [1]")])
    ))
    engine._no_answer_message = query_engine.NO_ANSWER_MESSAGE
    engine._system_prompt = ""
    assert [s.node_id for s in engine.query("q").sources] == ["chroma-node-1", "chroma-node-2", "chroma-node-3"]
    assert SourceCitation(index=1, file_name="f", similarity_score=0.5, text_excerpt="t").node_id is None


# --- item 7 ---

def test_item7_phase8_data_lacked_fields_for_runs_1_and_2():
    # The gap being fixed, on the real (read-only) Phase 8 data.
    phase8 = _rows(run_eval.MAIN_PASS_PATH)
    assert all("_cached_fields" in r for r in phase8 if r["run_idx"] == 0)
    assert not any("_cached_fields" in r for r in phase8 if r["run_idx"] in (1, 2))


def test_item7_runs_1_and_2_now_save_their_own_extracted_fields(main_rows):
    rows, expected, _ = main_rows
    for r in rows:
        assert r["_cached_fields"] == expected["fields"][(r["doc_id"], r["run_idx"])]
    for doc in TEST_DOCS:
        fees = {r["run_idx"]: r["_cached_fields"]["fees"] for r in rows if r["doc_id"] == doc["id"]}
        assert set(fees) == {0, 1, 2}
        assert len(set(fees.values())) == 3  # each run's own extraction, not run 0's copied


def test_item7_price_and_value_context_cache_stays_run0_only(main_rows):
    rows, _, _ = main_rows
    assert all(("_cached_price_and_value_context" in r) == (r["run_idx"] == 0) for r in rows)


# --- item 9 ---

def test_item9_raw_cited_sources_kept_alongside_resolved(main_rows):
    rows, _, _ = main_rows
    for r in rows:
        pv = r["outcomes"]["price_and_value"]
        assert pv["cited_sources_raw"] == [1, OUT_OF_RANGE]  # the out-of-range number is kept
        assert [s["index"] for s in pv["cited_sources"]] == [1]  # resolution dropped it
        assert pv["cited_source_count"] == 1
        assert pv["judgment"]["cited_sources"] == [1, OUT_OF_RANGE]
        other = r["outcomes"]["consumer_support"]
        assert other["cited_sources_raw"] == [1, 2]
        assert [s["index"] for s in other["cited_sources"]] == [1, 2]

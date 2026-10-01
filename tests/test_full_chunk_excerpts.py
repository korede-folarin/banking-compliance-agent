"""
Offline tests for Session 25, Option A (pilot finding 2): the judge, and the
claim checker, see each retrieved source's whole chunk instead of its first
300 characters. Every new row records the excerpt length its judge saw
(`source_excerpt_chars`), and every replay of a recorded row uses that row's
own length, so rows judged before Session 25 (Phase 8, the Session 23 pilot,
both 300 characters) still replay exactly what their judge saw.

No API calls, no Chroma, no embedding model: retrievers, agents and the LLM
client are fakes. The real Phase 8 file is only read; protected files are
hashed before and after, and docs/ is checked for new files.
"""

import argparse
import hashlib
import json
from types import SimpleNamespace

import pytest

from src.agent.compliance import OutcomeJudgment
from src.agent.first_pass import FirstPassResult
from src.agent.schemas import LoanAgreementFields
from src.evaluation import claim_verification as cv
from src.evaluation import groundedness
from src.evaluation import run_eval
from src.retrieval import query_engine
from src.retrieval.query_engine import QueryResult, SourceCitation
from tests.fixtures.eval_set import EVAL_DOCUMENTS, OUTCOME_KEYS

LONG_TEXT = "Regulatory chunk text. " * 100  # 2,300 characters
PROTECTED = [run_eval.MAIN_PASS_PATH, run_eval.SUMMARY_PATH, run_eval.DOCS_OUT_DIR / "eval_groundedness.md"]
PHASE8_ROWS = [
    json.loads(line) for line in run_eval.MAIN_PASS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()
]
PHASE8_RUN0 = [r for r in PHASE8_ROWS if r["run_idx"] == 0]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def protected_files_untouched():
    before = {p: _sha256(p) for p in PROTECTED}
    docs_before = sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir())
    yield
    assert {p: _sha256(p) for p in PROTECTED} == before
    assert sorted(p.name for p in run_eval.DOCS_OUT_DIR.iterdir()) == docs_before


class _Node:
    def __init__(self, i):
        self.node = SimpleNamespace(node_id=f"node-{i}")
        self.metadata = {"file_name": "fake.pdf"}
        self.score = 0.7
        self.text = LONG_TEXT


class _Retriever:
    def as_retriever(self, similarity_top_k):
        return self

    def retrieve(self, question):
        return [_Node(i) for i in range(1, 6)]


def test_judge_now_sees_whole_chunks():
    engine = query_engine.QueryEngine.__new__(query_engine.QueryEngine)  # no index/model loading
    engine._retriever = _Retriever()
    engine._client = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(content=[SimpleNamespace(type="text", text="a [1]")])
    ))
    engine._no_answer_message = query_engine.NO_ANSWER_MESSAGE
    engine._system_prompt = ""
    assert all(s.text_excerpt == LONG_TEXT for s in engine.query("q").sources)


def test_excerpt_chars_for_reads_the_row_else_pins_to_300():
    assert query_engine.excerpt_chars_for({"source_excerpt_chars": None}) is None
    assert query_engine.excerpt_chars_for({"source_excerpt_chars": 40}) == 40
    assert query_engine.excerpt_chars_for({}) == 300  # Phase 8 and Session 23 pilot rows
    assert all("source_excerpt_chars" not in r for r in PHASE8_ROWS)


def test_groundedness_replay_of_phase8_rows_stays_at_300(monkeypatch):
    monkeypatch.setattr(groundedness, "load_index", lambda: _Retriever())
    monkeypatch.setattr(groundedness, "compute_signal1", lambda reasoning, sources: 0.5)
    scope = groundedness.build_scope(PHASE8_RUN0[:2])
    assert scope and all(len(s["text_excerpt"]) == 300 for j in scope for s in j["sources"])


def test_groundedness_replay_of_a_new_row_uses_its_recorded_length(monkeypatch):
    monkeypatch.setattr(groundedness, "load_index", lambda: _Retriever())
    monkeypatch.setattr(groundedness, "compute_signal1", lambda reasoning, sources: 0.5)
    row = json.loads(json.dumps(PHASE8_RUN0[0]))
    row["source_excerpt_chars"] = None  # judged after Session 25, sources not saved (hypothetical)
    scope = groundedness.build_scope([row])
    assert scope and all(s["text_excerpt"] == LONG_TEXT for j in scope for s in j["sources"])


def test_claim_verification_spot_check_and_judge_replay_pin_phase8_to_300(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cv, "load_index", lambda: _Retriever())
    assert all(len(s["text_excerpt"]) == 300 for s in cv.replay_sources(
        _Retriever(), LoanAgreementFields(**PHASE8_RUN0[0]["_cached_fields"]), "price_and_value",
        query_engine.excerpt_chars_for(PHASE8_RUN0[0]),
    ))

    seen = []

    class FakeAgent:
        def evaluate(self, first_pass, document_text):
            seen.append({len(s.text_excerpt) for s in first_pass.price_and_value_context.sources})
            return {k: OutcomeJudgment(status="compliant", reasoning="r", cited_sources=[1], document_facts=[],
                                       regulatory_requirements=[], absences=[]) for k in OUTCOME_KEYS}

    monkeypatch.setattr(cv, "ComplianceAgent", FakeAgent)
    judgments = tmp_path / "judgments.jsonl"
    cv.cmd_judge(argparse.Namespace(docs=[PHASE8_RUN0[0]["doc_id"]], runs=[0], judgments=str(judgments),
                                    input=str(run_eval.MAIN_PASS_PATH)))
    row = json.loads(judgments.read_text(encoding="utf-8").splitlines()[0])
    assert seen == [{300}]  # the re-judge saw what the Phase 8 judge saw
    assert row["source_excerpt_chars"] == 300


def test_main_pass_records_its_excerpt_length_and_saves_whole_chunks(monkeypatch, tmp_path):
    base = PHASE8_RUN0[0]["_cached_fields"]

    class FakeFirstPassAgent:
        def run(self, text):
            srcs = [SourceCitation(index=i, file_name="f.pdf", similarity_score=0.7, text_excerpt=LONG_TEXT,
                                   node_id=f"n{i}") for i in range(1, 6)]
            ctx = {f"{k}_context": QueryResult(question="q", answer="a", sources=srcs, confidence=0.7,
                                               needs_human_review=False) for k in OUTCOME_KEYS}
            return FirstPassResult(document_fields=LoanAgreementFields(**base), **ctx)

    class FakeComplianceAgent:
        def evaluate(self, first_pass, document_text):
            return {k: OutcomeJudgment(status="compliant", reasoning="r", cited_sources=[1], document_facts=[],
                                       regulatory_requirements=[], absences=[]) for k in OUTCOME_KEYS}

    out = tmp_path / "pass.jsonl"
    monkeypatch.setattr(run_eval, "FirstPassAgent", FakeFirstPassAgent)
    monkeypatch.setattr(run_eval, "ComplianceAgent", FakeComplianceAgent)
    run_eval.cmd_main(argparse.Namespace(n_runs=1, output=str(out), docs=[EVAL_DOCUMENTS[0]["id"]]))
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert "source_excerpt_chars" in row and row["source_excerpt_chars"] is None
    assert all(s["text_excerpt"] == LONG_TEXT for s in row["outcomes"]["price_and_value"]["retrieved_sources"])

    # ingest carries the recorded length forward; an older row without it becomes 300.
    old = json.loads(json.dumps(row))
    del old["source_excerpt_chars"]
    old["doc_id"] = EVAL_DOCUMENTS[1]["id"]
    with open(out, "a", encoding="utf-8") as f:
        f.write(json.dumps(old) + "\n")
    target = tmp_path / "ingested.jsonl"
    cv.cmd_ingest(argparse.Namespace(input=str(out), judgments=str(target), docs=None, runs=None))
    ingested = {r["doc_id"]: r["source_excerpt_chars"] for r in map(json.loads, target.read_text(encoding="utf-8").splitlines())}
    assert ingested == {EVAL_DOCUMENTS[0]["id"]: None, EVAL_DOCUMENTS[1]["id"]: 300}

"""
Offline tests for deferred-checklist item 20 (ARCHITECTURE.md "Evaluation
notes"): the excerpt length a compliance judgment sees is defined once, as
src.retrieval.query_engine.SOURCE_EXCERPT_CHARS. The query engine,
groundedness.py's retrieval replay and claim_verification.py's retrieval
replay all read it at call time, so changing that one constant changes all
three without editing either evaluation file.

No API calls, no Chroma, no embedding model: retrievers and the LLM client
are fakes.
"""

import inspect
import json
from types import SimpleNamespace

import pytest

from src.agent.schemas import LoanAgreementFields
from src.evaluation import claim_verification as cv
from src.evaluation import groundedness
from src.evaluation import run_eval
from src.retrieval import query_engine

LONG_TEXT = "x" * 1000


class _FakeNode:
    def __init__(self, i):
        self.node = SimpleNamespace(node_id=f"n{i}")
        self.metadata = {"file_name": "fake.pdf"}
        self.score = 0.7
        self.text = LONG_TEXT


class _FakeRetriever:
    def retrieve(self, question):
        return [_FakeNode(i) for i in range(1, 6)]


class _FakeAnthropic:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="answer [1]")])


@pytest.fixture(scope="module")
def fields():
    row = next(
        json.loads(line)
        for line in run_eval.MAIN_PASS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["run_idx"] == 0
    )
    return LoanAgreementFields(**row["_cached_fields"])


def _query_engine_excerpts():
    engine = query_engine.QueryEngine.__new__(query_engine.QueryEngine)  # skip index/model loading
    engine._retriever = _FakeRetriever()
    engine._client = _FakeAnthropic()
    engine._no_answer_message = query_engine.NO_ANSWER_MESSAGE
    engine._system_prompt = ""
    return [s.text_excerpt for s in engine.query("q").sources]


def _all_excerpt_lengths(fields):
    return {
        "query_engine": {len(t) for t in _query_engine_excerpts()},
        "groundedness": {len(s["text_excerpt"]) for s in groundedness.reconstruct_sources(_FakeRetriever(), fields, "price_and_value")},
        "claim_verification": {len(s["text_excerpt"]) for s in cv.replay_sources(_FakeRetriever(), fields, "price_and_value")},
    }


def test_single_constant_is_defined_in_the_query_engine():
    assert query_engine.SOURCE_EXCERPT_CHARS == 300
    assert "node.text[:SOURCE_EXCERPT_CHARS]" in inspect.getsource(query_engine.QueryEngine.query)


def test_neither_evaluation_file_hardcodes_the_length():
    for module, func in [(groundedness, groundedness.reconstruct_sources), (cv, cv.replay_sources)]:
        assert "query_engine.SOURCE_EXCERPT_CHARS" in inspect.getsource(func)
        source = inspect.getsource(module)
        assert "[:300]" not in source
        assert "EXCERPT_CHARS = " not in source  # no local copy of the constant


def test_all_three_use_the_current_value(fields):
    assert _all_excerpt_lengths(fields) == {
        "query_engine": {300}, "groundedness": {300}, "claim_verification": {300},
    }


def test_changing_the_query_engine_constant_changes_all_three(fields, monkeypatch):
    monkeypatch.setattr(query_engine, "SOURCE_EXCERPT_CHARS", 40)
    assert _all_excerpt_lengths(fields) == {
        "query_engine": {40}, "groundedness": {40}, "claim_verification": {40},
    }

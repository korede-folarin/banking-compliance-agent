import os

import pytest

from src.retrieval.query_engine import NO_ANSWER_MESSAGE, QueryEngine

EXPECTED_SOURCE_FILES = {
    "FCA Handbook - PRIN 2A The Consumer Duty.pdf",
    "fg22-5.pdf",
    "ps22-9.pdf",
}

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") == "your_key_here",
    reason="ANTHROPIC_API_KEY not set — skipping live query engine tests",
)


@pytest.fixture(scope="module")
def engine():
    return QueryEngine()


def test_grounded_answer_names_the_four_outcomes(engine):
    result = engine.query(
        "What are the four outcomes firms must deliver under the Consumer Duty?"
    )
    assert result.answer.strip() != NO_ANSWER_MESSAGE
    assert len(result.sources) > 0
    assert all(s.file_name in EXPECTED_SOURCE_FILES for s in result.sources)
    assert "price and value" in result.answer.lower()
    assert "consumer understanding" in result.answer.lower()


def test_grounded_answer_for_vulnerable_customers(engine):
    result = engine.query(
        "How should firms treat vulnerable customers under the Consumer Duty?"
    )
    assert result.answer.strip() != NO_ANSWER_MESSAGE
    assert "vulnerab" in result.answer.lower()
    assert len(result.sources) > 0


def test_answer_cites_inline_source_markers(engine):
    result = engine.query("What is the price and value outcome?")
    assert result.answer.strip() != NO_ANSWER_MESSAGE
    assert any(f"[{s.index}]" in result.answer for s in result.sources)


def test_off_topic_question_is_refused_not_hallucinated(engine):
    result = engine.query("What is the capital of France?")
    assert result.answer.strip() == NO_ANSWER_MESSAGE

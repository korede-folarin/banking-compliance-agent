import os
from pathlib import Path

import pytest

from src.agent.first_pass import FirstPassResult, run_first_pass

DOC_PATH = Path(__file__).resolve().parent.parent / "data" / "synthetic_docs" / "loan_agreement_1.txt"

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") == "your_key_here",
    reason="ANTHROPIC_API_KEY not set — skipping live first-pass agent tests",
)

CONTEXT_FIELDS = [
    "price_and_value_context",
    "consumer_support_context",
    "products_and_services_context",
    "consumer_understanding_context",
]


@pytest.fixture(scope="module")
def result() -> FirstPassResult:
    return run_first_pass(DOC_PATH.read_text(encoding="utf-8"))


def test_result_is_combined_fields_plus_context(result):
    assert isinstance(result, FirstPassResult)
    assert result.document_fields is not None
    for field_name in CONTEXT_FIELDS:
        assert getattr(result, field_name) is not None


def test_extracted_fields_match_source_document(result):
    f = result.document_fields
    assert f.lender_name == "Northfield Consumer Finance Ltd"
    assert f.borrower_name == "Daniel Osei"
    assert f.loan_amount == pytest.approx(8500.0)
    assert f.apr == pytest.approx(24.9)
    assert f.term_months == 36


@pytest.mark.parametrize("field_name", CONTEXT_FIELDS)
def test_each_outcome_context_is_grounded_and_relevant(result, field_name):
    ctx = getattr(result, field_name)
    assert len(ctx.answer) > 0
    assert len(ctx.sources) > 0
    assert all(s.similarity_score > 0.4 for s in ctx.sources)
    assert "[1]" in ctx.answer  # inline citation marker


def test_the_four_regulatory_queries_are_genuinely_distinct(result):
    # Guards against a wiring bug where calls accidentally collapse onto
    # the same question/answer instead of being derived from the four
    # different Consumer-Duty-outcome fields.
    questions = [getattr(result, f).question for f in CONTEXT_FIELDS]
    answers = [getattr(result, f).answer for f in CONTEXT_FIELDS]
    assert len(set(questions)) == len(CONTEXT_FIELDS)
    assert len(set(answers)) == len(CONTEXT_FIELDS)

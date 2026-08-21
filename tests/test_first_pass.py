import os
from pathlib import Path

import pytest

from src.agent.first_pass import FirstPassResult, run_first_pass

DOC_PATH = Path(__file__).resolve().parent.parent / "data" / "synthetic_docs" / "loan_agreement_1.txt"

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") == "your_key_here",
    reason="ANTHROPIC_API_KEY not set — skipping live first-pass agent tests",
)


@pytest.fixture(scope="module")
def result() -> FirstPassResult:
    return run_first_pass(DOC_PATH.read_text(encoding="utf-8"))


def test_result_is_combined_fields_plus_context(result):
    assert isinstance(result, FirstPassResult)
    assert result.document_fields is not None
    assert result.fee_disclosure_context is not None
    assert result.vulnerable_customer_context is not None


def test_extracted_fields_match_source_document(result):
    f = result.document_fields
    assert f.lender_name == "Northfield Consumer Finance Ltd"
    assert f.borrower_name == "Daniel Osei"
    assert f.loan_amount == pytest.approx(8500.0)
    assert f.apr == pytest.approx(24.9)
    assert f.term_months == 36


def test_fee_context_is_grounded_and_relevant(result):
    ctx = result.fee_disclosure_context
    assert len(ctx.answer) > 0
    assert len(ctx.sources) > 0
    assert all(s.similarity_score > 0.4 for s in ctx.sources)
    assert "[1]" in ctx.answer  # inline citation marker


def test_vulnerable_customer_context_is_grounded_and_relevant(result):
    ctx = result.vulnerable_customer_context
    assert len(ctx.answer) > 0
    assert len(ctx.sources) > 0
    assert all(s.similarity_score > 0.4 for s in ctx.sources)
    assert "[1]" in ctx.answer


def test_the_two_regulatory_queries_are_genuinely_distinct(result):
    # Guards against a wiring bug where both calls accidentally get the
    # same question/answer instead of being derived from different parts
    # of the extracted fields.
    assert result.fee_disclosure_context.question != result.vulnerable_customer_context.question
    assert result.fee_disclosure_context.answer != result.vulnerable_customer_context.answer

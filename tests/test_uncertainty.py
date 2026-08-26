import os
from pathlib import Path

import pytest

from src.agent.schemas import LoanAgreementFields
from src.agent.uncertainty import (
    NOT_ADDRESSED,
    compute_field_confidence,
    extract_fields_with_confidence,
)

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic_docs"


def _load(name: str) -> str:
    return (DOCS_DIR / name).read_text(encoding="utf-8")


DOC1_TEXT = _load("loan_agreement_1.txt")

CORRECT_DOC1_FIELDS = LoanAgreementFields(
    lender_name="Northfield Consumer Finance Ltd",
    borrower_name="Daniel Osei",
    loan_amount=8500.0,
    apr=24.9,
    term_months=36,
    repayment_schedule="36 equal monthly instalments of £337.70",
    fees="Administration and arrangement charges may apply, referenced via the Lender's standard tariff of charges, no specific amount stated",
    vulnerable_customer_provision="The Lender recognises that some customers may be in vulnerable circumstances",
    fair_value_justification=NOT_ADDRESSED,
    target_market_suitability_statement="This Loan has been designed for consumers seeking a fixed-rate, fixed-term personal loan",
    key_terms_summary_provision="KEY FACTS AT A GLANCE: Loan amount, APR, term, monthly repayment, total repayable",
)


# --- Deterministic unit tests: no LLM call, no API key needed. ---


def test_correct_numeric_fields_are_fully_grounded():
    scores = compute_field_confidence(DOC1_TEXT, CORRECT_DOC1_FIELDS)
    assert scores["loan_amount"] == 1.0
    assert scores["apr"] == 1.0
    assert scores["term_months"] == 1.0


def test_fabricated_numeric_field_is_not_grounded():
    fabricated = CORRECT_DOC1_FIELDS.model_copy(update={"loan_amount": 99999.0, "apr": 5.5})
    scores = compute_field_confidence(DOC1_TEXT, fabricated)
    assert scores["loan_amount"] == 0.0
    assert scores["apr"] == 0.0
    # A field that wasn't tampered with should be unaffected.
    assert scores["term_months"] == 1.0


def test_correct_name_fields_are_fully_grounded():
    scores = compute_field_confidence(DOC1_TEXT, CORRECT_DOC1_FIELDS)
    assert scores["lender_name"] == 1.0
    assert scores["borrower_name"] == 1.0


def test_fabricated_name_field_is_not_grounded():
    fabricated = CORRECT_DOC1_FIELDS.model_copy(update={"borrower_name": "Someone Else Entirely"})
    scores = compute_field_confidence(DOC1_TEXT, fabricated)
    assert scores["borrower_name"] == 0.0
    assert scores["lender_name"] == 1.0


def test_not_addressed_fallback_is_always_trivially_grounded():
    fields = CORRECT_DOC1_FIELDS.model_copy(
        update={
            "vulnerable_customer_provision": NOT_ADDRESSED,
            "target_market_suitability_statement": NOT_ADDRESSED,
            "key_terms_summary_provision": NOT_ADDRESSED,
        }
    )
    scores = compute_field_confidence(DOC1_TEXT, fields)
    assert scores["vulnerable_customer_provision"] == 1.0
    assert scores["target_market_suitability_statement"] == 1.0
    assert scores["key_terms_summary_provision"] == 1.0
    assert scores["fair_value_justification"] == 1.0  # already NOT_ADDRESSED in the fixture


def test_correct_free_text_fields_score_above_threshold():
    scores = compute_field_confidence(DOC1_TEXT, CORRECT_DOC1_FIELDS)
    for field in ["repayment_schedule", "fees", "vulnerable_customer_provision", "target_market_suitability_statement", "key_terms_summary_provision"]:
        assert scores[field] > 0.65, f"{field} scored {scores[field]}, expected a genuinely grounded value to score comfortably higher"


def test_fabricated_free_text_field_scores_meaningfully_lower_than_correct():
    fabricated = CORRECT_DOC1_FIELDS.model_copy(
        update={
            "fees": "A fixed monthly maintenance fee of £45.00 is charged for account servicing, in addition to interest.",
            "vulnerable_customer_provision": "The Lender offers free financial counselling sessions to all customers every Tuesday at 2pm.",
        }
    )
    correct_scores = compute_field_confidence(DOC1_TEXT, CORRECT_DOC1_FIELDS)
    fabricated_scores = compute_field_confidence(DOC1_TEXT, fabricated)
    assert fabricated_scores["fees"] < correct_scores["fees"]
    assert fabricated_scores["vulnerable_customer_provision"] < correct_scores["vulnerable_customer_provision"]


# --- Live end-to-end tests: real extraction via the Claude API. ---

pytestmark_live = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") == "your_key_here",
    reason="ANTHROPIC_API_KEY not set — skipping live extraction-confidence tests",
)


@pytestmark_live
def test_real_extraction_on_all_three_docs_is_confidently_grounded():
    for name in ["loan_agreement_1.txt", "loan_agreement_2.txt", "loan_agreement_3.txt"]:
        result = extract_fields_with_confidence(_load(name))
        assert result.needs_human_review is False, (
            f"{name}: a correct, real extraction was flagged for human review "
            f"(confidence={result.confidence}, field_confidence={result.field_confidence})"
        )
        assert 0.0 <= result.confidence <= 1.0
        assert set(result.field_confidence.keys()) == {
            "lender_name", "borrower_name", "loan_amount", "apr", "term_months",
            "repayment_schedule", "fees", "vulnerable_customer_provision",
            "fair_value_justification", "target_market_suitability_statement",
            "key_terms_summary_provision",
        }

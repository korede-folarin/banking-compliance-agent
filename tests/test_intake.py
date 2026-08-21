import os
from pathlib import Path

import pytest

from src.agent.intake import extract_fields
from src.agent.schemas import LoanAgreementFields

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic_docs"
NOT_ADDRESSED = "Not addressed in this document."

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") == "your_key_here",
    reason="ANTHROPIC_API_KEY not set — skipping live intake extraction tests",
)


def _load(name: str) -> str:
    return (DOCS_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def doc1_fields() -> LoanAgreementFields:
    return extract_fields(_load("loan_agreement_1.txt"))


@pytest.fixture(scope="module")
def doc2_fields() -> LoanAgreementFields:
    return extract_fields(_load("loan_agreement_2.txt"))


@pytest.fixture(scope="module")
def doc3_fields() -> LoanAgreementFields:
    return extract_fields(_load("loan_agreement_3.txt"))


def test_doc1_core_fields_match_source(doc1_fields):
    f = doc1_fields
    assert f.lender_name == "Northfield Consumer Finance Ltd"
    assert f.borrower_name == "Daniel Osei"
    assert f.loan_amount == pytest.approx(8500.0)
    assert f.apr == pytest.approx(24.9)
    assert f.term_months == 36
    assert "337.70" in f.repayment_schedule


def test_doc2_core_fields_match_source(doc2_fields):
    f = doc2_fields
    assert f.lender_name == "Bridgeport Lending Group"
    assert f.borrower_name == "Rebecca Ashworth"
    assert f.loan_amount == pytest.approx(12000.0)
    assert f.apr == pytest.approx(19.9)
    assert f.term_months == 48
    assert "390.60" in f.repayment_schedule


def test_doc3_core_fields_match_source(doc3_fields):
    f = doc3_fields
    assert f.lender_name == "Thornebury Finance Ltd"
    assert f.borrower_name == "Marcus Chen"
    assert f.loan_amount == pytest.approx(10000.0)
    assert f.apr == pytest.approx(21.5)
    assert f.term_months == 42
    assert "340.80" in f.repayment_schedule


def test_doc1_fee_disclosure_is_captured_as_vague_not_invented(doc1_fields):
    # loan_agreement_1.txt deliberately never states a fee amount — it only
    # references a separate "tariff of charges". Extraction must reflect
    # that ambiguity rather than hallucinating a number.
    fees = doc1_fields.fees.lower()
    assert "tariff" in fees or "not stated" in fees or "no specific" in fees or "no amount" in fees
    assert "150" not in fees
    assert "200" not in fees


def test_doc2_and_doc3_fee_amounts_are_captured_precisely(doc2_fields, doc3_fields):
    assert "150" in doc2_fields.fees
    assert "200" in doc3_fields.fees


def test_doc2_reports_vulnerable_customer_provision_as_not_addressed(doc2_fields):
    # loan_agreement_2.txt deliberately omits any vulnerable-customer
    # process. Extraction must explicitly say so, not invent one or
    # silently omit the field.
    assert doc2_fields.vulnerable_customer_provision == NOT_ADDRESSED


def test_doc1_and_doc3_capture_their_vulnerable_customer_provisions(doc1_fields, doc3_fields):
    assert doc1_fields.vulnerable_customer_provision != NOT_ADDRESSED
    assert "vulnerab" in doc1_fields.vulnerable_customer_provision.lower()
    assert doc3_fields.vulnerable_customer_provision != NOT_ADDRESSED
    assert "vulnerab" in doc3_fields.vulnerable_customer_provision.lower()


@pytest.mark.parametrize("doc_fixture", ["doc1_fields", "doc2_fields", "doc3_fields"])
def test_fields_none_of_the_docs_address_report_not_addressed_explicitly(doc_fixture, request):
    # None of the 3 synthetic documents contain a fair-value justification,
    # a target-market suitability statement, or a standalone key-terms
    # summary — they weren't written with those features. Extraction must
    # say so explicitly for all three, for all three fields: this is the
    # "never silently omit" behaviour actually being exercised, not just
    # asserted in a docstring.
    fields: LoanAgreementFields = request.getfixturevalue(doc_fixture)
    assert fields.fair_value_justification == NOT_ADDRESSED
    assert fields.target_market_suitability_statement == NOT_ADDRESSED
    assert fields.key_terms_summary_provision == NOT_ADDRESSED

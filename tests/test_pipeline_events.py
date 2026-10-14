"""
Pipeline stage events (docs/audit_logging_design.md, section 5): extraction,
retrieval, judgment and validation log success events and checks when an
audit run is active, nothing when it is not, and never change a result.
Offline: built objects, no model call.
"""

import json

from src import config
from src.agent.compliance import OutcomeJudgment, validate_outcome
from src.agent.schemas import LoanAgreementFields
from src.monitoring import audit, pipeline_events
from src.retrieval.query_engine import QueryResult, SourceCitation

DOC = "Loan amount: £8,500.00. APR: 24.9%. Term: 36 months. Charges may apply."
CHUNK = "When considering the price charged, manufacturer firms must consider all the costs and charges."


def _fields(**over):
    base = dict(lender_name="L", borrower_name="B", loan_amount=8500.0, apr=24.9, term_months=36,
                repayment_schedule="monthly", fees="Charges may apply.",
                vulnerable_customer_provision="Not addressed in this document.",
                fair_value_justification="Not addressed in this document.",
                target_market_suitability_statement="x", key_terms_summary_provision="y")
    base.update(over)
    return LoanAgreementFields(**base)


def _context(score=0.68):
    return QueryResult(question="q?", answer="a", confidence=score, needs_human_review=False, sources=[
        SourceCitation(index=1, file_name="fg22-5.pdf", similarity_score=score, text_excerpt=CHUNK, node_id="n1")])


def _judgment(cited=(1,), quote="firms must consider all the costs and charges", doc_quote="Charges may apply."):
    return OutcomeJudgment.model_validate({
        "status": "potentially_non_compliant", "reasoning": "r", "cited_sources": list(cited),
        "document_facts": [{"claim": "c", "verbatim_quote": doc_quote}],
        "regulatory_requirements": [{"claim": "c", "sources": [{"excerpt_number": 1, "verbatim_quote": quote}]}],
        "absences": [],
    })


def _events():
    return [json.loads(line) for p in config.LOG_DIR.rglob("*-*.jsonl") for line in p.read_text(encoding="utf-8").splitlines()]


def _checks():
    return {e["data"]["name"]: e for e in _events() if e["event"] == "check"}


def test_nothing_is_written_without_a_run():
    pipeline_events.extraction(_fields(), DOC)
    pipeline_events.retrieval("price_and_value", _context())
    pipeline_events.judgment("price_and_value", _judgment(), _context(), DOC)
    assert not config.LOG_DIR.exists()


def test_extraction_success_and_numeric_checks():
    audit.start_run("unit test")
    pipeline_events.extraction(_fields(apr=19.9), DOC, 12)
    audit.end_run()
    [ok] = [e for e in _events() if e["stage"] == "extraction" and e["event"] == "success"]
    assert ok["data"]["not_addressed_count"] == 2 and ok["duration_ms"] == 12
    c = _checks()
    assert c["numeric_field_in_document:loan_amount"]["data"]["passed"] is True
    assert c["numeric_field_in_document:apr"]["data"]["passed"] is False  # 19.9 is not in the document
    assert c["numeric_field_in_document:apr"]["level"] == "warn"


def test_retrieval_logs_sources_and_flags_off_topic():
    audit.start_run("unit test")
    pipeline_events.retrieval("price_and_value", _context(0.38))
    audit.end_run()
    [ok] = [e for e in _events() if e["stage"] == "retrieval" and e["event"] == "success"]
    assert ok["outcome"] == "price_and_value" and ok["data"]["sources"][0]["node_id"] == "n1"
    assert _checks()["top_score_on_topic"]["data"]["passed"] is False


def test_judgment_checks_citations_and_quotes():
    audit.start_run("unit test")
    pipeline_events.judgment("price_and_value", _judgment(cited=(1, 7), quote="invented words not in chunk"),
                             _context(), DOC)
    audit.end_run()
    c = _checks()
    assert c["citations_in_range"]["data"]["passed"] is False and c["citations_in_range"]["data"]["metric"] == [7]
    q = c["quotes_found"]["data"]
    assert q["passed"] is False and q["metric"] == "1/2"
    assert q["not_found"] == [{"kind": "regulatory_requirement", "claim_index": 0, "excerpt_number": 1}]


def test_validation_event_matches_the_unchanged_result():
    audit.start_run("unit test")
    v = validate_outcome("price_and_value", _judgment(), _context(0.6), threshold=0.65)
    audit.end_run()
    assert v.status == "insufficient_evidence" and v.llm_status == "potentially_non_compliant"
    [e] = [e for e in _events() if e["stage"] == "validation" and e["event"] == "success"]
    assert e["data"]["overridden"] is True and e["data"]["confidence"] == 0.6 and e["data"]["threshold"] == 0.65
    assert _checks()["has_cited_source"]["data"]["passed"] is True

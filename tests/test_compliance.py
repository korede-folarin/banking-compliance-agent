import os
from pathlib import Path

import pytest

from src.agent.compliance import ComplianceCheckAgent, ComplianceReport

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic_docs"

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") == "your_key_here",
    reason="ANTHROPIC_API_KEY not set — skipping live compliance agent tests",
)

OUTCOME_KEYS = [
    "price_and_value",
    "consumer_support",
    "products_and_services",
    "consumer_understanding",
]

# Empirically, retrieval similarity for price_and_value and
# consumer_understanding against this corpus consistently comes back
# borderline (~0.61-0.68) regardless of which document is under review —
# it's a property of how well this corpus's text matches these two
# question framings, not of any particular document. consumer_support and
# products_and_services consistently retrieve much more strongly
# (~0.68-0.71). That gap matters beyond just the P4-02 confidence
# threshold: on a live rerun, the control document's own llm_status for
# price_and_value was observed as potentially_non_compliant once in five
# samples (compliant, compliant, insufficient_evidence,
# potentially_non_compliant, compliant) — a real, if infrequent, false
# accusation from P4-01 itself, not just P4-02 threshold caution. See
# ARCHITECTURE.md "Confidence threshold vs. LLM judgment" for the full
# account. "Never falsely flags" is only asserted below for the two
# consistently strongly-grounded outcomes; it is NOT a reliable claim for
# the other two given current retrieval quality.
STRONGLY_GROUNDED_OUTCOMES = ["consumer_support", "products_and_services"]


def _load(name: str) -> str:
    return (DOCS_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def agent() -> ComplianceCheckAgent:
    # Constructed once and reused across all 3 documents in this module —
    # avoids reloading the embedding model / reopening the Chroma client
    # per document.
    return ComplianceCheckAgent()


@pytest.fixture(scope="module")
def doc1_report(agent) -> ComplianceReport:
    return agent.run(_load("loan_agreement_1.txt"))


@pytest.fixture(scope="module")
def doc2_report(agent) -> ComplianceReport:
    return agent.run(_load("loan_agreement_2.txt"))


@pytest.fixture(scope="module")
def doc3_report(agent) -> ComplianceReport:
    return agent.run(_load("loan_agreement_3.txt"))


def _llm_statuses(report: ComplianceReport) -> dict[str, str]:
    return {key: getattr(report, key).llm_status for key in OUTCOME_KEYS}


def _statuses(report: ComplianceReport) -> dict[str, str]:
    return {key: getattr(report, key).status for key in OUTCOME_KEYS}


def test_doc1_vague_fee_flags_only_price_and_value(doc1_report):
    llm_statuses = _llm_statuses(doc1_report)
    assert llm_statuses["price_and_value"] == "potentially_non_compliant"
    for key in STRONGLY_GROUNDED_OUTCOMES:
        assert llm_statuses[key] != "potentially_non_compliant", (
            f"{key} was flagged non-compliant for doc1, but doc1's only "
            "deliberate issue is the vague fee disclosure (price_and_value)"
        )
    # Not asserting the post-threshold `status` here on purpose: this
    # outcome's retrieval confidence sits close to CONFIDENCE_THRESHOLD
    # (0.65), and which of the 5 candidate sources the LLM actually cites
    # varies slightly run to run even though retrieval itself is
    # deterministic — that citation-selection variance can flip
    # potentially_non_compliant to insufficient_evidence near the
    # boundary (see ARCHITECTURE.md "Confidence threshold vs. LLM
    # judgment"). llm_status is the stable, semantic signal this test is
    # actually about; needs_human_review holds either way.
    assert doc1_report.needs_human_review is True


def test_doc2_missing_vulnerable_customer_provision_flags_only_consumer_support(doc2_report):
    llm_statuses = _llm_statuses(doc2_report)
    assert llm_statuses["consumer_support"] == "potentially_non_compliant"
    for key in STRONGLY_GROUNDED_OUTCOMES:
        if key != "consumer_support":
            assert llm_statuses[key] != "potentially_non_compliant", (
                f"{key} was flagged non-compliant for doc2, but doc2's only "
                "deliberate issue is the missing vulnerable-customer "
                "provision (consumer_support)"
            )
    # Same reasoning as doc1 above: not asserting post-threshold `status`
    # here — doc2's consumer_support confidence has been observed as low
    # as 0.629 and as high as 0.651 across runs, straddling the 0.65
    # threshold, purely from which sources the LLM happens to cite.
    assert doc2_report.needs_human_review is True


def test_doc3_control_is_never_judged_non_compliant_on_strongly_grounded_outcomes(doc3_report):
    # This is the actual point of having a control: prove the reasoning
    # layer (P4-01) can recognise a fully compliant document, not just
    # flag everything by default. Restricted to STRONGLY_GROUNDED_OUTCOMES
    # (see module comment): across every sample collected during this
    # project, those two have never once been falsely flagged for the
    # control. price_and_value and consumer_understanding are excluded
    # from this hard assertion on purpose — they've been observed to
    # occasionally produce a real potentially_non_compliant verdict for
    # this same control document, traced to consistently weak retrieval
    # grounding for those two question framings against this corpus, not
    # a flaw in the document or the code. That's a genuine, documented
    # limitation (ARCHITECTURE.md), not something to test away.
    llm_statuses = _llm_statuses(doc3_report)
    statuses = _statuses(doc3_report)
    for key in STRONGLY_GROUNDED_OUTCOMES:
        assert llm_statuses[key] != "potentially_non_compliant", (
            f"Control document's own LLM judgment was potentially_non_compliant "
            f"on {key} — a strongly-grounded outcome that has never been "
            "falsely flagged before. Worth investigating, not just re-running."
        )
        assert statuses[key] != "potentially_non_compliant"


def test_doc3_control_may_still_need_review_due_to_untuned_threshold(doc3_report):
    # Known, documented behaviour, not a bug: CONFIDENCE_THRESHOLD (0.65,
    # from .env/config.py) hasn't been validated against real evaluation
    # data yet — that's Phase 8. For this corpus, retrieval similarity for
    # the price_and_value and consumer_understanding questions on this
    # specific document comes back just under 0.65, so the deterministic
    # layer downgrades those two outcomes to insufficient_evidence even
    # though the LLM's own judgment was compliant on all 4 — and
    # needs_human_review is still True as a result. See ARCHITECTURE.md
    # "Confidence threshold vs. LLM judgment" for the full account. This
    # assertion exists so a future threshold retune (once justified by
    # real Phase 8 evaluation data) has to consciously update it, not
    # silently break it.
    assert doc3_report.needs_human_review is True


def test_confidence_scores_are_grounded_in_retrieval_not_self_reported(doc1_report, doc2_report, doc3_report):
    for report in (doc1_report, doc2_report, doc3_report):
        for key in OUTCOME_KEYS:
            outcome = getattr(report, key)
            assert 0.0 <= outcome.confidence <= 1.0
            if outcome.cited_sources:
                expected = min(s.similarity_score for s in outcome.cited_sources)
                assert outcome.confidence == pytest.approx(expected)
            else:
                assert outcome.confidence == 0.0

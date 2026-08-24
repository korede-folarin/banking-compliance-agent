import os
from pathlib import Path

import pytest

from src.agent.compliance import ComplianceAgent, ComplianceCheckAgent

DOC_PATH = Path(__file__).resolve().parent.parent / "data" / "synthetic_docs" / "loan_agreement_1.txt"

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") == "your_key_here",
    reason="ANTHROPIC_API_KEY not set — skipping live MCP compliance tests",
)


@pytest.fixture(scope="module")
def baseline_report():
    # The existing P4-01/P4-02 pipeline, direct Python calls only, no MCP.
    return ComplianceCheckAgent().run(DOC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def enriched_result(baseline_report):
    # P5-04: the same outcome, judged via all three MCP tools.
    agent = ComplianceAgent()
    return agent.judge_price_and_value_with_mcp_context(baseline_report.document_fields, "Daniel Osei")


def test_enriched_judgment_cites_both_regulation_and_internal_policy_sources(enriched_result):
    _judgment, sources = enriched_result
    file_names = {s.file_name for s in sources}
    regulation_files = {f for f in file_names if f.endswith(".pdf")}
    policy_files = {f for f in file_names if f.endswith(".txt")}
    assert regulation_files, "expected at least one public regulation (.pdf) source"
    assert policy_files, "expected at least one internal policy (.txt) source"


def test_enriched_judgment_actually_cites_policy_sources_not_just_regulation(enriched_result):
    judgment, sources = enriched_result
    policy_indices = {s.index for s in sources if s.file_name.endswith(".txt")}
    assert set(judgment.cited_sources) & policy_indices, (
        "judgment.cited_sources never references an internal-policy source index — "
        "the policy tool's output was fetched but not actually used in reasoning"
    )


def test_enriched_reasoning_incorporates_account_context_baseline_never_sees(baseline_report, enriched_result):
    judgment, _sources = enriched_result
    enriched_reasoning = judgment.reasoning.lower()
    baseline_reasoning = baseline_report.price_and_value.reasoning.lower()

    # Content only available via the account-lookup MCP tool.
    assert "missed payment" in enriched_reasoning or "payment history" in enriched_reasoning
    # The baseline pipeline has no account tool at all, so this should be
    # absent there — proving the difference comes from the new tool calls,
    # not coincidental phrasing.
    assert "missed payment" not in baseline_reasoning
    assert "payment history" not in baseline_reasoning


def test_enriched_reasoning_differs_meaningfully_from_baseline_not_just_cosmetically(
    baseline_report, enriched_result
):
    judgment, _sources = enriched_result
    # Not a trivial equality check: the enriched version should be
    # substantially longer, reflecting genuinely new evidence incorporated
    # (regulation + policy + account), not a reworded restatement.
    assert len(judgment.reasoning) > len(baseline_report.price_and_value.reasoning) * 1.2


def test_enriched_judgment_has_valid_status_and_is_grounded(enriched_result):
    judgment, sources = enriched_result
    assert judgment.status in ("compliant", "potentially_non_compliant", "insufficient_evidence")
    assert len(judgment.cited_sources) > 0
    assert all(s.similarity_score > 0.4 for s in sources if s.index in judgment.cited_sources)

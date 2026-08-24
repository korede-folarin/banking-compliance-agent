import json
import os

import pytest
from dotenv import load_dotenv

# This file is the first in the suite whose imports (src.mcp_server.client)
# don't transitively import src.config, which is where every other test
# file's ANTHROPIC_API_KEY happens to get loaded from .env as a side
# effect. Relying on that import-order coincidence is fragile, so load
# .env explicitly here rather than depend on it.
load_dotenv()

from src.mcp_server.client import call_tools  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") == "your_key_here",
    reason="ANTHROPIC_API_KEY not set — skipping live MCP tool tests",
)


def test_lookup_account_finds_known_account_by_name():
    (raw,) = call_tools([("lookup_account", {"name_or_id": "Daniel Osei"})])
    result = json.loads(raw)
    assert result["found"] is True
    assert result["account_id"] == "ACC-10293"
    assert "two_missed_payments_last_12_months" in result["payment_history_flags"]


def test_lookup_account_finds_known_account_by_id():
    (raw,) = call_tools([("lookup_account", {"name_or_id": "ACC-20481"})])
    result = json.loads(raw)
    assert result["found"] is True
    assert result["account_holder_name"] == "Rebecca Ashworth"


def test_lookup_account_not_found_for_unknown_name():
    (raw,) = call_tools([("lookup_account", {"name_or_id": "Someone Who Does Not Exist"})])
    result = json.loads(raw)
    assert result["found"] is False


def test_lookup_regulation_returns_grounded_answer_from_fca_corpus():
    (raw,) = call_tools(
        [
            (
                "lookup_regulation",
                {"question": "What does the Price and Value outcome require regarding fee disclosure?"},
            )
        ]
    )
    result = json.loads(raw)
    assert len(result["answer"]) > 0
    assert len(result["sources"]) > 0
    assert all(s["similarity_score"] > 0.4 for s in result["sources"])
    # Every source should come from the public FCA corpus, not internal policy.
    assert all(not f["file_name"].endswith(".txt") for f in result["sources"])


def test_query_policy_returns_grounded_answer_from_internal_corpus():
    (raw,) = call_tools(
        [
            (
                "query_policy",
                {
                    "question": (
                        "What must happen if a loan agreement only references a fee via a "
                        "separate tariff of charges rather than stating a specific amount?"
                    )
                },
            )
        ]
    )
    result = json.loads(raw)
    assert len(result["answer"]) > 0
    assert len(result["sources"]) > 0
    # This is the actual proof of domain separation: the policy tool's
    # sources come from the internal policy corpus, never the FCA PDFs.
    # (Not asserting every source is underwriting_guidelines.txt
    # specifically: the internal corpus is intentionally tiny — 3 chunks
    # total across 2 files — so a top-5 retrieval naturally returns
    # chunks from both internal files, not just the most relevant one.)
    internal_policy_files = {"underwriting_guidelines.txt", "vulnerable_customer_escalation_procedure.txt"}
    assert all(s["file_name"] in internal_policy_files for s in result["sources"])
    assert "underwriting manager" in result["answer"].lower()


def test_policy_and_regulation_tools_give_genuinely_different_answers():
    # Same underlying question, asked of both tools. If the answers were
    # interchangeable, having two tools instead of one would be theatre.
    question = "What does the rule say about disclosing a fee that is only referenced via a separate tariff of charges?"
    raw_regulation, raw_policy = call_tools(
        [
            ("lookup_regulation", {"question": question}),
            ("query_policy", {"question": question}),
        ]
    )
    regulation_answer = json.loads(raw_regulation)["answer"]
    policy_answer = json.loads(raw_policy)["answer"]
    assert regulation_answer != policy_answer
    # The internal policy's specific, actionable language shouldn't appear
    # in the public-regulation answer, since that language isn't in the
    # FCA corpus at all.
    assert "underwriting manager" in policy_answer.lower()
    assert "underwriting manager" not in regulation_answer.lower()

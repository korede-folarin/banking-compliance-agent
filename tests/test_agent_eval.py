"""
Agent evaluation scoring (src/evaluation/agent_eval.py), offline. Rows come from the
real loop and validation layer driven by a scripted model and a fake MCP session on
real v2 documents, then scored against the real labels. No API calls.
"""

from pathlib import Path

import pytest

from src.agent.tool_agent import SUBMIT_TOOL, ToolAgent
from src.evaluation import agent_eval
from tests.test_tool_agent import (OWN, POLICY_TEXT, REG_CALLS, FakeClient, FakeSession, _account, _assessment,
                                   _factory, _judgment, _resp, _use)

LABELS = {d["doc_id"]: d for d in agent_eval._labels()}


def _row(doc_id, responses, account=None):
    lab = LABELS[doc_id]
    session = FakeSession(account or (_account() | {"customer_id": lab["customer_id"] or "CUST-00000"}))
    text = Path(lab["file"]).read_text(encoding="utf-8")
    result = ToolAgent(client=FakeClient(responses), session_factory=_factory(session), review_date="2026-10-01").run(text)
    return {"doc_id": doc_id, "run_idx": 0, "split": lab["split"], **result}


def _standard_turns(customer_id):
    return [_resp(_use(1, "get_account", {"customer_id": customer_id}), _use(2, "search_policy", {"query": "q"})),
            _resp(*REG_CALLS)]


def test_scores_tool_calls_outcomes_and_escalation():
    d01 = LABELS["v2_d01"]  # PV defect, two missed payments in window -> escalate 2.1(a)
    acct = (_account(events=("2026-03-14", "2026-07-14"))
            | {"customer_id": d01["customer_id"], "account_holder_name": "Amara Okafor"})  # the borrower in v2_d01
    a01 = _assessment(decision="escalate", triggers=("2.1(a)",),
                      outcomes={"price_and_value": _judgment([4], 4, status="potentially_non_compliant")})
    row01 = _row("v2_d01", [*_standard_turns(d01["customer_id"]), _resp(_use(9, SUBMIT_TOOL, a01))], account=acct)

    # v2_d19 is a letter: since the gate (2026-10-24) the model is not called and no tool can be
    row19 = _row("v2_d19", [])

    s = agent_eval.score_rows([row01, row19], LABELS, [])
    o = s["overall"]
    assert o["tool_calls"]["get_account"]["required_runs"] == 1 and o["tool_calls"]["get_account"]["correct_argument"] == 1
    assert o["tool_calls"]["search_regulation"]["all_outcomes_searched"] == 1
    assert o["tool_calls"]["search_regulation"]["forbidden_runs"] == 1
    assert o["tool_calls"]["search_regulation"]["forbidden_called"] == 0
    assert o["tool_calls"]["all"]["unnecessary_calls"] == 0 and o["tool_calls"]["all"]["turns"] == 3  # d01 only; d19 made none
    assert o["outcomes"]["price_and_value"]["llm_tp"] == 1 and o["outcomes"]["consumer_support"]["llm_tn"] == 1
    assert o["outcomes"]["price_and_value"]["not_applicable_docs"] == 1
    assert o["escalation"]["decision_correct"] == 2 and o["escalation"]["triggers_exact"] == 1
    assert set(s) == {"overall"}  # both rows are design: one split, so no per-split repeat of overall
    d02 = LABELS["v2_d02"]  # heldout
    row02 = _row("v2_d02", [*_standard_turns(d02["customer_id"]), _resp(_use(9, SUBMIT_TOOL, _assessment()))],
                 account=_account() | {"customer_id": d02["customer_id"]})
    s2 = agent_eval.score_rows([row01, row02], LABELS, [])
    assert s2["design"]["escalation"]["runs"] == 1 and s2["heldout"]["escalation"]["runs"] == 1
    assert "Tool calling" in agent_eval._report({**s, "meta": {"rows": 2, "input": "x", "claimchecks": 0, "errors": 0}})


def test_claims_for_claimcheck_carry_the_named_passage_text():
    lab = LABELS["v2_d01"]
    row = _row("v2_d01", [*_standard_turns(lab["customer_id"]),
                          _resp(_use(9, SUBMIT_TOOL, _assessment(policy=((2, POLICY_TEXT[:50]),))))],
               account=_account() | {"customer_id": lab["customer_id"]})
    claims = agent_eval._claims(row)
    assert len(claims) == 4
    for c in claims:  # each claim carries the text of its own outcome's passage
        assert len(c["texts"]) == 1 and f"({c['outcome']} passage 0)" in c["texts"][0]
    assert {c["outcome"] for c in claims} == set(OWN)


def test_refuses_protected_output():
    with pytest.raises(SystemExit):
        agent_eval._output("docs/eval_raw_main_pass_v2.jsonl")


# --- v1 set: the 15 hand-written baseline documents ---

def test_v1_labels_match_the_baseline_ground_truth_and_document_facts():
    from tests.fixtures.eval_set import EVAL_DOCUMENTS

    labels = agent_eval.build_v1_labels()
    assert [d["doc_id"] for d in labels] == [d["id"] for d in EVAL_DOCUMENTS]
    for lab, base in zip(labels, EVAL_DOCUMENTS):
        assert lab["ground_truth"] == base["ground_truth"]
        assert lab["expected_escalation"]["decision"] == "not_applicable"
        assert lab["expected_tool_calls"]["get_account"]["forbidden"] and lab["expected_tool_calls"]["search_policy"]["forbidden"]


def test_baseline_comparison_counts_the_same_documents():
    labels = {d["doc_id"]: d for d in agent_eval.build_v1_labels()}
    b = agent_eval.baseline_outcomes(labels)["outcomes"]
    for k, v in b.items():
        assert sum(n for key, n in v.items() if key.startswith("llm_")) == 45  # 15 documents x 3 runs

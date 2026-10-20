"""
P7-01 human review: "flagged issues require explicit human approval before marked resolved".
The rules are tested on the store directly (so no screen can skip them), then the Streamlit
screen is driven end to end with Streamlit's offline AppTest harness. No API calls.
"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import config
from src.review.cases import agent_case, baseline_case, load_cases
from src.review.store import DecisionStore, ReviewError

ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROW = json.loads((ROOT / "docs" / "eval_raw_main_pass_v2.jsonl").read_text(encoding="utf-8").splitlines()[0])


@pytest.fixture
def store(tmp_path):
    return DecisionStore(tmp_path / "decisions.jsonl")


@pytest.fixture
def case():
    return baseline_case(BASELINE_ROW)


# --- cases ---

def test_baseline_row_becomes_a_case_with_four_items_and_no_labels(case):
    assert [i.item_id for i in case.items] == ["price_and_value", "consumer_support", "products_and_services",
                                              "consumer_understanding"]
    assert case.document_file and case.document_file.name == "loan_agreement_1.txt"
    assert "ground_truth" not in json.dumps([vars(i) for i in case.items])  # reviewers never see labels
    pv = case.items[0]
    assert pv.system_verdict == BASELINE_ROW["outcomes"]["price_and_value"]["status"] and pv.claims


def test_agent_row_adds_the_escalation_item_and_its_flags():
    row = {"doc_id": "v2_d01", "run_idx": 0, "needs_human_review": True,
           "review_reasons": ["auto-approval disabled: no category has a calibrated gate"],
           "outcomes": {k: {"llm_status": "compliant", "status": "compliant", "confidence": 0.6, "reasoning": "r",
                            "below_reference_threshold": True, "forced_reasons": [], "judgment": None}
                        for k in ("price_and_value", "consumer_support", "products_and_services", "consumer_understanding")},
           "escalation": {"decision": "escalate", "triggers": ["2.1(a)"], "discrepancies": [],
                          "policy_quotes": [{"evidence_number": 2, "verbatim_quote": "two or more missed payment flags"}],
                          "note_quotes": [], "reasoning": "r", "cited_evidence": [1, 2]},
           "checks": [{"name": "policy_quotes_in_policy_text", "passed": False, "action": "route_to_review"}],
           "evidence": [{"number": 2, "kind": "policy", "file_name": "policy.txt", "text": "(a) two or more missed payment flags"}],
           "stop": {"reason": None}, "tool_calls": []}
    c = agent_case(row, "agent v2")
    esc = c.items[-1]
    assert esc.item_id == "escalation" and esc.system_verdict == "escalate"
    assert "check failed: policy_quotes_in_policy_text" in esc.flags and esc.quotes[0]["passage_text"]
    assert c.case_reasons[0].startswith("auto-approval disabled")


def test_dry_run_rows_load_and_are_marked_rehearsal():
    path = config.PROJECT_ROOT / "logs" / "dryrun" / "eval_agent_v2.jsonl"
    if not path.exists():
        pytest.skip("no dry-run rows on this machine")
    cases = load_cases({"rehearsal": path})
    assert cases and all(c.rehearsal and len(c.items) == 5 for c in cases)


# --- the rules ---

def test_a_decision_needs_a_reviewer(store, case):
    with pytest.raises(ReviewError, match="reviewer"):
        store.decide(case, "price_and_value", "confirm", "  ")
    assert store.history() == []


def test_an_override_needs_a_reason_a_different_verdict_and_an_allowed_one(store, case):
    item = case.items[0]
    other = next(v for v in item.allowed_verdicts if v != item.system_verdict)
    with pytest.raises(ReviewError, match="reason"):
        store.decide(case, item.item_id, "override", "Ada", other, "")
    with pytest.raises(ReviewError, match="must change"):
        store.decide(case, item.item_id, "override", "Ada", item.system_verdict, "why")
    with pytest.raises(ReviewError, match="must be one of"):
        store.decide(case, item.item_id, "override", "Ada", "fine", "why")
    rec = store.decide(case, item.item_id, "override", "Ada", other, "fee is quantified in clause 4")
    assert rec["reviewer_verdict"] == other and rec["system_verdict"] == item.system_verdict


def test_a_case_cannot_be_resolved_until_every_item_is_decided(store, case):
    store.decide(case, "price_and_value", "confirm", "Ada")
    with pytest.raises(ReviewError, match="no decision yet on consumer_support"):
        store.resolve(case, "Ada")
    for item in case.items[1:]:
        store.decide(case, item.item_id, "confirm", "Ada")
    assert store.outstanding(case) == []
    store.resolve(case, "Ada", "all confirmed")
    assert store.is_resolved(case.case_id)


def test_after_resolution_nothing_can_change(store, case):
    for item in case.items:
        store.decide(case, item.item_id, "confirm", "Ada")
    store.resolve(case, "Ada")
    with pytest.raises(ReviewError, match="already resolved"):
        store.decide(case, "price_and_value", "confirm", "Ada")
    with pytest.raises(ReviewError, match="already resolved"):
        store.resolve(case, "Ada")


def test_history_is_append_only_and_the_latest_decision_counts(store, case):
    item = case.items[0]
    other = next(v for v in item.allowed_verdicts if v != item.system_verdict)
    store.decide(case, item.item_id, "override", "Ada", other, "first view")
    store.decide(case, item.item_id, "confirm", "Ben")
    assert [h["action"] for h in store.history(case.case_id)] == ["override", "confirm"]
    assert store.current(case.case_id)[item.item_id]["reviewer"] == "Ben"


def test_decisions_reach_the_audit_log(store, case):
    from src.monitoring import audit

    audit.start_run("unit test")
    store.decide(case, "price_and_value", "confirm", "Ada")
    audit.end_run()
    events = [json.loads(l) for p in config.LOG_DIR.rglob("*-*.jsonl") for l in p.read_text(encoding="utf-8").splitlines()]
    [e] = [e for e in events if e["stage"] == "review"]
    assert e["event"] == "confirm" and e["data"]["reviewer_given"] is True and "Ada" not in json.dumps(e)


# --- the screen, end to end ---

def _app(tmp_path, monkeypatch):
    src = tmp_path / "rows.jsonl"
    src.write_text(json.dumps(BASELINE_ROW) + "\n", encoding="utf-8")
    monkeypatch.setenv("REVIEW_SOURCES", json.dumps({"baseline": str(src)}))
    monkeypatch.setattr(config, "REVIEW_DIR", tmp_path / "reviews")
    at = AppTest.from_file(str(ROOT / "src" / "app.py"), default_timeout=120)
    at.run()
    return at


def test_screen_shows_the_queue_and_blocks_resolution_until_every_item_is_decided(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch)
    assert not at.exception
    assert "Queue: 1 case(s)" in at.subheader[0].value
    assert any("Decide every item before resolving" in i.value for i in at.info)
    assert not [b for b in at.button if b.key == "resolve"]  # no resolve button yet


def test_screen_records_decisions_then_resolves(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch)
    at.text_input(key="reviewer").set_value("Ada").run()
    for item in ("price_and_value", "consumer_support", "products_and_services", "consumer_understanding"):
        at.button(key=f"rec_{item}").click().run()
        assert not at.exception and not at.error
    at.button(key="resolve").click().run()
    assert any("Resolved baseline:loan_agreement_1:run0" in s.value for s in at.success)
    assert "Queue: 0 case(s)" in at.subheader[0].value  # gone from the Open list
    at.radio(key="show").set_value("Resolved").run()
    assert any(s.value == "Resolved." for s in at.success) and not [b for b in at.button if b.key.startswith("rec_")]
    decisions = DecisionStore(tmp_path / "reviews" / "decisions.jsonl").history()
    assert [d["action"] for d in decisions] == ["confirm"] * 4 + ["resolve"]


def test_screen_refuses_a_decision_without_a_reviewer(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch)
    at.button(key="rec_price_and_value").click().run()
    assert any("reviewer name is required" in e.value for e in at.error)
    assert not (tmp_path / "reviews" / "decisions.jsonl").exists()


def test_screen_override_requires_a_reason(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch)
    at.text_input(key="reviewer").set_value("Ada").run()
    at.radio(key="act_price_and_value").set_value("override").run()
    at.button(key="rec_price_and_value").click().run()
    assert any("needs a written reason" in e.value for e in at.error)
    at.text_area(key="why_price_and_value").set_value("The fee is stated in clause 4.1").run()
    at.button(key="rec_price_and_value").click().run()
    [d] = DecisionStore(tmp_path / "reviews" / "decisions.jsonl").history()
    assert d["action"] == "override" and d["reason"] == "The fee is stated in clause 4.1"

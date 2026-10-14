"""
Agentic tool loop (src/agent/tool_agent.py) and its validation layer
(src/agent/agent_validation.py), offline: a scripted fake model and a fake MCP
session. No API calls, no Chroma, no embedding model.

Covers: the model's tool choices are executed as asked (tools from the server's
own list, parallel results in one message); evidence numbering; limits stop the
run; cached repeats count; placeholder-wrapped and schema-invalid calls; and the
validation rules:
  - outcomes only from their own cited passages (quotes found in the named
    passage, which must be in the outcome's citations) or forced to
    insufficient_evidence; "..." splices checked part by part;
  - policy searched for every Northbridge agreement; policy quotes found in the
    policy passage they name;
  - unnecessary calls flagged: other lender, no lender named, not a credit
    agreement, no customer number, second account lookup, repeats;
  - escalation fits the document; 2.1(a)/(b) match the account; 2.1(c) needs a
    quoted, dated, in-window note; unclaimed life-event notes flagged.
"""

import json
from pathlib import Path
from contextlib import asynccontextmanager
from types import SimpleNamespace

from src.agent import agent_validation as av
from src.agent import tool_agent
from src.agent.tool_agent import SUBMIT_TOOL, ToolAgent

REG_TEXT = "When considering the price charged, firms must consider all the costs and charges a consumer may pay."
POLICY_TEXT = ("2.1 Staff must escalate a case where any of the following is present: (a) two or more missed "
               "payment flags in the trailing 12 months; (b) an open financial hardship marker of any kind.")


def _doc(lender="Northbridge Consumer Lending Ltd, 40 Wharf Street, Manchester", cid="CUST-12345"):
    return (f"FIXED SUM LOAN AGREEMENT\nAgreement reference: NCL-2026-11111\nCustomer number: {cid}\n"
            f"(1) {lender} (\"the Lender\"); and\n(2) A B (\"the Borrower\").\n"
            "APR: 19.9%\n3.1 You will repay the Loan in 48 monthly instalments.\nFees: none are charged.\n")


DOC = _doc()
LETTER = "Northbridge Consumer Lending Ltd\nCustomer number: CUST-12345\nCONFIRMATION OF CHANGE OF ADDRESS\n"


def _account(events=(), markers=(), notes=()):
    return {"customer_id": "CUST-12345", "account_holder_name": "A B", "customer_since": "2019-01-01",
            "account_status": "active", "products": [{"type": "personal_loan", "reference": "NCL-2026-11111"}],
            "payment_events": [{"type": "missed_payment", "due_date": d, "product_reference": "x"} for d in events],
            "markers": list(markers), "notes": [{"date": d, "text": t} for d, t in notes]}


class FakeSession:
    def __init__(self, account=None):
        self.calls = []
        self.account = account or _account(events=("2026-03-14",))

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=n, description=f"{n} tool", inputSchema={"type": "object"})
                                      for n in ("search_regulation", "get_account", "search_policy")])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_account":
            found = arguments["customer_id"] == self.account["customer_id"]
            payload = {"found": True, **self.account} if found else {"found": False, "customer_id": arguments["customer_id"]}
        elif name == "search_policy":
            payload = {"query": "q", "results": [
                {"file_name": "policy.txt", "page_label": None, "node_id": f"policy-{i}", "similarity": 0.70 - i / 100,
                 "text": f"{POLICY_TEXT} (passage {i})"} for i in range(2)]}
        else:  # search_regulation: distinct passages for each outcome's search
            o = arguments["outcome"]
            payload = {"outcome": o, "query": arguments["query"], "results": [
                {"file_name": "fg22-5.pdf", "page_label": "1", "node_id": f"{o}-{i}", "similarity": 0.68 - i / 100,
                 "text": f"{REG_TEXT} ({o} passage {i})"} for i in range(2)]}
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))], isError=False)


def _factory(session):
    @asynccontextmanager
    async def f():
        yield session
    return f


def _use(i, name, args):
    return SimpleNamespace(type="tool_use", id=f"tu{i}", name=name, input=args)


def _resp(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, model="claude-sonnet-5", id="msg",
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50,
                                                 cache_read_input_tokens=0, cache_creation_input_tokens=0))


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def _judgment(cited, quote_from=None, quote=REG_TEXT[:60], status="compliant"):
    reqs = [] if quote_from is None else [{"claim": "c", "sources": [{"excerpt_number": quote_from, "verbatim_quote": quote}]}]
    return {"status": status, "reasoning": "r", "cited_sources": list(cited), "document_facts": [],
            "regulatory_requirements": reqs, "absences": []}


# Evidence numbers after STANDARD_TURNS: E1 account, E2-E3 policy, then each outcome's own search:
OWN = {"price_and_value": 4, "consumer_support": 6, "products_and_services": 8, "consumer_understanding": 10}


def _assessment(decision="no_escalation", triggers=(), policy=((2, POLICY_TEXT[:50]),), account=1,
                note_quotes=(), scope=(True, "Northbridge Consumer Lending Ltd", "yes"), outcome=None, outcomes=None):
    per = {k: (outcome or _judgment([n], n)) for k, n in OWN.items()} | (outcomes or {})
    return {"document": {"is_credit_agreement": scope[0], "lender_named": scope[1], "lender_is_northbridge": scope[2]},
            **per,
            "escalation": {"decision": decision, "triggers": list(triggers),
                           "policy_quotes": [{"evidence_number": n, "verbatim_quote": q} for n, q in policy],
                           "note_quotes": list(note_quotes), "discrepancies": [], "reasoning": "r",
                           "cited_evidence": [account, *[n for n, _ in policy]]}}


REG_CALLS = [_use(10 + i, "search_regulation", {"outcome": o, "query": f"{o} requirements"}) for i, o in enumerate(OWN)]
STANDARD_TURNS = [
    _resp(_use(1, "get_account", {"customer_id": "CUST-12345"}), _use(2, "search_policy", {"query": "escalation"})),
    _resp(*REG_CALLS),
]  # evidence: E1 account, E2-E3 policy, E4-E5 PV, E6-E7 CS, E8-E9 PS, E10-E11 CU


def _run(responses, doc=DOC, session=None):
    session = session or FakeSession()
    client = FakeClient(responses)
    result = ToolAgent(client=client, session_factory=_factory(session), review_date="2026-10-01").run(doc)
    return result, session, client


def _checks(result):
    return {c["name"]: c for c in result["checks"]}


def _standard(assessment, session=None, doc=DOC):
    return _run([*STANDARD_TURNS, _resp(_use(9, SUBMIT_TOOL, assessment))], doc=doc, session=session)


# --- the loop ---

def test_tools_come_from_the_mcp_server_and_the_model_chooses_them():
    result, session, client = _standard(_assessment())
    assert [t["name"] for t in client.requests[0]["tools"]] == ["search_regulation", "get_account", "search_policy", SUBMIT_TOOL]
    assert client.requests[0]["tool_choice"] == {"type": "auto"}
    assert session.calls[:2] == [("get_account", {"customer_id": "CUST-12345"}), ("search_policy", {"query": "escalation"})]
    assert [a["outcome"] for n, a in session.calls[2:]] == list(OWN)
    second = client.requests[1]["messages"][-1]  # both parallel results in ONE user message
    assert second["role"] == "user" and [r["tool_use_id"] for r in second["content"]] == ["tu1", "tu2"]
    assert result["stop"]["reason"] is None and result["turns"] == 3


def test_a_clean_run_passes_every_check():
    result, _, _ = _standard(_assessment())
    failed = [c for c in result["checks"] if c["passed"] is False]
    assert not failed, failed
    pv = result["outcomes"]["price_and_value"]
    assert pv["status"] == "compliant" and pv["confidence"] == 0.68 and pv["forced_reasons"] == []
    assert result["unnecessary_calls"] == []
    # auto-approval is off: even a clean case goes to a human, and that is the only reason given
    assert result["needs_human_review"] is True
    assert result["review_reasons"] == ["auto-approval disabled: no category has a calibrated gate"]


def test_low_confidence_is_reported_but_never_replaces_the_verdict(monkeypatch):
    monkeypatch.setattr(tool_agent.config, "CONFIDENCE_THRESHOLD", 0.90)
    pv = _standard(_assessment())[0]["outcomes"]["price_and_value"]
    assert pv["confidence"] == 0.68 and pv["below_reference_threshold"] is True
    assert pv["status"] == "compliant" and pv["forced_reasons"] == []


def test_with_auto_approval_on_a_clean_case_would_skip_review(monkeypatch):
    monkeypatch.setattr(tool_agent.config, "AGENT_AUTO_APPROVAL_ENABLED", True)
    result = _standard(_assessment())[0]
    assert result["needs_human_review"] is False and result["review_reasons"] == []


def test_regulation_cap_is_4_and_a_5th_search_stops_the_run():
    calls = REG_CALLS + [_use(99, "search_regulation", {"outcome": "price_and_value", "query": "again"})]
    result, session, _ = _run([_resp(*calls)])
    assert result["stop"]["reason"] == "limit" and len(session.calls) == 4
    assert "per-tool (search_regulation)" in result["stop"]["detail"]


def test_per_tool_limit_stops_the_run_and_routes_to_review():
    result, session, _ = _run([_resp(*[_use(i, "get_account", {"customer_id": "CUST-12345"}) for i in range(4)])])
    assert result["stop"]["reason"] == "limit" and len(session.calls) == 1  # 3 allowed, 2 of them cached repeats
    assert all(o["status"] == "insufficient_evidence" for o in result["outcomes"].values())
    assert _checks(result)["within_limits"]["passed"] is False and result["needs_human_review"] is True


def test_repeated_identical_call_is_cached_counted_and_unnecessary():
    same = {"outcome": "price_and_value", "query": "fees"}
    result, session, _ = _run([
        _resp(_use(1, "search_regulation", same)), _resp(_use(2, "search_regulation", same)),
        _resp(_use(3, SUBMIT_TOOL, _assessment(decision="cannot_determine", policy=())))])
    assert len(session.calls) == 1 and [c["cached"] for c in result["tool_calls"]] == [False, True]
    assert [u["reason"] for u in result["unnecessary_calls"]] == ["repeat of an identical call"]


def test_placeholder_wrapped_arguments_are_not_executed():
    result, session, _ = _run([
        _resp(_use(1, "get_account", {"$PARAMETER_NAME": "customer_id"})),
        _resp(_use(2, SUBMIT_TOOL, _assessment(decision="cannot_determine", policy=())))])
    assert session.calls == [] and result["tool_calls"][0]["is_error"] is True


def test_invalid_submission_gets_an_error_and_a_second_chance():
    bad = _assessment()
    del bad["document"]
    result, _, client = _run([*STANDARD_TURNS, _resp(_use(8, SUBMIT_TOOL, bad)), _resp(_use(9, SUBMIT_TOOL, _assessment()))])
    err = client.requests[3]["messages"][-1]["content"][0]
    assert err["is_error"] is True and "schema" in err["content"]
    assert result["escalation"]["decision"] == "no_escalation"


def test_no_submission_hits_the_turn_limit():
    result, _, client = _run([_resp(SimpleNamespace(type="text", text="..."), stop="end_turn")] * 6)
    assert result["stop"]["reason"] == "turn_limit" and len(client.requests) == 6 and result["needs_human_review"]


# --- outcomes only from their own cited passages ---

def test_quote_not_in_the_named_passage_forces_insufficient_evidence():
    result, _, _ = _standard(_assessment(outcomes={"price_and_value": _judgment([4], 4, quote="firms must publish a tariff on request")}))
    pv = result["outcomes"]["price_and_value"]
    assert pv["llm_status"] == "compliant" and pv["status"] == "insufficient_evidence"
    assert "a regulatory quote is not in the passage it names" in pv["forced_reasons"]
    assert _checks(result)["quotes_in_named_passages:price_and_value"]["passed"] is False


def test_quote_from_a_passage_the_outcome_did_not_cite_is_off_copy():
    # quote is real text of E5, but the outcome cites only E4
    result, _, _ = _standard(_assessment(outcomes={"price_and_value": _judgment([4], 5)}))
    pv = result["outcomes"]["price_and_value"]
    assert pv["status"] == "insufficient_evidence"
    bad = _checks(result)["quotes_in_named_passages:price_and_value"]["metric"]
    assert bad == [{"claim": 0, "evidence": 5, "why": "named passage is not in this outcome's citations"}]


def test_passage_from_another_outcomes_search_is_off_copy():
    # E6 is consumer_support's passage; price_and_value cites and quotes it
    result, _, _ = _standard(_assessment(outcomes={"price_and_value": _judgment([6], 6)}))
    pv = result["outcomes"]["price_and_value"]
    assert pv["status"] == "insufficient_evidence"
    assert "cites a regulation passage returned by another outcome's search" in pv["forced_reasons"]
    assert _checks(result)["regulation_from_own_search:price_and_value"]["metric"] == [6]
    assert result["outcomes"]["consumer_support"]["status"] == "compliant"


def test_confidence_uses_the_outcomes_own_search_score():
    result, _, _ = _standard(_assessment())
    assert {k: v["confidence"] for k, v in result["outcomes"].items()} == {k: 0.68 for k in OWN}


def test_every_outcome_needs_its_own_regulation_search_and_a_second_is_unnecessary():
    calls = REG_CALLS[:3] + [_use(98, "search_regulation", {"outcome": "price_and_value", "query": "fees again"})]
    no_cu = _assessment(outcomes={"consumer_understanding": _judgment([], None, status="insufficient_evidence")})
    result, _, _ = _run([
        _resp(_use(1, "get_account", {"customer_id": "CUST-12345"}), _use(2, "search_policy", {"query": "q"})),
        _resp(*calls), _resp(_use(9, SUBMIT_TOOL, no_cu))])
    c = _checks(result)["regulation_searched_for_each_outcome"]
    assert c["passed"] is False and c["metric"] == ["consumer_understanding"]
    assert [u["reason"] for u in result["unnecessary_calls"]] == ["second regulation search for the same outcome"]


def test_decided_outcome_with_no_quote_or_only_policy_is_forced():
    no_quote = _standard(_assessment(outcomes={"price_and_value": _judgment([4], None)}))[0]["outcomes"]["price_and_value"]
    assert no_quote["status"] == "insufficient_evidence"
    assert "no regulatory quote found in a cited passage" in no_quote["forced_reasons"]
    policy_only = _standard(_assessment(outcomes={"price_and_value": _judgment([2], 2, quote=POLICY_TEXT[:50])}))[0]["outcomes"]["price_and_value"]
    assert "no cited regulation passage" in policy_only["forced_reasons"]


def test_spliced_quote_is_checked_part_by_part():
    spliced = "firms must consider all the costs ... charges a consumer may pay"
    ok = _standard(_assessment(outcomes={"price_and_value": _judgment([4], 4, quote=spliced)}))[0]["outcomes"]["price_and_value"]
    assert ok["status"] == "compliant"
    invented = "firms must consider all the costs ... and publish every fee online"
    bad = _standard(_assessment(outcomes={"price_and_value": _judgment([4], 4, quote=invented)}))[0]["outcomes"]["price_and_value"]
    assert bad["status"] == "insufficient_evidence"


# --- policy every time, and policy quotes in the policy ---

def test_northbridge_agreement_without_a_policy_search_is_flagged():
    result, _, _ = _run([
        _resp(_use(1, "get_account", {"customer_id": "CUST-12345"}), *REG_CALLS),
        _resp(_use(3, SUBMIT_TOOL, _assessment(decision="cannot_determine", policy=())))])
    assert _checks(result)["policy_searched"]["passed"] is False and result["needs_human_review"] is True


def test_policy_quote_not_in_the_policy_is_flagged():
    result, _, _ = _standard(_assessment(policy=((2, "customers over 70 must always be escalated"),)))
    c = _checks(result)["policy_quotes_in_policy_text"]
    assert c["passed"] is False and c["metric"][0]["why"] == "quote not found"
    assert result["needs_human_review"] is True


def test_decision_without_any_policy_quote_is_flagged():
    result, _, _ = _standard(_assessment(policy=()))
    assert _checks(result)["policy_quoted"]["passed"] is False


# --- unnecessary calls, from the document's own facts ---

def test_other_lenders_agreement_account_and_policy_calls_are_unnecessary():
    doc = _doc(lender="Harlow Street Finance Ltd, 9 Cannon Row, Leeds")
    result, _, _ = _standard(_assessment(decision="not_applicable", policy=(), scope=(True, "Harlow Street Finance Ltd", "no")), doc=doc)
    assert {(u["tool"], u["reason"]) for u in result["unnecessary_calls"]} == {
        ("get_account", "no account lookup is needed for this document"),
        ("search_policy", "Northbridge policy does not apply to this document")}
    assert _checks(result)["no_unnecessary_calls"]["passed"] is False
    assert _checks(result)["escalation_decision_fits_document"]["passed"] is True


def test_no_lender_named_account_lookup_is_unnecessary_and_escalation_cannot_be_determined():
    doc = _doc(lender="The Lender")
    result, _, _ = _standard(_assessment(decision="no_escalation", scope=(True, None, "not_stated")), doc=doc)
    assert ("get_account", "no account lookup is needed for this document") in \
        {(u["tool"], u["reason"]) for u in result["unnecessary_calls"]}
    c = _checks(result)["escalation_decision_fits_document"]
    assert c["passed"] is False and c["threshold"] == ["cannot_determine"]


def test_not_a_credit_agreement_every_call_is_unnecessary_and_outcomes_not_applicable():
    result, _, _ = _standard(_assessment(decision="not_applicable", policy=(), scope=(False, None, "yes")), doc=LETTER)
    assert len(result["unnecessary_calls"]) == 6  # account, policy, and all 4 regulation searches
    assert all(o["status"] == "not_applicable" for o in result["outcomes"].values())
    assert result["necessary_calls"] == {"search_regulation": False, "search_policy": False, "get_account": False}


def test_second_account_lookup_and_other_customer_are_unnecessary():
    result, _, _ = _run([
        _resp(_use(1, "get_account", {"customer_id": "CUST-99999"}), _use(2, "get_account", {"customer_id": "CUST-12345"})),
        _resp(_use(3, SUBMIT_TOOL, _assessment(decision="cannot_determine", policy=())))])
    reasons = [u["reason"] for u in result["unnecessary_calls"]]
    assert reasons == ["lookup of a customer number not in the document", "second account lookup"]


def test_scope_claim_that_contradicts_the_document_is_flagged():
    result, _, _ = _standard(_assessment(scope=(True, "Northbridge Consumer Lending Ltd", "no")))
    assert _checks(result)["document_scope_matches_facts"]["passed"] is False


# --- escalation against the account ---

def test_claimed_2_1a_with_one_missed_payment_is_flagged():
    result, _, _ = _standard(_assessment(decision="escalate", triggers=("2.1(a)",)))
    c = _checks(result)["trigger_a_matches_account"]
    assert c["passed"] is False and c["metric"]["missed_in_window"] == 1


def test_2_1c_needs_a_quoted_in_window_note():
    note = ("2026-08-19", "Customer called to say their spouse died in July and asked for all post to be sent in their name only.")
    session = lambda: FakeSession(_account(notes=(note,)))  # noqa: E731
    good = _standard(_assessment(decision="escalate", triggers=("2.1(c)",), note_quotes=(
        {"evidence_number": 1, "note_date": note[0], "verbatim_quote": "their spouse died in July"},)), session=session())[0]
    assert _checks(good)["trigger_c_note_quoted_and_in_window"]["passed"] is True
    wrong_date = _standard(_assessment(decision="escalate", triggers=("2.1(c)",), note_quotes=(
        {"evidence_number": 1, "note_date": "2026-08-20", "verbatim_quote": "their spouse died in July"},)), session=session())[0]
    assert _checks(wrong_date)["trigger_c_note_quoted_and_in_window"]["passed"] is False
    unclaimed = _standard(_assessment(decision="no_escalation"), session=session())[0]
    c = _checks(unclaimed)["no_unclaimed_life_event_note"]
    assert c["passed"] is False and c["metric"] == ["2026-08-19"] and c["action"] == "warn"


def test_house_move_note_is_not_a_life_event():
    note = ("2026-06-12", "Customer has moved to a new address in Leeds for work; correspondence address updated.")
    result = _standard(_assessment(decision="no_escalation"), session=FakeSession(_account(notes=(note,))))[0]
    assert _checks(result)["no_unclaimed_life_event_note"]["passed"] is True


def test_account_facts_window():
    rec = {"payment_events": [{"type": "missed_payment", "due_date": d} for d in ("2025-06-20", "2026-02-20")],
           "markers": [{"type": "financial_hardship", "opened": "2025-11-10", "closed": "2026-02-28"}], "notes": []}
    assert av.account_facts(rec, "2026-10-01") == {"missed_in_window": 1, "open_hardship_markers": 0,
                                                  "life_event_notes_in_window": []}


def test_document_facts_on_the_real_fixtures():
    from pathlib import Path

    labels = json.loads(Path("tests/fixtures/eval_set_v2.json").read_text(encoding="utf-8"))["documents"]
    for d in labels:
        facts = av.document_facts(Path(d["file"]).read_text(encoding="utf-8"))
        assert facts["credit_agreement"] == d["document_facts"]["credit_agreement"], d["doc_id"]
        if facts["credit_agreement"]:
            assert facts["lender"] == d["document_facts"]["lender"], d["doc_id"]
        assert facts["customer_number"] == d["customer_id"], d["doc_id"]
        expected = {t: d["expected_tool_calls"][t]["required"] for t in ("search_regulation", "search_policy", "get_account")}
        assert av.necessary_calls(facts) == expected, d["doc_id"]


# --- lender reading and the shared-server batch ---

def test_lender_reading():
    assert av.document_facts(_doc(lender="Bridgeport Lending Group, a company registered in England"))["lender"] == "other"
    assert av.document_facts(_doc(lender="Elmsworth Credit Union, a society registered"))["lender"] == "other"
    assert av.document_facts(_doc(lender="The Lender"))["lender"] == "not_stated"
    assert av.document_facts(_doc(lender="[Lender name]"))["lender"] == "not_stated"
    assert av.document_facts(_doc())["lender"] == "northbridge"


def test_v1_documents_are_all_other_lenders():
    from tests.fixtures.eval_set import EVAL_DOCUMENTS

    for d in EVAL_DOCUMENTS:
        f = av.document_facts(Path("data/synthetic_docs", d["file"]).read_text(encoding="utf-8"))
        assert (f["credit_agreement"], f["lender"], f["customer_number"]) == (True, "other", None), d["id"]


def test_run_many_shares_one_server_but_each_run_is_separate():
    opened = []
    session = FakeSession()

    @asynccontextmanager
    async def factory():
        opened.append(1)
        yield session

    script = [*STANDARD_TURNS, _resp(_use(9, SUBMIT_TOOL, _assessment()))]
    bad = _assessment()
    del bad["escalation"]
    client = FakeClient(script + [_resp(SimpleNamespace(type="text", text="..."), stop="refusal")] + script)
    results = {}
    ToolAgent(client=client, session_factory=factory, review_date="2026-10-01").run_many(
        [("a", DOC), ("b", DOC), ("c", DOC)], after=lambda k, r, e: results.__setitem__(k, (r, e)))
    assert opened == [1]  # one server for the whole batch
    assert results["a"][0]["stop"]["reason"] is None and results["c"][0]["stop"]["reason"] is None
    assert results["b"][0]["stop"]["reason"] == "refusal"  # its own run; did not end the batch
    # each run numbers its own evidence from E1 and counts its own calls
    assert [e["number"] for e in results["c"][0]["evidence"]][:3] == [1, 2, 3]
    assert len(results["c"][0]["tool_calls"]) == 6


# --- "recent" in 2.1(c) = the 12 months before the review date (decision 2026-10-14) ---

def test_recent_window_boundaries():
    assert av.window_start("2026-10-01") == "2025-10-01"
    assert av.window_start("2026-03-31", months=12) == "2025-03-31"
    assert av.window_start("2026-10-01", months=6) == "2026-04-01"


def _claim_c(note_date, text="Customer called to say their spouse died and asked for post in their name only."):
    note = (note_date, text)
    return _standard(_assessment(decision="escalate", triggers=("2.1(c)",), note_quotes=(
        {"evidence_number": 1, "note_date": note_date, "verbatim_quote": "their spouse died"},)),
        session=FakeSession(_account(notes=(note,))))[0]


def test_2_1c_note_on_the_first_day_of_the_window_is_recent():
    assert _checks(_claim_c("2025-10-01"))["trigger_c_note_quoted_and_in_window"]["passed"] is True


def test_2_1c_note_one_day_older_than_12_months_is_not_recent():
    assert _checks(_claim_c("2025-09-30"))["trigger_c_note_quoted_and_in_window"]["passed"] is False


def test_old_life_event_note_is_not_flagged_as_unclaimed():
    old = ("2025-06-02", "Customer called to say their spouse died; post now in their name only.")
    result = _standard(_assessment(decision="no_escalation"), session=FakeSession(_account(notes=(old,))))[0]
    assert _checks(result)["no_unclaimed_life_event_note"]["passed"] is True


def test_the_agent_is_told_what_recent_means():
    _, _, client = _standard(_assessment())
    assert '"recent" means within the 12 months before the review date' in client.requests[0]["system"][0]["text"]


def test_changing_recent_does_not_move_the_2_1a_window(monkeypatch):
    monkeypatch.setattr(av.config, "AGENT_RECENT_WINDOW_MONTHS", 3)
    rec = {"payment_events": [{"type": "missed_payment", "due_date": d} for d in ("2025-11-01", "2026-02-01")],
           "markers": [], "notes": [{"date": "2026-02-01", "text": "Customer's partner died."}]}
    f = av.account_facts(rec, "2026-10-01")
    assert f["missed_in_window"] == 2 and f["life_event_notes_in_window"] == []

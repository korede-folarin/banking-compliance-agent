"""
A sample review, replayed in plain language: what code decided before any AI, what the AI looked up,
the account, the verdicts with their quotes, the checks, the escalation decision and the answer key.
Built from a recorded live run (docs/eval_agent_v2.jsonl). Used by the static site (src/site/build.py);
the Streamlit page shares its wording. No ML imports and no model calls.
"""

import json

from src import config
from src.agent.document_rules import account_facts, account_rule, document_facts, escalation_gate
from src.monitoring.overview import PLAIN, PLAIN_ESCALATION
from src.review.cases import OUTCOME_NAMES, OUTCOMES

TOOL_PLAIN = {"search_regulation": "Searched the FCA rules", "get_account": "Looked up the customer's account",
              "search_policy": "Searched Northbridge's escalation policy"}
TRIGGERS = {"2.1(a)": "two or more missed payments in the last 12 months",
            "2.1(b)": "an open financial-hardship marker",
            "2.1(c)": "a recent note about a life event (bereavement, separation, serious illness)"}
CHECKS = {
    "account_looked_up_with_document_customer_number": "Looked up the account with the agreement's customer number",
    "policy_searched": "Checked Northbridge's escalation policy",
    "regulation_searched_for_each_outcome": "Searched the regulation once for each outcome",
    "no_unnecessary_calls": "Made no unnecessary lookups",
    "within_limits": "Stayed within its limits on calls and turns",
    "regulation_from_own_search": "Cited only regulation that its own search returned",
    "quotes_in_named_passages": "Every regulation quote is really in the passage it names",
    "document_quotes_in_document": "Every quote from the agreement is really in the agreement",
    "document_scope_matches_facts": "Read the document type and lender correctly",
    "escalation_decision_fits_document": "Its escalation decision fits the document",
    "policy_quoted": "Quoted the escalation policy",
    "policy_quotes_in_policy_text": "Its policy quotes are really in the policy",
    "escalation_cites_account": "Its escalation decision cites the account record",
    "trigger_a_matches_account": "Missed-payment trigger matches the account",
    "trigger_b_matches_account": "Hardship trigger matches the account",
    "trigger_c_note_quoted_and_in_window": "Life-event note quoted, and recent",
    "no_unclaimed_life_event_note": "No recent life-event note left unmentioned",
}


def sample_title(doc_id: str, row: dict, label: dict) -> str:
    f = row["document_facts"]
    kind = ("Not a loan agreement" if not f["credit_agreement"] else
            {"northbridge": "Northbridge loan", "other": "Another lender's loan",
             "not_stated": "Loan with no lender named"}[f["lender"]])
    planted = [OUTCOME_NAMES[k].lower() for k, v in label["ground_truth"].items() if v == "non_compliant"]
    return f"{doc_id} · {kind} · " + (f"planted problem: {', '.join(planted)}" if planted else "no planted problem")


def replay(row: dict, label: dict, text: str) -> dict:
    """Everything the replay shows, as plain data."""
    evidence = {e["number"]: e for e in row["evidence"]}
    facts = document_facts(text) if text else row["document_facts"]
    gate = escalation_gate(facts)

    if not gate["call_model"]:
        gate_text = f"Code stops here: {gate['reason']}. The AI is not called at all."
    elif gate["decision"]:
        gate_text = (f"Code decides the escalation question already: {PLAIN_ESCALATION[gate['decision']].lower()}, "
                     f"because {gate['reason']}. The AI is only offered: "
                     + ", ".join(TOOL_PLAIN[t].lower() for t in sorted(gate["tools"])) + ".")
    else:
        gate_text = "A Northbridge loan with a customer number: the AI gets all three tools and decides for itself what to look up."

    unnecessary = {u["n"]: u["reason"] for u in row.get("unnecessary_calls", [])}
    lookups = []
    for c in row["tool_calls"]:
        a = c["arguments"]
        if c["tool"] == "search_regulation":
            detail = f"for {OUTCOME_NAMES.get(a.get('outcome'), a.get('outcome'))}: “{a.get('query', '')}”"
        elif c["tool"] == "get_account":
            detail = a.get("customer_id", "")
        else:
            detail = f"“{a.get('query', '')}”"
        lookups.append({"n": c["n"], "what": TOOL_PLAIN.get(c["tool"], c["tool"]), "detail": detail,
                        "unnecessary": unnecessary.get(c["n"])})

    account = None
    acct = [e for e in row["evidence"] if e["kind"] == "account"]
    if acct:
        e = acct[0]
        if not e.get("found"):
            account = {"found": False, "customer_id": e.get("customer_id")}
        else:
            record = json.loads(e["text"])
            f = account_facts(record, config.AGENT_REVIEW_DATE)
            account = {"found": True, "holder": record.get("account_holder_name"), "borrower": facts.get("borrower"),
                       "missed_payments": f["missed_in_window"], "hardship_markers": f["open_hardship_markers"],
                       "life_event_notes": len(f["life_event_notes_in_window"])}

    verdicts = []
    for k in OUTCOMES:
        o = row["outcomes"][k]
        j = o.get("judgment") or {}
        claims = []
        for req in (j.get("regulatory_requirements") or [])[:2]:
            for s in req["sources"][:1]:
                p = evidence.get(s["excerpt_number"], {})
                claims.append({"claim": req["claim"], "quote": s["verbatim_quote"],
                               "source": f"{p.get('file_name', 'the regulation')}"
                                         + (f", p. {p['page_label']}" if p.get("page_label") else ""),
                               "passage": (p.get("text") or "")[:1200]})
        verdicts.append({"outcome": OUTCOME_NAMES[k], "status": o["status"], "plain": PLAIN.get(o["status"], o["status"]),
                         "ai_said": PLAIN.get(o.get("llm_status"), o.get("llm_status")),
                         "overruled": o.get("forced_reasons") or [], "reasoning": j.get("reasoning"), "claims": claims})

    checks = row["checks"]
    failed = []
    for c in checks:
        if c["passed"] is False:
            name, _, where = c["name"].partition(":")
            failed.append(CHECKS.get(name, name) + (f" ({OUTCOME_NAMES.get(where, where)})" if where else ""))

    esc = row.get("escalation") or {}
    rule = gate["reason"] if gate["decision"] else (
        account_rule(facts, row["evidence"]) if facts["lender"] == "northbridge" and facts["customer_number"] else None)
    final = gate["decision"] or ("cannot_determine" if rule else esc.get("decision"))

    key = []
    for k in OUTCOMES:
        truth, said = label["ground_truth"].get(k), row["outcomes"][k].get("llm_status")
        if truth == "not_applicable":
            want, result = "not applicable", "right" if said in (None, "not_applicable") else "wrong"
        else:
            want = "a possible breach" if truth == "non_compliant" else "compliant"
            if said == "insufficient_evidence":
                result = "unsure"
            else:
                result = "right" if (said == "potentially_non_compliant") == (truth == "non_compliant") and said else "wrong"
        key.append({"outcome": OUTCOME_NAMES[k], "should_be": want, "ai_said": PLAIN.get(said, said), "result": result})
    if label.get("escalation"):
        key.append({"outcome": "Vulnerable customer", "should_be": PLAIN_ESCALATION[label["escalation"]],
                    "ai_said": PLAIN_ESCALATION.get(final, final), "result": "right" if final == label["escalation"] else "wrong"})

    return {
        "facts": {"loan_agreement": facts["credit_agreement"],
                  "lender": {"northbridge": "Northbridge", "other": "Another lender", "not_stated": "Not named"}[facts["lender"]],
                  "lender_named": facts.get("lender_clause"), "customer_number": facts["customer_number"]},
        "gate": gate_text,
        "lookups": lookups,
        "recorded_before_rules": bool(unnecessary),
        "account": account,
        "verdicts": verdicts,
        "checks": {"passed": sum(c["passed"] is not False for c in checks), "total": len(checks), "failed": failed},
        "escalation": {"decision": PLAIN_ESCALATION.get(final, final), "rule": rule,
                       "ai_said": PLAIN_ESCALATION.get(esc.get("decision"), esc.get("decision"))
                       if esc.get("decision") not in (None, final) else None,
                       "triggers": [f"Policy {t}: {TRIGGERS.get(t, t)}" for t in esc.get("triggers") or []],
                       "reasoning": None if rule else esc.get("reasoning")},
        "answer_key": key,
    }

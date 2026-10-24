"""
Deterministic validation of an agentic tool-loop run (plain Python, no model call).

Runs after the model submits (src/agent/tool_agent.py). It decides from facts it
reads itself, never from the model's say-so:

1. Document facts, read from the document text: is it a credit agreement, who is
   the lender (Northbridge / another lender / not stated), is there a customer
   number. These decide which tool calls were NECESSARY:
     search_regulation  needed for any credit agreement: one search per Consumer Duty
                        outcome, each naming that outcome
     search_policy      needed for a Northbridge credit agreement (every time)
     get_account        needed for a Northbridge credit agreement with a customer
                        number, with exactly that number, once
   A call outside these is UNNECESSARY (flagged, counted); a missing necessary call
   routes the case to review.
2. Outcomes come only from the passages they cite ("no off-copy"): every regulatory
   quote must be found in the exact passage it names, and that passage must be in
   the outcome's own citation list, and a cited regulation passage must have been
   returned by that outcome's OWN search. A decided outcome needs at least one such quote
   and at least one cited regulation passage. Otherwise the outcome is FORCED to
   insufficient_evidence. Quotes spliced with "..." are checked part by part, in order.
   Confidence = minimum similarity of the cited passages; below the threshold the
   outcome becomes insufficient_evidence (as P4-02).
3. Escalation: the decision must fit the document facts (not_applicable for another
   lender's agreement or a non-agreement); a decision must quote the procedure, and
   each policy quote must be found in the policy passage it names; claimed triggers
   2.1(a)/(b) must match the account's dated facts; 2.1(c) needs a quoted, dated note
   that is in the record and inside the window; a note in the window with
   bereavement, separation or health wording that 2.1(c) does not claim is flagged.

"Recent" in 2.1(c) means within config.AGENT_RECENT_WINDOW_MONTHS (12) months before the
review date: the procedure does not define it, so this was set as a project decision
(2026-10-14) and the agent is told it as a fact of the setting.
"""

import re

from src import config
from src.agent.agent_schemas import OUTCOME_KEYS, AgentAssessment
from src.monitoring import audit

from src.agent.document_rules import (  # noqa: F401  (re-exported: tests and tool_agent use them here)
    CUSTOMER_NUMBER, LENDER_CLAUSE, BORROWER_CLAUSE, NO_LENDER_NAME, LIFE_EVENT_WORDS, ALL_TOOLS, document_facts, escalation_gate, _same_name, account_gate, account_rule, window_start, account_facts,
)


def necessary_calls(facts: dict) -> dict:
    northbridge_credit = facts["credit_agreement"] and facts["lender"] == "northbridge"
    return {"search_regulation": facts["credit_agreement"], "search_policy": northbridge_credit,
            "get_account": northbridge_credit and facts["customer_number"] is not None}


def unnecessary_calls(calls: list[dict], facts: dict) -> list[dict]:
    need = necessary_calls(facts)
    out, seen_account, seen_outcomes = [], False, set()
    for c in calls:
        reason = None
        if c.get("cached"):
            reason = "repeat of an identical call"
        elif not need.get(c["tool"], False):
            reason = {"get_account": "no account lookup is needed for this document",
                      "search_policy": "Northbridge policy does not apply to this document",
                      "search_regulation": "the document is not a credit agreement"}.get(c["tool"], "unknown tool")
        elif c["tool"] == "search_regulation":
            outcome = c["arguments"].get("outcome")
            if outcome in seen_outcomes:
                reason = "second regulation search for the same outcome"
            seen_outcomes.add(outcome)
        elif c["tool"] == "get_account":
            if seen_account:
                reason = "second account lookup"
            elif c["arguments"].get("customer_id") != facts["customer_number"]:
                reason = "lookup of a customer number not in the document"
        if c["tool"] == "get_account":
            seen_account = True
        if reason:
            out.append({"n": c["n"], "tool": c["tool"], "arguments": c["arguments"], "reason": reason})
    return out


# --- quote matching ---

def quote_in(quote: str, text: str) -> bool:
    """
    Found by the claim checker's matcher, the same rule the baseline is scored with: exactly,
    normalised, fuzzily, or as a "..."-splice whose parts all appear in the quote's order (rule B).
    """
    from src.evaluation.claim_verification import match_quote

    return match_quote(quote, text)["match_type"] != "none"


# --- account facts ---

# --- the validation ---

def validate_run(document_text: str, assessment: AgentAssessment | None, registry, calls: list[dict], turns: int,
                 stop: dict, review_date: str, threshold: float | None = None, gate: dict | None = None) -> dict:
    """
    `threshold` is a REFERENCE value only (default CONFIDENCE_THRESHOLD, 0.65, which was never calibrated):
    each outcome reports whether its confidence is below it, but the agent's verdict is not replaced on
    that basis (decision 2026-10-14). Verdicts are replaced only by the quote and citation rules.
    """
    threshold = config.CONFIDENCE_THRESHOLD if threshold is None else threshold
    checks = []

    def check(name, passed, metric=None, threshold_=None, action="route_to_review", **ctx):
        checks.append({"name": name, "passed": passed, "metric": metric, "threshold": threshold_, "action": action, **ctx})
        audit.check("agent", name, passed, metric=metric, threshold=threshold_, action=action, **ctx)

    facts = document_facts(document_text)
    need = necessary_calls(facts)
    called = {t: [c for c in calls if c["tool"] == t] for t in ("search_regulation", "search_policy", "get_account")}

    # 1. necessary and unnecessary calls
    if need["get_account"]:
        check("account_looked_up_with_document_customer_number",
              any(c["arguments"].get("customer_id") == facts["customer_number"] for c in called["get_account"]),
              [c["arguments"].get("customer_id") for c in called["get_account"]], facts["customer_number"])
    if need["search_policy"]:
        check("policy_searched", bool(called["search_policy"]), len(called["search_policy"]), ">= 1")
    if need["search_regulation"]:
        searched = {c["arguments"].get("outcome") for c in called["search_regulation"] if not c["is_error"]}
        missing = [o for o in OUTCOME_KEYS if o not in searched]
        check("regulation_searched_for_each_outcome", not missing, missing, "one search for each of the 4 outcomes")
    unnecessary = unnecessary_calls(calls, facts)
    check("no_unnecessary_calls", not unnecessary, [f"{u['tool']}: {u['reason']}" for u in unnecessary], "0", "warn")
    check("within_limits", stop.get("reason") not in ("limit", "turn_limit"), stop.get("reason"), "no limit hit")

    # 2. outcomes from their own cited passages only
    chunk_kinds = {n: e["kind"] for n, e in registry.items.items() if e["kind"] in ("regulation", "policy")}
    outcomes = {}
    for key in OUTCOME_KEYS:
        if not facts["credit_agreement"]:
            j = getattr(assessment, key) if assessment else None
            outcomes[key] = {"llm_status": j.status if j else None, "status": "not_applicable", "confidence": None,
                             "cited_sources": [], "cited_sources_raw": list(j.cited_sources) if j else [],
                             "reasoning": j.reasoning if j else None, "judgment": j.model_dump() if j else None,
                             "forced_reasons": []}
            continue
        if assessment is None:
            outcomes[key] = {"llm_status": None, "status": "insufficient_evidence", "confidence": 0.0, "cited_sources": [],
                             "cited_sources_raw": [], "reasoning": None, "judgment": None,
                             "forced_reasons": ["no assessment submitted"]}
            continue
        j = getattr(assessment, key)
        cited = [n for n in j.cited_sources if n in chunk_kinds]
        reasons, bad_quotes, good_quotes = [], [], 0
        foreign = [n for n in cited if chunk_kinds[n] == "regulation"
                   and key not in registry.items[n].get("similarity_by_outcome", {})]
        if foreign:
            reasons.append("cites a regulation passage returned by another outcome's search")
        check(f"regulation_from_own_search:{key}", not foreign, foreign,
              "every cited regulation passage came from this outcome's search", outcome=key)
        for i, req in enumerate(j.regulatory_requirements):
            for src in req.sources:
                n = src.excerpt_number
                if n not in j.cited_sources:
                    bad_quotes.append({"claim": i, "evidence": n, "why": "named passage is not in this outcome's citations"})
                elif n not in chunk_kinds:
                    bad_quotes.append({"claim": i, "evidence": n, "why": "named evidence is not a returned passage"})
                elif chunk_kinds[n] == "regulation" and key not in registry.items[n].get("similarity_by_outcome", {}):
                    bad_quotes.append({"claim": i, "evidence": n, "why": "named passage came from another outcome's search"})
                elif not quote_in(src.verbatim_quote, registry.items[n]["text"]):
                    bad_quotes.append({"claim": i, "evidence": n, "why": "quote not found in the named passage"})
                else:
                    good_quotes += 1
        decided = j.status in ("compliant", "potentially_non_compliant")
        if bad_quotes:
            reasons.append("a regulatory quote is not in the passage it names")
        own_regulation = [n for n in cited if chunk_kinds[n] == "regulation" and n not in foreign]
        if decided and not own_regulation:
            reasons.append("no cited regulation passage")
        if decided and good_quotes == 0:
            reasons.append("no regulatory quote found in a cited passage")
        check(f"quotes_in_named_passages:{key}", not bad_quotes, bad_quotes, "every quote in the passage it names",
              outcome=key)
        doc_misses = [i for i, f in enumerate(j.document_facts) if not quote_in(f.verbatim_quote, document_text)]
        check(f"document_quotes_in_document:{key}", not doc_misses, doc_misses, "every document quote found", "warn",
              outcome=key)
        confidence = min((_similarity(registry.items[n], key) for n in cited), default=0.0)
        # Only the quote/citation rules (groundedness) replace a verdict. Confidence is reported, not applied.
        status = "insufficient_evidence" if reasons else j.status
        outcomes[key] = {"llm_status": j.status, "status": status, "confidence": confidence,
                         "below_reference_threshold": confidence < threshold, "reference_threshold": threshold,
                         "cited_sources": [_source(registry.items[n], key) for n in cited],
                         "cited_sources_raw": list(j.cited_sources), "reasoning": j.reasoning,
                         "judgment": j.model_dump(), "forced_reasons": reasons}

    # 3. escalation
    escalation = None
    if assessment is not None:
        e = assessment.escalation
        escalation = e.model_dump()
        d = assessment.document
        check("document_scope_matches_facts",
              d.is_credit_agreement == facts["credit_agreement"] and
              (not facts["credit_agreement"] or d.lender_is_northbridge ==
               {"northbridge": "yes", "other": "no", "not_stated": "not_stated"}[facts["lender"]]),
              {"claimed": d.model_dump(), "facts": {k: facts[k] for k in ("credit_agreement", "lender")}},
              "model's scope and lender reading match the document")
        if not facts["credit_agreement"] or facts["lender"] == "other":
            expected = {"not_applicable"}
        elif facts["lender"] == "not_stated" or not facts["customer_number"]:
            expected = {"cannot_determine"}
        else:
            expected = {"escalate", "no_escalation", "cannot_determine"}
        check("escalation_decision_fits_document", e.decision in expected, e.decision, sorted(expected))
        if e.decision in ("escalate", "no_escalation"):
            bad = [{"evidence": q.evidence_number,
                    "why": "not a policy passage" if chunk_kinds.get(q.evidence_number) != "policy" else "quote not found"}
                   for q in e.policy_quotes
                   if chunk_kinds.get(q.evidence_number) != "policy"
                   or not quote_in(q.verbatim_quote, registry.items[q.evidence_number]["text"])]
            check("policy_quoted", bool(e.policy_quotes), len(e.policy_quotes), ">= 1 quote from the procedure")
            check("policy_quotes_in_policy_text", not bad, bad, "every policy quote in the passage it names")
            records = [registry.items[n] for n in e.cited_evidence
                       if registry.items.get(n, {}).get("kind") == "account" and registry.items[n].get("found")]
            check("escalation_cites_account", bool(records), len(records), ">= 1 account record cited")
            if records:
                facts_acct = account_facts(records[0]["record"], review_date)
                claimed = set(e.triggers)
                check("trigger_a_matches_account", ("2.1(a)" in claimed) == (facts_acct["missed_in_window"] >= 2),
                      {"claimed": "2.1(a)" in claimed, "missed_in_window": facts_acct["missed_in_window"]},
                      "2.1(a) iff >= 2 missed payments in the window")
                check("trigger_b_matches_account", ("2.1(b)" in claimed) == (facts_acct["open_hardship_markers"] >= 1),
                      {"claimed": "2.1(b)" in claimed, "open_markers": facts_acct["open_hardship_markers"]},
                      "2.1(b) iff an open hardship marker")
                if "2.1(c)" in claimed:
                    notes = records[0]["record"].get("notes", [])
                    start = window_start(review_date)
                    ok = bool(e.note_quotes) and all(
                        any(n.get("date") == q.note_date and quote_in(q.verbatim_quote, n.get("text", "")) for n in notes)
                        and start <= q.note_date < review_date for q in e.note_quotes)
                    check("trigger_c_note_quoted_and_in_window", ok, [q.model_dump() for q in e.note_quotes],
                          "a quoted note, in the record, dated inside the window")
                else:
                    check("no_unclaimed_life_event_note", not facts_acct["life_event_notes_in_window"],
                          facts_acct["life_event_notes_in_window"],
                          "no in-window bereavement/separation/health note left unclaimed", "warn")

    # 4. escalation rules decided by code (user decision 2026-10-24). The model's own decision is kept
    # as llm_decision; where the rule applies, it sets the decision. cannot_determine always goes to review.
    gate = gate or escalation_gate(facts)
    rule = gate["reason"]
    forced = gate["decision"]
    if forced is None and facts["credit_agreement"] and facts["lender"] == "northbridge" and facts["customer_number"]:
        rule = account_gate(facts, registry)
        forced = "cannot_determine" if rule else None
    if forced:
        escalation = {**(escalation or {"decision": None, "triggers": [], "policy_quotes": [], "note_quotes": [],
                                        "discrepancies": [], "reasoning": None, "cited_evidence": []})}
        escalation["llm_decision"] = escalation.get("decision")
        escalation["decision"] = forced
        escalation["rule"] = rule
        if forced != "escalate":
            escalation["triggers"] = []
    elif escalation is not None:
        escalation["llm_decision"] = escalation["decision"]
        escalation["rule"] = None

    # Why a reviewer should look, case by case. These are reported even while auto-approval is off,
    # so the report shows which cases would still need a human if a calibrated gate existed.
    review_reasons = []
    if assessment is None and gate.get("call_model", True):
        review_reasons.append("no assessment submitted")
    review_reasons += [f"{k}: {o['status']}" for k, o in outcomes.items()
                       if o["status"] in ("potentially_non_compliant", "insufficient_evidence")]
    if (escalation or {}).get("decision") not in (None, "no_escalation", "not_applicable"):
        review_reasons.append(f"escalation: {escalation['decision']}"
                              + (f" (rule: {escalation['rule']})" if escalation.get("rule") else ""))
    if escalation and escalation.get("rule") and escalation["llm_decision"] not in (None, escalation["decision"]):
        review_reasons.append(f"escalation rule overrode the model's {escalation['llm_decision']}")
    if (escalation or {}).get("discrepancies"):
        review_reasons.append("discrepancies reported")
    review_reasons += [f"check failed: {c['name']}" for c in checks
                       if c["passed"] is False and c["action"] == "route_to_review"]
    if not config.AGENT_AUTO_APPROVAL_ENABLED:
        review_reasons.insert(0, "auto-approval disabled: no category has a calibrated gate")
    needs_review = bool(review_reasons)
    audit.event("agent", "end", data={"needs_human_review": needs_review, "stop": stop, "turns": turns,
                                      "tool_calls": len(calls), "unnecessary_calls": len(unnecessary),
                                      "statuses": {k: v["status"] for k, v in outcomes.items()},
                                      "confidence": {k: v.get("confidence") for k, v in outcomes.items()},
                                      "review_reasons": review_reasons,
                                      "escalation": (escalation or {}).get("decision")})
    return {
        "document_facts": facts, "necessary_calls": need, "unnecessary_calls": unnecessary,
        "outcomes": outcomes, "escalation": escalation, "needs_human_review": needs_review,
        "review_reasons": review_reasons, "auto_approval_enabled": config.AGENT_AUTO_APPROVAL_ENABLED,
        "tool_calls": calls, "turns": turns, "stop": stop, "checks": checks,
        "evidence": [{k: v for k, v in e.items() if k != "record"} for e in registry.items.values()],
    }


def _similarity(e: dict, outcome: str) -> float:
    """A regulation passage's score in this outcome's own search (0.0 if that search did not return it)."""
    if e["kind"] == "regulation":
        return e.get("similarity_by_outcome", {}).get(outcome, 0.0)
    return e["similarity"]


def _source(e: dict, outcome: str) -> dict:
    return {"index": e["number"], "file_name": e["file_name"], "similarity_score": _similarity(e, outcome),
            "text_excerpt": e["text"], "node_id": e["node_id"]}

"""
The document rules: what code decides from the document text and the account record alone, with no
model call (user decisions 2026-10-14 and 2026-10-24). Pure Python with no ML imports, so the hosted
demo can replay them. src/agent/agent_validation.py uses them for every run.
"""

import re

from src import config

CUSTOMER_NUMBER = re.compile(r"Customer number:\s*(CUST-\d{5})")
LENDER_CLAUSE = re.compile(r"\(1\)\s*(.+?)\s*\(\"the Lender\"\)", re.S)
BORROWER_CLAUSE = re.compile(r"\(2\)\s*(.+?),\s+of\b", re.S)
# A party clause that names no lender: "The Lender", or a blank placeholder like "[Lender name]".
NO_LENDER_NAME = re.compile(r"^(the lender|\[[^\]]*\]|_+)?$", re.I)
LIFE_EVENT_WORDS = re.compile(
    r"\b(died|death|passed away|bereave\w*|funeral|widow\w*|separat\w*|divorc\w*|split up|hospital\w*|"
    r"diagnos\w*|surgery|cancer|stroke|terminal|serious(ly)? ill\w*)\b", re.I)


# --- document facts ---

def document_facts(text: str) -> dict:
    credit = bool(re.search(r"\bAPR\b", text)) and bool(re.search(r"repay", text, re.I))
    clause = LENDER_CLAUSE.search(text)
    if not clause:
        lender = "not_stated"
    elif "Northbridge Consumer Lending" in clause.group(1):
        lender = "northbridge"
    elif NO_LENDER_NAME.match(clause.group(1).strip()):
        lender = "not_stated"
    else:  # any named lender: "... Ltd", "... Lending Group", "... Credit Union", ...
        lender = "other"
    cid = (m.group(1) if (m := CUSTOMER_NUMBER.search(text)) else None)
    borrower = (" ".join(m.group(1).split()) if (m := BORROWER_CLAUSE.search(text)) else None)
    return {"credit_agreement": credit, "lender": lender, "customer_number": cid,
            "lender_clause": clause.group(1).strip() if clause else None, "borrower": borrower}


# --- the gate: decided by code before any model call (user decision 2026-10-24) ---

ALL_TOOLS = frozenset({"search_regulation", "search_policy", "get_account"})


def escalation_gate(facts: dict) -> dict:
    """
    What code can decide from the document alone, before the model runs:
    - not a credit agreement: nothing applies; the model is not called at all;
    - another lender: escalation is not_applicable; only the regulation search is offered;
    - no lender named, or a Northbridge agreement with no customer number: escalation is
      cannot_determine, which always goes to a reviewer; the account lookup is not offered.
    decision None = the model decides escalation (Northbridge agreement with a customer number).
    """
    if not facts["credit_agreement"]:
        return {"decision": "not_applicable", "reason": "not a credit agreement: no outcome or procedure applies",
                "tools": frozenset(), "call_model": False}
    if facts["lender"] == "other":
        return {"decision": "not_applicable", "call_model": True, "tools": frozenset({"search_regulation"}),
                "reason": "another lender's agreement: Northbridge's escalation procedure does not apply"}
    if facts["lender"] == "not_stated":
        return {"decision": "cannot_determine", "call_model": True, "tools": frozenset({"search_regulation"}),
                "reason": "the agreement names no lender, so it cannot be established that the customer is Northbridge's"}
    if not facts["customer_number"]:
        return {"decision": "cannot_determine", "call_model": True,
                "tools": frozenset({"search_regulation", "search_policy"}),
                "reason": "the agreement has no customer number, so there is no account to check"}
    return {"decision": None, "reason": None, "tools": ALL_TOOLS, "call_model": True}


def _same_name(a: str | None, b: str | None) -> bool:
    norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())  # noqa: E731
    return bool(a and b) and norm(a) == norm(b)


def account_gate(facts: dict, registry) -> str | None:
    """
    After the run, for a Northbridge agreement with a customer number: the reason escalation cannot be
    determined from the account, or None. Checked by code from the lookup result itself.
    """
    return account_rule(facts, list(registry.items.values()))


def account_rule(facts: dict, evidence: list[dict]) -> str | None:
    """account_gate on a list of evidence items: live ones carry `record`, saved ones its JSON in `text`."""
    import json

    cid = facts["customer_number"]
    looked_up = [e if "record" in e or not e.get("found") else {**e, "record": json.loads(e["text"])}
                 for e in evidence if e["kind"] == "account" and e.get("customer_id") == cid]
    if not looked_up:
        return f"the account for {cid} was not looked up"
    if not any(e.get("found") for e in looked_up):
        return f"no account record exists for {cid}"
    holder = next(e for e in looked_up if e.get("found"))["record"].get("account_holder_name")
    if facts.get("borrower") and not _same_name(holder, facts["borrower"]):
        return f"the account for {cid} belongs to {holder}, not to {facts['borrower']}, the borrower named in the agreement"
    return None


def window_start(review_date: str, months: int | None = None) -> str:
    """First day inside the window: `months` before the review date (default: the 2.1(c) window, 12)."""
    months = config.AGENT_RECENT_WINDOW_MONTHS if months is None else months
    y, m, d = (int(x) for x in review_date.split("-"))
    total = y * 12 + (m - 1) - months
    y2, m2 = divmod(total, 12)
    return f"{y2:04d}-{m2 + 1:02d}-{min(d, 28) if m2 + 1 == 2 else d:02d}"


def account_facts(record: dict, review_date: str) -> dict:
    """Facts checkable without judgment: missed payments in the window, open hardship markers, life-event notes."""
    trailing_12 = window_start(review_date, months=12)  # 2.1(a): the procedure's own "trailing 12 months"
    recent = window_start(review_date)                  # 2.1(c): "recent", AGENT_RECENT_WINDOW_MONTHS
    missed = [e for e in record.get("payment_events", [])
              if e.get("type") == "missed_payment" and trailing_12 <= (e.get("due_date") or "") < review_date]
    open_markers = [m for m in record.get("markers", []) if m.get("type") == "financial_hardship" and not m.get("closed")]
    life_notes = [n for n in record.get("notes", [])
                  if recent <= (n.get("date") or "") < review_date and LIFE_EVENT_WORDS.search(n.get("text", ""))]
    return {"missed_in_window": len(missed), "open_hardship_markers": len(open_markers),
            "life_event_notes_in_window": [n["date"] for n in life_notes]}



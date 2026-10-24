"""
Try a sample: a step-by-step replay of how one synthetic loan agreement was reviewed by the AI agent,
from the saved live run (docs/eval_agent_v2.jsonl, run 0). Nothing here calls a model. The code rules
(src/agent/document_rules.py) are re-run on the spot, because they are plain code.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from src import config, ui  # noqa: E402
from src.agent.document_rules import account_facts, account_rule, document_facts, escalation_gate  # noqa: E402
from src.monitoring.overview import PLAIN, PLAIN_ESCALATION, _labels  # noqa: E402
from src.review.cases import OUTCOME_NAMES, OUTCOMES, _document_file  # noqa: E402
from src.review.replay import CHECKS, TOOL_PLAIN, TRIGGERS, sample_title  # noqa: E402  (shared with the static site)

st.set_page_config(page_title="Try a sample", layout="wide")
ui.style()
st.title("Try a sample")
st.caption("Follow one synthetic loan agreement through the AI agent's review, step by step. This replays a real "
           "recorded run; nothing here calls a model.")

@st.cache_data
def samples() -> dict[str, dict]:
    path = config.PROJECT_ROOT / "docs" / "eval_agent_v2.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["doc_id"]: r for r in rows if r["run_idx"] == 0}


rows = samples()
labels = _labels()
choice = st.selectbox("Pick an agreement", sorted(rows), format_func=lambda d: sample_title(d, rows[d], labels[d]), key="sample")
row, label = rows[choice], labels[choice]
evidence = {e["number"]: e for e in row["evidence"]}
doc_file = _document_file(choice)
text = doc_file.read_text(encoding="utf-8") if doc_file else ""
with st.expander("Read the agreement"):
    st.text(text)

# 1 -------------------------------------------------------------------------------------------
st.subheader("1 · Before any AI: what the code reads")
facts = document_facts(text) if text else row["document_facts"]
gate = escalation_gate(facts)
lender = {"northbridge": "Northbridge Consumer Lending (our bank)", "other": facts.get("lender_clause") or "another lender",
          "not_stated": "not named"}[facts["lender"]]
c1, c2, c3 = st.columns(3)
c1.metric("A loan agreement?", "Yes" if facts["credit_agreement"] else "No")
c2.metric("Lender", "Northbridge" if facts["lender"] == "northbridge" else
          ("Not named" if facts["lender"] == "not_stated" else "Another lender"), help=lender)
c3.metric("Customer number", facts["customer_number"] or "None")
if not gate["call_model"]:
    st.info(f"Code stops here: {gate['reason']}. The AI is not called at all.")
elif gate["decision"]:
    st.info(f"Code decides the escalation question already: {PLAIN_ESCALATION[gate['decision']].lower()}, because "
            f"{gate['reason']}. The AI is only offered: " + ", ".join(TOOL_PLAIN[t].lower() for t in sorted(gate["tools"])) + ".")
else:
    st.success("A Northbridge loan with a customer number: the AI gets all three tools and decides for itself what to look up.")

# 2 -------------------------------------------------------------------------------------------
st.subheader("2 · What the AI chose to look up")
calls = row["tool_calls"]
if not calls:
    st.write("Nothing: no lookup was needed.")
unnecessary = {u["n"]: u["reason"] for u in row.get("unnecessary_calls", [])}
for c in calls:
    a = c["arguments"]
    detail = (f"for **{OUTCOME_NAMES.get(a.get('outcome'), a.get('outcome'))}**: “{a.get('query', '')}”"
              if c["tool"] == "search_regulation" else
              f"**{a.get('customer_id')}**" if c["tool"] == "get_account" else f"“{a.get('query', '')}”")
    flag = f" — :orange[unnecessary: {unnecessary[c['n']]}]" if c["n"] in unnecessary else ""
    st.markdown(f"{c['n']}. {TOOL_PLAIN.get(c['tool'], c['tool'])} {detail}{flag}")
if unnecessary:
    st.caption("This run was recorded before the code rules in step 1 were added. Today the unnecessary tools "
               "would not even be offered.")

# 3 -------------------------------------------------------------------------------------------
account = [e for e in row["evidence"] if e["kind"] == "account"]
if account:
    st.subheader("3 · What the customer's account shows")
    e = account[0]
    if not e.get("found"):
        st.warning(f"No account exists for {e.get('customer_id')}.")
    else:
        record = json.loads(e["text"])
        f = account_facts(record, config.AGENT_REVIEW_DATE)
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Account holder", record.get("account_holder_name"),
                  help=None if not facts.get("borrower") else f"The agreement names: {facts['borrower']}")
        a2.metric("Missed payments, last 12 months", f["missed_in_window"])
        a3.metric("Open hardship markers", f["open_hardship_markers"])
        a4.metric("Recent life-event notes", len(f["life_event_notes_in_window"]))

# 4 -------------------------------------------------------------------------------------------
st.subheader("4 · Its verdict on each Consumer Duty outcome")
for k in OUTCOMES:
    o = row["outcomes"][k]
    j = o.get("judgment") or {}
    with st.expander(f"{OUTCOME_NAMES[k]}: {PLAIN.get(o['status'], o['status'])}"):
        ui.verdict_badge(o["status"])
        if o.get("forced_reasons"):
            st.warning("The code overruled the AI here: " + "; ".join(o["forced_reasons"]) +
                       f". The AI had said “{PLAIN.get(o.get('llm_status'), o.get('llm_status'))}”.")
        if j.get("reasoning"):
            st.markdown(f"**Why:** {j['reasoning']}")
        for req in (j.get("regulatory_requirements") or [])[:2]:
            for src in req["sources"][:1]:
                st.markdown(f"**Claim:** {req['claim']}")
                st.markdown(f"> “{src['verbatim_quote']}”")
                passage = evidence.get(src["excerpt_number"], {})
                if passage.get("text"):
                    st.caption(f"From {passage.get('file_name', 'the regulation')}"
                               f"{', p. ' + str(passage['page_label']) if passage.get('page_label') else ''}:")
                    st.text(passage["text"][:1200])

# 5 -------------------------------------------------------------------------------------------
st.subheader("5 · The code checks its work")
checks = row["checks"]
failed = [c for c in checks if c["passed"] is False]
st.metric("Checks passed", f"{sum(c['passed'] is not False for c in checks)} of {len(checks)}")
for c in failed:
    name = c["name"].split(":")[0]
    where = f" ({OUTCOME_NAMES.get(c['name'].split(':')[1], '')})" if ":" in c["name"] else ""
    st.markdown(f"- :orange[Failed:] {CHECKS.get(name, name)}{where}")
if not failed:
    st.markdown("Every check passed.")

# 6 -------------------------------------------------------------------------------------------
st.subheader("6 · Should the customer go to the vulnerable-customer team?")
esc = row.get("escalation") or {}
rule = gate["reason"] if gate["decision"] else (
    account_rule(facts, row["evidence"]) if facts["lender"] == "northbridge" and facts["customer_number"] else None)
final = gate["decision"] or ("cannot_determine" if rule else esc.get("decision"))
st.markdown(f"**Decision:** {PLAIN_ESCALATION.get(final, final)}")
if rule:
    st.caption(f"Set by code: {rule}." + (f" The AI had said “{PLAIN_ESCALATION.get(esc.get('decision'), esc.get('decision'))}”."
                                          if esc.get("decision") not in (None, final) else ""))
for t in esc.get("triggers") or []:
    st.markdown(f"- Policy {t}: {TRIGGERS.get(t, t)}")
if esc.get("reasoning") and not rule:
    st.markdown(f"**Why:** {esc['reasoning']}")

# 7 -------------------------------------------------------------------------------------------
st.subheader("7 · The answer key")
st.caption("This is a test agreement with problems planted on purpose, so the right answers are known.")
for k in OUTCOMES:
    truth = label["ground_truth"].get(k)
    said = row["outcomes"][k].get("llm_status")
    if truth == "not_applicable":
        ok, want = said in (None, "not_applicable"), "not applicable"
    else:
        want = "a possible breach" if truth == "non_compliant" else "compliant"
        ok = (said == "potentially_non_compliant") == (truth == "non_compliant") and said not in (None, "insufficient_evidence")
    mark = ":green[✓ right]" if ok else (":gray[unsure, so sent to a person]" if said == "insufficient_evidence"
                                              else ":orange[✗ wrong]")
    st.markdown(f"- **{OUTCOME_NAMES[k]}:** should be {want}; the AI said {PLAIN.get(said, said).lower()}. {mark}")
if label.get("escalation"):
    ok = final == label["escalation"]
    st.markdown(f"- **Vulnerable customer:** should be “{PLAIN_ESCALATION[label['escalation']]}”; "
                f"the review ends with “{PLAIN_ESCALATION.get(final, final)}”. "
                + (":green[✓ right]" if ok else ":orange[✗ wrong]"))

st.divider()
st.markdown("**In the real tool, every one of these goes to a person,** who confirms or overrides each verdict.")
st.markdown("[Open the review queue →](/)")

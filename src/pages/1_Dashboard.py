"""
Dashboard (P9-02), two audiences:
- "Compliance overview": plain language for compliance staff, from the saved results, the known
  answers for the synthetic test documents, and reviewers' decisions (src/monitoring/overview.py);
- "System health": failure rate, flagged rate, latency and cost from the audit log, or a committed
  snapshot of it where no log exists, e.g. the hosted demo (src/monitoring/dashboard.py).
No API calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import altair as alt  # noqa: E402  (ships with Streamlit)
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import config, ui  # noqa: E402
from src.monitoring import audit, dashboard, overview  # noqa: E402
from src.review.store import DecisionStore  # noqa: E402

st.set_page_config(page_title="Dashboard", layout="wide")
ui.style()
st.title("Dashboard")

OUTCOME_MEANING = {
    "Price and value": "Is the price fair for what the customer gets? Fees and charges must be justified.",
    "Consumer support": "Can customers get help when they need it, especially vulnerable customers?",
    "Products and services": "Is the product designed for, and sold to, the right customers?",
    "Consumer understanding": "Are the key terms explained clearly enough for the customer to understand?",
}
STATUS_COLOURS = {"Possible breach": "#ff4f12", "Not enough evidence": "#8a8f7e", "Looks compliant": "#1e4a3b",
                  "Not applicable": "#cfcbbd", "No answer": "#0e0e0c"}

compliance, health = st.tabs(["Compliance overview", "System health"])

# ---------------------------------------------------------------- compliance overview
with compliance:
    st.caption("Synthetic loan agreements checked against the FCA Consumer Duty. Every agreement still goes to a "
               "person: nothing here is approved automatically.")
    system = st.radio("Which system", list(overview.SYSTEMS), horizontal=True, key="system")
    s = overview.summary(system, DecisionStore())
    is_agent = system.startswith("AI agent")

    a, b, c, d = st.columns(4)
    a.metric("Loan agreements reviewed", s["agreements"])
    b.metric("With a possible breach", s["agreements_with_a_possible_breach"])
    c.metric("A person must look closely", s["agreements_needing_a_person"],
             help="A possible breach, not enough evidence to decide, or a vulnerable-customer question.")
    d.metric("Vulnerable customers to escalate", s["escalation"].get("Escalate: vulnerable customer", 0)
             if is_agent else "n/a", help=None if is_agent else "Only the AI agent checks customer accounts.")

    st.subheader("What it found, by Consumer Duty outcome")
    st.caption("Each agreement counted once (its first review), as the reviewer receives it.")
    long = pd.DataFrame([{"Outcome": o, "Result": res, "Agreements": n}
                         for o, counts in s["found"].items() for res, n in counts.items()])
    order = [k for k in STATUS_COLOURS if k in set(long["Result"])]
    st.altair_chart(
        alt.Chart(long).mark_bar().encode(
            y=alt.Y("Outcome:N", sort=list(OUTCOME_MEANING), title=None, axis=alt.Axis(labelLimit=320)),
            x=alt.X("Agreements:Q", title="Agreements"),
            color=alt.Color("Result:N", sort=order, title=None, legend=alt.Legend(orient="bottom"),
                            scale=alt.Scale(domain=order, range=[STATUS_COLOURS[k] for k in order])),
            order=alt.Order("sort_key:Q"),
            tooltip=["Outcome", "Result", "Agreements"],
        ).transform_calculate(sort_key=f"indexof({order!r}, datum.Result)").properties(height=230),
        width="stretch")
    with st.expander("What the four outcomes mean"):
        for name, meaning in OUTCOME_MEANING.items():
            st.markdown(f"**{name}.** {meaning}")

    st.subheader("How reliable is it?")
    st.caption(f"Measured on test agreements with known, planted problems: {s['reviews']} reviews in total. "
               "This is the system's own call, before any safety rule sent it to a person.")
    r1, r2, r3 = st.columns(3)
    r1.metric("Real problems caught", f"{s['caught']} of {s['real_problems']}")
    r2.metric("Real problems missed", s["missed"],
              help="A real problem the system called compliant. The most serious kind of error.")
    r3.metric("False alarms", s["false_alarms"], help="A compliant agreement flagged as a possible breach. "
              "Costs reviewer time, not customers.")
    rel = pd.DataFrame(s["reliability"]).T.reindex(columns=["caught", "missed", "false_alarm", "unsure"]).fillna(0)
    rel.columns = ["Problems caught", "Problems missed", "False alarms", "Unsure (sent to a person)"]
    st.dataframe(rel.astype(int), width="stretch")
    worst = max(s["reliability"].items(), key=lambda kv: kv[1].get("missed", 0))
    if s["missed"]:
        where = ("all of them" if worst[1].get("missed", 0) == s["missed"] else f"{worst[1].get('missed', 0)} of them")
        st.warning(f"{s['missed']} real {'problem was' if s['missed'] == 1 else 'problems were'} missed, {where} in "
                   f"{worst[0].lower()}. This is why a person reviews every agreement.")
    else:
        st.success("No real problem was missed in these tests. With this few test agreements that still cannot "
                   "prove a low miss rate, so a person reviews every agreement.")

    if is_agent:
        st.subheader("Vulnerable customers")
        right, total = s["escalation_right"]
        st.caption(f"Whether the customer's case should go to the vulnerable-customer team, decided from their "
                   f"account and Northbridge's policy. Right in {right} of {total} reviews.")
        esc = pd.DataFrame([{"Decision": k, "Agreements": v} for k, v in s["escalation"].items()])
        st.altair_chart(alt.Chart(esc).mark_bar(color="#1e4a3b").encode(
            y=alt.Y("Decision:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
            x=alt.X("Agreements:Q"), tooltip=["Decision", "Agreements"]).properties(height=170), width="stretch")

    st.subheader("What reviewers did")
    p = s.get("people", {})
    q1, q2, q3 = st.columns(3)
    q1.metric("Cases resolved", f"{p.get('resolved', 0)} of {p.get('cases', 0)}")
    q2.metric("Decisions recorded", p.get("decisions", 0))
    q3.metric("Times a reviewer disagreed", p.get("overrides", 0),
              help="An override: the reviewer changed the system's verdict, with a written reason.")
    if p.get("overrides_by_outcome"):
        st.caption("Where reviewers disagreed most: " + ", ".join(
            f"{k} ({v})" for k, v in sorted(p["overrides_by_outcome"].items(), key=lambda kv: -kv[1])))
    if config.DEMO_MODE:
        st.caption("Public demo: decisions are kept only until the app restarts.")

# ---------------------------------------------------------------- system health
with health:
    st.caption(f"For the technical team. From the audit log ({audit.redact(config.LOG_DIR)}/index.jsonl and each "
               "run's log). Every number is a count of logged events; nothing here calls the model.")
    include_rehearsal = st.checkbox("Include rehearsal (dry-run) runs", value=False)
    commands, docs, snapshot_at = dashboard.load_or_snapshot()
    if not commands:
        st.info("No audit runs logged yet.")
        st.stop()
    if snapshot_at:
        st.info(f"No live audit log here, so this shows a saved snapshot of it (last run {snapshot_at[:16]} UTC).")
    days = pd.DataFrame(dashboard.by_day(commands, docs, include_rehearsal)).set_index("day")
    done = [x for x in docs if (include_rehearsal or not x["rehearsal"]) and not x["failed"]]
    all_docs = [x for x in docs if include_rehearsal or not x["rehearsal"]]
    lat = sorted(x["latency_s"] for x in done if x["latency_s"] is not None)
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Agent document runs", len(all_docs))
    h2.metric("Document failure rate", f"{sum(x['failed'] for x in all_docs) / len(all_docs):.1%}" if all_docs else "n/a")
    h3.metric("Flagged for review", f"{sum(x['flagged'] for x in done) / len(done):.1%}" if done else "n/a",
              help="100% while auto-approval is disabled: every case goes to a person by design.")
    h4.metric("Median latency per document", f"{lat[len(lat) // 2]:.0f} s" if lat else "n/a")
    st.subheader("Failure rate over time")
    st.caption("Commands: share of audit runs not 'completed'. Documents: share of agent document runs that raised an error.")
    st.line_chart(days[["command_failure_rate", "document_failure_rate"]])
    st.subheader("Flagged rate over time")
    st.caption("Flagged: the run needs human review (100% while auto-approval is off). Beyond policy: flagged for a reason "
               "other than 'auto-approval disabled'; logged from 2026-10-24 on, blank before.")
    st.line_chart(days[["flagged_rate", "flagged_beyond_policy_rate"]])
    st.subheader("Latency over time (seconds per agent document run)")
    st.line_chart(days[["median_latency_s", "p90_latency_s"]])
    st.subheader("By day")
    st.dataframe(days, width="stretch")
    st.subheader("Every logged command")
    st.dataframe(pd.DataFrame([x for x in commands if include_rehearsal or not x["rehearsal"]]), hide_index=True,
                 width="stretch")

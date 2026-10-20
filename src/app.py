"""
Compliance review screen (P7-01): every flagged case needs an explicit human decision on each
item before it can be marked resolved. Auto-approval is disabled, so every case is in the queue.

Run:  streamlit run src/app.py

The rules (reviewer named, override needs a reason, resolve only when every item is decided,
append-only history) are enforced by src/review/store.py; this screen only displays and passes
decisions through. Sources can be overridden with REVIEW_SOURCES='{"name": "path", ...}' (tests).
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from src import config  # noqa: E402
from src.monitoring import audit  # noqa: E402
from src.review.cases import DEFAULT_SOURCES, load_cases  # noqa: E402
from src.review.store import DecisionStore, ReviewError  # noqa: E402

REHEARSAL_SOURCES = {"agent v2 (rehearsal)": config.LOG_DIR / "dryrun" / "eval_agent_v2.jsonl",
                     "agent v1 (rehearsal)": config.LOG_DIR / "dryrun" / "eval_agent_v1.jsonl"}


def sources(include_rehearsal: bool) -> dict:
    if os.getenv("REVIEW_SOURCES"):
        return {k: Path(v) for k, v in json.loads(os.environ["REVIEW_SOURCES"]).items()}
    s = dict(DEFAULT_SOURCES) | (REHEARSAL_SOURCES if include_rehearsal else {})
    return {k: v for k, v in s.items() if Path(v).exists()}


st.set_page_config(page_title="Compliance review", layout="wide")
if not audit.active():  # one audit run per app process; decisions are logged under it
    audit.start_run("review app")
store = DecisionStore()

st.title("Compliance review")
flash = st.session_state.pop("flash", None)  # confirmation from the previous action, shown once after the refresh
if flash:
    st.success(flash)
    st.toast(flash)  # floats on screen, so it is seen even when the reviewer is scrolled down at the Resolve button
st.caption("Synthetic documents and accounts only. Auto-approval is disabled: every case needs a human decision "
           "on each item before it can be resolved. Confidence is shown for information and never replaces a verdict.")

with st.sidebar:
    reviewer = st.text_input("Reviewer name", key="reviewer")
    include_rehearsal = st.checkbox("Include rehearsal (dry-run) rows", value=False,
                                    help="Rows from an offline rehearsal: placeholder verdicts, for trying the screen.")
    available = sources(include_rehearsal)
    chosen = st.multiselect("Sources", list(available), default=list(available), key="sources")
    show = st.radio("Show", ("Open", "Resolved", "All"), horizontal=True, key="show")

cases = load_cases({k: available[k] for k in chosen})
resolved = {c.case_id for c in cases if store.is_resolved(c.case_id)}
visible = [c for c in cases if show == "All" or (show == "Resolved") == (c.case_id in resolved)]

st.subheader(f"Queue: {len(visible)} case(s)  ·  open {len(cases) - len(resolved)}  ·  resolved {len(resolved)}")
if not visible:
    st.info("No cases to show. Agent results appear here once `agent_eval run` has written them.")
    st.stop()

st.dataframe([{"case": c.case_id, "document": c.doc_id, "run": c.run_idx, "source": c.source,
               "items still to decide": len(store.outstanding(c)), "resolved": c.case_id in resolved,
               "rehearsal": c.rehearsal} for c in visible], hide_index=True, width="stretch")

case_id = st.selectbox("Open a case", [c.case_id for c in visible], key="case")
case = next(c for c in visible if c.case_id == case_id)
is_resolved = case.case_id in resolved
decided = store.current(case.case_id)

if flash and flash.startswith("Resolved "):  # the resolved case left the Open list: say a different case is now shown
    st.info(f"{flash} Now showing the next case: {case.case_id}.")
st.markdown(f"### {case.doc_id} · run {case.run_idx} · {case.source}")
# The agent numbers its evidence E1, E2...; the baseline numbers the excerpts it retrieved 1-5.
passage_label = "passage E" if case.tool_calls or case.items[-1].item_id == "escalation" else "excerpt "
if case.rehearsal:
    st.warning("Rehearsal row: the verdicts are placeholders from an offline dry run, not the model's.")
for r in case.case_reasons:
    st.write(f"- {r}")
if case.document_file:
    with st.expander("The document"):
        st.text(case.document_file.read_text(encoding="utf-8"))
if case.tool_calls:
    with st.expander(f"Tool calls the agent made ({len(case.tool_calls)})"):
        st.dataframe([{"#": t["n"], "turn": t["turn"], "tool": t["tool"], "arguments": json.dumps(t["arguments"]),
                       "cached": t["cached"], "error": t["is_error"]} for t in case.tool_calls], hide_index=True)

for item in case.items:
    current = decided.get(item.item_id)
    label = f"{item.title}: system says **{item.system_verdict}**"
    if current:
        label += f"  ·  decided: {current['action']} → {current['reviewer_verdict']}"
    with st.expander(label, expanded=current is None and not is_resolved):
        if item.confidence is not None:
            note = " (below the uncalibrated 0.65 reference)" if item.below_reference else ""
            st.write(f"Confidence: {item.confidence:.4f}{note}")
        for f in item.flags:
            st.write(f"- {f}")
        if item.reasoning:
            st.markdown(f"**Reasoning:** {item.reasoning}")
        for c in item.claims:
            st.markdown(f"**Claim:** {c['claim']}  \n**Quote:** “{c['quote']}”  \n"
                        f"**From:** {(passage_label + str(c['passage_number']) + ', ') if c['passage_number'] else ''}{c['file']}")
            if c.get("passage_text"):
                st.text(c["passage_text"])
        for q in item.quotes:
            st.markdown(f"**{q['kind']} quote (E{q['evidence_number']}):** “{q['quote']}”")
            if q.get("passage_text"):
                st.text(q["passage_text"])
        if is_resolved:
            continue
        action = st.radio("Decision", ("confirm", "override"), horizontal=True, key=f"act_{item.item_id}")
        verdict, reason = None, ""
        if action == "override":
            options = [v for v in item.allowed_verdicts if v != item.system_verdict]
            verdict = st.selectbox("Correct verdict", options, key=f"ver_{item.item_id}")
            reason = st.text_area("Reason (required)", key=f"why_{item.item_id}")
        if st.button("Record decision", key=f"rec_{item.item_id}"):
            try:
                store.decide(case, item.item_id, action, reviewer, verdict, reason)
                st.session_state["flash"] = f"Recorded: {item.title}, {action}."
                st.rerun()
            except ReviewError as exc:
                st.error(str(exc))

st.markdown("### Resolve")
missing = store.outstanding(case)
if is_resolved:
    st.success("Resolved.")
elif missing:
    st.info(f"Decide every item before resolving. Still to decide: {', '.join(missing)}.")
else:
    note = st.text_area("Resolution note (optional)", key="resolve_note")
    if st.button("Mark case resolved", key="resolve"):
        try:
            store.resolve(case, reviewer, note)
            st.session_state["flash"] = f"Resolved {case.case_id}. It has moved to the Resolved list."
            st.rerun()
        except ReviewError as exc:
            st.error(str(exc))

history = store.history(case.case_id)
if history:
    st.markdown("### History")
    st.dataframe([{k: h.get(k) for k in ("ts", "item_id", "action", "system_verdict", "reviewer_verdict", "reason",
                                          "reviewer")} for h in history], hide_index=True, width="stretch")

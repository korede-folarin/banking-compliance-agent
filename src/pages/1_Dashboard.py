"""
Monitoring dashboard (P9-02): failure rate, flagged rate and latency over time, from the audit log.
Opened from the review app's sidebar (Streamlit multipage: src/pages/). Reads LOG_DIR only; no API calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import config, ui  # noqa: E402
from src.monitoring import audit, dashboard  # noqa: E402

st.set_page_config(page_title="Monitoring", layout="wide")
ui.style()
st.title("Monitoring")
st.caption(f"From the audit log ({audit.redact(config.LOG_DIR)}/index.jsonl and each run's log). Every number is a count of "
           "logged events; nothing here calls the model.")

include_rehearsal = st.sidebar.checkbox("Include rehearsal (dry-run) runs", value=False)
commands, docs = dashboard.load()
if not commands:
    st.info("No audit runs logged yet.")
    st.stop()
days = pd.DataFrame(dashboard.by_day(commands, docs, include_rehearsal)).set_index("day")

c1, c2, c3, c4 = st.columns(4)
done = [d for d in docs if (include_rehearsal or not d["rehearsal"]) and not d["failed"]]
all_docs = [d for d in docs if include_rehearsal or not d["rehearsal"]]
lat = sorted(d["latency_s"] for d in done if d["latency_s"] is not None)
c1.metric("Agent document runs", len(all_docs))
c2.metric("Document failure rate", f"{sum(d['failed'] for d in all_docs) / len(all_docs):.1%}" if all_docs else "n/a")
c3.metric("Flagged for review", f"{sum(d['flagged'] for d in done) / len(done):.1%}" if done else "n/a",
          help="100% while auto-approval is disabled: every case goes to a person by design.")
c4.metric("Median latency per document", f"{lat[len(lat) // 2]:.0f} s" if lat else "n/a")

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
st.dataframe(pd.DataFrame([c for c in commands if include_rehearsal or not c["rehearsal"]]), hide_index=True,
             width="stretch")

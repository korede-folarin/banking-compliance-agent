"""Shared look for every page: only what .streamlit/config.toml cannot express. Visual only."""

import streamlit as st

# Verdict -> st.badge colour. The label text is never changed, only its colour.
VERDICT_COLOUR = {
    "compliant": "green",
    "potentially_non_compliant": "orange",  # a person needs to look
    "insufficient_evidence": "gray",
    "not_applicable": "gray",
}

_CSS = """
<style>
/* Page title: uppercase display, tight tracking, like the portfolio */
h1 { text-transform: uppercase; letter-spacing: -0.055em !important; line-height: 0.9 !important; }
h2, h3 { letter-spacing: -0.03em !important; }

/* Small labels in mono: captions, metric labels, widget labels */
[data-testid="stCaptionContainer"] p,
[data-testid="stMetricLabel"] p,
[data-testid="stWidgetLabel"] p { font-family: "JetBrains Mono", monospace; font-size: 0.74rem;
  letter-spacing: 0.05em; text-transform: uppercase; }
[data-testid="stCaptionContainer"] p { text-transform: none; letter-spacing: 0.01em; font-size: 0.82rem; }
/* Metric labels wrap instead of being cut off with an ellipsis */
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * { white-space: normal !important; overflow: visible !important;
  text-overflow: clip !important; }

/* Metrics as bordered cards; the first one is the solid green highlight */
[data-testid="stMetric"] { background: #f7f6f0; border: 1.5px solid #0e0e0c; border-radius: 16px; padding: 14px 16px 12px; }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:first-child [data-testid="stMetric"] {
  background: #1e4a3b; border-color: #1e4a3b; }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div:first-child [data-testid="stMetric"] * { color: #f1ece2 !important; }

/* Expanders read as case cards */
[data-testid="stExpander"] details { border: 1.5px solid #0e0e0c; border-radius: 16px; background: #f7f6f0; }
[data-testid="stExpander"] summary p { font-weight: 700; letter-spacing: -0.01em; }

/* Sidebar: bolder page links */
[data-testid="stSidebarNav"] a span { font-weight: 600; }
/* Sidebar multiselect chips: cream pill, green text (readable on the green sidebar) */
[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] span { color: #1e4a3b !important; }
[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] svg { fill: #1e4a3b !important; color: #1e4a3b !important; }

/* Quotes from the regulation: set apart, never decorative */
blockquote { border-left: 3px solid #1e4a3b !important; background: #ecebe2; border-radius: 0 10px 10px 0; padding: 8px 14px !important; }
</style>
"""


def style() -> None:
    """Call once at the top of every page, right after st.set_page_config."""
    st.markdown(_CSS, unsafe_allow_html=True)


def verdict_badge(status: str) -> None:
    """The verdict as a coloured pill; the text is the verdict itself."""
    st.badge(status, color=VERDICT_COLOUR.get(status, "gray"))

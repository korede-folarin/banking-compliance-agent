"""
MCP server for the agentic tool loop (docs/agent_tool_use_design.md).

Separate from server.py on purpose. server.py's three tools return an
LLM-written answer and look accounts up by name; they stay unchanged for
P5-04 and the baseline. These three tools return raw evidence only, with no
model call inside, and look accounts up by customer number only:

  search_regulation(outcome, query)  top-5 chunks from the FCA corpus, for one named outcome
  get_account(customer_id)   one account record from the v2 accounts file
  search_policy(query)       top-5 chunks from Northbridge's internal policy

Tool descriptions say what each tool holds, never what it is "for" in an
evaluation. Runs as a stdio subprocess (src/agent/tool_agent.py), so nothing
here may print to stdout: stdout is the MCP channel.

Configuration (environment, read at start-up):
  AGENT_ACCOUNTS_PATH  accounts JSON (default data/fixtures_v2/accounts.json)
"""

import json
import os
import re
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from src.config import CHROMA_COLLECTION_NAME, INTERNAL_POLICY_COLLECTION_NAME, PROJECT_ROOT

TOP_K = 5
CUSTOMER_ID = re.compile(r"^CUST-\d{5}$")
ACCOUNTS_PATH = Path(os.getenv("AGENT_ACCOUNTS_PATH", PROJECT_ROOT / "data" / "fixtures_v2" / "accounts.json"))

mcp = FastMCP("compliance-agent-tools")
_retrievers: dict = {}


def _retriever(collection: str):
    """Built on first use and reused: loading the embedding model is the slow part."""
    if collection not in _retrievers:
        from src.retrieval.query_engine import load_index

        _retrievers[collection] = load_index(collection).as_retriever(similarity_top_k=TOP_K)
    return _retrievers[collection]


def _chunks(collection: str, query: str) -> str:
    if not query or not query.strip():
        return json.dumps({"error": "query must be a non-empty string"})
    nodes = _retriever(collection).retrieve(query)
    return json.dumps({"query": query, "results": [
        {"file_name": n.metadata.get("file_name", "unknown"), "page_label": n.metadata.get("page_label"),
         "node_id": n.node.node_id, "similarity": round(n.score or 0.0, 4), "text": n.text}
        for n in nodes
    ]})


Outcome = Literal["price_and_value", "consumer_support", "products_and_services", "consumer_understanding"]


@mcp.tool()
def search_regulation(outcome: Outcome, query: str) -> str:
    """
    Search the FCA Consumer Duty texts (PRIN 2A, FG22/5 guidance, PS22/9 policy statement) for one
    Consumer Duty outcome. Each call covers exactly one outcome, named in `outcome`.
    Returns up to 5 passages, each with file name, page, similarity score and full text.
    """
    result = json.loads(_chunks(CHROMA_COLLECTION_NAME, query))
    return json.dumps({"outcome": outcome, **result})


@mcp.tool()
def get_account(customer_id: str) -> str:
    """
    Return the account record held by Northbridge Consumer Lending for one customer number
    (format CUST- followed by 5 digits): account holder name, customer since, account status,
    products, dated payment events, markers with opened and closed dates, and dated notes.
    Returns {"found": false} when no record exists for that customer number.
    """
    if not CUSTOMER_ID.match(customer_id or ""):
        return json.dumps({"error": "customer_id must look like CUST-12345", "customer_id": customer_id})
    data = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))
    for a in data["accounts"]:
        if a["customer_id"] == customer_id:
            return json.dumps({"found": True, **a})
    return json.dumps({"found": False, "customer_id": customer_id})


@mcp.tool()
def search_policy(query: str) -> str:
    """
    Search Northbridge Consumer Lending's internal policy documents (underwriting guidelines and
    the vulnerable customer escalation procedure). Returns up to 5 passages, each with file name,
    similarity score and full text. Takes a natural-language search query.
    """
    return _chunks(INTERNAL_POLICY_COLLECTION_NAME, query)


def warm_up() -> None:
    """
    Load the embedding model and both indexes BEFORE serving. On Windows, loading them inside the
    first tool call (while the stdio transport has a read pending on stdin) hung indefinitely: found
    2026-10-14. The same retrieval ran in ~20 s from a shell or a plain subprocess, and in the server
    the hang came before the model began loading. Warming up first means a tool call never does a
    first-time load.
    """
    _retriever(CHROMA_COLLECTION_NAME).retrieve("warm up")
    _retriever(INTERNAL_POLICY_COLLECTION_NAME).retrieve("warm up")


if __name__ == "__main__":
    warm_up()
    mcp.run()

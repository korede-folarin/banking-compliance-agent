import json
import logging

from mcp.server.fastmcp import FastMCP

from src.config import INTERNAL_POLICY_COLLECTION_NAME
from src.mcp_server.mock_accounts import lookup_account as _lookup_account
from src.retrieval.query_engine import QueryEngine

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP("banking-compliance-tools")

# Lazily constructed and reused for the life of the server process: each
# QueryEngine loads the embedding model and opens a Chroma client, so
# building one per tool call would be wasteful.
_regulation_engine: QueryEngine | None = None
_policy_engine: QueryEngine | None = None


def _get_regulation_engine() -> QueryEngine:
    global _regulation_engine
    if _regulation_engine is None:
        _regulation_engine = QueryEngine()
    return _regulation_engine


def _get_policy_engine() -> QueryEngine:
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = QueryEngine(
            collection_name=INTERNAL_POLICY_COLLECTION_NAME,
            corpus_description=(
                "Northbridge Consumer Lending's internal underwriting and "
                "vulnerable-customer escalation policy"
            ),
            no_answer_message=(
                "The provided internal policy corpus does not contain enough "
                "information to answer this question."
            ),
        )
    return _policy_engine


@mcp.tool()
def lookup_regulation(question: str) -> str:
    """
    Answer a question about the public FCA Consumer Duty regulatory corpus
    (PRIN 2A, FG22/5, PS22/9), grounded with cited sources. Returns a JSON
    object with "question", "answer", and "sources" (file name, similarity
    score, and excerpt for each cited chunk).
    """
    result = _get_regulation_engine().query(question)
    return result.model_dump_json()


@mcp.tool()
def lookup_account(name_or_id: str) -> str:
    """
    Look up a mock customer account by account ID or account holder name
    (exact match, case-insensitive). Synthetic data only, not real customer
    records. Returns a JSON object with the account details, or
    {"found": false} if no match exists.
    """
    account = _lookup_account(name_or_id)
    if account is None:
        return json.dumps({"found": False, "query": name_or_id})
    return json.dumps({"found": True, **account})


@mcp.tool()
def query_policy(question: str) -> str:
    """
    Answer a question about Northbridge Consumer Lending's internal
    underwriting guidelines and vulnerable-customer escalation procedure
    (synthetic, distinct from the public FCA regulatory corpus), grounded
    with cited sources. Returns a JSON object with "question", "answer",
    and "sources".
    """
    result = _get_policy_engine().query(question)
    return result.model_dump_json()


if __name__ == "__main__":
    mcp.run(transport="stdio")

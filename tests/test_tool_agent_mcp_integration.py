"""
End-to-end tool calling through the REAL MCP server (src/mcp_server/agent_server.py)
as a stdio subprocess, against the real local Chroma index and the real v2
accounts file. The model is scripted (no API call); everything below it is real:
list_tools, the tool schemas, call_tool, retrieval, the account lookup, evidence
numbering and validation.

Offline: needs the local Chroma index and the cached embedding model. Skipped if
the index is missing. Slow (the server loads the embedding model).
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import chromadb
import pytest

from src.agent.tool_agent import SUBMIT_TOOL, ToolAgent
from src.config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, INTERNAL_POLICY_COLLECTION_NAME, PROJECT_ROOT

QUERIES = {"price_and_value": "price and value fees fair value",
           "consumer_support": "support for customers in vulnerable circumstances",
           "products_and_services": "target market and product design",
           "consumer_understanding": "clear communication of key terms"}
LABELS = json.loads((PROJECT_ROOT / "tests/fixtures/eval_set_v2.json").read_text(encoding="utf-8"))["documents"]


def _index_ready():
    try:
        c = chromadb.PersistentClient(path=str(PROJECT_ROOT / CHROMA_PERSIST_DIR))
        return c.get_collection(CHROMA_COLLECTION_NAME).count() > 0 and c.get_collection(INTERNAL_POLICY_COLLECTION_NAME).count() > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _index_ready(), reason="local Chroma index not built")


def _use(i, name, args):
    return SimpleNamespace(type="tool_use", id=f"tu{i}", name=name, input=args)


def _resp(*blocks):
    return SimpleNamespace(content=list(blocks), stop_reason="tool_use", model="claude-sonnet-5", id="m",
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1,
                                                 cache_read_input_tokens=0, cache_creation_input_tokens=0))


class ScriptedModel:
    """Plays the model's side; builds the final assessment from the evidence the real tools returned."""

    def __init__(self, customer_id):
        self.customer_id = customer_id
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        n = len(self.requests)
        if n == 1:
            return _resp(_use(1, "get_account", {"customer_id": self.customer_id}),
                         _use(2, "search_policy", {"query": "when must a case be escalated for vulnerability"}))
        if n == 2:
            return _resp(*[_use(3 + i, "search_regulation", {"outcome": o, "query": QUERIES[o]})
                           for i, o in enumerate(QUERIES)])
        results = [r for m in kwargs["messages"] if m["role"] == "user" and isinstance(m["content"], list)
                   for r in m["content"]]
        self.tool_results = {r["tool_use_id"]: r["content"] for r in results}
        judgments = {}
        for i, o in enumerate(QUERIES):  # each outcome cites and quotes its OWN search's top passage
            m = re.search(r"^E(\d+) \|[^\n]*\n(.+?)(?:\n\nE\d+ \||\Z)", self.tool_results[f"tu{3 + i}"], re.S | re.M)
            number, text = int(m.group(1)), m.group(2)
            judgments[o] = {"status": "compliant", "reasoning": "r", "cited_sources": [number], "document_facts": [],
                            "regulatory_requirements": [{"claim": "c", "sources": [
                                {"excerpt_number": number, "verbatim_quote": " ".join(text.split()[:12])}]}],
                            "absences": []}
        return _resp(_use(9, SUBMIT_TOOL, {
            "document": {"is_credit_agreement": True, "lender_named": "Northbridge Consumer Lending Ltd",
                         "lender_is_northbridge": "yes"},
            **judgments,
            "escalation": {"decision": "cannot_determine", "triggers": [], "policy_quotes": [], "note_quotes": [],
                           "discrepancies": [], "reasoning": "r", "cited_evidence": []}}))


def test_real_mcp_server_tools_are_listed_and_called_as_the_model_asked(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    doc = next(d for d in LABELS if d["doc_id"] == "v2_d01")
    text = (PROJECT_ROOT / doc["file"]).read_text(encoding="utf-8")
    model = ScriptedModel(doc["customer_id"])
    result = ToolAgent(client=model, review_date="2026-10-01").run(text)

    # tools come from the real server's list_tools, with their real schemas
    tools = {t["name"]: t for t in model.requests[0]["tools"]}
    assert set(tools) == {"search_regulation", "get_account", "search_policy", SUBMIT_TOOL}
    assert tools["get_account"]["input_schema"]["required"] == ["customer_id"]
    assert tools["search_regulation"]["input_schema"]["required"] == ["outcome", "query"]
    assert set(tools["search_regulation"]["input_schema"]["properties"]["outcome"]["enum"]) == set(QUERIES)

    # the calls the model asked for were made, in order, with its arguments
    assert [(c["tool"], c["arguments"]) for c in result["tool_calls"]] == [
        ("get_account", {"customer_id": doc["customer_id"]}),
        ("search_policy", {"query": "when must a case be escalated for vulnerability"}),
        *[("search_regulation", {"outcome": o, "query": q}) for o, q in QUERIES.items()]]
    assert not any(c["is_error"] for c in result["tool_calls"])

    # what came back is real: the right account, the real policy, real FCA passages
    account = model.tool_results["tu1"]
    assert f"account record for {doc['customer_id']}" in account and "Amara Okafor" in account
    assert "missed_payment" in account
    assert "escalat" in model.tool_results["tu2"].lower()
    kinds = {e["kind"] for e in result["evidence"]}
    assert kinds == {"account", "policy", "regulation"}
    reg_files = {e["file_name"] for e in result["evidence"] if e["kind"] == "regulation"}
    assert reg_files <= {"FCA Handbook - PRIN 2A The Consumer Duty.pdf", "fg22-5.pdf", "ps22-9.pdf"}
    by_outcome = {o: [e for e in result["evidence"] if o in e.get("similarity_by_outcome", {})] for o in QUERIES}
    assert all(len(v) == 5 for v in by_outcome.values())  # each outcome's own top 5

    # validation ran on the real evidence: the quote is found in the passage it names
    names = {c["name"]: c for c in result["checks"]}
    for o in QUERIES:
        out = result["outcomes"][o]
        assert out["forced_reasons"] in ([], [f"confidence {out['confidence']:.4f} below 0.65"]), (o, out["forced_reasons"])
        assert names[f"quotes_in_named_passages:{o}"]["passed"] is True
        assert names[f"regulation_from_own_search:{o}"]["passed"] is True
    assert names["regulation_searched_for_each_outcome"]["passed"] is True
    assert names["account_looked_up_with_document_customer_number"]["passed"] is True
    assert names["policy_searched"]["passed"] is True and names["no_unnecessary_calls"]["passed"] is True


def test_real_server_rejects_a_malformed_customer_number(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    class OneCall(ScriptedModel):
        def create(self, **kwargs):
            self.requests.append(kwargs)
            if len(self.requests) == 1:
                return _resp(_use(1, "get_account", {"customer_id": "Amara Okafor"}))
            if len(self.requests) == 2:  # the tool result for call 1; later turns carry text nudges
                self.result_text = kwargs["messages"][-1]["content"][0]
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="done")], stop_reason="end_turn",
                                   model="m", id="m", usage=SimpleNamespace(input_tokens=1, output_tokens=1,
                                                                            cache_read_input_tokens=0,
                                                                            cache_creation_input_tokens=0))

    model = OneCall("x")
    result = ToolAgent(client=model, review_date="2026-10-01").run("Customer number: CUST-12345")
    assert result["tool_calls"][0]["is_error"] is True
    assert "must look like CUST-12345" in model.result_text["content"]


def test_one_real_server_serves_several_documents_as_separate_runs(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    docs = [d for d in LABELS if d["doc_id"] in ("v2_d01", "v2_d02")]

    class PerDocModel(ScriptedModel):
        def create(self, **kwargs):
            if len(kwargs["messages"]) == 1:  # a new document's first turn: start its script again
                self.requests, self.customer_id = [], self.ids.pop(0)
            return super().create(**kwargs)

    model = PerDocModel(None)
    model.ids = [d["customer_id"] for d in docs]
    results = {}
    ToolAgent(client=model, review_date="2026-10-01").run_many(
        [(d["doc_id"], (PROJECT_ROOT / d["file"]).read_text(encoding="utf-8")) for d in docs],
        after=lambda k, r, e: results.__setitem__(k, (r, e)))
    for d in docs:
        result, error = results[d["doc_id"]]
        assert error is None
        assert result["tool_calls"][0]["arguments"] == {"customer_id": d["customer_id"]}
        assert [e["number"] for e in result["evidence"]][0] == 1  # numbering restarts per run
        names = {c["name"]: c for c in result["checks"]}
        assert names["account_looked_up_with_document_customer_number"]["passed"] is True
        assert names["regulation_searched_for_each_outcome"]["passed"] is True

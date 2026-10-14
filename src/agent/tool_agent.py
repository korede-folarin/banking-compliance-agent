"""
Agentic tool loop (docs/agent_tool_use_design.md).

The model chooses which MCP tools to call, when, and with what arguments.
Code owns everything else:
  - the tools come from the MCP server's own list (src/mcp_server/agent_server.py),
    fetched with list_tools and passed to the model as-is;
  - limits: at most MAX_TOOL_CALLS tool calls, MAX_CALLS_PER_TOOL per tool and
    MAX_TURNS model turns (src/config.py). An identical repeated call returns the
    cached result and still counts. Hitting a limit stops the run; every outcome
    becomes insufficient_evidence and the case goes to human review;
  - every passage or record a tool returns gets an evidence number (E1, E2, ...);
    the model must cite those numbers, and only those;
  - after the run, a deterministic validation layer (src/agent/agent_validation.py) computes
    confidence from the cited passages, checks necessary and unnecessary tool calls,
    forces outcomes whose quotes are not in their own cited passages to
    insufficient_evidence, and checks the escalation decision against the
    procedure text and the account record.

The model ends the run by calling submit_assessment, a local output tool (not an
MCP tool, not counted as a tool call).

Baseline comparison: the fixed pipeline (ComplianceCheckAgent) is unchanged.
"""

import asyncio
import json
import re
import sys
import time
from typing import Any

from pydantic import ValidationError

from src import config
from src.agent.agent_schemas import OUTCOME_KEYS, AgentAssessment  # noqa: F401  (re-exported)
from src.agent.agent_validation import account_facts, validate_run  # noqa: F401  (re-exported)
from src.monitoring import audit

SUBMIT_TOOL = "submit_assessment"
SERVER_ENV_ALLOWLIST = ("AGENT_ACCOUNTS_PATH", "CHROMA_PERSIST_DIR", "HF_HUB_OFFLINE", "HF_HOME",
                        "TRANSFORMERS_OFFLINE", "SENTENCE_TRANSFORMERS_HOME")


SYSTEM_PROMPT = """You review a document received by Northbridge Consumer Lending's compliance team.

First establish what the document is: whether it is a credit (loan) agreement, and which lender it names.

Then produce:
1. For each of the four FCA Consumer Duty outcomes (price and value, consumer support, products and
   services, consumer understanding): whether the agreement is compliant, potentially non-compliant,
   or there is insufficient evidence to judge, grounded in regulatory text you retrieve. Each judgment
   must rest on quotes from the passages it cites, and only those passages.
2. Whether Northbridge's internal vulnerable customer escalation procedure requires this customer's
   case to be escalated. A decision must rest on the procedure text itself, quoted exactly from the
   policy passage you cite, and on the customer's account record. For an account note, quote the note
   and its date.

Facts about the setting:
- The review date is {review_date}. "Trailing 12 months" means the 12 months before that date.
- In the escalation procedure, "recent" means within the {recent_months} months before the review date.
- Northbridge's procedure applies only to Northbridge customers.
- Agreements under review have been signed, so the customer's account should list the agreement
  reference among its products.
- Call a tool only when its result can change your assessment.

You have tools. Choose which to call and with what arguments. Budget: at most {max_calls} tool calls
in total; at most {max_regulation} regulation searches, each for exactly one Consumer Duty outcome (one
search per outcome); at most {max_per_tool} calls to each other tool. Repeating an identical call still
uses budget. If you exceed the budget the review stops and goes to a human. An outcome's judgment may
cite only regulation passages returned by that outcome's own search. Every passage or record a tool returns is labelled with an
evidence number like E3. Cite only those numbers; in the assessment, "excerpt number" means evidence
number. Quote text exactly as it appears in the agreement or the evidence. If the evidence does not
support a judgment, say so (insufficient_evidence or cannot_determine) rather than guessing.

You have at most {max_turns} turns, and the final submission uses one of them. You can request several
tool calls in a single turn; their results come back together.

When you are done, call submit_assessment exactly once."""


def _schema_without_titles(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _schema_without_titles(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [_schema_without_titles(v) for v in schema]
    return schema


def submit_tool_definition() -> dict:
    return {"name": SUBMIT_TOOL,
            "description": "Submit the final assessment. Call exactly once, at the end.",
            "input_schema": _schema_without_titles(AgentAssessment.model_json_schema())}


# --- evidence ---

class EvidenceRegistry:
    """Numbers every passage and account result a tool returns; the same passage keeps its number."""

    def __init__(self):
        self.items: dict[int, dict] = {}
        self._by_key: dict[str, int] = {}

    def add(self, key: str, item: dict, outcome: str | None = None) -> int:
        if key not in self._by_key:
            n = len(self.items) + 1
            self._by_key[key] = n
            self.items[n] = {"number": n, **item, "similarity_by_outcome": {}}
        n = self._by_key[key]
        if outcome is not None:  # a regulation passage: remember which outcome's search returned it, and its score there
            self.items[n]["similarity_by_outcome"].setdefault(outcome, item.get("similarity"))
        return n

    def chunk_numbers(self) -> set[int]:
        return {n for n, e in self.items.items() if e["kind"] in ("regulation", "policy")}


def format_tool_result(tool: str, raw: str, registry: EvidenceRegistry) -> tuple[str, bool]:
    """Turn an MCP tool's JSON into the text the model sees, registering evidence. Returns (text, is_error)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return f"Tool returned unreadable output: {raw[:200]}", True
    if "error" in data:
        return f"Error: {data['error']}", True
    if tool == "get_account":
        cid = data.get("customer_id")
        if not data.get("found"):
            n = registry.add(f"account:{cid}:missing", {"kind": "account", "customer_id": cid, "found": False,
                                                        "text": json.dumps(data)})
            return f"E{n} | account lookup {cid}: no account record exists for this customer number.", False
        record = {k: v for k, v in data.items() if k != "found"}
        n = registry.add(f"account:{cid}", {"kind": "account", "customer_id": cid, "found": True,
                                            "record": record, "text": json.dumps(record, indent=1)})
        return f"E{n} | account record for {cid}\n{json.dumps(record, indent=1)}", False
    kind = "regulation" if tool == "search_regulation" else "policy"
    outcome = data.get("outcome") if kind == "regulation" else None
    lines = [f"Regulation search for outcome: {outcome}"] if outcome else []
    for r in data.get("results", []):
        n = registry.add(f"node:{r['node_id']}", {"kind": kind, "file_name": r["file_name"],
                                                  "page_label": r.get("page_label"), "node_id": r["node_id"],
                                                  "similarity": r["similarity"], "text": r["text"]}, outcome)
        page = f" p.{r['page_label']}" if r.get("page_label") else ""
        lines.append(f"E{n} | {r['file_name']}{page} | similarity {r['similarity']:.4f}\n{r['text']}")
    return ("\n\n".join(lines) if len(lines) > (1 if outcome else 0) else "No passages found."), False


def tool_limit(tool: str) -> int:
    return config.AGENT_CALL_LIMIT_BY_TOOL.get(tool, config.AGENT_MAX_CALLS_PER_TOOL)


def _malformed(arguments: Any) -> bool:
    """The placeholder-wrapped argument shape seen in 49 judge retries (ARCHITECTURE.md known limitation)."""
    return isinstance(arguments, dict) and len(arguments) == 1 and next(iter(arguments)).startswith("$PARAMETER")


# --- the loop ---

class ToolAgent:
    def __init__(self, client=None, session_factory=None, model: str = config.ANTHROPIC_MODEL,
                 review_date: str = config.AGENT_REVIEW_DATE):
        if client is None:
            from anthropic import Anthropic

            client = Anthropic()
        self._client = client
        self._session_factory = session_factory or _mcp_session
        self._model = model
        self._review_date = review_date

    def run(self, document_text: str) -> dict:
        return asyncio.run(self._run(document_text))

    def run_many(self, items, before=None, after=None) -> None:
        """
        Several documents through ONE MCP server (it loads the embedding model once, ~16 s, instead
        of once per document). Each document is still a separate run: its own messages, evidence
        numbers, call counts, limits and cache. The server holds no per-run state.
        items: iterable of (key, document_text). before(key) runs first (e.g. set the audit context);
        after(key, result, error) receives each result, or the exception that ended that run.
        """
        asyncio.run(self._run_many(list(items), before, after))

    async def _run_many(self, items, before, after) -> None:
        async with self._session_factory() as session:
            tools = await self._tools(session)
            for key, text in items:
                if before:
                    before(key)
                try:
                    result = await self._start(session, tools, text)
                except Exception as exc:  # one document's failure must not end the batch
                    after(key, None, exc)
                    continue
                after(key, result, None)

    async def _run(self, document_text: str) -> dict:
        async with self._session_factory() as session:
            return await self._start(session, await self._tools(session), document_text)

    async def _tools(self, session) -> list[dict]:
        listed = await session.list_tools()
        tools = [{"name": t.name, "description": t.description, "input_schema": t.inputSchema}
                 for t in listed.tools] + [submit_tool_definition()]
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        return tools

    async def _start(self, session, tools: list[dict], document_text: str) -> dict:
        audit.event("agent", "start", data={"tools": [t["name"] for t in tools], "limits": _limits(),
                                            "document_sha256": audit.sha256_text(document_text)})
        return await self._loop(session, tools, document_text)

    async def _loop(self, session, tools: list[dict], document_text: str) -> dict:
        system = [{"type": "text", "cache_control": {"type": "ephemeral"}, "text": SYSTEM_PROMPT.format(
            review_date=self._review_date, max_calls=config.AGENT_MAX_TOOL_CALLS,
            recent_months=config.AGENT_RECENT_WINDOW_MONTHS, max_turns=config.AGENT_MAX_TURNS,
            max_per_tool=config.AGENT_MAX_CALLS_PER_TOOL,
            max_regulation=tool_limit("search_regulation"))}]
        messages: list[dict] = [{"role": "user", "content": f"Loan agreement under review:\n\n{document_text}"}]
        registry = EvidenceRegistry()
        calls: list[dict] = []
        per_tool: dict[str, int] = {}
        cache: dict[str, tuple[str, bool]] = {}
        stop = {"reason": None, "detail": None}
        assessment = None
        turns = 0
        while turns < config.AGENT_MAX_TURNS:
            turns += 1
            request = {"system": system, "messages": messages}
            t0 = time.time()
            response = self._client.messages.create(
                model=self._model, max_tokens=config.AGENT_MAX_OUTPUT_TOKENS, tools=tools,
                tool_choice={"type": "auto"}, **request)
            audit.llm_call("agent", "agent_turn", response, kwargs=request, attempt=turns,
                           duration_ms=int((time.time() - t0) * 1000))
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "refusal":
                stop.update(reason="refusal", detail=str(getattr(response, "stop_details", None)))
                break
            uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            if not uses:
                if response.stop_reason == "max_tokens":
                    note = "Your response was cut off. Call submit_assessment now, with shorter reasoning."
                else:
                    note = "Call submit_assessment now with your final assessment."
                messages.append({"role": "user", "content": note})
                continue
            results = []
            for use in uses:
                if use.name == SUBMIT_TOOL:
                    try:
                        if _malformed(use.input):
                            raise ValueError("arguments were wrapped in a placeholder key")
                        assessment = AgentAssessment.model_validate(use.input)
                        results.append({"type": "tool_result", "tool_use_id": use.id, "content": "Received."})
                    except (ValidationError, ValueError) as exc:
                        audit.event("agent", "retry", level="warn", data={"tool": SUBMIT_TOOL, "error": str(exc)[:2000]})
                        results.append({"type": "tool_result", "tool_use_id": use.id, "is_error": True,
                                        "content": f"The assessment did not match the schema: {str(exc)[:1500]}"})
                    continue
                if len(calls) >= config.AGENT_MAX_TOOL_CALLS or per_tool.get(use.name, 0) >= tool_limit(use.name):
                    which = "total" if len(calls) >= config.AGENT_MAX_TOOL_CALLS else f"per-tool ({use.name})"
                    stop.update(reason="limit", detail=f"{which} tool-call limit reached")
                    audit.event("agent", "limit", level="warn", data={"limit": which, "tool": use.name,
                                                                      "calls_so_far": len(calls)})
                    break
                key = f"{use.name}:{json.dumps(use.input, sort_keys=True)}"
                cached = key in cache
                if _malformed(use.input):
                    text, is_error = "Error: arguments were wrapped in a placeholder key; send the real arguments.", True
                elif cached:
                    text, is_error = cache[key]
                else:
                    t1 = time.time()
                    raw = await _call(session, use.name, use.input)
                    text, is_error = format_tool_result(use.name, raw, registry)
                    cache[key] = (text, is_error)
                per_tool[use.name] = per_tool.get(use.name, 0) + 1
                record = {"n": len(calls) + 1, "turn": turns, "tool": use.name, "arguments": use.input,
                          "cached": cached, "is_error": is_error,
                          "evidence": [int(m) for m in re.findall(r"^E(\d+) \|", text, re.M)]}
                calls.append(record)
                audit.event("agent", "tool_call", level="warn" if is_error else "info", data={
                    **record, "result_sha256": audit.sha256_text(text), "result_chars": len(text),
                    "count": len(calls), "count_for_tool": per_tool[use.name]})
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": text, "is_error": is_error})
            if stop["reason"]:
                break
            if assessment is not None:
                messages.append({"role": "user", "content": results})
                break
            messages.append({"role": "user", "content": results})
        if assessment is None and stop["reason"] is None:
            stop.update(reason="turn_limit", detail=f"no assessment after {config.AGENT_MAX_TURNS} turns")
            audit.event("agent", "limit", level="warn", data={"limit": "turns", "turns": turns})
        return validate_run(document_text, assessment, registry, calls, turns, stop, self._review_date)


async def _call(session, name: str, arguments: dict) -> str:
    result = await session.call_tool(name, arguments)
    text = "".join(getattr(b, "text", "") for b in result.content if getattr(b, "type", None) == "text")
    if getattr(result, "isError", False):
        return json.dumps({"error": text or "tool error"})
    return text


def _limits() -> dict:
    return {"max_tool_calls": config.AGENT_MAX_TOOL_CALLS, "max_calls_per_tool": config.AGENT_MAX_CALLS_PER_TOOL,
            "call_limit_by_tool": dict(config.AGENT_CALL_LIMIT_BY_TOOL),
            "max_turns": config.AGENT_MAX_TURNS}


def _mcp_session():
    """A stdio session to src/mcp_server/agent_server.py (one subprocess per run)."""
    from contextlib import asynccontextmanager

    import os

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import get_default_environment, stdio_client

    # The stdio client passes only a minimal default environment to the server, so settings the
    # server reads must be forwarded explicitly. The API key is deliberately not forwarded: the
    # server makes no model calls.
    env = get_default_environment()
    env.update({k: v for k, v in os.environ.items() if k in SERVER_ENV_ALLOWLIST})
    params = StdioServerParameters(command=sys.executable, args=["-m", "src.mcp_server.agent_server"],
                                   cwd=str(config.PROJECT_ROOT), env=env)

    @asynccontextmanager
    async def session():
        # The server's stderr goes to a file, never to a pipe: when stderr is a pipe nobody reads
        # (pytest capture, a background job), the embedding model's progress output fills the pipe
        # buffer and the server blocks forever. Found by the integration test, 2026-10-13.
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.LOG_DIR / "agent_server_stderr.log", "a", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as s:
                    await s.initialize()
                    yield s

    return session()


if __name__ == "__main__":
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("Usage: python -m src.agent.tool_agent <path-to-document> [--log-payloads]")
        raise SystemExit(1)
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    audit.start_run("tool agent", settings={"document": sys.argv[1], **_limits()},
                    log_payloads="--log-payloads" in sys.argv[2:])
    audit.set_context(doc_id=Path(sys.argv[1]).stem)
    status = "failed"
    try:
        result = ToolAgent().run(text)
        status = "completed"
    finally:
        audit.end_run(status)
    print(json.dumps(result, indent=2, default=str))

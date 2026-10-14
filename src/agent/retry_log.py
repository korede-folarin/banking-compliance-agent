"""
Observe-only logging of why instructor structured calls retry (Session 26).

Instructor re-asks the model when a response fails validation, but records
nothing about why, so retries could only be inferred from request counts.
`attach(client, call_site)` registers two instructor hooks on a client:

  completion:response  remembers the raw response of the latest attempt
  parse:error          appends one JSON line per failed attempt: call site,
                       current context (e.g. doc_id, run_idx, outcome),
                       attempt number, error type and message, and facts
                       about the response that failed: stop_reason, output
                       tokens, content-block types, tool_use count and names

The handlers only read. They never touch the call's arguments or return
value, they are called by instructor after the API call, and any exception
inside them is swallowed here (instructor would also turn it into a
warning), so attaching them cannot change what a call sends or returns.

Logging is OFF unless a path is set with `set_path()` (run_eval.py's `main`
sets `<output stem>_retries.jsonl`), so ordinary runs and tests write
nothing.

Audit log (docs/audit_logging_design.md): the same hooks, plus
`completion:kwargs`, also send every model request (`llm_call`: tokens,
stop reason, request id, prompt hash) and every failed attempt (`retry`) to
src/monitoring/audit.py when an audit run is active. Still observe-only. The
retries file above is kept as it was, so existing readers are unaffected.
"""

import json
import time
from pathlib import Path
from typing import Any

from src.monitoring import audit

# Audit-log stage for each call site; anything else logs under its own name.
STAGE_BY_CALL_SITE = {"judge": "judgment", "mcp_judge": "judgment", "extraction": "extraction"}

_path: Path | None = None
_context: dict[str, Any] = {}


def set_path(path: Path | str | None) -> None:
    """Where to append retry records; None turns logging off."""
    global _path
    _path = Path(path) if path else None


def set_context(**fields: Any) -> None:
    """Replace the context fields stamped on every record (e.g. doc_id, run_idx)."""
    _context.clear()
    _context.update(fields)


def update_context(**fields: Any) -> None:
    """Add or change context fields (e.g. the outcome being judged)."""
    _context.update(fields)


def _describe(response: Any) -> dict:
    blocks = list(getattr(response, "content", None) or [])
    usage = getattr(response, "usage", None)
    tool_uses = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
    return {
        "stop_reason": getattr(response, "stop_reason", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "content_block_types": [getattr(b, "type", None) for b in blocks],
        "tool_use_count": len(tool_uses),
        "tool_names": [getattr(b, "name", None) for b in tool_uses],
    }


def attach(client: Any, call_site: str) -> Any:
    """Register the observe-only hooks on an instructor client and return it unchanged."""
    if not hasattr(client, "on"):  # e.g. a test double; nothing to attach to
        return client
    last: dict[str, Any] = {}
    stage = STAGE_BY_CALL_SITE.get(call_site, call_site)

    def on_kwargs(*args: Any, **kwargs: Any) -> None:
        try:
            last["kwargs"], last["t0"] = kwargs, time.time()
            # A new request is attempt 1 unless the previous attempt failed validation.
            last["attempt"] = last.get("attempt", 0) + 1 if last.pop("retrying", False) else 1
        except Exception:
            pass

    def on_response(response: Any) -> None:
        last["response"] = response
        try:
            t0 = last.get("t0")
            audit.llm_call(stage, call_site, response, kwargs=last.get("kwargs"), attempt=last.get("attempt"),
                           duration_ms=int((time.time() - t0) * 1000) if t0 else None)
        except Exception:
            pass  # observation must never affect the call

    def on_parse_error(error: Exception, **meta: Any) -> None:
        last["retrying"] = not meta.get("is_last_attempt")  # after the last attempt, the next request is a new call
        try:
            audit.event(stage, "retry", level="warn", component=f"src/agent/retry_log.py:{call_site}", data={
                "call_site": call_site, "attempt_number": meta.get("attempt_number"),
                "is_last_attempt": meta.get("is_last_attempt"), "error_type": type(error).__name__,
                "error": str(error)[:3000], **_describe(last.get("response"))})
        except Exception:
            pass
        try:
            if _path is None:
                return
            record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "call_site": call_site,
                **_context,
                "attempt_number": meta.get("attempt_number"),
                "is_last_attempt": meta.get("is_last_attempt"),
                "error_type": type(error).__name__,
                "error": str(error)[:3000],
                **_describe(last.get("response")),
            }
            with open(_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception:
            pass  # observation must never affect the call

    client.on("completion:kwargs", on_kwargs)
    client.on("completion:response", on_response)
    client.on("parse:error", on_parse_error)
    return client

"""
Audit log: one JSON line per event, one file per run (docs/audit_logging_design.md).

Logging is OFF until `start_run()` is called, so library use and tests write
nothing unless they ask to. Entry points (run_eval main, ingestion, the
compliance CLI) start a run; pipeline code calls `event()`, `check()` and
`llm_call()`, which do nothing when no run is active.

Layout:  LOG_DIR/<YYYY-MM-DD>/<run_id>.jsonl   the run's events
         LOG_DIR/<YYYY-MM-DD>/<run_id>_payloads.jsonl   prompt text, only with log_payloads
         LOG_DIR/index.jsonl                    one line per finished run

Every event passes through `redact()` before it is written. Writing never
raises into the caller: a logging failure must not change what a run does.
"""

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import config

SCHEMA_VERSION = 1
LEVELS = ("info", "warn", "error")
SETTINGS_ALLOWLIST = (
    "ANTHROPIC_MODEL", "CONFIDENCE_THRESHOLD", "QUERY_SIMILARITY_TOP_K", "EMBED_MODEL_NAME",
    "CHUNK_SIZE", "CHUNK_OVERLAP", "CHROMA_COLLECTION_NAME", "CHROMA_PERSIST_DIR",
)
PACKAGES = ("anthropic", "instructor", "llama-index-core", "chromadb", "pydantic", "mcp")
SECRET_MARKERS = ("sk-ant",)

_run: dict | None = None
_context: dict[str, Any] = {}


# --- redaction ---

def _home_prefixes() -> list[str]:
    home = str(Path.home())
    return sorted({home, home.replace("\\", "/")}, key=len, reverse=True)


def _redact_str(s: str) -> str:
    for root in (str(config.PROJECT_ROOT), str(config.PROJECT_ROOT).replace("\\", "/")):
        s = s.replace(root + "\\", "").replace(root + "/", "").replace(root, ".")
    for home in _home_prefixes():
        s = s.replace(home, "<USER_HOME>")
    return s


def redact(obj: Any) -> Any:
    """Paths relative to the repo, the home folder as <USER_HOME>, recursively."""
    if isinstance(obj, str):
        return _redact_str(obj)
    if isinstance(obj, Path):
        return _redact_str(str(obj))
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- run lifecycle ---

def active() -> bool:
    return _run is not None


def run_id() -> str | None:
    return _run["run_id"] if _run else None


def _git() -> dict:
    def git(*args):
        out = subprocess.run(["git", *args], cwd=config.PROJECT_ROOT, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    try:
        return {"git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain"))}
    except Exception:
        return {"git_commit": None, "git_dirty": None}


def _settings(extra: dict | None) -> dict:
    s = {k: getattr(config, k) for k in SETTINGS_ALLOWLIST}
    # Read at call time (it can change), but only if the query engine is already loaded: importing it
    # pulls in the ML stack (~90 s cold), which a run that does no retrieval (e.g. the review app)
    # must not pay for.
    query_engine = sys.modules.get("src.retrieval.query_engine")
    s["SOURCE_EXCERPT_CHARS"] = query_engine.SOURCE_EXCERPT_CHARS if query_engine else "not loaded"
    s.update(extra or {})
    return s


def _versions() -> dict:
    v = {"python": platform.python_version()}
    for p in PACKAGES:
        try:
            v[p] = importlib.metadata.version(p)
        except Exception:
            v[p] = None
    return v


def start_run(command: str, *, settings: dict | None = None, corpus: dict | None = None,
              overrides: list[str] | None = None, log_dir: Path | str | None = None,
              log_payloads: bool = False) -> str:
    """Start logging; writes the run header. Returns the run_id."""
    global _run
    base = Path(log_dir) if log_dir else config.LOG_DIR
    if (config.PROJECT_ROOT / "docs").resolve() in [base.resolve(), *base.resolve().parents]:
        raise ValueError(f"Refusing to write audit logs inside docs/: {base}")
    rid = str(uuid.uuid4())
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = base / day / f"{rid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved = _settings(settings)
    _run = {
        "run_id": rid, "command": command, "base": base, "path": path,
        "payloads_path": path.with_name(f"{rid}_payloads.jsonl") if log_payloads else None,
        "started": time.time(), "started_ts": _now(),
        "levels": {lvl: 0 for lvl in LEVELS}, "failed_checks": [], "overrides": list(overrides or []),
        "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}, "llm_calls": 0,
        "model": resolved.get("ANTHROPIC_MODEL"),
    }
    _context.clear()
    event("run", "start", data={
        "command": command, **_git(), "settings": resolved,
        "settings_sha256": sha256_text(json.dumps(redact(resolved), sort_keys=True, default=str)),
        "corpus": corpus or {}, "versions": _versions(), "overrides": list(overrides or []),
        "log_payloads": bool(log_payloads), "argv": sys.argv[1:],
    })
    return rid


def end_run(status: str = "completed") -> None:
    """Write the end event and the index line, then stop logging."""
    global _run
    if not _run:
        return
    r = _run
    cost = _estimate_cost(r["model"], r["tokens"])
    event("run", "end", data={
        "status": status, "levels": dict(r["levels"]), "failed_checks": list(r["failed_checks"]),
        "llm_calls": r["llm_calls"], "tokens": dict(r["tokens"]), "estimated_cost_usd": cost,
    }, duration_ms=int((time.time() - r["started"]) * 1000))
    try:
        log = r["path"].relative_to(r["base"]).as_posix()
    except ValueError:
        log = _redact_str(str(r["path"]))
    _append(r["base"] / "index.jsonl", {
        "run_id": r["run_id"], "command": r["command"], "status": status,
        "started": r["started_ts"], "ended": _now(), "log": log,
        "levels": dict(r["levels"]), "failed_checks": [c["name"] for c in r["failed_checks"]],
        "overrides": r["overrides"], "estimated_cost_usd": cost,
    })
    _run = None
    _context.clear()


def set_context(**fields: Any) -> None:
    """Replace the doc_id / run_idx / outcome stamped on later events."""
    _context.clear()
    _context.update({k: v for k, v in fields.items() if v is not None})


def update_context(**fields: Any) -> None:
    _context.update({k: v for k, v in fields.items() if v is not None})


# --- events ---

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _caller(depth: int) -> str:
    try:
        f = sys._getframe(depth)
        return f"{_redact_str(f.f_code.co_filename).replace(chr(92), '/')}:{f.f_code.co_name}"
    except Exception:
        return "unknown"


def event(stage: str, event: str, *, level: str = "info", data: dict | None = None,
          duration_ms: int | None = None, component: str | None = None, **ctx: Any) -> None:
    """Write one event. Does nothing when no run is active."""
    if not _run:
        return
    record = {
        "schema_version": SCHEMA_VERSION, "ts": _now(), "run_id": _run["run_id"],
        "stage": stage, "event": event, "level": level if level in LEVELS else "info",
        "component": component or _caller(2),
        **{k: v for k, v in {**_context, **ctx}.items() if k in ("doc_id", "run_idx", "outcome")},
    }
    if duration_ms is not None:
        record["duration_ms"] = duration_ms
    record["data"] = data or {}
    _write(record)


def check(stage: str, name: str, passed: bool | None, *, metric: Any = None, threshold: Any = None,
          action: str = "warn", data: dict | None = None, **ctx: Any) -> bool | None:
    """
    Log a check whether it passes or fails, so a missing check is visible.
    passed=None means not applicable (logged, not counted as a failure).
    action: none | warn | block | route_to_review. A failed `block` check is
    logged at error, any other failure at warn. Returns `passed`.
    """
    level = "info" if passed or passed is None else ("error" if action == "block" else "warn")
    if passed is False and _run:
        _run["failed_checks"].append({"stage": stage, "name": name, "action": action})
    event(stage, "check", level=level, component=_caller(2), data={
        "name": name, "passed": passed, "metric": metric, "threshold": threshold,
        "action": action if passed is False else "none", **(data or {}),
    }, **ctx)
    return passed


def _usage(response: Any) -> dict:
    u = getattr(response, "usage", None)
    get = lambda k: getattr(u, k, None) or 0  # noqa: E731
    return {"input": get("input_tokens"), "output": get("output_tokens"),
            "cache_read": get("cache_read_input_tokens"), "cache_write": get("cache_creation_input_tokens")}


def prompt_hash(kwargs: dict | None) -> str | None:
    if not kwargs:
        return None
    parts = {k: kwargs.get(k) for k in ("system", "messages") if k in kwargs}
    return sha256_text(json.dumps(parts, sort_keys=True, default=str)) if parts else None


def llm_call(stage: str, call_site: str, response: Any, *, kwargs: dict | None = None,
             attempt: int | None = None, duration_ms: int | None = None) -> None:
    """One model request: model, request id, tokens, stop reason, tool names, prompt hash."""
    if not _run:
        return
    usage = _usage(response)
    for k, v in usage.items():
        _run["tokens"][k] += v
    _run["llm_calls"] += 1
    blocks = list(getattr(response, "content", None) or [])
    ph = prompt_hash(kwargs)
    event(stage, "llm_call", component=_caller(2), duration_ms=duration_ms, data={
        "call_site": call_site, "model": getattr(response, "model", None),
        "request_id": getattr(response, "_request_id", None) or getattr(response, "id", None),
        "tokens": usage, "stop_reason": getattr(response, "stop_reason", None), "attempt": attempt,
        "tool_names": [getattr(b, "name", None) for b in blocks if getattr(b, "type", None) == "tool_use"],
        "prompt_sha256": ph,
    })
    if _run["payloads_path"] and kwargs:
        _append(_run["payloads_path"], redact({
            "ts": _now(), "run_id": _run["run_id"], "call_site": call_site, "prompt_sha256": ph,
            **{k: v for k, v in _context.items() if k in ("doc_id", "run_idx", "outcome")},
            "system": kwargs.get("system"), "messages": kwargs.get("messages"),
            "response": [b.model_dump() if hasattr(b, "model_dump") else str(b) for b in blocks],
        }))


def _estimate_cost(model: str | None, tokens: dict) -> float | None:
    price = config.PRICE_PER_MTOK.get(model or "")
    if not price:
        return None
    pin, pout = price
    usd = (tokens["input"] * pin + tokens["cache_read"] * pin * 0.1 + tokens["cache_write"] * pin * 1.25
           + tokens["output"] * pout) / 1_000_000
    return round(usd, 4)


# --- writing ---

def _append(path: Path, record: dict) -> None:
    try:
        line = json.dumps(record, default=str, ensure_ascii=False)
        if any(m in line for m in SECRET_MARKERS):
            line = json.dumps({"ts": _now(), "run_id": record.get("run_id"), "stage": "run",
                               "event": "redaction", "level": "warn",
                               "data": {"dropped": "an event containing a secret marker was not written"}})
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # logging must never change what a run does


def _write(record: dict) -> None:
    record = redact(record)
    if record["level"] in _run["levels"]:
        _run["levels"][record["level"]] += 1
    _append(_run["path"], record)

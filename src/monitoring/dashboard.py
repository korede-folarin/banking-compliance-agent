"""
Monitoring dashboard data (P9-02): failure rate, flagged rate and latency over time, read from the
audit log (LOG_DIR/index.jsonl and each run's JSONL). Zero API cost; the log is the only source, so
every number can be traced to a logged event.

Two levels:
- commands: one per audit run (an evaluation pass, an ingestion check, the review app...);
- agent document runs: one per (document, run) inside an agent evaluation, from the agent's start
  and end events. Latency is end minus start for that document.

Rehearsal runs (agent_eval run --dry-run) are marked, so the page can leave them out.
"""

import json
import statistics
from datetime import datetime
from pathlib import Path

from src import config

OK_STATUSES = ("completed",)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a partly written last line must not break the page
    return out


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load(log_dir: Path | None = None) -> tuple[list[dict], list[dict]]:
    """(commands, agent document runs) from the audit log."""
    base = Path(log_dir or config.LOG_DIR)
    commands, docs = [], []
    for row in _read(base / "index.jsonl"):
        events = _read(base / row["log"])
        header = next((e for e in events if e.get("stage") == "run" and e.get("event") == "start"), {})
        argv = (header.get("data") or {}).get("argv") or []
        rehearsal = "--dry-run" in argv
        commands.append({
            "run_id": row["run_id"], "command": row["command"], "status": row["status"],
            "day": row["started"][:10], "started": row["started"],
            "duration_s": round((_ts(row["ended"]) - _ts(row["started"])).total_seconds(), 1),
            "cost_usd": row.get("estimated_cost_usd") or 0.0, "failed_checks": len(row.get("failed_checks") or []),
            "errors": (row.get("levels") or {}).get("error", 0), "rehearsal": rehearsal})
        starts, failed = {}, set()
        for e in events:
            key = (e.get("doc_id"), e.get("run_idx"))
            if e.get("stage") == "agent" and e.get("event") == "start":
                starts[key] = e["ts"]
            elif e.get("stage") == "evaluation" and e.get("event") == "error" and key[0]:
                failed.add(key)
                docs.append({"run_id": row["run_id"], "day": e["ts"][:10], "doc_id": key[0], "run_idx": key[1],
                             "failed": True, "flagged": None, "flagged_beyond_policy": None, "latency_s": None,
                             "rehearsal": rehearsal})
            elif e.get("stage") == "agent" and e.get("event") == "end" and key not in failed:
                d = e.get("data") or {}
                reasons = d.get("review_reasons") or []
                docs.append({
                    "run_id": row["run_id"], "day": e["ts"][:10], "doc_id": key[0], "run_idx": key[1], "failed": False,
                    "flagged": bool(d.get("needs_human_review")),
                    # Flagged for a reason other than "auto-approval disabled"; None where the reasons
                    # were not logged (runs before 2026-10-24).
                    "flagged_beyond_policy": (any(not r.startswith("auto-approval disabled") for r in reasons)
                                              if "review_reasons" in d else None),
                    "latency_s": round((_ts(e["ts"]) - _ts(starts[key])).total_seconds(), 1) if key in starts else None,
                    "rehearsal": rehearsal})
    return commands, docs


SNAPSHOT = config.PROJECT_ROOT / "docs" / "monitoring_snapshot.json"


def write_snapshot(path: Path = SNAPSHOT, log_dir: Path | None = None) -> Path:
    """
    A committed summary of the audit log for the hosted demo, where logs/ (gitignored) does not exist.
    Holds only what the page shows: per-run status, duration and cost, and per-document latency and
    flags. No settings, paths, prompts or reviewer names.
    """
    commands, docs = load(log_dir)
    taken = max((c["started"] for c in commands), default=None)
    path.write_text(json.dumps({"taken_at": taken, "commands": commands, "docs": docs}, indent=1) + "\n",
                    encoding="utf-8")
    return path


def load_or_snapshot(log_dir: Path | None = None) -> tuple[list[dict], list[dict], str | None]:
    """The live audit log if it has runs; otherwise the committed snapshot. Third value: snapshot time or None."""
    commands, docs = load(log_dir)
    if commands or not SNAPSHOT.exists():
        return commands, docs, None
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return snap["commands"], snap["docs"], snap["taken_at"]


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def by_day(commands: list[dict], docs: list[dict], include_rehearsal: bool = False) -> list[dict]:
    """One row per day: command and document counts, failure and flagged rates, latency, cost."""
    commands = [c for c in commands if include_rehearsal or not c["rehearsal"]]
    docs = [d for d in docs if include_rehearsal or not d["rehearsal"]]
    out = []
    for day in sorted({c["day"] for c in commands} | {d["day"] for d in docs}):
        cs = [c for c in commands if c["day"] == day]
        ds = [d for d in docs if d["day"] == day]
        done = [d for d in ds if not d["failed"]]
        lat = sorted(d["latency_s"] for d in done if d["latency_s"] is not None)
        known = [d for d in done if d["flagged_beyond_policy"] is not None]
        out.append({
            "day": day, "commands": len(cs),
            "command_failure_rate": _rate(sum(c["status"] not in OK_STATUSES for c in cs), len(cs)),
            "agent_documents": len(ds),
            "document_failure_rate": _rate(sum(d["failed"] for d in ds), len(ds)),
            "flagged_rate": _rate(sum(d["flagged"] for d in done), len(done)),
            "flagged_beyond_policy_rate": _rate(sum(d["flagged_beyond_policy"] for d in known), len(known)),
            "median_latency_s": round(statistics.median(lat), 1) if lat else None,
            "p90_latency_s": lat[min(len(lat) - 1, int(0.9 * len(lat)))] if lat else None,
            "cost_usd": round(sum(c["cost_usd"] for c in cs), 4),
        })
    return out

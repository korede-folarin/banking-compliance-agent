"""
Human review decisions (P7-01): "flagged issues require explicit human approval before marked
resolved". The rules live here, not in the screen, so no caller can skip them:

  - every decision names a reviewer;
  - a decision on an item is either `confirm` (agree with the system's verdict) or `override`
    (a different verdict from the item's allowed list, with a written reason);
  - a case can be marked resolved only when every one of its items has an explicit decision;
  - nothing is deleted or edited: decisions are appended, the latest per item counts, and the
    full history stays readable;
  - every decision is also written to the audit log (stage "review").

Storage: REVIEW_DIR/decisions.jsonl (default ./reviews/, gitignored: it holds reviewer names).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.monitoring import audit
from src.review.cases import Case

ACTIONS = ("confirm", "override")


class ReviewError(ValueError):
    """A decision that breaks a review rule; nothing was written."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class DecisionStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.REVIEW_DIR / "decisions.jsonl"

    def history(self, case_id: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [r for r in rows if case_id is None or r["case_id"] == case_id]

    def current(self, case_id: str) -> dict[str, dict]:
        """Latest decision per item for a case (resolution records excluded)."""
        out = {}
        for r in self.history(case_id):
            if r["action"] in ACTIONS:
                out[r["item_id"]] = r
        return out

    def is_resolved(self, case_id: str) -> bool:
        return any(r["action"] == "resolve" for r in self.history(case_id))

    def outstanding(self, case: Case) -> list[str]:
        decided = self.current(case.case_id)
        return [i.item_id for i in case.items if i.item_id not in decided]

    def _append(self, record: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        audit.event("review", record["action"], data={k: v for k, v in record.items() if k != "reviewer"}
                    | {"reviewer_given": bool(record.get("reviewer"))})
        return record

    def decide(self, case: Case, item_id: str, action: str, reviewer: str,
               verdict: str | None = None, reason: str = "") -> dict:
        reviewer, reason = (reviewer or "").strip(), (reason or "").strip()
        if not reviewer:
            raise ReviewError("a reviewer name is required")
        if self.is_resolved(case.case_id):
            raise ReviewError("this case is already resolved; decisions can no longer change")
        item = next((i for i in case.items if i.item_id == item_id), None)
        if item is None:
            raise ReviewError(f"case {case.case_id} has no item {item_id!r}")
        if action not in ACTIONS:
            raise ReviewError(f"action must be one of {ACTIONS}")
        if action == "confirm":
            if item.system_verdict is None:
                raise ReviewError("there is no system verdict to confirm; override with a verdict instead")
            verdict = item.system_verdict
        else:
            if verdict not in item.allowed_verdicts:
                raise ReviewError(f"verdict must be one of {item.allowed_verdicts}")
            if verdict == item.system_verdict:
                raise ReviewError("an override must change the verdict; use confirm to agree")
            if not reason:
                raise ReviewError("an override needs a written reason")
        return self._append({"ts": _now(), "case_id": case.case_id, "source": case.source, "doc_id": case.doc_id,
                             "run_idx": case.run_idx, "item_id": item_id, "action": action,
                             "system_verdict": item.system_verdict, "reviewer_verdict": verdict,
                             "reason": reason, "reviewer": reviewer})

    def resolve(self, case: Case, reviewer: str, note: str = "") -> dict:
        reviewer = (reviewer or "").strip()
        if not reviewer:
            raise ReviewError("a reviewer name is required")
        if self.is_resolved(case.case_id):
            raise ReviewError("this case is already resolved")
        missing = self.outstanding(case)
        if missing:
            raise ReviewError(f"cannot resolve: no decision yet on {', '.join(missing)}")
        decisions = self.current(case.case_id)
        return self._append({"ts": _now(), "case_id": case.case_id, "source": case.source, "doc_id": case.doc_id,
                             "run_idx": case.run_idx, "item_id": None, "action": "resolve",
                             "overrides": sum(d["action"] == "override" for d in decisions.values()),
                             "reason": (note or "").strip(), "reviewer": reviewer})

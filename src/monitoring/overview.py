"""
Compliance overview for the dashboard: plain-language numbers a compliance manager can read without
knowing how the system works. Built from the saved results in docs/ (committed, so it also works on
the hosted demo), the known answers for the synthetic test documents, and the review decisions.

Counting rules, stated on the page:
- "Agreements" counts each document once, by its first review (run 0).
- "How reliable" uses every run, and the system's own verdict before any safety rule replaced it.
"""

import json
from collections import Counter

from src import config
from src.review.cases import DEFAULT_SOURCES, OUTCOMES, OUTCOME_NAMES

SYSTEMS = {
    "AI agent (chooses its own tools)": ["agent v2", "agent v1"],
    "Fixed workflow (baseline)": ["baseline"],
}
PLAIN = {
    "compliant": "Looks compliant",
    "potentially_non_compliant": "Possible breach",
    "insufficient_evidence": "Not enough evidence",
    "not_applicable": "Not applicable",
    None: "No answer",
}
PLAIN_ESCALATION = {
    "escalate": "Escalate: vulnerable customer",
    "no_escalation": "No escalation needed",
    "cannot_determine": "Can't tell: a person must check",
    "not_applicable": "Not applicable",
    None: "No answer",
}
NEEDS_A_PERSON = ("potentially_non_compliant", "insufficient_evidence")


def _read_jsonl(path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _labels() -> dict[str, dict]:
    """Known answers per document: {doc_id: {"ground_truth": {...}, "escalation": str | None}}."""
    from tests.fixtures.eval_set import EVAL_DOCUMENTS

    out = {d["id"]: {"ground_truth": d["ground_truth"], "escalation": None} for d in EVAL_DOCUMENTS}
    for name in ("eval_set_v2.json", "eval_set_v1_agent.json"):
        path = config.PROJECT_ROOT / "tests" / "fixtures" / name
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for d in raw["documents"] if isinstance(raw, dict) else raw:
                out[d["doc_id"]] = {"ground_truth": d["ground_truth"],
                                    "escalation": (d.get("expected_escalation") or {}).get("decision")}
    return out


def rows_for(system: str, sources: dict | None = None) -> list[dict]:
    srcs = sources or DEFAULT_SOURCES
    rows = []
    for name in SYSTEMS[system]:
        for r in _read_jsonl(srcs[name]) if name in srcs else []:
            if r.get("model") == "rehearsal":
                continue
            rows.append({**r, "_source": name})
    return rows


def summary(system: str, store=None, sources: dict | None = None) -> dict:
    rows = rows_for(system, sources)
    labels = _labels()
    first = [r for r in rows if r["run_idx"] == 0]
    out = {"agreements": len({(r["_source"], r["doc_id"]) for r in first}), "reviews": len(rows)}

    # What the system found: each agreement once, final verdict as a reviewer sees it.
    found = {OUTCOME_NAMES[k]: Counter(PLAIN.get(r["outcomes"][k]["status"], "No answer") for r in first)
             for k in OUTCOMES}
    out["found"] = found
    out["possible_breaches"] = sum(c["Possible breach"] for c in found.values())
    out["agreements_with_a_possible_breach"] = sum(
        any(r["outcomes"][k]["status"] == "potentially_non_compliant" for k in OUTCOMES) for r in first)
    out["agreements_needing_a_person"] = sum(
        any(r["outcomes"][k]["status"] in NEEDS_A_PERSON for k in OUTCOMES)
        or (r.get("escalation") or {}).get("decision") in ("escalate", "cannot_determine") for r in first)
    esc = [r for r in first if "escalation" in r]
    out["escalation"] = Counter(PLAIN_ESCALATION.get((r["escalation"] or {}).get("decision"), "No answer") for r in esc)

    # How reliable: every run, the system's own verdict, against the known answers.
    rel = {}
    for k in OUTCOMES:
        c = Counter()
        for r in rows:
            truth = labels.get(r["doc_id"], {}).get("ground_truth", {}).get(k)
            said = r["outcomes"][k].get("llm_status")
            if truth not in ("compliant", "non_compliant"):
                continue
            if said in (None, "insufficient_evidence"):
                c["unsure"] += 1
            elif truth == "non_compliant":
                c["caught" if said == "potentially_non_compliant" else "missed"] += 1
            else:
                c["false_alarm" if said == "potentially_non_compliant" else "correct_clear"] += 1
        rel[OUTCOME_NAMES[k]] = dict(c)
    out["reliability"] = rel
    out["real_problems"] = sum(v.get("caught", 0) + v.get("missed", 0) for v in rel.values())
    out["caught"] = sum(v.get("caught", 0) for v in rel.values())
    out["missed"] = sum(v.get("missed", 0) for v in rel.values())
    out["false_alarms"] = sum(v.get("false_alarm", 0) for v in rel.values())
    esc_known = [(labels.get(r["doc_id"], {}).get("escalation"), (r.get("escalation") or {}).get("decision"))
                 for r in rows if "escalation" in r and labels.get(r["doc_id"], {}).get("escalation")]
    out["escalation_right"] = (sum(a == b for a, b in esc_known), len(esc_known))

    # The people: what reviewers decided (this deployment's decisions only).
    if store is not None:
        prefix = tuple(f"{s}:" for s in SYSTEMS[system])
        decided = overridden = 0
        overrides = Counter()
        resolved = 0
        case_ids = {f"{r['_source']}:{r['doc_id']}:run{r['run_idx']}" for r in rows}
        for cid in case_ids:
            if not cid.startswith(prefix):
                continue
            for item_id, d in store.current(cid).items():
                decided += 1
                if d["action"] == "override":
                    overridden += 1
                    overrides[OUTCOME_NAMES.get(item_id, item_id)] += 1
            resolved += store.is_resolved(cid)
        out["people"] = {"cases": len(case_ids), "resolved": resolved, "decisions": decided,
                         "overrides": overridden, "overrides_by_outcome": dict(overrides)}
    return out

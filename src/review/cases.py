"""
Review cases (P7-01): turns saved pipeline rows into one shape the review screen and the
decision store use, whichever system produced them.

Sources:
  baseline  docs/eval_raw_main_pass_v2.jsonl: the fixed pipeline's full pass (real results)
  agent     docs/eval_agent_v2.jsonl, docs/eval_agent_v1.jsonl: the agentic tool loop
            (rows written by `agent_eval run`); a dry-run file can be loaded too and is
            labelled as a rehearsal

A case is one (document, run). Its items are the four Consumer Duty outcomes and, for agent
rows, the escalation decision. Every item carries what a reviewer needs: the system's
verdict, its confidence, the reasoning, the quoted claims with the passages they name, and
the reasons it was flagged. Labels (ground truth) are never shown to the reviewer.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from src import config

OUTCOMES = ("price_and_value", "consumer_support", "products_and_services", "consumer_understanding")
OUTCOME_NAMES = {"price_and_value": "Price and value", "consumer_support": "Consumer support",
                 "products_and_services": "Products and services", "consumer_understanding": "Consumer understanding",
                 "escalation": "Vulnerable-customer escalation"}
OUTCOME_VERDICTS = ("compliant", "potentially_non_compliant", "insufficient_evidence", "not_applicable")
ESCALATION_VERDICTS = ("escalate", "no_escalation", "cannot_determine", "not_applicable")
DEFAULT_SOURCES = {
    "baseline": config.PROJECT_ROOT / "docs" / "eval_raw_main_pass_v2.jsonl",
    "agent v2": config.PROJECT_ROOT / "docs" / "eval_agent_v2.jsonl",
    "agent v1": config.PROJECT_ROOT / "docs" / "eval_agent_v1.jsonl",
}


@dataclass
class Item:
    item_id: str                 # an outcome key, or "escalation"
    title: str
    system_verdict: str | None
    allowed_verdicts: tuple
    confidence: float | None
    below_reference: bool | None
    reasoning: str | None
    flags: list[str] = field(default_factory=list)          # why a reviewer should look at this item
    claims: list[dict] = field(default_factory=list)        # {claim, quote, passage_number, passage_text, file}
    quotes: list[dict] = field(default_factory=list)        # policy / note quotes (escalation)


@dataclass
class Case:
    case_id: str                 # "<source>:<doc_id>:run<n>"
    source: str
    doc_id: str
    run_idx: int
    document_file: Path | None
    rehearsal: bool
    case_reasons: list[str]
    items: list[Item]
    tool_calls: list[dict] = field(default_factory=list)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def _document_file(doc_id: str) -> Path | None:
    for p in (config.PROJECT_ROOT / "data" / "synthetic_docs" / f"{doc_id}.txt",
              config.PROJECT_ROOT / "data" / "fixtures_v2" / "docs" / f"{doc_id}.txt"):
        if p.exists():
            return p
    return None


def _claims(judgment: dict | None, passages: dict[int, dict]) -> list[dict]:
    out = []
    for req in (judgment or {}).get("regulatory_requirements", []):
        for s in req.get("sources", []):
            p = passages.get(s.get("excerpt_number"), {})
            out.append({"claim": req.get("claim"), "quote": s.get("verbatim_quote"),
                        "passage_number": s.get("excerpt_number"), "file": p.get("file_name"),
                        "passage_text": p.get("text")})
    for f in (judgment or {}).get("document_facts", []):
        out.append({"claim": f.get("claim"), "quote": f.get("verbatim_quote"), "passage_number": None,
                    "file": "the loan agreement", "passage_text": None})
    return out


def baseline_case(row: dict, source: str = "baseline") -> Case:
    items = []
    for key in OUTCOMES:
        o = row["outcomes"][key]
        passages = {s["index"]: {"file_name": s["file_name"], "text": s.get("text_excerpt")}
                    for s in o.get("retrieved_sources") or o.get("cited_sources") or []}
        flags = []
        if o["status"] in ("potentially_non_compliant", "insufficient_evidence"):
            flags.append(f"verdict: {o['status']}")
        if o["status"] != o["llm_status"]:
            flags.append(f"confidence {o['confidence']:.4f} below the 0.65 threshold replaced '{o['llm_status']}'")
        items.append(Item(key, OUTCOME_NAMES[key], o["status"], OUTCOME_VERDICTS, o.get("confidence"),
                          o.get("confidence", 1) < config.CONFIDENCE_THRESHOLD, o.get("reasoning"), flags,
                          _claims(o.get("judgment"), passages)))
    reasons = ["flagged by the baseline pipeline"] if row.get("needs_human_review") else []
    return Case(f"{source}:{row['doc_id']}:run{row['run_idx']}", source, row["doc_id"], row["run_idx"],
                _document_file(row["doc_id"]), False, reasons, items)


def agent_case(row: dict, source: str, rehearsal: bool = False) -> Case:
    evidence = {e["number"]: e for e in row.get("evidence", [])}
    passages = {n: {"file_name": e.get("file_name") or e.get("kind"), "text": e.get("text")} for n, e in evidence.items()}
    checks_by_outcome: dict[str, list[str]] = {}
    for c in row.get("checks", []):
        if c["passed"] is False:
            target = c.get("outcome") or (c["name"].split(":", 1)[1] if ":" in c["name"] else "case")
            checks_by_outcome.setdefault(target, []).append(f"check failed: {c['name'].split(':')[0]}")
    items = []
    for key in OUTCOMES:
        o = row["outcomes"][key]
        flags = [f"verdict: {o['status']}"] if o["status"] in ("potentially_non_compliant", "insufficient_evidence") else []
        flags += [f"forced: {r}" for r in o.get("forced_reasons") or []]
        flags += checks_by_outcome.get(key, [])
        items.append(Item(key, OUTCOME_NAMES[key], o["status"], OUTCOME_VERDICTS, o.get("confidence"),
                          o.get("below_reference_threshold"), o.get("reasoning"), flags,
                          _claims(o.get("judgment"), passages)))
    e = row.get("escalation") or {}
    quotes = [{"kind": "policy", "evidence_number": q["evidence_number"], "quote": q["verbatim_quote"],
               "passage_text": passages.get(q["evidence_number"], {}).get("text")} for q in e.get("policy_quotes", [])]
    quotes += [{"kind": f"account note {q['note_date']}", "evidence_number": q["evidence_number"],
                "quote": q["verbatim_quote"], "passage_text": None} for q in e.get("note_quotes", [])]
    esc_flags = [f"decision: {e.get('decision')}"] if e.get("decision") in ("escalate", "cannot_determine", None) else []
    esc_flags += [f"discrepancy: {d}" for d in e.get("discrepancies", [])]
    esc_flags += checks_by_outcome.get("case", [])
    items.append(Item("escalation", OUTCOME_NAMES["escalation"], e.get("decision"), ESCALATION_VERDICTS, None, None,
                      e.get("reasoning"), esc_flags, [], quotes))
    reasons = list(row.get("review_reasons") or (["flagged"] if row.get("needs_human_review") else []))
    if row.get("stop", {}).get("reason"):
        reasons.append(f"run stopped: {row['stop']['reason']}")
    return Case(f"{source}:{row['doc_id']}:run{row['run_idx']}", source, row["doc_id"], row["run_idx"],
                _document_file(row["doc_id"]), rehearsal, reasons, items, row.get("tool_calls", []))


def load_cases(sources: dict[str, Path] | None = None) -> list[Case]:
    """Every case from every source file that exists. Agent rows are recognised by their `evidence` field."""
    cases = []
    for name, path in (sources or DEFAULT_SOURCES).items():
        for row in _read_jsonl(Path(path)):
            if "evidence" in row:
                cases.append(agent_case(row, name, rehearsal=row.get("model") == "rehearsal" or "dryrun" in str(path)))
            else:
                cases.append(baseline_case(row, name))
    return cases

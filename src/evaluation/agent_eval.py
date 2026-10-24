"""
Evaluation of the agentic tool loop on the v2 fixtures (docs/agent_tool_use_design.md).

  plan        zero cost: documents, runs, nominal and worst-case requests, cost estimate
  run         API: the agent (src/agent/tool_agent.py) on each document x --n-runs; one
              row per (doc, run) appended to the output as it finishes; resumes; failures
              go to <output stem>_errors.jsonl; an audit run is logged
  claimcheck  API: the existing narrow claim check (claim_verification._check_claim, same
              prompt and model as the baseline's) on every regulatory claim, against the
              text of the passages that claim names; append-only store, resumes
  score       zero cost: tool calling, outcomes, escalation, validation checks and
              groundedness, against the set's labels (written before any run); writes
              <output stem>_scores.json and <output stem>_report.md
  labels-v1   zero cost: writes the agent labels for the 15 hand-written v1 documents
              (tests/fixtures/eval_set_v1_agent.json, docs/agent_v1_labels.md)

--set v2 (default): data/fixtures_v2/, 19 documents with accounts; tests escalation and
                    tool use.
--set v1:           the 15 hand-written baseline documents (data/synthetic_docs/). Other
                    lenders, no customer numbers: escalation not_applicable, account and
                    policy calls unnecessary. Outcomes are compared with the baseline's
                    full pass on the same documents.

Reported as counts and rates, per split and overall. Labels are never shown to the agent.
"""

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.monitoring import audit  # noqa: E402

LABELS = {"v2": ROOT / "tests" / "fixtures" / "eval_set_v2.json",
          "v1": ROOT / "tests" / "fixtures" / "eval_set_v1_agent.json"}
DEFAULT_OUTPUT = {"v2": ROOT / "docs" / "eval_agent_v2.jsonl", "v1": ROOT / "docs" / "eval_agent_v1.jsonl"}
BASELINE_PASS = ROOT / "docs" / "eval_raw_main_pass_v2.jsonl"
V1_LABELS_MD = ROOT / "docs" / "agent_v1_labels.md"
OUTCOMES = ("price_and_value", "consumer_support", "products_and_services", "consumer_understanding")
# Budget guard (--max-usd): a paid command stops before the next unit of work could pass the cap.
# Per-unit worst cases, from the design-doc estimate (worst run ~$0.28) with headroom, and a claim
# check with its retries.
RUN_WORST_USD = 0.35
CLAIM_EST_USD = 0.004
CLAIM_WORST_USD = 0.02
TOOLS = ("search_regulation", "get_account", "search_policy")
EXPECTED_STATUS = {"non_compliant": "potentially_non_compliant", "compliant": "compliant"}


def _labels(which: str = "v2") -> list[dict]:
    path = LABELS[which]
    if not path.exists():
        raise SystemExit(f"No labels at {path}. For v1, run `agent_eval labels-v1` first (zero cost).")
    return json.loads(path.read_text(encoding="utf-8"))["documents"]


def build_v1_labels() -> list[dict]:
    """Agent labels for the 15 hand-written v1 documents, from the baseline's own ground truth."""
    from tests.fixtures.eval_set import EVAL_DOCUMENTS

    from src.agent.agent_validation import document_facts, necessary_calls

    out = []
    for d in EVAL_DOCUMENTS:
        rel = f"data/synthetic_docs/{d['file']}"
        facts = document_facts((ROOT / rel).read_text(encoding="utf-8"))
        # Every v1 document is a credit agreement from a named lender other than Northbridge, with no
        # customer number. Refuse to write labels if that ever stops being true.
        assert facts["credit_agreement"] and facts["lender"] == "other" and facts["customer_number"] is None, (d["id"], facts)
        assert necessary_calls(facts) == {"search_regulation": True, "search_policy": False, "get_account": False}
        out.append({
            "doc_id": d["id"], "split": "v1", "file": rel, "customer_id": None, "loan_reference": None,
            "ground_truth": d["ground_truth"], "planted_defect": d.get("issue_outcome"),
            "account_scenario": "other_lender",
            "document_facts": {"credit_agreement": True, "lender": "other", "customer_number": None},
            "expected_escalation": {"decision": "not_applicable", "triggers": []}, "expected_discrepancy": False,
            "expected_tool_calls": {"get_account": {"required": False, "forbidden": True},
                                    "search_policy": {"required": False, "forbidden": True},
                                    "search_regulation": {"required": True, "per_outcome": list(OUTCOMES)}},
            "reason": f"another lender ({facts['lender_clause'].split(',')[0]}); no customer number. "
                      f"Planted issue: {d.get('issue_note') or 'none (control)'}",
        })
    return out


def cmd_labels_v1(args) -> None:
    from datetime import date

    docs = build_v1_labels()
    LABELS["v1"].write_text(json.dumps(
        {"_disclaimer": "Labels for graders only. Never passed to the agent or to any tool.",
         "review_date": config.AGENT_REVIEW_DATE, "source": "tests/fixtures/eval_set.py EVAL_DOCUMENTS",
         "documents": docs}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    L = ["# Agent labels for the v1 documents", "",
         f"Written {date.today().isoformat()}, **before any agent run on them**, by "
         "`python -m src.evaluation.agent_eval labels-v1`. Outcome ground truth is the baseline's "
         "(`tests/fixtures/eval_set.py`), unchanged. Graders only: the agent never sees this file.", "",
         "Every v1 document is a credit agreement from a named lender other than Northbridge, with no "
         "customer number. So for every document: **search_regulation x4 (one per outcome) required; "
         "get_account and search_policy unnecessary; escalation not_applicable.**", ""]
    for d in docs:
        nc = [o for o, v in d["ground_truth"].items() if v == "non_compliant"]
        L.append(f"- **{d['doc_id']}** - non-compliant: {', '.join(nc) or 'none'}. Reason: {d['reason']}")
    V1_LABELS_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Wrote {LABELS['v1'].relative_to(ROOT)} ({len(docs)} documents) and {V1_LABELS_MD.relative_to(ROOT)}")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def _append(path: Path, row: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")


def _output(arg: str | None, which: str = "v2") -> Path:
    from src.evaluation.run_eval import AUDIT_PROTECTED_NAMES

    out = Path(arg) if arg else DEFAULT_OUTPUT[which]
    if out.name in AUDIT_PROTECTED_NAMES:
        raise SystemExit(f"Refusing to write agent rows to protected file {out.name}.")
    return out


def _select(args) -> list[dict]:
    docs = _labels(args.set)
    if getattr(args, "split", None):
        docs = [d for d in docs if d["split"] == args.split]
    if getattr(args, "docs", None):
        unknown = set(args.docs) - {d["doc_id"] for d in docs}
        if unknown:
            raise SystemExit(f"Unknown doc ids: {sorted(unknown)}")
        docs = [d for d in docs if d["doc_id"] in args.docs]
    return docs


# --- plan ---

def cmd_plan(args) -> None:
    docs = _select(args)
    runs = len(docs) * args.n_runs
    price_in, price_out = config.PRICE_PER_MTOK.get(config.ANTHROPIC_MODEL, (None, None))
    print(f"Set {args.set}. Documents: {len(docs)} ({Counter(d['split'] for d in docs)}), runs each: {args.n_runs}, "
          f"total runs: {runs}")
    print(f"Model requests: at most {config.AGENT_MAX_TURNS} per run -> worst case {runs * config.AGENT_MAX_TURNS}; "
          f"typical 3-4 per run -> about {runs * 3}-{runs * 4}. Tool calls themselves make no model requests.")
    if price_in:
        print(f"Estimated cost ({config.ANTHROPIC_MODEL}, ${price_in}/${price_out} per M tokens, design-doc assumptions): "
              f"typical ~${runs * 0.12:.2f}, worst case ~${runs * 0.28:.2f} (4 regulation searches per run).")
    rows = _read_jsonl(_output(args.output, args.set))
    if rows:
        claims = sum(len(_claims(r)) for r in rows)
        print(f"Existing rows: {len(rows)}; regulatory claims for claimcheck: {claims} (one request each, "
              f"~${claims * 0.004:.2f}).")


# --- run ---

class RehearsalModel:
    """
    Offline stand-in for the model, for `run --dry-run`: zero API calls. Per document it makes the calls
    the validation layer considers necessary (all in one turn), then submits an assessment that cites
    and quotes each outcome's own top passage. It exercises the real MCP server, data, loop, validation,
    rows and scorer end to end. Its verdicts are placeholders: a dry run tests plumbing, not accuracy.
    """

    def __init__(self):
        self.messages = self
        self.requests = 0

    @staticmethod
    def _resp(*blocks):
        from types import SimpleNamespace as NS

        return NS(content=list(blocks), stop_reason="tool_use", model="rehearsal", id="rehearsal",
                  usage=NS(input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0))

    def create(self, **kwargs):
        import re
        from types import SimpleNamespace as NS

        from src.agent.agent_validation import document_facts, necessary_calls

        self.requests += 1
        msgs = kwargs["messages"]
        facts = document_facts(msgs[0]["content"])
        need = necessary_calls(facts)
        if len(msgs) == 1:
            calls = []
            if need["get_account"]:
                calls.append(NS(type="tool_use", id="r_acct", name="get_account",
                                input={"customer_id": facts["customer_number"]}))
            if need["search_policy"]:
                calls.append(NS(type="tool_use", id="r_pol", name="search_policy",
                                input={"query": "vulnerable customer escalation triggers"}))
            if need["search_regulation"]:
                calls += [NS(type="tool_use", id=f"r_{o}", name="search_regulation",
                             input={"outcome": o, "query": f"{o.replace('_', ' ')} requirements"}) for o in OUTCOMES]
            if calls:
                return self._resp(*calls)
        results = {r["tool_use_id"]: r["content"] for m in msgs if m["role"] == "user" and isinstance(m["content"], list)
                   for r in m["content"]}
        judgments = {}
        for o in OUTCOMES:
            m = re.search(r"^E(\d+) \|[^\n]*\n(.+?)(?:\n\nE\d+ \||\Z)", results.get(f"r_{o}", ""), re.S | re.M)
            reqs = [{"claim": "placeholder", "sources": [{"excerpt_number": int(m.group(1)),
                                                          "verbatim_quote": " ".join(m.group(2).split()[:10])}]}] if m else []
            judgments[o] = {"status": "compliant" if m else "insufficient_evidence", "reasoning": "rehearsal",
                            "cited_sources": [int(m.group(1))] if m else [], "document_facts": [],
                            "regulatory_requirements": reqs, "absences": []}
        decision = ("not_applicable" if not facts["credit_agreement"] or facts["lender"] == "other"
                    else "cannot_determine")
        lender_flag = {"northbridge": "yes", "other": "no", "not_stated": "not_stated"}[facts["lender"]]
        return self._resp(NS(type="tool_use", id="r_submit", name="submit_assessment", input={
            "document": {"is_credit_agreement": facts["credit_agreement"], "lender_named": facts["lender_clause"],
                         "lender_is_northbridge": lender_flag},
            **judgments,
            "escalation": {"decision": decision, "triggers": [], "policy_quotes": [], "note_quotes": [],
                           "discrepancies": [], "reasoning": "rehearsal", "cited_evidence": []}}))


def cmd_run(args) -> None:
    from src.agent.tool_agent import ToolAgent

    if args.dry_run:  # zero API calls: rehearsal model, separate output under LOG_DIR, then score it
        args.output = str(config.LOG_DIR / "dryrun" / f"eval_agent_{args.set}.jsonl")
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "_errors", "_claimchecks"):
            Path(args.output).with_name(f"eval_agent_{args.set}{suffix}.jsonl").unlink(missing_ok=True)
        print("DRY RUN: offline rehearsal model, real MCP server and data, ZERO API calls.")
    elif getattr(args, "max_usd", None) is None:
        raise SystemExit("run makes API calls: pass --max-usd (a hard cap on this command's spend).")
    out = _output(args.output, args.set)
    out.parent.mkdir(parents=True, exist_ok=True)  # before any paid call: a missing folder must not lose a result
    errors = out.with_name(f"{out.stem}_errors.jsonl")
    docs = _select(args)
    done = {(r["doc_id"], r["run_idx"]) for r in _read_jsonl(out)}
    todo = [(d, i) for d in docs for i in range(args.n_runs) if (d["doc_id"], i) not in done]
    skipped = len(docs) * args.n_runs - len(todo)
    if skipped:
        print(f"WARNING: {skipped} (doc, run) pairs already in {out.name}; skipping them.")
    if not todo:
        print("WARNING: nothing to run; NO API calls made.")
        return
    print(f"Running the agent: {len(todo)} runs -> {out}")
    audit.start_run("agent_eval run", settings={"set": args.set, "n_runs": args.n_runs, "docs": [d["doc_id"] for d in docs],
                                                "output": str(out)}, log_payloads=args.log_payloads)
    status, state = "failed", {"failed": 0, "t0": 0.0}
    by_key = {(d["doc_id"], i): d for d, i in todo}

    def before(key):
        audit.set_context(doc_id=key[0], run_idx=key[1])
        state["t0"] = time.time()

    def after(key, result, exc):
        (doc_id, run_idx), d = key, by_key[key]
        if exc is not None:  # this document failed; the batch continues
            state["failed"] += 1
            _append(errors, {"doc_id": doc_id, "run_idx": run_idx, "error": repr(exc)})
            audit.event("evaluation", "error", level="error", data={"error": repr(exc)})
            print(f"[FAILED] {doc_id} run {run_idx}: {exc!r}")
            return
        _append(out, {"doc_id": doc_id, "run_idx": run_idx, "split": d["split"], "run_id": audit.run_id(),
                      "model": config.ANTHROPIC_MODEL, "duration_s": round(time.time() - state["t0"], 1), **result})
        print(f"[{doc_id} run {run_idx}] calls={[c['tool'] for c in result['tool_calls']]} "
              f"escalation={(result['escalation'] or {}).get('decision')} stop={result['stop']['reason']}")

    cap = getattr(args, "max_usd", None)

    def capped(items):
        """Stop before a run that could take the spend past --max-usd (worst case per run: RUN_WORST_USD)."""
        for item in items:
            spent = audit.estimated_cost() or 0.0
            if cap is not None and spent + RUN_WORST_USD > cap:
                state["capped"] = spent
                print(f"BUDGET STOP: ~${spent:.2f} spent; the next run could pass the ${cap:.2f} cap. "
                      "Re-running resumes from here.")
                return
            yield item

    try:
        # One MCP server for the whole batch; every (doc, run) is still its own agent run.
        agent = ToolAgent(client=RehearsalModel()) if args.dry_run else ToolAgent()
        agent.run_many(capped(((d["doc_id"], i), (ROOT / d["file"]).read_text(encoding="utf-8")) for d, i in todo),
                       before=before, after=after)
        status = "completed" if not state["failed"] else "completed_with_failures"
        if "capped" in state:
            status = "budget_stop"
        audit.check("evaluation", "within_budget", (audit.estimated_cost() or 0.0) <= (cap if cap is not None else float("inf")),
                    metric=audit.estimated_cost(), threshold=cap)
    finally:
        spent = audit.estimated_cost() or 0.0
        audit.end_run(status)
    print(f"Estimated spend this command: ~${spent:.2f} (status: {status})")
    if args.dry_run:
        cmd_score(args)


# --- claim check ---

def _claims(row: dict) -> list[dict]:
    evidence = {e["number"]: e for e in row.get("evidence", [])}
    out = []
    for key in OUTCOMES:
        j = (row["outcomes"].get(key) or {}).get("judgment")
        if not j or row["outcomes"][key]["status"] == "not_applicable":
            continue
        for i, req in enumerate(j["regulatory_requirements"]):
            texts = [evidence[s["excerpt_number"]]["text"] for s in req["sources"]
                     if s["excerpt_number"] in evidence and evidence[s["excerpt_number"]]["kind"] in ("regulation", "policy")]
            out.append({"doc_id": row["doc_id"], "run_idx": row["run_idx"], "outcome": key, "claim_index": i,
                        "claim": req["claim"], "texts": texts})
    return out


def cmd_claimcheck(args) -> None:
    import instructor
    from anthropic import Anthropic

    from src.agent import retry_log
    from src.evaluation.claim_verification import _check_claim

    out = _output(args.output, args.set)
    store = out.with_name(f"{out.stem}_claimchecks.jsonl")
    runs, cap = getattr(args, "runs", None), getattr(args, "max_usd", None)
    rows = [r for r in _read_jsonl(out) if runs is None or r["run_idx"] in runs]
    done = {(c["doc_id"], c["run_idx"], c["outcome"], c["claim_index"], c["claim"]) for c in _read_jsonl(store)}
    todo = [c for r in rows for c in _claims(r)
            if (c["doc_id"], c["run_idx"], c["outcome"], c["claim_index"], c["claim"]) not in done]
    sendable = sum(1 for c in todo if c["texts"])
    print(f"Claims to check: {len(todo)} ({sendable} sent to the model, ~${sendable * CLAIM_EST_USD:.2f}; "
          f"already stored: {len(done)}; runs: {runs or 'all'}) -> {store}")
    if not todo or getattr(args, "count_only", False):
        print("NO API calls made." if todo else "WARNING: nothing to check; NO API calls made.")
        return
    if cap is None:
        raise SystemExit("claimcheck makes API calls: pass --max-usd (a hard cap on this command's spend).")
    audit.start_run("agent_eval claimcheck", settings={"input": str(out), "store": str(store), "runs": runs,
                                                       "max_usd": cap})
    status = "failed"
    try:
        client = retry_log.attach(instructor.from_anthropic(Anthropic()), "agent_claim_check")
        for c in todo:
            spent = audit.estimated_cost() or 0.0
            if spent + CLAIM_WORST_USD > cap:
                print(f"BUDGET STOP: ~${spent:.2f} spent; the next check could pass the ${cap:.2f} cap.")
                status = "budget_stop"
                return
            audit.set_context(doc_id=c["doc_id"], run_idx=c["run_idx"], outcome=c["outcome"])
            if not c["texts"]:
                verdict = {"verdict": "no_named_passage", "supporting_sentence": "",
                           "note": "claim names no returned passage; not sent to the checker"}
            else:
                verdict = _check_claim(client, c["claim"], c["texts"]).model_dump()
            _append(store, {k: v for k, v in c.items() if k != "texts"} | {"llm_check": verdict})
        status = "completed"
    finally:
        audit.end_run(status)


# --- score ---

def _rate(n, d):
    return None if d == 0 else round(n / d, 4)


def score_rows(rows: list[dict], labels: dict, claimchecks: list[dict]) -> dict:
    groups = {"overall": rows}
    for split in sorted({r["split"] for r in rows}):
        if split != "overall" and len({r["split"] for r in rows}) > 1:
            groups[split] = [r for r in rows if r["split"] == split]
    cc = {(c["doc_id"], c["run_idx"], c["outcome"], c["claim_index"]): c["llm_check"]["verdict"] for c in claimchecks}
    return {name: _score_group(g, labels, cc) for name, g in groups.items()}


def _score_group(rows: list[dict], labels: dict, cc: dict) -> dict:
    t = defaultdict(Counter)
    outcome_cm = {k: Counter() for k in OUTCOMES}
    esc, checks_failed, forced, per_doc = Counter(), Counter(), Counter(), {}
    ground = Counter()
    for r in rows:
        lab = labels[r["doc_id"]]
        calls = r["tool_calls"]
        for tool in TOOLS:
            exp = lab["expected_tool_calls"][tool]
            made = [c for c in calls if c["tool"] == tool]
            if exp["required"]:
                t[tool]["required_runs"] += 1
                t[tool]["required_made"] += bool(made)
                if tool == "get_account":
                    t[tool]["correct_argument"] += any(c["arguments"].get("customer_id") == exp["arguments"]["customer_id"]
                                                       for c in made)
                if tool == "search_regulation":
                    searched = {c["arguments"].get("outcome") for c in made if not c["is_error"]}
                    t[tool]["all_outcomes_searched"] += set(exp.get("per_outcome", OUTCOMES)) <= searched
                    for o in OUTCOMES:
                        t[tool][f"searched:{o}"] += o in searched
            if exp.get("forbidden"):
                t[tool]["forbidden_runs"] += 1
                t[tool]["forbidden_called"] += bool(made)
            t[tool]["calls"] += len(made)
        t["all"]["runs"] += 1
        t["all"]["calls"] += len(calls)
        t["all"]["unnecessary_calls"] += len(r.get("unnecessary_calls", []))
        t["all"]["runs_with_unnecessary"] += bool(r.get("unnecessary_calls"))
        t["all"]["limit_stops"] += r["stop"]["reason"] in ("limit", "turn_limit")
        t["all"]["turns"] += r["turns"]
        for key in OUTCOMES:
            gt = lab["ground_truth"][key]
            o = r["outcomes"][key]
            if gt == "not_applicable":
                outcome_cm[key]["not_applicable_docs"] += 1
                outcome_cm[key]["not_applicable_reported"] += o["status"] == "not_applicable"
                continue
            for stage, status in (("llm", o["llm_status"]), ("post", o["status"])):
                if status in (None, "insufficient_evidence"):
                    outcome_cm[key][f"{stage}_abstain"] += 1
                elif gt == "non_compliant":
                    outcome_cm[key][f"{stage}_tp" if status == "potentially_non_compliant" else f"{stage}_fn"] += 1
                else:
                    outcome_cm[key][f"{stage}_tn" if status == "compliant" else f"{stage}_fp"] += 1
            if o["llm_status"] not in (None, "insufficient_evidence") and o.get("forced_reasons"):
                forced[f"{key}:rule"] += 1
            forced[f"{key}:below_reference"] += bool(o.get("below_reference_threshold"))
            for i, req in enumerate(((o.get("judgment") or {}).get("regulatory_requirements")) or []):
                v = cc.get((r["doc_id"], r["run_idx"], key, i))
                if v:
                    ground[f"claimcheck_{v}"] += 1
        exp_esc = lab["expected_escalation"]
        got = r["escalation"] or {}
        esc["runs"] += 1
        esc["decision_correct"] += got.get("decision") == exp_esc["decision"]
        esc[f"expected_{exp_esc['decision']}"] += 1
        esc[f"expected_{exp_esc['decision']}_correct"] += got.get("decision") == exp_esc["decision"]
        if exp_esc["decision"] == "escalate":
            esc["triggers_exact"] += sorted(got.get("triggers") or []) == sorted(exp_esc["triggers"])
        if lab["expected_discrepancy"]:
            esc["discrepancy_expected"] += 1
            esc["discrepancy_reported"] += bool(got.get("discrepancies"))
        for c in r["checks"]:
            if c["passed"] is False:
                checks_failed[c["name"].split(":")[0]] += 1
            if c["name"].startswith("quotes_in_named_passages"):
                ground["outcomes_quote_checked"] += 1
                ground["outcomes_all_quotes_in_named_passage"] += bool(c["passed"])
            if c["name"] == "policy_quotes_in_policy_text":
                ground["policy_quote_checks"] += 1
                ground["policy_quotes_all_found"] += bool(c["passed"])
        per_doc.setdefault(r["doc_id"], []).append({
            "run": r["run_idx"], "calls": [f"{c['tool']}({json.dumps(c['arguments'])[:60]})" for c in calls],
            "escalation": got.get("decision"), "expected": exp_esc["decision"],
            "unnecessary": [u["reason"] for u in r.get("unnecessary_calls", [])], "stop": r["stop"]["reason"]})
    return {"tool_calls": {k: dict(v) for k, v in t.items()}, "outcomes": {k: dict(v) for k, v in outcome_cm.items()},
            "forced_to_insufficient": dict(forced), "escalation": dict(esc), "checks_failed": dict(checks_failed),
            "groundedness": dict(ground), "per_doc": per_doc}


def cmd_score(args) -> None:
    out = _output(args.output, args.set)
    rows = _read_jsonl(out)
    if not rows:
        raise SystemExit(f"No rows in {out}. Run `agent_eval run` first.")
    labels = {d["doc_id"]: d for d in _labels(args.set)}
    claimchecks = _read_jsonl(out.with_name(f"{out.stem}_claimchecks.jsonl"))
    s = score_rows(rows, labels, claimchecks)
    if args.set == "v1":
        s["baseline"] = baseline_outcomes(labels)
    s1 = _read_jsonl(out.with_name(f"{out.stem}_signal1.jsonl"))
    if s1:
        s["signal1"] = {"agent": signal1_summary(s1)}
        if args.set == "v1":
            base = [x for x in _read_jsonl(BASELINE_SIGNAL1) if x["doc_id"] in labels]
            s["signal1"]["baseline"] = signal1_summary(base)
    s["meta"] = {"rows": len(rows), "input": out.name, "claimchecks": len(claimchecks),
                 "errors": len(_read_jsonl(out.with_name(f"{out.stem}_errors.jsonl")))}
    if len({r["run_idx"] for r in rows}) > 1:  # run-to-run agreement, the baseline's ruler (src/evaluation/agreement.py)
        from src.evaluation import agreement

        as_main = [{"doc_id": r["doc_id"], "run_idx": r["run_idx"], "ground_truth": labels[r["doc_id"]]["ground_truth"],
                    "outcomes": {k: {"llm_status": r["outcomes"][k]["llm_status"] or "insufficient_evidence"}
                                 for k in OUTCOMES}} for r in rows]
        pairs = agreement.pair_table(as_main)
        s["agreement"] = agreement.summarise(pairs)
        agreement.write_report(pairs, s["agreement"], out, out.with_name(f"eval_agreement_{out.stem}.md"))
    out.with_name(f"{out.stem}_scores.json").write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    out.with_name(f"{out.stem}_report.md").write_text(_report(s), encoding="utf-8")
    print(f"Wrote {out.stem}_scores.json and {out.stem}_report.md")


BASELINE_SIGNAL1 = ROOT / "docs" / "eval_raw_main_pass_v2_signal1.jsonl"


def signal1_rows(rows: list[dict]) -> list[dict]:
    """
    Signal 1 for the agent, the baseline's ruler (groundedness.compute_signal1_cited): cosine similarity
    between an outcome's reasoning and each regulation or policy passage it cites. Zero API cost (local
    embeddings). Outcomes with no reasoning or no cited passage are skipped, as in the baseline.
    """
    from src.evaluation.groundedness import compute_signal1_cited

    out = []
    for r in rows:
        evidence = {e["number"]: e for e in r.get("evidence", [])}
        for key in OUTCOMES:
            o = r["outcomes"].get(key) or {}
            j = o.get("judgment") or {}
            cited = [{"index": n, "text_excerpt": evidence[n]["text"]} for n in j.get("cited_sources") or []
                     if n in evidence and evidence[n]["kind"] in ("regulation", "policy")]
            if not j.get("reasoning") or not cited:
                continue
            out.append({"doc_id": r["doc_id"], "run_idx": r["run_idx"], "outcome": key, "llm_status": o.get("llm_status"),
                        "signal1_cited": compute_signal1_cited(j["reasoning"], cited)})
    return out


def signal1_summary(s1: list[dict]) -> dict:
    """Per outcome: n, and the median and minimum of each judgment's lowest cited-passage similarity."""
    import statistics

    out = {}
    for key in OUTCOMES:
        mins = sorted(x["signal1_cited"]["min"] for x in s1 if x["outcome"] == key and x["signal1_cited"]["min"] is not None)
        out[key] = {"n": len(mins), "median_min": round(statistics.median(mins), 4) if mins else None,
                    "lowest": round(mins[0], 4) if mins else None}
    return out


def cmd_signal1(args) -> None:
    out = _output(args.output, args.set)
    rows = _read_jsonl(out)
    if not rows:
        raise SystemExit(f"No rows in {out}. Run `agent_eval run` first.")
    path = out.with_name(f"{out.stem}_signal1.jsonl")
    s1 = signal1_rows(rows)
    path.write_text("".join(json.dumps(x) + "\n" for x in s1), encoding="utf-8")
    print(f"Wrote {path.name}: {len(s1)} outcome judgments (zero API cost).")


def baseline_outcomes(labels: dict) -> dict:
    """The fixed pipeline's full pass on the same v1 documents, counted the same way (llm and post)."""
    cm = {k: Counter() for k in OUTCOMES}
    for r in _read_jsonl(BASELINE_PASS):
        if r["doc_id"] not in labels:
            continue
        for key in OUTCOMES:
            gt = labels[r["doc_id"]]["ground_truth"][key]
            o = r["outcomes"][key]
            for stage, status in (("llm", o["llm_status"]), ("post", o["status"])):
                if status in (None, "insufficient_evidence"):
                    cm[key][f"{stage}_abstain"] += 1
                elif gt == "non_compliant":
                    cm[key][f"{stage}_tp" if status == "potentially_non_compliant" else f"{stage}_fn"] += 1
                else:
                    cm[key][f"{stage}_tn" if status == "compliant" else f"{stage}_fp"] += 1
    return {"source": BASELINE_PASS.name, "outcomes": {k: dict(v) for k, v in cm.items()}}


def _report(s: dict) -> str:
    m = s["meta"]
    L = ["# Agentic tool loop: evaluation on fixtures v2", "",
         f"Input: `docs/{m['input']}` ({m['rows']} runs; {m['errors']} failed runs logged; {m['claimchecks']} claim checks). "
         "Labels: `tests/fixtures/eval_set_v2.json`, written before any run. Counts and rates only.", ""]
    if "baseline" in s:
        L += ["## Agent vs baseline on the same v1 documents", "",
              f"Baseline: the fixed pipeline's full pass (`docs/{s['baseline']['source']}`). Same documents and "
              "ground truth; the two systems differ in more than one way (see ARCHITECTURE.md), so a difference "
              "reflects the whole design, not one variable.", "",
              "Runs differ between the two systems, so compare the rates: accuracy = (TP+TN)/(TP+TN+FP+FN), "
              "abstention = Abstain/runs.", "",
              "| Outcome | Stage | System | Runs | TP | TN | FP | FN | Abstain | Accuracy (excl. abstain) | Abstention |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for k in OUTCOMES:
            for stage in ("llm", "post"):
                for system, v in (("agent", s["overall"]["outcomes"][k]), ("baseline", s["baseline"]["outcomes"][k])):
                    tp, tn, fp, fn, ab = (v.get(f"{stage}_{x}", 0) for x in ("tp", "tn", "fp", "fn", "abstain"))
                    runs, decided = tp + tn + fp + fn + ab, tp + tn + fp + fn
                    acc = f"{(tp + tn) / decided:.3f}" if decided else "n/a"
                    L.append(f"| {k} | {stage} | {system} | {runs} | {tp} | {tn} | {fp} | {fn} | {ab} | {acc} | "
                             f"{ab / runs:.3f} |" if runs else f"| {k} | {stage} | {system} | 0 | - | - | - | - | - | n/a | n/a |")
        L.append("")
    if "signal1" in s:
        L += ["## Signal 1: reasoning vs the passages it cites", "",
              "Cosine similarity (local embeddings, zero API cost) between each outcome's reasoning and each "
              "regulation or policy passage it cites; per judgment, the lowest. The same ruler as the baseline "
              "(`groundedness.compute_signal1_cited`). No threshold: a coarse topical signal, not proof of support.", "",
              "| Outcome | System | Judgments | Median of lowest | Lowest |", "|---|---|---|---|---|"]
        for k in OUTCOMES:
            for system, v in s["signal1"].items():
                x = v[k]
                L.append(f"| {k} | {system} | {x['n']} | {x['median_min'] if x['median_min'] is not None else 'n/a'} | "
                         f"{x['lowest'] if x['lowest'] is not None else 'n/a'} |")
        L.append("")
    if "agreement" in s:
        a, d = s["agreement"]["agree"], s["agreement"]["disagree"]
        L += ["## Run-to-run agreement", "",
              f"Pairs (document, outcome) where every run gave the same verdict: {a['pairs']}, with {a['wrong']} wrong "
              f"verdicts. Pairs where runs disagreed: {d['pairs']}, with {d['wrong']} wrong verdicts and "
              f"{d['abstained']} abstentions. Full table: `docs/eval_agreement_{m['input'].removesuffix('.jsonl')}.md`.", ""]
    for name in [k for k in s if k not in ("meta", "baseline", "signal1", "agreement")]:
        g = s[name]
        t = g["tool_calls"]
        L += [f"## {name}", "", "### Tool calling", "",
              "| Tool | Required runs | Called when required | Correct argument | Unnecessary-call runs | Called when unnecessary | Total calls |",
              "|---|---|---|---|---|---|---|"]
        for tool in TOOLS:
            x = t.get(tool, {})
            L.append(f"| {tool} | {x.get('required_runs', 0)} | {x.get('required_made', 0)} | "
                     f"{x.get('correct_argument', '-') if tool == 'get_account' else '-'} | {x.get('forbidden_runs', 0)} | "
                     f"{x.get('forbidden_called', 0)} | {x.get('calls', 0)} |")
        r = t.get("search_regulation", {})
        L += ["", f"Regulation searched for all 4 outcomes (one search each): {r.get('all_outcomes_searched', 0)} / "
              f"{r.get('required_runs', 0)} runs; by outcome: "
              + ", ".join(f"{o} {r.get(f'searched:{o}', 0)}" for o in OUTCOMES) + "."]
        a = t.get("all", {})
        L += ["", f"Runs: {a.get('runs', 0)}; tool calls: {a.get('calls', 0)}; unnecessary calls (validation layer): "
              f"{a.get('unnecessary_calls', 0)} in {a.get('runs_with_unnecessary', 0)} runs; runs stopped by a limit: "
              f"{a.get('limit_stops', 0)}; model turns: {a.get('turns', 0)}.", "", "### Outcomes", "",
              "Positive = non-compliant. `llm` = the agent's verdict; `post` = after the validation layer's quote "
              "and citation rules. Auto-approval is disabled: every case goes to a human. Confidence is reported "
              "against the uncalibrated 0.65 reference but never replaces a verdict.", "",
              "Forced by rule: verdicts replaced with insufficient_evidence because a quote or citation rule failed. "
              "Below 0.65: outcomes whose confidence is under the reference value (reported only).", "",
              "| Outcome | Stage | TP | TN | FP | FN | Abstain | Forced by rule | Below 0.65 (reported only) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for k, v in g["outcomes"].items():
            for stage in ("llm", "post"):
                L.append(f"| {k} | {stage} | {v.get(f'{stage}_tp', 0)} | {v.get(f'{stage}_tn', 0)} | {v.get(f'{stage}_fp', 0)} | "
                         f"{v.get(f'{stage}_fn', 0)} | {v.get(f'{stage}_abstain', 0)} | "
                         f"{g['forced_to_insufficient'].get(f'{k}:rule', 0) if stage == 'post' else '-'} | "
                         f"{g['forced_to_insufficient'].get(f'{k}:below_reference', 0) if stage == 'post' else '-'} |")
        e = g["escalation"]
        L += ["", "### Escalation", "", f"Decision correct: {e.get('decision_correct', 0)} / {e.get('runs', 0)}."]
        for dec in ("escalate", "no_escalation", "cannot_determine", "not_applicable"):
            if e.get(f"expected_{dec}"):
                L.append(f"- expected {dec}: {e.get(f'expected_{dec}_correct', 0)} / {e[f'expected_{dec}']} correct")
        L += [f"- triggers exactly right when escalating: {e.get('triggers_exact', 0)} / {e.get('expected_escalate', 0)}",
              f"- discrepancy reported when expected: {e.get('discrepancy_reported', 0)} / {e.get('discrepancy_expected', 0)}",
              "", "### Groundedness", ""]
        gr = g["groundedness"]
        L += [f"- outcomes whose every regulatory quote is in the passage it names: "
              f"{gr.get('outcomes_all_quotes_in_named_passage', 0)} / {gr.get('outcomes_quote_checked', 0)}",
              f"- escalation decisions whose every policy quote is in the policy passage it names: "
              f"{gr.get('policy_quotes_all_found', 0)} / {gr.get('policy_quote_checks', 0)}",
              f"- narrow claim check: yes {gr.get('claimcheck_yes', 0)}, partially {gr.get('claimcheck_partially', 0)}, "
              f"no {gr.get('claimcheck_no', 0)}; claims naming no returned passage (not sent): "
              f"{gr.get('claimcheck_no_named_passage', 0)}", "", "### Validation checks failed", ""]
        L += [f"- {k}: {v}" for k, v in sorted(g["checks_failed"].items())] or ["- none"]
        L.append("")
    L += ["## Per document (overall)", ""]
    for doc, runs in sorted(s["overall"]["per_doc"].items()):
        for r in runs:
            L.append(f"- **{doc}** run {r['run']}: {', '.join(r['calls']) or 'no calls'} -> escalation `{r['escalation']}` "
                     f"(expected `{r['expected']}`){'; unnecessary: ' + '; '.join(r['unnecessary']) if r['unnecessary'] else ''}"
                     f"{'; stopped: ' + r['stop'] if r['stop'] else ''}")
    return "\n".join(L) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="Evaluate the agentic tool loop on fixtures v2")
    sub = p.add_subparsers(dest="command", required=True)
    for name, fn in (("plan", cmd_plan), ("run", cmd_run), ("claimcheck", cmd_claimcheck), ("score", cmd_score),
                     ("signal1", cmd_signal1), ("labels-v1", cmd_labels_v1)):
        sp = sub.add_parser(name)
        sp.add_argument("--set", choices=("v2", "v1"), default="v2", help="Fixture set (default v2)")
        sp.add_argument("--output", help="Agent rows JSONL (default docs/eval_agent_<set>.jsonl)")
        if name in ("plan", "run"):
            sp.add_argument("--n-runs", type=int, default=1)
            sp.add_argument("--split", choices=("design", "heldout"))
            sp.add_argument("--docs", nargs="+")
        if name == "run":
            sp.add_argument("--log-payloads", action="store_true")
            sp.add_argument("--dry-run", action="store_true",
                            help="Zero API calls: offline rehearsal model with the real tools and data, then score.")
        if name in ("run", "claimcheck"):
            sp.add_argument("--max-usd", type=float,
                            help="Hard cap on this command's estimated spend (required unless --dry-run/--count-only)")
        if name == "claimcheck":
            sp.add_argument("--runs", nargs="+", type=int, help="Only rows with these run_idx values (default all)")
            sp.add_argument("--count-only", action="store_true", help="Count the claims and the cost; no API calls")
        sp.set_defaults(func=fn)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

"""
Calibration report (P8-11), zero API cost: could any outcome category skip
human review, and how much evidence would it take to show that?

Auto-approval means a `compliant` verdict is accepted without a person. The
risk is a missed issue: an approved verdict whose label is non_compliant. A
`potentially_non_compliant` verdict always goes to a person, so it is never a
candidate. For each outcome and each candidate gate, this counts how many
(document, outcome) pairs the gate would approve and how many of those are
missed issues, then gives the exact one-sided 95% upper bound (Clopper-Pearson)
on the missed-issue rate. A category qualifies for a risk target only when that
bound is at or below the target.

Gates (the 0.65 reference is CONFIDENCE_THRESHOLD; nothing here changes it):
  one_run_conf      a single run says compliant with confidence >= 0.65
                    (evaluated on each run; the worst run is reported)
  three_runs_agree  all runs say compliant
  three_runs_conf   all runs say compliant, each with confidence >= 0.65

The unit is the document: the 3 runs of one document are not independent
evidence, so they count once.

    python -m src.evaluation.calibration [--input docs/eval_raw_main_pass_v2.jsonl] [--output <md>]
"""

import argparse
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import CONFIDENCE_THRESHOLD  # noqa: E402
from src.evaluation.run_eval import INPUT_HELP, resolve_main_input  # noqa: E402
from tests.fixtures.eval_set import OUTCOME_KEYS  # noqa: E402

RISK_TARGETS = (0.01, 0.02, 0.05)  # missed-issue rates shown; choosing one is a business decision
GATES = ("one_run_conf", "three_runs_agree", "three_runs_conf")


def upper_bound(errors: int, n: int, alpha: float = 0.05) -> float | None:
    """Exact one-sided (1 - alpha) Clopper-Pearson upper bound on a binomial rate."""
    if n == 0:
        return None
    if errors >= n:
        return 1.0
    if errors == 0:
        return 1 - alpha ** (1 / n)

    def cdf(p):
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(errors + 1))
    lo, hi = errors / n, 1.0
    for _ in range(100):  # cdf falls as p rises: find p where cdf(p) = alpha
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > alpha else (lo, mid)
    return hi


def docs_needed(target: float, alpha: float = 0.05) -> int:
    """Approved documents needed, with zero missed issues, for the bound to reach the target."""
    return math.ceil(math.log(alpha) / math.log(1 - target))


def _pairs(rows: list[dict]) -> dict[tuple, dict]:
    pairs: dict[tuple, dict] = {}
    for r in rows:
        for k in OUTCOME_KEYS:
            o = r["outcomes"][k]
            p = pairs.setdefault((r["doc_id"], k), {"label": r["ground_truth"][k], "runs": {}})
            p["runs"][r["run_idx"]] = (o["llm_status"], o["confidence"])
    return pairs


def _passes(status: str, conf: float | None, threshold: float) -> bool:
    return status == "compliant" and conf is not None and conf >= threshold


def gate_counts(rows: list[dict], threshold: float = CONFIDENCE_THRESHOLD) -> dict:
    """{outcome: {gate: {"approved", "missed", "per_run"?}}} plus the label mix per outcome."""
    pairs = _pairs(rows)
    runs = sorted({i for p in pairs.values() for i in p["runs"]})
    out = {}
    for k in OUTCOME_KEYS:
        ps = [p for (_, o), p in pairs.items() if o == k]
        res = {"documents": len(ps), "labelled_non_compliant": sum(p["label"] == "non_compliant" for p in ps)}
        per_run = []
        for i in runs:
            approved = [p for p in ps if i in p["runs"] and _passes(*p["runs"][i], threshold)]
            per_run.append({"run": i, "approved": len(approved),
                            "missed": sum(p["label"] == "non_compliant" for p in approved)})
        worst = min(per_run, key=lambda x: (-x["missed"], x["approved"]))  # most missed, then fewest approved
        res["one_run_conf"] = {"approved": worst["approved"], "missed": worst["missed"], "per_run": per_run}
        agree = [p for p in ps if all(s == "compliant" for s, _ in p["runs"].values())]
        res["three_runs_agree"] = {"approved": len(agree), "missed": sum(p["label"] == "non_compliant" for p in agree)}
        conf = [p for p in agree if all(_passes(s, c, threshold) for s, c in p["runs"].values())]
        res["three_runs_conf"] = {"approved": len(conf), "missed": sum(p["label"] == "non_compliant" for p in conf)}
        for g in GATES:
            res[g]["upper_95"] = upper_bound(res[g]["missed"], res[g]["approved"])
            res[g]["qualifies"] = {t: res[g]["upper_95"] is not None and res[g]["upper_95"] <= t for t in RISK_TARGETS}
        out[k] = res
    return out


def write_report(counts: dict, input_path: Path, output_path: Path, threshold: float) -> None:
    any_q = {t: [(k, g) for k, r in counts.items() for g in GATES if r[g]["qualifies"][t]] for t in RISK_TARGETS}
    L = ["# Calibration: could any category skip human review? (P8-11)", "",
         f"Input: `{input_path.name}`. Generated by `src/evaluation/calibration.py` (zero API cost). "
         f"Confidence reference: {threshold}. Auto-approval is off (`AGENT_AUTO_APPROVAL_ENABLED = False`); "
         "this report decides nothing by itself.", "",
         "**Question.** If a `compliant` verdict skipped review, how often would it be a missed issue (label "
         "non_compliant)? A category qualifies for a risk target only if the exact 95% upper bound on that rate "
         "is at or below the target. One document counts once, however many runs it has.", "",
         "## Conclusion", ""]
    for t in RISK_TARGETS:
        L.append(f"- **Target {t:.0%}:** " + ("no category qualifies under any gate." if not any_q[t] else
                 "qualifies: " + ", ".join(f"{k} ({g})" for k, g in any_q[t]) + "."))
    max_docs = max(r["documents"] for r in counts.values())
    L += ["", f"The reason is the amount of evidence, not the errors seen. Even if a gate approved all {max_docs} "
          f"documents with zero missed issues, the bound would be {upper_bound(0, max_docs):.1%}. To show a rate at or below a target "
          "with zero missed issues, a gate must approve at least:", "",
          "| Risk target | Approved documents needed (0 missed) |", "|---|---|"]
    for t in RISK_TARGETS:
        L.append(f"| {t:.0%} | {docs_needed(t)} |")
    L += ["", "Those documents must be new ones, labelled before the run, with the gate fixed in advance (calibrate "
          "on the design split, then test once on held-out data).", "",
          "## By outcome and gate", "",
          "Approved = (document, outcome) pairs the gate would let skip review. Missed = approved pairs labelled "
          "non_compliant.", "",
          "| Outcome | Docs (non-compliant) | Gate | Approved | Missed | 95% upper bound |",
          "|---|---|---|---|---|---|"]
    for k, r in counts.items():
        for g in GATES:
            b = r[g]["upper_95"]
            extra = (" (runs: " + ", ".join(f"{x['approved']}" for x in r[g]["per_run"]) + ")") if g == "one_run_conf" else ""
            L.append(f"| {k} | {r['documents']} ({r['labelled_non_compliant']}) | {g} | {r[g]['approved']}{extra} | "
                     f"{r[g]['missed']} | {'n/a (none approved)' if b is None else f'{b:.1%}'} |")
    L += ["", "`one_run_conf` shows the worst run (most missed, then fewest approved); each run's approvals are in brackets.",
          "", "## What this does and doesn't show", "",
          "- No missed issue appears under any gate here; the baseline's 8 wrong verdicts were all false alarms, "
          "which go to a person anyway.",
          "- The 0.65 reference behaves as an on/off switch by category: compare `three_runs_agree` with "
          "`three_runs_conf`.",
          "- 15 synthetic documents with planted defects. This bounds nothing about real agreements."]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(L) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Calibration report (zero API cost)")
    parser.add_argument("--input", help=INPUT_HELP)
    parser.add_argument("--output", help="Report path (default docs/eval_calibration_<input stem>.md)")
    args = parser.parse_args(argv)
    input_path = resolve_main_input(args.input)
    output_path = Path(args.output) if args.output else input_path.with_name(f"eval_calibration_{input_path.stem}.md")
    if output_path.resolve() == input_path.resolve():
        raise SystemExit("Refusing to overwrite the input.")
    counts = gate_counts(_read_jsonl(input_path))
    write_report(counts, input_path, output_path, CONFIDENCE_THRESHOLD)
    for k, r in counts.items():
        print(k, {g: (r[g]["approved"], r[g]["missed"]) for g in GATES})
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()

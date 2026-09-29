"""
Phase 8 evaluation harness.

Subcommands (see ARCHITECTURE.md "Evaluation approach" and docs/eval_results.md
for the full methodology and findings):

  recall    Retrieval recall@k against tests/fixtures/eval_set.py's
            RETRIEVAL_QUERIES. Zero API cost — uses the local retriever
            directly, no LLM call, safe to run anytime.

  main      Runs the full pipeline (extraction + compliance judgment) against
            every document in tests/fixtures/eval_set.py's EVAL_DOCUMENTS,
            --n-runs times each (default 3). This is the expensive pass —
            9 Claude API calls per run (1 extraction + 4 retrieval-synthesis
            + 4 compliance judgments) x 15 docs x n_runs. Appends one JSON
            line per (doc, run) to docs/eval_raw_main_pass_v2.jsonl (or
            --output) as it goes, so a partial run is never silently lost.
            Never writes to the Phase 8 file, docs/eval_raw_main_pass.jsonl,
            and warns loudly about any (doc, run) pair it skips because the
            output file already has it.

  variants  Compares 2 system-prompt phrasings for the price_and_value
            judgment specifically (P8-04), reusing the first successful
            main-pass FirstPassResult per document as fixed input context
            (no extra extraction/retrieval calls) — only the judgment call
            itself is repeated, --n-runs times per variant per doc. Reads
            the main-pass file given by --input (default
            docs/eval_raw_main_pass_v2.jsonl; run `main` first).
            Appends to docs/eval_raw_variant_pass.jsonl.

  summary   Reads the main-pass file given by --input (default
            docs/eval_raw_main_pass_v2.jsonl), the variant JSONL and the
            recall@k JSON, and prints/saves computed metrics to
            <input stem>_summary.json next to the input. Never writes the
            Phase 8 summary, docs/eval_summary.json (eval_results.md cites
            it). Does not call the API.

  For Phase 8 reference, pass --input docs/eval_raw_main_pass.jsonl.

Ground truth: tests/fixtures/eval_set.py. See its module docstring for the
compliant/non_compliant labelling convention.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.agent.compliance import (  # noqa: E402
    COMPLIANCE_SYSTEM_PROMPT,
    ComplianceAgent,
    OutcomeJudgment,
    build_compliance_report,
)
from src.agent.first_pass import FirstPassAgent  # noqa: E402
from src.config import ANTHROPIC_MODEL, CONFIDENCE_THRESHOLD  # noqa: E402
from src.retrieval.query_engine import load_index  # noqa: E402
from tests.fixtures.eval_set import (  # noqa: E402
    EVAL_DOCUMENTS,
    OUTCOME_KEYS,
    RETRIEVAL_QUERIES,
)

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "synthetic_docs"
DOCS_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "docs"
# Phase 8 main-pass data (Session 13). Read-only from here on: `main` refuses
# to write to it (see _resolve_main_output). Readers (`variants`, `summary`,
# groundedness.py, claim_verification.py) default to MAIN_PASS_V2_PATH and
# reach this file only via an explicit --input (checklist item 13).
MAIN_PASS_PATH = DOCS_OUT_DIR / "eval_raw_main_pass.jsonl"
MAIN_PASS_ERRORS_PATH = DOCS_OUT_DIR / "eval_raw_main_pass_errors.jsonl"
# Default output for any new `main` pass (checklist item 11).
MAIN_PASS_V2_PATH = DOCS_OUT_DIR / "eval_raw_main_pass_v2.jsonl"
VARIANT_PASS_PATH = DOCS_OUT_DIR / "eval_raw_variant_pass.jsonl"
RECALL_PATH = DOCS_OUT_DIR / "eval_recall_at_k.json"
# The Phase 8 summary, cited by docs/eval_results.md. `summary` never writes
# here any more: its output path is derived from --input (see
# _summary_output_for), so no input can overwrite this file.
SUMMARY_PATH = DOCS_OUT_DIR / "eval_summary.json"

K_VALUES = [1, 2, 3, 5, 10]
MAX_K = max(K_VALUES)


# --- Variant B system prompt (P8-04) ---
# Targets the specific, diagnosed root cause documented in ARCHITECTURE.md
# "Confidence threshold vs. LLM judgment": price_and_value's top-5 retrieved
# chunks, for this corpus, consistently mix genuinely relevant general-
# principle text with worked examples for OTHER product types (BNPL fee
# stacking, SME business accounts, mortgages, distributor chains), which
# was found to cause the LLM to occasionally treat a mismatched example as
# establishing a requirement the document under review fails to meet.
# Variant B asks the model to explicitly check whether an excerpt concerns
# the same product/scenario before treating it as establishing a
# requirement, and to prefer insufficient_evidence over
# potentially_non_compliant when it doesn't. Variant A is the unmodified
# production prompt (COMPLIANCE_SYSTEM_PROMPT).
COMPLIANCE_SYSTEM_PROMPT_VARIANT_B = (
    "You are a compliance analyst comparing a specific clause (or the "
    "explicit absence of one) from a UK consumer loan agreement against "
    "retrieved excerpts of the FCA's Consumer Duty regulation for one "
    "specific outcome. Judge only from the retrieved excerpts provided — "
    "do not use outside knowledge of the Consumer Duty.\n\n"
    "Before deciding, explicitly check whether each retrieved excerpt is "
    "actually about the SAME kind of product and scenario as the document "
    "under review (a fixed-rate, fixed-term personal loan), or whether it "
    "is a general principle illustrated with a worked example for a "
    "DIFFERENT product type (e.g. buy-now-pay-later, a business current "
    "account, a mortgage, multi-party distribution chains). An excerpt "
    "that is only generally on-topic, but whose specific illustration "
    "concerns a different product or scenario, should NOT by itself be "
    "treated as establishing a requirement the document under review "
    "fails to meet.\n\n"
    "Return status as one of:\n"
    '- "compliant": the document\'s stated approach is consistent with '
    "what the retrieved excerpts require.\n"
    '- "potentially_non_compliant": the document\'s stated approach '
    "conflicts with, falls short of, or fails to address something the "
    "retrieved excerpts establish as required for THIS kind of product. "
    "This includes the case where the document explicitly states an "
    'aspect is "Not addressed in this document" and the retrieved '
    "excerpts show firms are required to address it — that is a real gap "
    "in the document, not missing evidence.\n"
    '- "insufficient_evidence": the retrieved excerpts do not contain '
    "enough specific, on-topic detail — for this product type — to "
    "support a compliant or potentially_non_compliant judgment either "
    "way. Use this when the regulatory text is the limiting factor "
    "(including when it's only relevant via a mismatched worked example), "
    "not when the document simply doesn't address the topic (that case is "
    "potentially_non_compliant, above).\n\n"
    "cited_sources must list the excerpt number(s) your reasoning "
    "actually relies on. Do not invent or state a confidence score or "
    "percentage anywhere in your reasoning — confidence is computed "
    "separately, deterministically, from retrieval quality, not from "
    "your judgment."
)

VARIANTS = {
    "A_production": COMPLIANCE_SYSTEM_PROMPT,
    "B_scenario_match": COMPLIANCE_SYSTEM_PROMPT_VARIANT_B,
}


def _load_doc_text(file_name: str) -> str:
    return (DOCS_DIR / file_name).read_text(encoding="utf-8")


def _append_jsonl(path: Path, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def resolve_main_input(input_path: str | None) -> Path:
    """
    Checklist item 13: which main-pass file a reader opens. Defaults to the
    file `main` now writes (MAIN_PASS_V2_PATH), never silently to the Phase
    8 file; the Phase 8 file stays readable by passing it explicitly, e.g.
    `--input docs/eval_raw_main_pass.jsonl`, so the Phase 8 write-ups remain
    reproducible. Shared by run_eval.py, groundedness.py and
    claim_verification.py.
    """
    return Path(input_path) if input_path else MAIN_PASS_V2_PATH


INPUT_HELP = (
    f"Main-pass JSONL to read (default: docs/{MAIN_PASS_V2_PATH.name}). Pass "
    f"docs/{MAIN_PASS_PATH.name} to read the Phase 8 data."
)


def _summary_output_for(input_path: Path) -> Path:
    """
    `summary` writes next to its input, named after it:
    eval_raw_main_pass_v2.jsonl -> eval_raw_main_pass_v2_summary.json. The
    Phase 8 summary (SUMMARY_PATH, cited by eval_results.md) is never the
    target; an input whose derived name would collide with it is refused.
    """
    out = input_path.with_name(f"{input_path.stem}_summary.json")
    if out.resolve() == SUMMARY_PATH.resolve():
        raise SystemExit(
            f"Refusing to write the summary to {SUMMARY_PATH}: that is the Phase 8 summary "
            "cited by docs/eval_results.md. Rename the input file."
        )
    return out


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --- recall@k (zero API cost) ---

def cmd_recall(_args) -> None:
    index = load_index()
    retriever = index.as_retriever(similarity_top_k=MAX_K)

    results = []
    for q in RETRIEVAL_QUERIES:
        nodes = retriever.retrieve(q["question"])
        marker = q["relevant_marker"]
        hits_by_rank = []
        for i, node in enumerate(nodes, start=1):
            text_lower = node.text.lower()
            is_relevant = marker is not None and marker in text_lower
            hits_by_rank.append(
                {
                    "rank": i,
                    "file": node.metadata.get("file_name", "unknown"),
                    "score": node.score or 0.0,
                    "relevant": is_relevant,
                }
            )
        recall_at_k = {}
        for k in K_VALUES:
            top_k = hits_by_rank[:k]
            n_relevant_total = sum(1 for h in hits_by_rank if h["relevant"])
            n_relevant_at_k = sum(1 for h in top_k if h["relevant"])
            if q["relevant_marker"] is None:
                # Off-topic control: "correct" behavior is zero relevant
                # hits at any k. Report as hit_rate 0/1 (0 = correctly
                # found nothing relevant), not a recall fraction.
                recall_at_k[k] = 0 if n_relevant_at_k == 0 else 1
            else:
                recall_at_k[k] = (
                    (n_relevant_at_k / n_relevant_total) if n_relevant_total > 0 else 0.0
                )
        results.append(
            {
                "id": q["id"],
                "question": q["question"],
                "hits_by_rank": hits_by_rank,
                "recall_at_k": recall_at_k,
            }
        )
        print(f"[{q['id']}] recall@k: " + ", ".join(f"k={k}:{recall_at_k[k]:.2f}" for k in K_VALUES))

    DOCS_OUT_DIR.mkdir(exist_ok=True)
    RECALL_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {RECALL_PATH}")


# --- main pass (expensive: full pipeline, n_runs per doc) ---

def _resolve_main_output(output: str | None) -> tuple[Path, Path]:
    """
    Deferred-checklist item 11 (ARCHITECTURE.md "Evaluation notes"): the
    main pass writes to MAIN_PASS_V2_PATH by default, never to the Phase 8
    file. All 45 (doc_id, run_idx) pairs already exist in MAIN_PASS_PATH, so
    resuming against it would silently skip the whole re-run. Writing to it
    is refused outright, so the Phase 8 data is never appended to or moved.
    The errors file sits next to whichever output file is used, so a new
    pass's failures don't mix with Phase 8's.
    """
    output_path = Path(output) if output else MAIN_PASS_V2_PATH
    if output_path.resolve() == MAIN_PASS_PATH.resolve():
        raise SystemExit(
            f"Refusing to write the main pass to {MAIN_PASS_PATH}: that is the Phase 8 "
            "data, which must not be modified. Omit --output to use "
            f"{MAIN_PASS_V2_PATH.name}, or pass a different path."
        )
    return output_path, output_path.with_name(f"{output_path.stem}_errors.jsonl")


def cmd_main(args) -> None:
    n_runs = args.n_runs
    output_path, errors_path = _resolve_main_output(args.output)
    total_calls = len(EVAL_DOCUMENTS) * n_runs * 9
    print(
        f"Running main pass: {len(EVAL_DOCUMENTS)} docs x {n_runs} runs x 9 calls/run "
        f"= {total_calls} Claude API calls.\nOutput: {output_path}"
    )

    # Resume support: a single malformed generation (observed once, see
    # eval_results.md) shouldn't force re-spending API calls on combinations
    # already recorded, and shouldn't crash the whole batch. Skip (doc_id,
    # run_idx) pairs already in the OUTPUT file (not the Phase 8 file); on a
    # per-run failure, log it to the errors file and continue rather than
    # aborting. Skipping is announced loudly, never silent: a re-run that
    # skips everything is exactly the failure item 11 exists to prevent.
    requested = {(doc["id"], run_idx) for doc in EVAL_DOCUMENTS for run_idx in range(n_runs)}
    existing = {(r["doc_id"], r["run_idx"]) for r in _read_jsonl(output_path)}
    skipped = requested & existing
    if skipped:
        print(
            f"\nWARNING: {output_path.name} already has rows for {len(skipped)} of the "
            f"{len(requested)} requested (doc_id, run_idx) pairs. These will be SKIPPED, "
            "not re-run:"
        )
        for doc_id, run_idx in sorted(skipped):
            print(f"  - {doc_id} run {run_idx}")
        if skipped == requested:
            print(
                "WARNING: every requested pair already exists, so this invocation will make "
                "NO API calls and write nothing. For a fresh pass, use a different --output."
            )
        print()

    first_pass_agent = FirstPassAgent()
    compliance_agent = ComplianceAgent()

    done = len(skipped)
    failed = 0
    total = len(requested)
    for doc in EVAL_DOCUMENTS:
        text = _load_doc_text(doc["file"])
        for run_idx in range(n_runs):
            if (doc["id"], run_idx) in skipped:
                continue
            try:
                first_pass = first_pass_agent.run(text)
                judgments = compliance_agent.evaluate(first_pass)
                report = build_compliance_report(first_pass, judgments)
            except Exception as exc:
                failed += 1
                _append_jsonl(
                    errors_path,
                    {"doc_id": doc["id"], "run_idx": run_idx, "error": repr(exc)},
                )
                print(f"[FAILED] {doc['id']} run {run_idx}: {exc!r} (logged to {errors_path}, continuing)")
                continue

            record = {
                "doc_id": doc["id"],
                "run_idx": run_idx,
                "ground_truth": doc["ground_truth"],
                "outcomes": {
                    key: {
                        "llm_status": getattr(report, key).llm_status,
                        "status": getattr(report, key).status,
                        "confidence": getattr(report, key).confidence,
                        "cited_source_count": len(getattr(report, key).cited_sources),
                        # Forward-looking fix, added alongside compliance.py's
                        # matching logging fix (see ARCHITECTURE.md "Evaluation
                        # notes"): the full cited source objects, not just a
                        # count, so a future main pass carries real per-claim
                        # citation data. Does not touch already-recorded rows.
                        "cited_sources": [s.model_dump() for s in getattr(report, key).cited_sources],
                        "reasoning": getattr(report, key).reasoning,
                    }
                    for key in OUTCOME_KEYS
                },
                "needs_human_review": report.needs_human_review,
            }
            # Only the price_and_value first_pass context is cached for the
            # variant comparison — that's the only outcome P8-04 varies.
            if run_idx == 0:
                record["_cached_price_and_value_context"] = first_pass.price_and_value_context.model_dump()
                record["_cached_fields"] = first_pass.document_fields.model_dump()

            _append_jsonl(output_path, record)
            done += 1
            print(f"[{done}/{total}] {doc['id']} run {run_idx}: "
                  f"{ {k: record['outcomes'][k]['llm_status'] for k in OUTCOME_KEYS} }")

    print(f"\nWrote {output_path} ({done}/{total} runs, {failed} failed)")


# --- prompt variant comparison for price_and_value (P8-04) ---

def cmd_variants(args) -> None:
    import instructor
    from anthropic import Anthropic

    n_runs = args.n_runs
    input_path = resolve_main_input(args.input)
    print(f"Main-pass input: {input_path}")
    main_records = _read_jsonl(input_path)
    cached_by_doc = {
        r["doc_id"]: r
        for r in main_records
        if "_cached_price_and_value_context" in r
    }
    missing = [d["id"] for d in EVAL_DOCUMENTS if d["id"] not in cached_by_doc]
    if missing:
        print(
            f"ERROR: missing cached price_and_value context in {input_path} for: {missing}. "
            "Run `main` first, or pass --input."
        )
        raise SystemExit(1)

    total_calls = len(EVAL_DOCUMENTS) * len(VARIANTS) * n_runs
    print(
        f"Running variant comparison: {len(EVAL_DOCUMENTS)} docs x {len(VARIANTS)} "
        f"variants x {n_runs} runs = {total_calls} Claude API calls (no extraction/"
        f"retrieval calls — reuses cached first-pass context)."
    )

    client = instructor.from_anthropic(Anthropic())
    done = 0
    for doc in EVAL_DOCUMENTS:
        cached = cached_by_doc[doc["id"]]
        fields = cached["_cached_fields"]
        context = cached["_cached_price_and_value_context"]
        evidence = "\n\n".join(
            f"[{s['index']}] (Source: {s['file_name']})\n{s['text_excerpt']}"
            for s in context["sources"]
        )
        user_message = (
            "Consumer Duty outcome under review: Price and Value\n\n"
            f'What the loan agreement states for this outcome:\n'
            f'Stated fees: "{fields["fees"]}"\n'
            f'Fair value justification: "{fields["fair_value_justification"]}"\n\n'
            f"Retrieved regulatory excerpts for this outcome:\n{evidence}"
        )

        for variant_name, system_prompt in VARIANTS.items():
            for run_idx in range(n_runs):
                judgment = client.messages.create(
                    model=ANTHROPIC_MODEL,
                    max_tokens=4096,  # see compliance.py: P8-06 structured-claim fields
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                    response_model=OutcomeJudgment,
                )
                sources_by_index = {s["index"]: s for s in context["sources"]}
                cited = [sources_by_index[i] for i in judgment.cited_sources if i in sources_by_index]
                confidence = min((s["similarity_score"] for s in cited), default=0.0)
                status = judgment.status if confidence >= CONFIDENCE_THRESHOLD else "insufficient_evidence"

                record = {
                    "doc_id": doc["id"],
                    "variant": variant_name,
                    "run_idx": run_idx,
                    "ground_truth": doc["ground_truth"]["price_and_value"],
                    "llm_status": judgment.status,
                    "status": status,
                    "confidence": confidence,
                    "cited_source_count": len(cited),
                }
                _append_jsonl(VARIANT_PASS_PATH, record)
                done += 1
                print(f"[{done}/{total_calls}] {doc['id']} {variant_name} run {run_idx}: {judgment.status}")

    print(f"\nWrote {VARIANT_PASS_PATH} ({done} judgments)")


# --- summary metrics (zero API cost, reads JSONL) ---

def _score_predictions(records: list[dict], status_field: str, outcome_key: str | None = None) -> dict:
    """
    records: list of {"ground_truth": "compliant"/"non_compliant", status_field: <llm status string>}
    Returns confusion counts + derived rates. "insufficient_evidence" is
    scored as an abstention, excluded from accuracy/FP/FN denominators and
    reported separately as abstention_rate over all samples.
    """
    tp = tn = fp = fn = abstain = 0
    for r in records:
        gt = r["ground_truth"] if outcome_key is None else r["ground_truth"][outcome_key]
        pred_raw = r[status_field] if outcome_key is None else r["outcomes"][outcome_key][status_field]
        if pred_raw == "insufficient_evidence":
            abstain += 1
            continue
        pred = "non_compliant" if pred_raw == "potentially_non_compliant" else "compliant"
        if gt == "non_compliant" and pred == "non_compliant":
            tp += 1
        elif gt == "compliant" and pred == "compliant":
            tn += 1
        elif gt == "compliant" and pred == "non_compliant":
            fp += 1
        elif gt == "non_compliant" and pred == "compliant":
            fn += 1
    n = tp + tn + fp + fn + abstain
    scored = tp + tn + fp + fn
    return {
        "n": n,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "abstain": abstain,
        "accuracy_excl_abstain": (tp + tn) / scored if scored else None,
        "false_positive_rate": fp / (fp + tn) if (fp + tn) else None,
        "false_negative_rate": fn / (fn + tp) if (fn + tp) else None,
        "abstention_rate": abstain / n if n else None,
    }


def cmd_summary(args) -> None:
    input_path = resolve_main_input(args.input)
    output_path = _summary_output_for(input_path)
    print(f"Main-pass input: {input_path}")
    main_records = _read_jsonl(input_path)
    variant_records = _read_jsonl(VARIANT_PASS_PATH)
    recall_data = json.loads(RECALL_PATH.read_text(encoding="utf-8")) if RECALL_PATH.exists() else None

    if not main_records:
        print(f"No main pass records found in {input_path} — run `main` first, or pass --input.")
        raise SystemExit(1)

    summary: dict = {"n_main_runs": len(main_records), "n_variant_runs": len(variant_records)}

    # Per-outcome, llm_status vs post-threshold status
    summary["by_outcome"] = {}
    for outcome_key in OUTCOME_KEYS:
        summary["by_outcome"][outcome_key] = {
            "llm_status": _score_predictions(main_records, "llm_status", outcome_key),
            "post_threshold_status": _score_predictions(main_records, "status", outcome_key),
        }

    # Confidence vs correctness (threshold validation)
    conf_correct = defaultdict(list)
    conf_incorrect = defaultdict(list)
    for r in main_records:
        for outcome_key in OUTCOME_KEYS:
            gt = r["ground_truth"][outcome_key]
            o = r["outcomes"][outcome_key]
            if o["llm_status"] == "insufficient_evidence":
                continue
            pred = "non_compliant" if o["llm_status"] == "potentially_non_compliant" else "compliant"
            bucket = conf_correct if pred == gt else conf_incorrect
            bucket[outcome_key].append(o["confidence"])

    summary["confidence_by_correctness"] = {
        outcome_key: {
            "correct_mean": (sum(conf_correct[outcome_key]) / len(conf_correct[outcome_key]))
            if conf_correct[outcome_key] else None,
            "correct_n": len(conf_correct[outcome_key]),
            "incorrect_mean": (sum(conf_incorrect[outcome_key]) / len(conf_incorrect[outcome_key]))
            if conf_incorrect[outcome_key] else None,
            "incorrect_n": len(conf_incorrect[outcome_key]),
        }
        for outcome_key in OUTCOME_KEYS
    }

    # Threshold sweep: at each candidate threshold, what fraction of
    # CORRECT llm_status judgments would be overridden to
    # insufficient_evidence (wasted human review) vs what fraction of
    # INCORRECT judgments would be caught (safety net working as intended)?
    sweep = {}
    for t in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
        overridden_correct = sum(1 for outcome_key in OUTCOME_KEYS for c in conf_correct[outcome_key] if c < t)
        total_correct = sum(len(conf_correct[k]) for k in OUTCOME_KEYS)
        overridden_incorrect = sum(1 for outcome_key in OUTCOME_KEYS for c in conf_incorrect[outcome_key] if c < t)
        total_incorrect = sum(len(conf_incorrect[k]) for k in OUTCOME_KEYS)
        sweep[str(t)] = {
            "correct_overridden_rate": overridden_correct / total_correct if total_correct else None,
            "incorrect_caught_rate": overridden_incorrect / total_incorrect if total_incorrect else None,
        }
    summary["threshold_sweep"] = sweep

    # Variant comparison (price_and_value only)
    if variant_records:
        by_variant = defaultdict(list)
        for r in variant_records:
            by_variant[r["variant"]].append(r)
        summary["price_and_value_variants"] = {
            variant_name: {
                "llm_status": _score_predictions(recs, "llm_status"),
                "post_threshold_status": _score_predictions(recs, "status"),
            }
            for variant_name, recs in by_variant.items()
        }

    if recall_data:
        summary["recall_at_k"] = {r["id"]: r["recall_at_k"] for r in recall_data}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8 evaluation harness")
    sub = parser.add_subparsers(dest="command", required=True)

    p_recall = sub.add_parser("recall", help="Retrieval recall@k (zero API cost)")
    p_recall.set_defaults(func=cmd_recall)

    p_main = sub.add_parser("main", help="Full pipeline pass (expensive)")
    p_main.add_argument("--n-runs", type=int, default=3)
    p_main.add_argument(
        "--output",
        help=f"Output JSONL (default: docs/{MAIN_PASS_V2_PATH.name}). The Phase 8 file is refused.",
    )
    p_main.set_defaults(func=cmd_main)

    p_variants = sub.add_parser("variants", help="price_and_value prompt variant comparison")
    p_variants.add_argument("--n-runs", type=int, default=3)
    p_variants.add_argument("--input", help=INPUT_HELP)
    p_variants.set_defaults(func=cmd_variants)

    p_summary = sub.add_parser("summary", help="Compute metrics from saved JSONL (zero API cost)")
    p_summary.add_argument(
        "--input",
        help=INPUT_HELP + " Output is written next to it as <input stem>_summary.json.",
    )
    p_summary.set_defaults(func=cmd_summary)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

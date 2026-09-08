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
            line per (doc, run) to docs/eval_raw_main_pass.jsonl as it goes,
            so a partial run is never silently lost.

  variants  Compares 2 system-prompt phrasings for the price_and_value
            judgment specifically (P8-04), reusing the first successful
            main-pass FirstPassResult per document as fixed input context
            (no extra extraction/retrieval calls) — only the judgment call
            itself is repeated, --n-runs times per variant per doc. Requires
            docs/eval_raw_main_pass.jsonl to exist (run `main` first).
            Appends to docs/eval_raw_variant_pass.jsonl.

  summary   Reads both JSONL files (and the recall@k JSON) and prints/saves
            computed metrics to docs/eval_summary.json. Does not call the
            API.

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
MAIN_PASS_PATH = DOCS_OUT_DIR / "eval_raw_main_pass.jsonl"
VARIANT_PASS_PATH = DOCS_OUT_DIR / "eval_raw_variant_pass.jsonl"
RECALL_PATH = DOCS_OUT_DIR / "eval_recall_at_k.json"
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

def cmd_main(args) -> None:
    n_runs = args.n_runs
    total_calls = len(EVAL_DOCUMENTS) * n_runs * 9
    print(
        f"Running main pass: {len(EVAL_DOCUMENTS)} docs x {n_runs} runs x 9 calls/run "
        f"= {total_calls} Claude API calls."
    )
    first_pass_agent = FirstPassAgent()
    compliance_agent = ComplianceAgent()

    done = 0
    for doc in EVAL_DOCUMENTS:
        text = _load_doc_text(doc["file"])
        for run_idx in range(n_runs):
            first_pass = first_pass_agent.run(text)
            judgments = compliance_agent.evaluate(first_pass)
            report = build_compliance_report(first_pass, judgments)

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

            _append_jsonl(MAIN_PASS_PATH, record)
            done += 1
            print(f"[{done}/{len(EVAL_DOCUMENTS) * n_runs}] {doc['id']} run {run_idx}: "
                  f"{ {k: record['outcomes'][k]['llm_status'] for k in OUTCOME_KEYS} }")

    print(f"\nWrote {MAIN_PASS_PATH} ({done} runs)")


# --- prompt variant comparison for price_and_value (P8-04) ---

def cmd_variants(args) -> None:
    import instructor
    from anthropic import Anthropic

    n_runs = args.n_runs
    main_records = _read_jsonl(MAIN_PASS_PATH)
    cached_by_doc = {
        r["doc_id"]: r
        for r in main_records
        if "_cached_price_and_value_context" in r
    }
    missing = [d["id"] for d in EVAL_DOCUMENTS if d["id"] not in cached_by_doc]
    if missing:
        print(f"ERROR: missing cached price_and_value context for: {missing}. Run `main` first.")
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
                    max_tokens=1024,
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


def cmd_summary(_args) -> None:
    main_records = _read_jsonl(MAIN_PASS_PATH)
    variant_records = _read_jsonl(VARIANT_PASS_PATH)
    recall_data = json.loads(RECALL_PATH.read_text(encoding="utf-8")) if RECALL_PATH.exists() else None

    if not main_records:
        print("No main pass records found — run `main` first.")
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

    DOCS_OUT_DIR.mkdir(exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {SUMMARY_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8 evaluation harness")
    sub = parser.add_subparsers(dest="command", required=True)

    p_recall = sub.add_parser("recall", help="Retrieval recall@k (zero API cost)")
    p_recall.set_defaults(func=cmd_recall)

    p_main = sub.add_parser("main", help="Full pipeline pass (expensive)")
    p_main.add_argument("--n-runs", type=int, default=3)
    p_main.set_defaults(func=cmd_main)

    p_variants = sub.add_parser("variants", help="price_and_value prompt variant comparison")
    p_variants.add_argument("--n-runs", type=int, default=3)
    p_variants.set_defaults(func=cmd_variants)

    p_summary = sub.add_parser("summary", help="Compute metrics from saved JSONL (zero API cost)")
    p_summary.set_defaults(func=cmd_summary)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

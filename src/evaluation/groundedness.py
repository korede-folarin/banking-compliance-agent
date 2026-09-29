"""
Groundedness / faithfulness cross-check for the Compliance Agent's reasoning.

New scope, not part of Phase 8's original plan (see feature_list.json's
P8-05 and ARCHITECTURE.md's "Groundedness cross-check (P8-05)" section for
why this exists, the paraphrase-tolerance-vs-overreach-detection tradeoff it
is designed around, and why two independent signals are compared rather than
either trusted alone).

Runs against the already-recorded docs/eval_raw_main_pass.jsonl, restricted
to run_idx == 0 rows, across all 4 outcomes. That restriction is a real,
structural data constraint, not a convenience:

- The raw log cached `_cached_fields` (the extracted LoanAgreementFields)
  only for run_idx == 0. Reconstructing which regulatory excerpts a
  judgment actually saw requires rebuilding that outcome's exact question
  text from the extracted fields (deterministic string formatting,
  `src.agent.first_pass.QUESTION_BUILDERS`) and replaying retrieval
  (deterministic given the question and the persisted Chroma index — spot-
  checked against the one outcome/run the raw log DOES cache verbatim,
  price_and_value run 0, and reproduced it exactly: same file names, same
  similarity scores, same text excerpts). For run_idx 1/2, fields were never
  cached and extract_fields() is a fresh, non-reproducible LLM call each
  run, so those rows are out of scope here.
- The raw log recorded `cited_source_count` (an int) per judgment, not
  which of the retrieved sources were actually cited. Both signals below
  are therefore computed against the FULL set of sources retrieved for
  that outcome/document (typically 5) — what the compliance judgment
  actually had in front of it — not strictly the cited subset. Documented
  here and in ARCHITECTURE.md, not silently assumed.
- `insufficient_evidence` judgments are excluded: cited_sources is empty by
  design for them (OutcomeJudgment's own field description), and their
  reasoning explains an evidence gap rather than asserting a compliance
  finding against evidence — there is nothing to fact-check.

Two signals, neither trusted alone:

  Signal 1 (mechanical, zero API cost): embedding similarity (same local
  model used everywhere else in this project, BAAI/bge-small-en-v1.5)
  between the judgment's full reasoning text and each retrieved source
  excerpt; the maximum across sources is the score. Coarse and paraphrase-
  tolerant — high similarity is weak positive evidence (the reasoning
  resembles some retrieved text, not proof it is a correct or non-
  overreaching characterization of it), low similarity is a stronger red
  flag (the reasoning doesn't resemble anything it was shown).

  Signal 2 (narrow LLM claim-check, new API calls): the reasoning is split
  into individual sentence-level claims by a mechanical, non-LLM extraction
  step (regex sentence splitting, not an LLM call), then each claim is
  checked with its own narrow LLM call — "does this specific claim appear,
  in substance, in this source text: yes / no / partially" — never a single
  holistic "is this grounded" judgment.

  Comparison: cases where the two signals agree (high similarity + all
  claims supported, or low similarity + a flagged/unsupported claim) are
  lower priority. Cases where they DISAGREE are the actual output of
  interest, flagged for human review.

Subcommands:
  plan   Reconstructs sources (retrieval replay) + Signal 1 (local
         embeddings) + mechanical claim extraction for every in-scope
         judgment. Zero API cost. Prints the exact number of Signal-2 LLM
         calls a `run` would make, for approval before spending anything.
  run    Does everything `plan` does, plus the Signal-2 per-claim LLM
         calls, the signal comparison, and writes docs/eval_groundedness.md.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.agent.first_pass import QUESTION_BUILDERS  # noqa: E402
from src.agent.schemas import LoanAgreementFields  # noqa: E402
from src.agent.uncertainty import _cosine_similarity, _get_embed_model  # noqa: E402
from src.config import ANTHROPIC_MODEL  # noqa: E402
from src.retrieval.query_engine import load_index  # noqa: E402
from tests.fixtures.eval_set import OUTCOME_KEYS  # noqa: E402

DOCS_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "docs"
MAIN_PASS_PATH = DOCS_OUT_DIR / "eval_raw_main_pass.jsonl"
GROUNDEDNESS_OUT_PATH = DOCS_OUT_DIR / "eval_groundedness.md"

# Descriptive-only bucket boundary for Signal 1, used solely to label rows
# "high"/"low" similarity in the comparison table below. NOT a system
# config value, NOT CONFIDENCE_THRESHOLD, and not calibrated against this
# evaluation set — chosen as a round number sitting between this project's
# own prior empirical finding (src/agent/uncertainty.py: correct free-text
# extractions scored 0.80-0.92 similarity, fabricated ones 0.55-0.67 on the
# same documents) and the retrieval-similarity range this project's
# compliance judgments actually operate in (~0.60-0.70, see
# docs/eval_results.md). No claim is made that 0.75 is "correct" for this
# purpose; it exists only so the report has readable buckets.
SIGNAL1_HIGH_THRESHOLD = 0.75

CLAIM_MIN_LENGTH = 25

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"])")

CLAIM_CHECK_SYSTEM_PROMPT = (
    "You are fact-checking exactly one specific claim from a compliance "
    "analyst's reasoning against specific regulatory source text. Do not "
    "evaluate the claim's overall quality, relevance, phrasing, or the "
    "reasoning as a whole — judge ONLY whether this one claim is supported "
    "by the source text provided.\n\n"
    "Respond with exactly one verdict:\n"
    '- "yes": the claim is directly and substantively supported by the '
    "source text.\n"
    '- "partially": the source text supports part of the claim, or '
    "supports it with a material difference in scope, degree, or "
    "condition, but not the claim as fully stated.\n"
    '- "no": the source text does not address the claim, or contradicts '
    "it."
)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def extract_claims(reasoning: str) -> list[str]:
    """
    Mechanical, non-LLM claim extraction: split reasoning into sentences and
    drop fragments too short to be a standalone factual claim. Deliberately
    simple (regex sentence splitting, a length filter) rather than an LLM
    extraction step, per this feature's design: the extraction stays as
    close to mechanical as possible, so the only open-ended judgment call in
    the whole pipeline is the single, narrow, per-claim LLM check downstream
    (Signal 2), not claim identification itself.
    """
    sentences = _SENTENCE_SPLIT_RE.split(reasoning.strip())
    return [s.strip() for s in sentences if len(s.strip()) >= CLAIM_MIN_LENGTH]


def reconstruct_sources(retriever, fields: LoanAgreementFields, outcome_key: str) -> list[dict]:
    """
    Replays retrieval (zero API cost, deterministic given the question and
    the persisted index) to reconstruct the set of sources a judgment for
    this outcome/document actually saw. Matches
    src.retrieval.query_engine.QueryEngine.query()'s own source-building
    exactly (same 300-char excerpt truncation), since that's what's being
    reconstructed. Spot-checked against the one outcome/run the raw eval
    log DOES cache verbatim (price_and_value, run_idx 0) and reproduced it
    exactly.
    """
    question = QUESTION_BUILDERS[outcome_key](fields)
    nodes = retriever.retrieve(question)
    return [
        {
            "index": i,
            "file_name": node.metadata.get("file_name", "unknown"),
            "similarity_score": node.score or 0.0,
            "text_excerpt": node.text[:300],
        }
        for i, node in enumerate(nodes, start=1)
    ]


def compute_signal1(reasoning: str, sources: list[dict]) -> float:
    """
    Mechanical groundedness signal: maximum cosine similarity between the
    judgment's reasoning text and any single retrieved source excerpt.
    Coarse and paraphrase-tolerant by construction (same embedding model,
    same cosine-similarity helper, as src.agent.uncertainty's free-text
    field check) — see this module's docstring for what high/low similarity
    here does and does not indicate.
    """
    if not sources:
        return 0.0
    embed_model = _get_embed_model()
    reasoning_embedding = embed_model.get_text_embedding(reasoning)
    return max(
        _cosine_similarity(reasoning_embedding, embed_model.get_text_embedding(s["text_excerpt"]))
        for s in sources
    )


def compute_signal1_cited(reasoning: str, cited_sources: list[dict]) -> dict:
    """
    Signal 1 against the judgment's LOGGED cited chunks only (available for
    any run recorded after the citation-logging fix, see ARCHITECTURE.md
    "Evaluation notes"), not the full retrieved set. Returns every per-chunk
    cosine similarity (reasoning vs. cited chunk text as shown to the judge)
    plus the minimum and the mean. No pass/fail threshold is applied here or
    anywhere downstream; it is a logged measurement only.

    compute_signal1 above (max over the full retrieved set) is kept only for
    the pre-fix Phase 8 data, where which sources were cited was never
    recorded.
    """
    if not cited_sources:
        return {"per_chunk": [], "min": None, "mean": None}
    embed_model = _get_embed_model()
    reasoning_embedding = embed_model.get_text_embedding(reasoning)
    per_chunk = [
        {
            "index": s["index"],
            "score": _cosine_similarity(reasoning_embedding, embed_model.get_text_embedding(s["text_excerpt"])),
        }
        for s in cited_sources
    ]
    scores = [c["score"] for c in per_chunk]
    return {"per_chunk": per_chunk, "min": min(scores), "mean": sum(scores) / len(scores)}


def build_scope(main_records: list[dict]) -> list[dict]:
    """
    Builds the full in-scope judgment list (run_idx == 0, all 4 outcomes,
    llm_status != insufficient_evidence) with reconstructed sources, Signal
    1, and extracted claims. Zero API cost — safe to call from `plan`.
    """
    retriever = load_index().as_retriever(similarity_top_k=5)

    scope: list[dict] = []
    for r in main_records:
        if r["run_idx"] != 0:
            continue
        fields = LoanAgreementFields(**r["_cached_fields"])
        for outcome_key in OUTCOME_KEYS:
            o = r["outcomes"][outcome_key]
            if o["llm_status"] == "insufficient_evidence":
                continue
            sources = reconstruct_sources(retriever, fields, outcome_key)
            signal1 = compute_signal1(o["reasoning"], sources)
            claims = extract_claims(o["reasoning"])
            scope.append(
                {
                    "doc_id": r["doc_id"],
                    "outcome": outcome_key,
                    "ground_truth": r["ground_truth"][outcome_key],
                    "llm_status": o["llm_status"],
                    "reasoning": o["reasoning"],
                    "sources": sources,
                    "signal1": signal1,
                    # Only rows recorded after the citation-logging fix carry
                    # "cited_sources"; the current Phase 8 data does not, so
                    # this is None for every row in it.
                    "signal1_cited": (
                        compute_signal1_cited(o["reasoning"], o["cited_sources"]) if "cited_sources" in o else None
                    ),
                    "claims": claims,
                }
            )
    return scope


def cmd_plan(_args) -> None:
    main_records = _read_jsonl(MAIN_PASS_PATH)
    if not main_records:
        print(f"No records found at {MAIN_PASS_PATH} — run `python -m src.evaluation.run_eval main` first.")
        raise SystemExit(1)

    scope = build_scope(main_records)
    total_claims = sum(len(j["claims"]) for j in scope)
    zero_claim_judgments = [j for j in scope if not j["claims"]]

    print(f"In-scope judgments (run_idx=0, all 4 outcomes, llm_status != insufficient_evidence): {len(scope)}")
    by_outcome: dict[str, int] = {}
    for j in scope:
        by_outcome[j["outcome"]] = by_outcome.get(j["outcome"], 0) + 1
    for k in OUTCOME_KEYS:
        print(f"  {k}: {by_outcome.get(k, 0)} judgments")
    print(f"\nMechanical claims extracted (regex sentence split, zero API cost): {total_claims}")
    if zero_claim_judgments:
        print(
            f"  {len(zero_claim_judgments)} judgment(s) produced 0 claims after the "
            f"{CLAIM_MIN_LENGTH}-char length filter (short reasoning text) — these "
            "will be reported with signal2 = 'no_claims', not silently dropped."
        )
    print(f"\nSignal 1 (embedding similarity) computed for all {len(scope)} judgments — zero API cost.")
    print(
        f"\n=> Running `run` would make exactly {total_claims} additional Claude API "
        "calls (one per extracted claim, Signal 2 only). No extraction or compliance-"
        "judgment calls are repeated."
    )


def check_claim(client, claim: str, source_text: str) -> str:
    from pydantic import BaseModel
    from typing import Literal

    class ClaimVerdict(BaseModel):
        verdict: Literal["yes", "no", "partially"]

    result = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=256,
        system=CLAIM_CHECK_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"SOURCE TEXT (retrieved regulatory excerpts):\n{source_text}\n\nCLAIM:\n{claim}",
            }
        ],
        response_model=ClaimVerdict,
    )
    return result.verdict


def _signal2_bucket(verdicts: list[str]) -> str:
    if not verdicts:
        return "no_claims"
    if any(v == "no" for v in verdicts):
        return "flagged"
    if any(v == "partially" for v in verdicts):
        return "partial"
    return "clean"


def _agreement(signal1: float, signal2_bucket: str) -> str:
    signal1_bucket = "high" if signal1 >= SIGNAL1_HIGH_THRESHOLD else "low"
    if signal2_bucket == "no_claims":
        return "no_claims"
    if signal1_bucket == "high" and signal2_bucket == "clean":
        return "agree_grounded"
    if signal1_bucket == "low" and signal2_bucket in ("flagged", "partial"):
        return "agree_flagged"
    return "disagreement"


def cmd_run(_args) -> None:
    import instructor
    from anthropic import Anthropic

    main_records = _read_jsonl(MAIN_PASS_PATH)
    if not main_records:
        print(f"No records found at {MAIN_PASS_PATH} — run `python -m src.evaluation.run_eval main` first.")
        raise SystemExit(1)

    scope = build_scope(main_records)
    total_claims = sum(len(j["claims"]) for j in scope)
    print(f"Running Signal 2: {total_claims} narrow per-claim LLM calls across {len(scope)} judgments.")

    client = instructor.from_anthropic(Anthropic())
    done = 0
    for j in scope:
        source_text = "\n\n".join(s["text_excerpt"] for s in j["sources"])
        verdicts = []
        for claim in j["claims"]:
            verdict = check_claim(client, claim, source_text)
            verdicts.append(verdict)
            done += 1
            print(f"[{done}/{total_claims}] {j['doc_id']} {j['outcome']}: {verdict}")
        j["claim_verdicts"] = list(zip(j["claims"], verdicts))
        j["signal2_bucket"] = _signal2_bucket(verdicts)
        j["agreement"] = _agreement(j["signal1"], j["signal2_bucket"])

    _write_report(scope)
    print(f"\nWrote {GROUNDEDNESS_OUT_PATH}")


def _write_report(scope: list[dict]) -> None:
    counts: dict[str, int] = {}
    for j in scope:
        counts[j["agreement"]] = counts.get(j["agreement"], 0) + 1

    lines = []
    lines.append("# Groundedness / Faithfulness Cross-Check (P8-05)")
    lines.append("")
    lines.append(
        "New scope, not part of Phase 8's original plan — see feature_list.json's "
        "P8-05 and ARCHITECTURE.md's \"Groundedness cross-check (P8-05)\" section "
        "for the design rationale (why two independent signals, why neither is "
        "trusted alone) and the class-of-project-methodology caveat (this is this "
        "project's own applied approach, not a settled technique drawn from "
        "established literature)."
    )
    lines.append("")
    lines.append(
        "**Scope**: run_idx == 0 rows only, all 4 outcomes, judgments where "
        "`llm_status` is `compliant` or `potentially_non_compliant` (not "
        "`insufficient_evidence`, which has no cited evidence to check by "
        "design). See this file's generating script, "
        "`src/evaluation/groundedness.py`, for why run_idx 0 specifically, and "
        "why both signals are computed against the full retrieved source set "
        "rather than a reconstructed \"cited-only\" subset — both are real, "
        "structural data-availability constraints from the original eval log, "
        "not a convenience."
    )
    lines.append("")
    lines.append(f"**Total in-scope judgments**: {len(scope)}")
    lines.append(f"**Total Signal-2 LLM calls made**: {sum(len(j['claims']) for j in scope)}")
    lines.append("")
    lines.append("## Signal agreement vs. disagreement")
    lines.append("")
    lines.append("| Category | Count | Meaning |")
    lines.append("|---|---|---|")
    lines.append(
        f"| agree_grounded | {counts.get('agree_grounded', 0)} | Signal 1 high "
        f"(>= {SIGNAL1_HIGH_THRESHOLD}) AND Signal 2 all claims supported — lower priority |"
    )
    lines.append(
        f"| agree_flagged | {counts.get('agree_flagged', 0)} | Signal 1 low "
        f"(< {SIGNAL1_HIGH_THRESHOLD}) AND Signal 2 flagged/partial — lower priority, both "
        "signals independently suggest a problem |"
    )
    lines.append(
        f"| disagreement | {counts.get('disagreement', 0)} | Signals disagree — "
        "**flagged for human review below** |"
    )
    lines.append(
        f"| no_claims | {counts.get('no_claims', 0)} | Reasoning produced 0 claims "
        f"after mechanical extraction (< {CLAIM_MIN_LENGTH} chars) — Signal 2 not "
        "computed, not counted as agreement or disagreement |"
    )
    lines.append("")
    lines.append("## Disagreement cases (for human review)")
    lines.append("")
    disagreements = [j for j in scope if j["agreement"] == "disagreement"]
    if not disagreements:
        lines.append("None observed in this run.")
    for j in disagreements:
        lines.append(f"### {j['doc_id']} / {j['outcome']} (llm_status: {j['llm_status']})")
        lines.append("")
        lines.append(f"- Signal 1 (max embedding similarity to retrieved sources): {j['signal1']:.4f}")
        lines.append(f"- Signal 2 bucket: {j['signal2_bucket']}")
        lines.append("- Per-claim verdicts:")
        for claim, verdict in j["claim_verdicts"]:
            lines.append(f"  - `{verdict}`: {claim}")
        lines.append(f"- Full reasoning: {j['reasoning']}")
        lines.append("")
    lines.append("## All in-scope judgments")
    lines.append("")
    lines.append("| doc_id | outcome | llm_status | signal1 | signal2 | agreement |")
    lines.append("|---|---|---|---|---|---|")
    for j in scope:
        lines.append(
            f"| {j['doc_id']} | {j['outcome']} | {j['llm_status']} | {j['signal1']:.4f} | "
            f"{j.get('signal2_bucket', 'n/a')} | {j.get('agreement', 'n/a')} |"
        )
    lines.append("")

    DOCS_OUT_DIR.mkdir(exist_ok=True)
    GROUNDEDNESS_OUT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Groundedness/faithfulness cross-check (P8-05)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="Zero-API-cost dry run: reports exact Signal-2 call count")
    p_plan.set_defaults(func=cmd_plan)

    p_run = sub.add_parser("run", help="Runs Signal 2 (real API calls) and writes docs/eval_groundedness.md")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

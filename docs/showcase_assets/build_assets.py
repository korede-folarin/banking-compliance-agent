"""
Builds the showcase evidence assets in docs/showcase_assets/ from files that
already exist. Read-only with respect to every source: it opens the saved
full-pass outputs and the local Chroma index for reading, and writes only
into this folder. Zero API calls (no Anthropic client is constructed; no
embedding model is loaded).

Run from the repo root:
    python docs/showcase_assets/build_assets.py

Assets 6 (pytest line) and the system flow are written by hand from a
command run / the code; see INDEX.md.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
MAIN = DOCS / "eval_raw_main_pass_v2.jsonl"
CHECKS = DOCS / "eval_raw_main_pass_v2_claim_judgments_checks_results.jsonl"
RETRIES = DOCS / "eval_raw_main_pass_v2_retries.jsonl"
ERRORS = DOCS / "eval_raw_main_pass_v2_errors.jsonl"
SUMMARY = DOCS / "eval_raw_main_pass_v2_summary.json"

DISCLAIMER = ("All loan documents, borrowers and lenders referred to here are synthetic "
              "(data/synthetic_docs/). Regulatory text is from the FCA corpus in "
              "data/regulatory_corpus/.")

# The judgments used in assets 1, 3 and 4 (chosen by the criteria stated in INDEX.md).
ASSET1 = ("loan_agreement_1", 1, "price_and_value")
ASSET2 = ("loan_agreement_1", 0)  # only run 0 rows carry the saved retrieval query
FIVE = [
    ("loan_agreement_1", 1, "price_and_value"),
    ("loan_agreement_4", 0, "price_and_value"),
    ("loan_agreement_13", 1, "consumer_support"),
    ("loan_agreement_13", 2, "consumer_support"),
    ("loan_agreement_11", 1, "price_and_value"),
]
EXPECTED = {"non_compliant": "potentially_non_compliant", "compliant": "compliant"}
THRESHOLD = 0.65  # CONFIDENCE_THRESHOLD as recorded for the full pass (.env / src/config.py default)


def redact(text: str) -> str:
    text = re.sub(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", "<USER_HOME>", text)
    text = re.sub(r"sk-ant-[A-Za-z0-9_\-]+", "<REDACTED_KEY>", text)
    return text


def write(name: str, text: str) -> None:
    (OUT / name).write_text(redact(text), encoding="utf-8")
    print("wrote", name)


def jl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main_rows() -> dict:
    return {(r["doc_id"], r["run_idx"]): r for r in jl(MAIN)}


def page_labels() -> dict:
    """node id -> (file_name, page_label), read from the local Chroma index."""
    sys.path.insert(0, str(ROOT))
    from src.evaluation.negative_control import load_corpus_meta
    return {m["id"]: (m["file_name"], m["page_label"]) for m in load_corpus_meta()}


def asset1(rows: dict) -> None:
    doc, run, outcome = ASSET1
    row = rows[(doc, run)]
    o = row["outcomes"][outcome]
    chunks = {s["index"]: s for s in o["retrieved_sources"]}
    chk = next(c for c in jl(CHECKS) if (c["doc_id"], c["run_idx"], c["outcome"]) == ASSET1)
    j = o["judgment"]
    L = [f"# Asset 1: one complete judgment, {doc} run {run}, {outcome}", "", DISCLAIMER, "",
         f"- Ground truth (planted label): `{row['ground_truth'][outcome]}`",
         f"- Judge (LLM) status: `{o['llm_status']}`",
         f"- Status after validation layer: `{o['status']}`",
         f"- Confidence (min similarity of cited sources): {o['confidence']:.4f} (threshold {THRESHOLD})",
         f"- Cited excerpts: {j['cited_sources']}",
         f"- Claim check (LLM, sees claim + chunk only) verdicts: "
         f"{[r['llm_check']['verdict'] for r in chk['regulatory_requirements']]}", "",
         "## Judge reasoning (verbatim)", "", o["reasoning"], "",
         "## Regulatory claims: claim, verbatim quote, source excerpt, claim-check verdict", ""]
    for n, req in enumerate(chk["regulatory_requirements"], 1):
        L += [f"### Claim {n}", "", f"**Claim:** {req['claim']}", ""]
        for s in req["sources"]:
            c = chunks[s["excerpt_number"]]
            L += [f"**Verbatim quote (cites excerpt [{s['excerpt_number']}]):** \"{s['verbatim_quote']}\"", "",
                  f"- Quote check (deterministic): found in `{s['quote_location']}`, match type `{s['match_type']}`",
                  f"- Excerpt [{s['excerpt_number']}]: `{c['file_name']}`, retrieval similarity "
                  f"{c['similarity_score']:.4f}, node `{c['node_id']}`", "",
                  "Excerpt text exactly as the judge saw it (whole chunk):", "", "```text", c["text_excerpt"].strip(), "```", ""]
        lc = req["llm_check"]
        L += [f"**Claim-check verdict:** `{lc['verdict']}`", "",
              f"Supporting sentence the checker gave: \"{lc['supporting_sentence']}\" "
              f"(found in chunk: `{lc['supporting_sentence_match_type']}`)", ""]
    L += ["## Document facts (quotes from the synthetic loan agreement)", ""]
    for f in chk["document_facts"]:
        L += [f"- **Claim:** {f['claim']}", f"  - Quote: \"{f['verbatim_quote']}\"",
              f"  - Found in document: `{f['document_match']['match_type']}`"]
    L += ["", "## Absences the judge recorded", ""]
    for a in chk["absences"]:
        L += [f"- **{a['kind']}:** {a['claim']}", f"  - {a['explanation']}"]
    write("01_judgment_with_claim_check.md", "\n".join(L) + "\n")


def asset2(rows: dict, pages: dict) -> None:
    row = rows[ASSET2]
    ctx = row["_cached_price_and_value_context"]
    L = [f"# Asset 2: retrieval example, {ASSET2[0]} run {ASSET2[1]}, price_and_value query", "", DISCLAIMER, "",
         "Saved by `run_eval main` at run time (`_cached_price_and_value_context`). Retriever: "
         "`QueryEngine` over Chroma collection `regulatory_corpus`, embeddings `BAAI/bge-small-en-v1.5`, "
         "top k = 5 (`src/config.py` QUERY_SIMILARITY_TOP_K). Page labels looked up in the local "
         "Chroma index by node id.", "",
         "## Query (built by `first_pass.build_price_and_value_question` from the extracted fields)", "",
         "```text", ctx["question"], "```", "",
         "## Top 5 retrieved chunks", "",
         "| Rank | Source file | Page | Similarity | Node id |", "|---|---|---|---|---|"]
    for s in ctx["sources"]:
        f, p = pages.get(s["node_id"], (s["file_name"], "?"))
        L.append(f"| {s['index']} | {s['file_name']} | {p} | {s['similarity_score']:.4f} | `{s['node_id']}` |")
    L += ["", f"Retrieval-level confidence on this result (min similarity): {ctx['confidence']:.4f}.", "",
          "The QueryEngine also produced an LLM-written `answer` for this query; the judge does not use it "
          "(it receives the chunks, not the answer), so it is not reproduced here.", ""]
    for s in ctx["sources"]:
        L += [f"### [{s['index']}] {s['file_name']}, page {pages.get(s['node_id'], ('', '?'))[1]}", "",
              "```text", s["text_excerpt"].strip(), "```", ""]
    write("02_retrieval_example.md", "\n".join(L))


def asset3(rows: dict) -> None:
    doc, run, _ = ASSET1
    fields = rows[(doc, run)]["_cached_fields"]
    write("03_extracted_loan_terms.json", json.dumps(
        {"_disclaimer": "Synthetic document. " + DISCLAIMER,
         "_source": f"docs/eval_raw_main_pass_v2.jsonl, row {doc} run {run}, field _cached_fields",
         "_schema": "src/agent/schemas.py LoanAgreementFields (output of src/agent/intake.py extract_fields)",
         "document": f"data/synthetic_docs/{doc}.txt",
         "fields": fields}, indent=2, ensure_ascii=False) + "\n")


def asset4(rows: dict) -> None:
    summ = json.loads(SUMMARY.read_text(encoding="utf-8"))
    L = ["# Asset 4: confidence inputs", "", DISCLAIMER, "",
         "## What feeds the confidence score", "",
         "`src/agent/compliance.py` `compute_confidence` / `validate_outcome`:",
         "- **One input:** the retrieval similarity score of each source the judge cited "
         "(cosine similarity between the retrieval query and the chunk, from the vector store).",
         "- **Aggregation:** the minimum over cited sources; 0.0 if none cited.",
         f"- **Rule:** if confidence < {THRESHOLD}, the status is replaced by `insufficient_evidence`.",
         "", "Not inputs: the judge's own status or reasoning, claim-to-chunk similarity (Signal 1), "
         "the quote check, the LLM claim check, and extraction confidence (`src/agent/uncertainty.py`, "
         "which is not called by the main path).", "",
         "## Five judgments from the full pass", "",
         "| Doc / run / outcome | Ground truth | Judge status | Correct? | Cited similarities | Confidence (min) | Final status |",
         "|---|---|---|---|---|---|---|"]
    for doc, run, outc in FIVE:
        r = rows[(doc, run)]
        o = r["outcomes"][outc]
        gt = r["ground_truth"][outc]
        sims = ", ".join(f"{s['similarity_score']:.4f}" for s in o["cited_sources"])
        L.append(f"| {doc} / {run} / {outc} | {gt} | {o['llm_status']} | "
                 f"{'yes' if EXPECTED[gt] == o['llm_status'] else 'no'} | {sims} | {o['confidence']:.4f} | {o['status']} |")
    L += ["", "## Across all 45 runs (from `eval_raw_main_pass_v2_summary.json`)", "",
          "| Outcome | Correct: mean confidence (n) | Incorrect: mean confidence (n) |", "|---|---|---|"]
    for k, v in summ["confidence_by_correctness"].items():
        inc = f"{v['incorrect_mean']:.4f} ({v['incorrect_n']})" if v["incorrect_mean"] is not None else f"none ({v['incorrect_n']})"
        L.append(f"| {k} | {v['correct_mean']:.4f} ({v['correct_n']}) | {inc} |")
    L += ["", "| Threshold | Correct judgments overridden | Incorrect judgments caught |", "|---|---|---|"]
    for t, v in summ["threshold_sweep"].items():
        L.append(f"| {t} | {v['correct_overridden_rate']:.3f} | {v['incorrect_caught_rate']:.3f} |")
    L += ["", "## What the score does and does not separate (facts from the tables above)", "",
          "- It separates judgments by how closely the cited chunks matched the retrieval query. "
          "Below 0.65 the judgment is withheld and routed to review.",
          "- It does not separate correct from incorrect judgments in this pass: per outcome, the mean "
          "confidence of correct and incorrect judgments differs by at most 0.0123.",
          "- Rows 3 and 4 are the same document and outcome: confidence 0.6997 (correct) and 0.6995 "
          "(incorrect). Both pass the threshold.",
          "- Row 2 is correct and is overridden (0.6349). Row 5 is incorrect and is overridden (0.6444).",
          "- At 0.65, 0.5 of correct judgments are overridden and 0.625 of incorrect judgments are caught.", ""]
    write("04_confidence_inputs.md", "\n".join(L))


def asset5() -> None:
    progress = (ROOT / "progress.md").read_text(encoding="utf-8").splitlines()
    i = next(n for n, l in enumerate(progress) if "silently falls back to reading" in l)
    excerpt = "\n".join(progress[i:i + 8])
    retries = jl(RETRIES)
    errors = jl(ERRORS)
    keys = {}
    for r in retries:
        m = re.search(r"'(\$PARAMETER_[A-Za-z_]+)'", r["error"])
        k = m.group(1) if m else "other"
        keys[k] = keys.get(k, 0) + 1
    by_outcome, by_attempt = {}, {}
    for r in retries:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
        by_attempt[r["attempt_number"]] = by_attempt.get(r["attempt_number"], 0) + 1
    short = sum(1 for r in retries if (r.get("output_tokens") or 0) < 200)

    def logline(r):
        r = dict(r)
        r["error"] = r["error"].split("\n")[0] + " ... (first line of the error; full text in the source file)"
        return json.dumps(r, ensure_ascii=False)

    L = ["# Asset 5: failure record", "", DISCLAIMER, "",
         "## A. 5,540 garbage chunks: silent ingestion failure (2026-08-20)", "",
         "**What happened.** `SimpleDirectoryReader` (`src/ingestion/ingest.py`) fell back to reading raw PDF "
         "bytes as text because `llama-index-readers-file` was not installed. The run reported success with "
         "5,540 chunks; every chunk was binary PDF data.", "",
         "**How it was found.** By opening and reading sample chunks, not from the exit code or logs.", "",
         "**What changed (commit `cb3a7dd`, 2026-08-20):**",
         "- `requirements.txt`: added `llama-index-readers-file>=0.4.0`.",
         "- Re-ingested: 558 chunks of real text across the 3 PDFs.",
         "- `tests/test_ingestion.py::test_chunks_contain_real_text_not_raw_pdf_bytes` added, with source "
         "coverage and retrieval-relevance tests.", "",
         "**Log lines.** No log of the failed run was saved. The real records are the session note and the "
         "commit message, quoted verbatim:", "",
         "`progress.md` (Session 2):", "", "```text", excerpt, "```", "",
         "Commit `cb3a7dd` message (`git show -s cb3a7dd`), excerpt:", "", "```text",
         "SimpleDirectoryReader silently reads raw PDF\nbytes as text without llama-index-readers-file installed (5540 \"chunks\"\n"
         "that were actually binary PDF data)", "```", "",
         "## B. Placeholder tool-argument retries (full pass, 2026-10-07)", "",
         f"Source: `docs/eval_raw_main_pass_v2_retries.jsonl` ({len(retries)} records, written by the "
         "observe-only hooks in `src/agent/retry_log.py`).", "",
         f"- Records: {len(retries)}, all `call_site: judge`, all `ValidationError`.",
         f"- Wrapper key in the tool arguments: {json.dumps(keys)}.",
         f"- Failed attempt number: {json.dumps(by_attempt)} (attempt 1 failed then 2 succeeded; attempt 2 "
         "failed then 3 succeeded).",
         f"- Last-attempt failures: {sum(1 for r in retries if r['is_last_attempt'])} (none hard-failed).",
         f"- Under 200 output tokens: {short}; the rest carried a full judgment inside the wrapper.",
         f"- By outcome: {json.dumps(by_outcome)}.",
         f"- All `stop_reason: tool_use` with 1 tool call: "
         f"{all(r['stop_reason'] == 'tool_use' and r['tool_use_count'] == 1 for r in retries)}.", "",
         "**Fix: none applied.** Recorded as a known limitation (`progress.md`, Session 25; "
         "ARCHITECTURE.md \"Evaluation notes\"). instructor's retry recovered every one. Cost, per `progress.md`: the second resume "
         "sent 337 requests against 288 nominal, a difference of 49, matching the 49 records.", "",
         "Real log lines (first two records; error text cut to its first line):", "", "```json",
         logline(retries[0]), logline(retries[1]), "```", "",
         "## C. Related, and fixed: parallel tool-use HTTP 400s (same pass)", "",
         f"Source: `docs/eval_raw_main_pass_v2_errors.jsonl` ({len(errors)} records, before the fix). "
         "Fix: `src/agent/structured_output.single_tool_choice` sets `disable_parallel_tool_use: True` on all "
         "6 structured calls; tested in `tests/test_single_tool_choice.py`. After the fix: 0 hard failures; "
         "both failed runs were redone.", "", "```json"] + [json.dumps(e, ensure_ascii=False) for e in errors] + ["```", ""]
    write("05_failure_record.md", "\n".join(L))


def asset7() -> None:
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    L = ["# Asset 7: evaluation numbers (full pass v2)", "", DISCLAIMER, "",
         f"Source: `docs/eval_raw_main_pass_v2_summary.json`. Runs: {s['n_main_runs']} (15 documents x 3). "
         f"Completeness warnings recorded in the file: {s['completeness_warnings']}.", "",
         "Positive class = non-compliant. `llm_status` = the judge's verdict; `post_threshold_status` = after "
         "the confidence override. Abstain = `insufficient_evidence`.", "",
         "| Outcome | Stage | n | TP | TN | FP | FN | Abstain | Accuracy (excl. abstain) | FPR | FNR | Abstention rate |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda x: "n/a" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))
    for o, d in s["by_outcome"].items():
        for stage, m in d.items():
            L.append(f"| {o} | {stage} | {m['n']} | {m['tp']} | {m['tn']} | {m['fp']} | {m['fn']} | {m['abstain']} | "
                     f"{f(m['accuracy_excl_abstain'])} | {f(m['false_positive_rate'])} | {f(m['false_negative_rate'])} | "
                     f"{f(m['abstention_rate'])} |")
    L += ["", "## Recall@k (retrieval)", "", "| Query set | @1 | @2 | @3 | @5 | @10 |", "|---|---|---|---|---|---|"]
    for o, d in s["recall_at_k"].items():
        L.append(f"| {o} | " + " | ".join(f(d[k]) for k in ("1", "2", "3", "5", "10")) + " |")
    L += ["", "Confidence by correctness and the threshold sweep are in `04_confidence_inputs.md`.", ""]
    write("07_evaluation_numbers.md", "\n".join(L))


if __name__ == "__main__":
    rows = main_rows()
    asset1(rows)
    asset2(rows, page_labels())
    asset3(rows)
    asset4(rows)
    asset5()
    asset7()

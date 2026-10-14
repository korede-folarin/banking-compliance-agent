"""
Images for video clips 9 (build status) and 10 (confidence signals).

1. Writes 08_confidence_signals.md from the saved full-pass data (every value
   read from docs/eval_raw_main_pass_v2*.jsonl / _summary.json).
2. Renders images/04-07 from line ranges of the asset files, using the same
   renderer as build_images.py: every drawn line is read from a file.

Zero API calls. Run from the repo root:
    python docs/showcase_assets/build_video_images.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from build_images import file_lines, render, rows  # noqa: E402

DOCS = ROOT / "docs"
KEY = ("loan_agreement_1", 1, "price_and_value")
DISCLAIMER = "Synthetic loan document (data/synthetic_docs/). Regulatory text: FCA corpus."


def jl(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_signals_page() -> Path:
    main = next(r for r in jl(DOCS / "eval_raw_main_pass_v2.jsonl") if (r["doc_id"], r["run_idx"]) == KEY[:2])
    o = main["outcomes"][KEY[2]]
    chk = next(c for c in jl(DOCS / "eval_raw_main_pass_v2_claim_judgments_checks_results.jsonl")
               if (c["doc_id"], c["run_idx"], c["outcome"]) == KEY)
    summ = json.loads((DOCS / "eval_raw_main_pass_v2_summary.json").read_text(encoding="utf-8"))
    s1 = chk["signal1_cited"]
    L = [f"Confidence signals measured for one judgment: {KEY[0]} run {KEY[1]}, {KEY[2]}",
         DISCLAIMER, "",
         "A. ROUTING SIGNAL (decides review; src/agent/compliance.py compute_confidence)",
         "   Retrieval similarity of each cited source:  "
         + ", ".join(f"[{s['index']}] {s['similarity_score']:.4f}" for s in o["cited_sources"]),
         f"   Confidence = minimum:  {o['confidence']:.4f}   threshold 0.65   ->  status {o['status']}",
         "",
         "B. EVALUATION SIGNALS (measured after the run; do not change routing)",
         "   Signal 1, reasoning vs each cited chunk (embedding similarity):  "
         + ", ".join(f"[{c['index']}] {c['score']:.4f}" for c in s1["per_chunk"])
         + f"   min {s1['min']:.4f}  mean {s1['mean']:.4f}",
         "   Per regulatory claim (quote check is deterministic; verdict is a narrow LLM check):"]
    for n, req in enumerate(chk["regulatory_requirements"], 1):
        for q in req["sources"]:
            L.append(f"     claim {n}: quote {q['match_type']} in {q['quote_location']}, "
                     f"claim-to-excerpt similarity {q['claim_similarity']:.4f}, "
                     f"check verdict {req['llm_check']['verdict']}")
    for n, f in enumerate(chk["document_facts"], 1):
        L.append(f"     document fact {n}: quote found in loan document ({f['document_match']['match_type']})")
    L += ["",
          "C. WHAT THE ROUTING SIGNAL SEPARATES ACROSS ALL 45 RUNS (eval_raw_main_pass_v2_summary.json)",
          "   Mean confidence, correct vs incorrect judge verdicts:"]
    for k, v in summ["confidence_by_correctness"].items():
        inc = f"{v['incorrect_mean']:.4f} (n={v['incorrect_n']})" if v["incorrect_mean"] is not None else "none (n=0)"
        L.append(f"     {k:<24} correct {v['correct_mean']:.4f} (n={v['correct_n']})   incorrect {inc}")
    t = summ["threshold_sweep"]["0.65"]
    L.append(f"   At threshold 0.65: {t['correct_overridden_rate']:.3f} of correct verdicts overridden, "
             f"{t['incorrect_caught_rate']:.3f} of incorrect verdicts caught.")
    out = HERE / "08_confidence_signals.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", out)
    return out


def main() -> None:
    signals = write_signals_page()
    a1, a2, a3 = HERE / "01_judgment_with_claim_check.md", HERE / "02_retrieval_example.md", HERE / "03_extracted_loan_terms.json"
    render("04_clip9_regulation_retrieval.png", [{
        "title": "Regulation retrieval: query and top 5 chunks from the FCA index", "style": "log",
        "rows": rows(file_lines(a2, 10, 10) + file_lines(a2, 15, 21)),
    }], "Source: docs/showcase_assets/02_retrieval_example.md L10, L15-21, built from docs/eval_raw_main_pass_v2.jsonl "
        "(loan_agreement_1 run 0, saved at run time, 2026-10-07). Local Chroma index, bge-small-en-v1.5, top k = 5. "
        "Synthetic loan document.")
    render("05_clip9_extracted_loan_terms.png", [{
        "title": "Extracted loan terms (structured output, LoanAgreementFields)", "style": "log",
        "rows": rows(file_lines(a3, 5, 18)),
    }], "Source: docs/showcase_assets/03_extracted_loan_terms.json L5-18, the _cached_fields of loan_agreement_1 run 1 "
        "in docs/eval_raw_main_pass_v2.jsonl (2026-10-07). Synthetic loan document.")
    render("06_clip9_supporting_citation.png", [{
        "title": "A supporting citation: claim, verbatim quote, source excerpt, claim-check verdict", "style": "log",
        "rows": rows(file_lines(a1, 18, 47)),
    }], "Source: docs/showcase_assets/01_judgment_with_claim_check.md L18-47 (loan_agreement_1 run 1, price_and_value), "
        "built from docs/eval_raw_main_pass_v2.jsonl and the claim-check results (2026-10-07/08). Synthetic loan document.")
    n = len(signals.read_text(encoding="utf-8").split("\n")) - 1
    render("07_clip10_confidence_signals.png", [{
        "title": "Confidence signals the system measures (real values)", "style": "log",
        "rows": rows(file_lines(signals, 1, n)),
    }], "Source: docs/showcase_assets/08_confidence_signals.md, written by build_video_images.py from "
        "docs/eval_raw_main_pass_v2.jsonl, _claim_judgments_checks_results.jsonl and _summary.json. "
        "Only signal A affects routing.")


if __name__ == "__main__":
    main()

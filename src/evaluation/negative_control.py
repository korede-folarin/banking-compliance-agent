"""
Negative control for the P8-06 claim checker (Session 27).

In the full pass the narrow LLM claim check returned `yes` for 484 of 536
claims and `no` for none. This control tests whether it can say `no` when
the source text does not support a claim, and still says `yes` when it does.
The criteria were written first, before any pair was selected or any call
made: docs/negative_control_criteria.md.

Subcommands:
  build   Zero API cost. Selects 30 pairs (10 unrelated, 10 neighbouring,
          10 positive) from the full-pass claim-check results, mechanically
          verifies each (quote absent from every wrong chunk, present in
          every positive chunk), and freezes them to
          docs/negative_control_pairs.jsonl. Refuses to overwrite an
          existing pairs file.
  run     One `claim_verification._check_claim` call per pair (the same
          function, prompt, model and tool settings as the full pass).
          Each result is appended as it returns; a re-run skips pairs
          already done and says so. Retries are logged, observe-only.
  report  Zero API cost. Scores the results against the criteria as
          written and writes docs/negative_control_report.md: per group,
          the LLM-only result (what the pass criteria apply to) and the
          combined gate (quote found AND LLM yes). Every negative pair the
          checker marked `yes` is listed as a checker failure, with the
          user's annotation from docs/negative_control_annotations.jsonl if
          present. Annotations never change any count or pass/fail.
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.agent import retry_log  # noqa: E402
from src.evaluation import claim_verification as cv  # noqa: E402
from tests.fixtures.eval_set import OUTCOME_KEYS  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent.parent / "docs"
RESULTS_PATH = DOCS / "eval_raw_main_pass_v2_claim_judgments_checks_results.jsonl"
JUDGMENTS_PATH = DOCS / "eval_raw_main_pass_v2_claim_judgments.jsonl"
PAIRS_PATH = DOCS / "negative_control_pairs.jsonl"
OUT_PATH = DOCS / "negative_control_results.jsonl"
RETRIES_PATH = DOCS / "negative_control_retries.jsonl"
REPORT_PATH = DOCS / "negative_control_report.md"
ANNOTATIONS_PATH = DOCS / "negative_control_annotations.jsonl"

SEED = 20261008
PER_GROUP = 10
GROUPS = ("unrelated", "neighbouring", "positive")
MIN_PART_WORDS = 5

# docs/negative_control_criteria.md, as written before any call.
CRITERIA = {
    "unrelated": ("no", 10),     # rejected = verdict "no"; need 10 of 10
    "neighbouring": ("no", 7),   # need at least 7 of 10
    "positive": ("yes", 9),      # accepted = verdict "yes"; need at least 9 of 10
}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --- mechanical checks (no LLM) ---

def _quote_parts(quote: str) -> list[str]:
    """The "..."-separated parts of a quote with at least MIN_PART_WORDS words."""
    parts = quote.replace("…", "...").split("...")
    return [p.strip(" ;.,") for p in parts if len(cv.normalise(p).split()) >= MIN_PART_WORDS]


def quote_absent(quote: str, text: str) -> dict:
    """Absent = the matcher says `none` AND no long-enough "..." part appears (normalised)."""
    m = cv.match_quote(quote, text, prefilter=False)
    parts_present = [p for p in _quote_parts(quote) if cv.normalise(p) in cv.normalise(text)]
    return {
        "absent": m["match_type"] == "none" and not parts_present,
        "match_type": m["match_type"],
        "fuzzy_score": m["fuzzy_score"],
        "parts_present": parts_present,
    }


def quote_present(quote: str, text: str) -> dict:
    m = cv.match_quote(quote, text)
    return {"present": m["match_type"] in ("exact", "normalised"), "match_type": m["match_type"]}


# --- corpus order (for neighbouring chunks) ---

def corpus_order(corpus_meta: list[dict]) -> dict[str, tuple[str | None, str | None]]:
    """
    node_id -> (previous node_id, next node_id) within the same file, ordered
    by file_name, numeric page_label, start_char_idx.
    """
    def key(c):
        try:
            page = int(c["page_label"])
        except (TypeError, ValueError):
            page = 10**9
        return (c["file_name"], page, c["start_char_idx"] or 0)

    ordered = sorted(corpus_meta, key=key)
    neighbours = {}
    for i, c in enumerate(ordered):
        prev = ordered[i - 1] if i > 0 and ordered[i - 1]["file_name"] == c["file_name"] else None
        nxt = ordered[i + 1] if i + 1 < len(ordered) and ordered[i + 1]["file_name"] == c["file_name"] else None
        neighbours[c["id"]] = (prev["id"] if prev else None, nxt["id"] if nxt else None)
    return neighbours


def load_corpus_meta() -> list[dict]:
    """id, text, file_name, page_label, start_char_idx for every corpus chunk (local Chroma read)."""
    import chromadb

    from src.config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR

    coll = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR).get_collection(CHROMA_COLLECTION_NAME)
    got = coll.get(include=["documents", "metadatas"])
    out = []
    for i, d, m in zip(got["ids"], got["documents"], got["metadatas"]):
        node = json.loads((m or {}).get("_node_content", "{}"))
        out.append({
            "id": i, "text": d or "", "file_name": (m or {}).get("file_name", "unknown"),
            "page_label": (m or {}).get("page_label"), "start_char_idx": node.get("start_char_idx"),
        })
    return out


# --- selection ---

def eligible_claims(results: list[dict], judgments: dict) -> list[dict]:
    """Single-source claims the full pass accepted (`yes`) with the quote found exactly/normalised in its named chunk."""
    out = []
    for r in results:
        sources = {s["index"]: s for s in judgments[(r["doc_id"], r["run_idx"])]["outcomes"][r["outcome"]]["sources"]}
        for i, q in enumerate(r["regulatory_requirements"]):
            if q["source_count"] != 1 or not q.get("llm_check") or q["llm_check"]["verdict"] != "yes":
                continue
            s = q["sources"][0]
            if s["quote_location"] != "named_chunk" or s["match_type"] not in ("exact", "normalised"):
                continue
            named = sources.get(s["excerpt_number"])
            if not named:
                continue
            out.append({
                "doc_id": r["doc_id"], "run_idx": r["run_idx"], "outcome": r["outcome"], "claim_index": i,
                "claim": q["claim"], "quote": s["verbatim_quote"], "excerpt_number": s["excerpt_number"],
                "named_node_id": named.get("node_id"), "named_text": named["text_excerpt"],
                "full_pass_verdict": "yes",
            })
    return out


def _try_unrelated(c, judgments, rng):
    row = judgments[(c["doc_id"], c["run_idx"])]
    own_ids = {s.get("node_id") for s in row["outcomes"][c["outcome"]]["sources"]}
    options = [
        (k, s) for k in OUTCOME_KEYS if k != c["outcome"] for s in row["outcomes"][k]["sources"]
        if s.get("node_id") not in own_ids
    ]
    rng.shuffle(options)
    for k, s in options:
        chk = quote_absent(c["quote"], s["text_excerpt"])
        if chk["absent"]:
            return {"chunk_node_id": s.get("node_id"), "chunk_file_name": s["file_name"], "chunk_text": s["text_excerpt"],
                    "chunk_origin": f"retrieved for {k} in the same row", "check": chk}
    return None


def _try_neighbouring(c, corpus_by_id, neighbours, rng):
    prev_id, next_id = neighbours.get(c["named_node_id"], (None, None))
    options = [("previous", prev_id), ("next", next_id)]
    rng.shuffle(options)
    for side, nid in options:
        if not nid:
            continue
        chunk = corpus_by_id[nid]
        chk = quote_absent(c["quote"], chunk["text"])
        if chk["absent"]:
            return {"chunk_node_id": nid, "chunk_file_name": chunk["file_name"], "chunk_text": chunk["text"],
                    "chunk_origin": f"{side} chunk of the named chunk in {chunk['file_name']}", "check": chk}
    return None


def _try_positive(c):
    chk = quote_present(c["quote"], c["named_text"])
    if chk["present"]:
        return {"chunk_node_id": c["named_node_id"], "chunk_file_name": None, "chunk_text": c["named_text"],
                "chunk_origin": "the claim's own named chunk (as the judge saw it)", "check": chk}
    return None


def select_pairs(results, judgments, corpus_meta, seed=SEED) -> tuple[list[dict], list[dict]]:
    """Returns (pairs, rejected_candidates). Deterministic for a given seed and inputs."""
    rng = random.Random(seed)
    corpus_by_id = {c["id"]: c for c in corpus_meta}
    neighbours = corpus_order(corpus_meta)
    pool = eligible_claims(results, judgments)
    by_outcome = {k: [c for c in pool if c["outcome"] == k] for k in OUTCOME_KEYS}
    for k in OUTCOME_KEYS:
        rng.shuffle(by_outcome[k])

    used_claims, pairs, rejected = set(), [], []
    for group in GROUPS:
        n, turn = 0, 0
        cursors = {k: 0 for k in OUTCOME_KEYS}
        while n < PER_GROUP:
            k = OUTCOME_KEYS[turn % len(OUTCOME_KEYS)]
            turn += 1
            if turn > 100 * PER_GROUP:
                raise SystemExit(f"Could not find {PER_GROUP} valid {group} pairs.")
            bucket = by_outcome[k]
            while cursors[k] < len(bucket) and bucket[cursors[k]]["claim"] in used_claims:
                cursors[k] += 1
            if cursors[k] >= len(bucket):
                continue
            c = bucket[cursors[k]]
            cursors[k] += 1
            if group == "unrelated":
                chunk = _try_unrelated(c, judgments, rng)
            elif group == "neighbouring":
                chunk = _try_neighbouring(c, corpus_by_id, neighbours, rng)
            else:
                chunk = _try_positive(c)
            if chunk is None:
                rejected.append({"group": group, "doc_id": c["doc_id"], "run_idx": c["run_idx"],
                                 "outcome": c["outcome"], "claim_index": c["claim_index"],
                                 "reason": "no chunk passed the mechanical check"})
                continue
            used_claims.add(c["claim"])
            n += 1
            pairs.append({"pair_id": f"{group[0].upper()}{n:02d}", "group": group,
                          **{f: c[f] for f in ("doc_id", "run_idx", "outcome", "claim_index", "claim", "quote",
                                               "excerpt_number", "named_node_id", "full_pass_verdict")},
                          **chunk})
    return pairs, rejected


# --- subcommands ---

def cmd_build(args) -> None:
    pairs_path = Path(args.pairs) if args.pairs else PAIRS_PATH
    if pairs_path.exists():
        raise SystemExit(f"Refusing to overwrite {pairs_path}: the pairs are frozen once built.")
    results = _read_jsonl(RESULTS_PATH)
    judgments = {(j["doc_id"], j.get("run_idx", 0)): j for j in _read_jsonl(JUDGMENTS_PATH)}
    pairs, rejected = select_pairs(results, judgments, load_corpus_meta())
    pairs_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pairs_path, "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")
    print(f"Wrote {len(pairs)} pairs to {pairs_path} (seed {SEED}); "
          f"{len(rejected)} candidate(s) replaced after failing the mechanical check.")
    for r in rejected:
        print(f"  replaced: {r}")
    print(f"=> `run` would make exactly {len(pairs)} claim-check calls (nominal; at most {4 * len(pairs)} with retries).")


def cmd_run(args) -> None:
    import instructor
    from anthropic import Anthropic

    pairs = _read_jsonl(Path(args.pairs) if args.pairs else PAIRS_PATH)
    if not pairs:
        raise SystemExit("No pairs: run `build` first.")
    out_path = Path(args.output) if args.output else OUT_PATH
    done = {r["pair_id"] for r in _read_jsonl(out_path)}
    todo = [p for p in pairs if p["pair_id"] not in done]
    if done:
        print(f"WARNING: {out_path.name} already has results for {len(done)} of {len(pairs)} pairs. "
              "These will be SKIPPED, not re-run.")
        if not todo:
            print("WARNING: every pair already has a result, so this invocation makes NO API calls.")
    print(f"Running {len(todo)} claim-check calls.")
    if not todo:
        return
    retry_log.set_path(out_path.with_name(f"{out_path.stem.replace('_results', '')}_retries.jsonl"))
    client = retry_log.attach(instructor.from_anthropic(Anthropic()), "negative_control")
    for n, p in enumerate(todo, start=1):
        retry_log.set_context(pair_id=p["pair_id"], group=p["group"])
        res = cv._check_claim(client, p["claim"], [p["chunk_text"]])
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"pair_id": p["pair_id"], "group": p["group"], "verdict": res.verdict,
                                "supporting_sentence": res.supporting_sentence}) + "\n")
        print(f"[{n}/{len(todo)}] {p['pair_id']} {p['group']}: {res.verdict}")


def quote_found(pair: dict) -> bool:
    """The project's quote matcher finds the pair's quote in the pair's chunk (exact, normalised or fuzzy)."""
    return cv.match_quote(pair["quote"], pair["chunk_text"])["match_type"] != "none"


def gate_decision(pair: dict, verdict: str) -> str:
    """
    Combined gate (criteria addendum): accepted = quote found AND `yes`;
    rejected = quote not found OR `no`; neither = quote found AND `partially`.
    """
    found = quote_found(pair)
    if found and verdict == "yes":
        return "accepted"
    if not found or verdict == "no":
        return "rejected"
    return "neither"


def score_gate(pairs: list[dict], results: list[dict]) -> dict:
    """The combined gate against the same thresholds, for information only."""
    by_id = {r["pair_id"]: r for r in results}
    out = {}
    for group in GROUPS:
        target, need = CRITERIA[group]
        wanted = "accepted" if target == "yes" else "rejected"
        decisions = [gate_decision(p, by_id[p["pair_id"]]["verdict"])
                     for p in pairs if p["group"] == group and p["pair_id"] in by_id]
        hit = decisions.count(wanted)
        out[group] = {
            "n": len(decisions), "target": wanted, "required": need, "met": hit,
            "counts": {d: decisions.count(d) for d in ("accepted", "neither", "rejected")},
            "passes": len(decisions) == PER_GROUP and hit >= need,
        }
    out["all_pass"] = all(out[g]["passes"] for g in GROUPS)
    return out


def checker_failures(pairs: list[dict], results: list[dict]) -> list[dict]:
    """Every negative (unrelated or neighbouring) pair the checker marked `yes`."""
    by_id = {r["pair_id"]: r for r in results}
    return [p for p in pairs if p["group"] != "positive" and by_id.get(p["pair_id"], {}).get("verdict") == "yes"]


def score(pairs: list[dict], results: list[dict]) -> dict:
    """LLM-only result: what the pass criteria apply to."""
    by_id = {r["pair_id"]: r for r in results}
    out = {}
    for group in GROUPS:
        target, need = CRITERIA[group]
        verdicts = [by_id[p["pair_id"]]["verdict"] for p in pairs if p["group"] == group and p["pair_id"] in by_id]
        hit = sum(v == target for v in verdicts)
        out[group] = {
            "n": len(verdicts), "target_verdict": target, "required": need, "met": hit,
            "partially": verdicts.count("partially"),
            "counts": {v: verdicts.count(v) for v in ("yes", "partially", "no")},
            "passes": len(verdicts) == PER_GROUP and hit >= need,
        }
    out["all_pass"] = all(out[g]["passes"] for g in GROUPS)
    return out


def cmd_report(args) -> None:
    pairs = _read_jsonl(Path(args.pairs) if args.pairs else PAIRS_PATH)
    results = _read_jsonl(Path(args.output) if args.output else OUT_PATH)
    annotations = {a["pair_id"]: a for a in _read_jsonl(
        Path(args.annotations) if getattr(args, "annotations", None) else ANNOTATIONS_PATH)}
    s, gate = score(pairs, results), score_gate(pairs, results)
    by_id = {r["pair_id"]: r for r in results}
    failures = checker_failures(pairs, results)
    L = ["# Negative control: results", "",
         "Scored against `docs/negative_control_criteria.md` (criteria and addendum written before any call).", "",
         "## LLM-only (the result the pass criteria apply to)", "",
         "Rejected = `no`; accepted = `yes`; `partially` is neither.", "",
         "| Group | Required | Met | yes | partially | no | Result |", "|---|---|---|---|---|---|---|"]
    for g in GROUPS:
        r = s[g]
        L.append(f"| {g} | {r['target_verdict']} >= {r['required']}/10 | {r['met']}/{r['n']} | {r['counts']['yes']} | "
                 f"{r['counts']['partially']} | {r['counts']['no']} | {'PASS' if r['passes'] else 'FAIL'} |")
    L += ["", f"**LLM-only overall: {'PASS' if s['all_pass'] else 'FAIL'}**", "",
          "## Combined gate: quote found AND LLM yes (for information)", "",
          "Accepted = quote found AND `yes`; rejected = quote not found OR `no`; neither = quote found AND "
          "`partially`. Every wrong chunk was selected so that the quote is absent, so this gate rejects every "
          "negative pair by construction: its negative rows show what the quote check adds, not the LLM.", "",
          "| Group | Required | Met | accepted | neither | rejected | Result |", "|---|---|---|---|---|---|---|"]
    for g in GROUPS:
        r = gate[g]
        L.append(f"| {g} | {r['target']} >= {r['required']}/10 | {r['met']}/{r['n']} | {r['counts']['accepted']} | "
                 f"{r['counts']['neither']} | {r['counts']['rejected']} | {'PASS' if r['passes'] else 'FAIL'} |")
    L += ["", f"**Combined gate overall: {'PASS' if gate['all_pass'] else 'FAIL'}**", "",
          "## Checker failures (negative pairs marked `yes`)", "",
          "Annotation = the user's reading of whether the wrong chunk supports the claim in its own words. "
          "It never changes any count or result above.", ""]
    if not failures:
        L.append("None.")
    for p in failures:
        a = annotations.get(p["pair_id"])
        note = (f"chunk supports claim: `{a['chunk_supports_claim']}`" + (f"; note: {a['note']}" if a.get("note") else "")
                if a else "annotation pending")
        L.append(f"- **{p['pair_id']}** ({p['group']}; {p['doc_id']} run {p['run_idx']} / {p['outcome']}): "
                 f"CHECKER FAILURE | {note}")
        L.append(f"  - claim: {p['claim']}")
        L.append(f"  - chunk ({p['chunk_origin']}): {p['chunk_text'][:600]!r}")
        if by_id[p["pair_id"]].get("supporting_sentence"):
            L.append(f"  - supporting sentence the checker gave: {by_id[p['pair_id']]['supporting_sentence'][:300]!r}")
    L += ["", "## Every pair", ""]
    for p in pairs:
        r = by_id.get(p["pair_id"], {})
        gd = gate_decision(p, r["verdict"]) if r else "not run"
        L.append(f"- **{p['pair_id']}** ({p['group']}; {p['doc_id']} run {p['run_idx']} / {p['outcome']}) -> "
                 f"LLM `{r.get('verdict', 'not run')}` | quote found: {quote_found(p)} | gate: {gd} | "
                 f"chunk: {p['chunk_origin']}")
        L.append(f"  - claim: {p['claim']}")
        if r.get("supporting_sentence"):
            L.append(f"  - supporting sentence given: {r['supporting_sentence'][:300]!r}")
    Path(args.report or REPORT_PATH).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"llm_only": s, "combined_gate": gate,
                      "checker_failures": [p["pair_id"] for p in failures]}, indent=2))
    print(f"Wrote {args.report or REPORT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Negative control for the claim checker")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("build", cmd_build), ("run", cmd_run), ("report", cmd_report)):
        p = sub.add_parser(name)
        p.add_argument("--pairs", help=f"Pairs file (default docs/{PAIRS_PATH.name})")
        if name != "build":
            p.add_argument("--output", help=f"Results file (default docs/{OUT_PATH.name})")
        if name == "report":
            p.add_argument("--report", help=f"Report file (default docs/{REPORT_PATH.name})")
            p.add_argument("--annotations", help=f"User annotations (default docs/{ANNOTATIONS_PATH.name})")
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

"""
Structured-claim verification (P8-06): checks the Compliance Agent's
itemised claims (OutcomeJudgment.document_facts / regulatory_requirements /
absences, appended after status and reasoning) mostly without an LLM.
Replaces P8-05's regex sentence splitter (Signal 2 Part A): claims are no
longer carved out of free-text reasoning after the fact; the judgment itself
declares which bucket each claim belongs to and quotes its evidence verbatim.

See ARCHITECTURE.md "Structured-claim verification (P8-06)" for the design,
why verbatim quotes make non-LLM checking possible, and its limits.

What each bucket gets (every result is logged; no step is gated on a
threshold):

  document_facts           verbatim_quote vs. the loan document text
                           (exact / normalised / fuzzy / none). No LLM.
  regulatory_requirements  per source: quote match (named excerpt first,
                           then the judgment's other retrieved excerpts,
                           then the full corpus), claim-vs-named-excerpt
                           embedding similarity (every score + the minimum),
                           source_count, and whether each named excerpt was
                           in cited_sources. No LLM. THEN every claim, with
                           no gating, goes to one narrow LLM check that sees
                           only the claim and the named excerpts' text (no
                           excerpt labels, no reasoning).
  absences                 absent_from_document: checked against the
                           extracted fields (and the nearest document chunk
                           is logged). absent_from_retrieved_regulation:
                           marked needs_human_review, not verified.
  comparison / status      not mechanically checked.

Signal 1 (reasoning vs. chunk embedding similarity) is computed against the
judgment's logged cited chunks only, per chunk, with min and mean reported
(src.evaluation.groundedness.compute_signal1_cited).

Judgment rows are identified by (doc_id, run_idx), and any run can be used
(checklist item 10). Two ways to fill a judgments file (--judgments):

  judge   Pilot: re-judges selected (doc, run) pairs (--docs, --runs; default
          the pilot docs, run 0). Extraction is that run's saved
          `_cached_fields` from the main-pass file given by --input (default
          docs/eval_raw_main_pass_v2.jsonl; pass docs/eval_raw_main_pass.jsonl
          for the Phase 8 data, where only run 0 has fields). Excerpts are
          the row's saved `retrieved_sources` when present, else replayed
          (deterministic, zero API cost). The judge sees the full document
          (checklist item 4). 4 judgment calls per pair.
  ingest  Zero API cost: copies judgments a main pass already made (every run
          saves the full judgment, retrieved sources and fields since
          checklist items 3/6/7/8/9) into a judgments file, so the main
          pass's own judgments can be claim-checked without re-judging.

Both skip (doc, run) pairs already in the judgments file and say so
(checklist item 16). The 405-call main pass is NOT re-run here.

Subcommands:
  plan    Zero API cost. Retrieval-replay spot check against the cached
          price_and_value context (run 0), the exact number of judgment
          calls still to make, and (once judgments exist) all mechanical
          checks plus the exact number of claim-check calls `check` would
          make.
  judge   See above.
  ingest  See above.
  check   One narrow LLM claim-check call per regulatory claim not already
          checked. Each result is appended to the claim-check store
          (--output; default docs/eval_claim_pilot_checks.jsonl for the pilot
          judgments file, else <judgments stem>_checks.jsonl) as soon as it
          comes back; a re-run skips claims already in the store and says
          so (checklist item 18). Then rebuilds, from EVERY judgment in the
          judgments file plus the whole store, <store>_results.jsonl and
          <store>_report.md (checklist item 17). --docs / --runs only limit
          which claims get new checks.
"""

import argparse
import difflib
import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pydantic import BaseModel, Field  # noqa: E402

from src.agent.compliance import (  # noqa: E402
    CONTEXT_FIELD_BY_OUTCOME,
    ComplianceAgent,
    OutcomeJudgment,
    validate_outcome,
)
from src.agent.first_pass import QUESTION_BUILDERS, FirstPassResult  # noqa: E402
from src.agent import retry_log  # noqa: E402
from src.agent.schemas import LoanAgreementFields  # noqa: E402
from src.agent.structured_output import single_tool_choice  # noqa: E402
from src.agent.uncertainty import NOT_ADDRESSED, _cosine_similarity, _get_embed_model, _splitter  # noqa: E402
from src.config import ANTHROPIC_MODEL, CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR  # noqa: E402
from src.evaluation.groundedness import compute_signal1_cited  # noqa: E402
from src.evaluation.run_eval import INPUT_HELP, MAIN_PASS_PATH, resolve_main_input  # noqa: E402
from src.retrieval import query_engine  # noqa: E402  (SOURCE_EXCERPT_CHARS, read at call time)
from src.retrieval.query_engine import QueryResult, SourceCitation, load_index  # noqa: E402
from tests.fixtures.eval_set import EVAL_DOCUMENTS, OUTCOME_KEYS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = ROOT / "data" / "synthetic_docs"
DOCS_OUT_DIR = ROOT / "docs"
PILOT_JUDGMENTS_PATH = DOCS_OUT_DIR / "eval_claim_pilot_judgments.jsonl"
# Claim-check store (checklist items 17/18): append-only, one line per
# regulatory claim checked by the LLM, appended as each result comes back.
# It holds the paid-for results and is never rewritten. The full results
# JSONL and the report are derived from it (see _resolve_check_outputs).
PILOT_CHECKS_PATH = DOCS_OUT_DIR / "eval_claim_pilot_checks.jsonl"

# One document per deliberately-planted issue outcome where available, plus
# the control: loan_agreement_1 (price_and_value issue), _2 (consumer_support
# issue), _3 (control; its cached run-0 price_and_value is the known false
# accusation), _12 (consumer_understanding issue; cached run-0
# price_and_value is insufficient_evidence).
DEFAULT_PILOT_DOCS = ["loan_agreement_1", "loan_agreement_2", "loan_agreement_3", "loan_agreement_12"]

RETRIEVAL_TOP_K = 5
# The excerpt length the judge sees is query_engine.SOURCE_EXCERPT_CHARS
# (checklist item 20; the whole chunk since Session 25). Replay of a
# recorded row uses that row's own length (query_engine.excerpt_chars_for),
# never a copy here.

# Classification cutoff for match_type == "fuzzy": the fraction of the
# quote's words found, in order, in the best-matching window of the target
# text. It only decides which label a match gets; nothing downstream is
# gated on it, and the best score is logged for every quote regardless.
FUZZY_CUTOFF = 0.9

OUTCOME_DOCUMENT_FIELDS = {
    "price_and_value": ["fees", "fair_value_justification"],
    "consumer_support": ["vulnerable_customer_provision"],
    "products_and_services": ["target_market_suitability_statement"],
    "consumer_understanding": ["key_terms_summary_provision"],
}

LOCATION_ORDER = ["named_chunk", "other_retrieved_chunk", "corpus_not_retrieved", "not_found"]
MATCH_ORDER = ["exact", "normalised", "fuzzy", "none"]

CLAIM_CHECK_SYSTEM_PROMPT = (
    "You are checking exactly one claim against the source text provided. "
    "Judge ONLY whether this one claim is supported by the source text. Do "
    "not assess the claim's relevance, phrasing, or anything beyond the "
    "source text.\n\n"
    "verdict:\n"
    '- "yes": the source text directly supports the claim as stated.\n'
    '- "partially": the source text supports part of the claim, or supports '
    "it with a material difference in scope, degree, or condition.\n"
    '- "no": the source text does not address the claim, or contradicts it.\n\n'
    "supporting_sentence: the single sentence from the source text that best "
    "supports the claim, copied exactly. Empty string if verdict is \"no\"."
)


class ClaimCheck(BaseModel):
    verdict: Literal["yes", "no", "partially"]
    supporting_sentence: str = Field(
        description="The sentence from the source text that best supports the claim, copied exactly; empty if none."
    )


# --- IO helpers ---

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _append_jsonl(path: Path, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _doc_meta(doc_id: str) -> dict:
    for d in EVAL_DOCUMENTS:
        if d["id"] == doc_id:
            return d
    raise SystemExit(f"Unknown doc id: {doc_id}")


def _cached_run(doc_id: str, run_idx: int, main_pass_path: Path) -> dict:
    """The main-pass row for (doc_id, run_idx), which must carry `_cached_fields`."""
    for r in _read_jsonl(main_pass_path):
        if r["doc_id"] == doc_id and r["run_idx"] == run_idx:
            if "_cached_fields" not in r:
                raise SystemExit(
                    f"{doc_id} run {run_idx} in {main_pass_path} has no _cached_fields (the Phase 8 pass saved "
                    "them for run 0 only; main passes since checklist item 7 save them for every run)."
                )
            return r
    raise SystemExit(f"No row for {doc_id} run {run_idx} in {main_pass_path} (pass --input?)")


def _announce_skips(path: Path, noun: str, n_requested: int, skipped_labels: list[str], nothing_left: bool) -> None:
    """Checklist item 16: skips are announced, never silent (same pattern as items 11 and 18)."""
    if not skipped_labels:
        return
    print(
        f"\nWARNING: {path.name} already has {len(skipped_labels)} of the {n_requested} requested {noun}. "
        "These will be SKIPPED, not redone:"
    )
    for label in skipped_labels:
        print(f"  - {label}")
    if nothing_left:
        print(
            f"WARNING: every requested {noun[:-1] if noun.endswith('s') else noun} is already present, so this "
            "invocation will make NO API calls and write nothing."
        )
    print()


# --- quote matching (no LLM) ---

_APOSTROPHES = "'`‘’ʼ�"  # �: the corpus PDFs decode apostrophes to U+FFFD


def normalise(text: str) -> str:
    """
    Lowercase, strip punctuation, collapse whitespace, and undo PDF
    artefacts: soft hyphens, line-end hyphenation ("regu-\\nlation"), and
    apostrophes decoded as U+FFFD. Intra-word hyphens are dropped rather
    than turned into spaces, so "long-term", "long-\\nterm" and "longterm"
    all normalise identically.
    """
    t = unicodedata.normalize("NFKC", text).replace("­", "")
    t = re.sub(r"[-‐‑]\s*\n\s*", "", t)
    t = re.sub(r"[-‐‑]", "", t)
    t = re.sub(f"[{re.escape(_APOSTROPHES)}]", "", t)
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _fuzzy_score(quote_tokens: list[str], text_tokens: list[str], prefilter: bool = True) -> float:
    """
    Best fraction of the quote's words matched, in order, within any window
    of the text of roughly the quote's length (difflib matching blocks over
    word lists). Windows are only tried where the text contains one of the
    quote's first three words. With prefilter=True (the corpus-wide search,
    for speed) a text whose vocabulary can't reach FUZZY_CUTOFF is skipped
    and scored 0.0; the named-excerpt search always computes the real score
    so it can be logged for quotes that end up not_found.
    """
    n = len(quote_tokens)
    if n == 0 or not text_tokens:
        return 0.0
    text_vocab = set(text_tokens)
    if prefilter and sum(1 for w in quote_tokens if w in text_vocab) / n < FUZZY_CUTOFF:
        return 0.0
    slack = max(2, n // 5)
    starts = set()
    for j, w in enumerate(quote_tokens[:3]):
        for i, tw in enumerate(text_tokens):
            if tw == w:
                starts.add(max(0, i - j))
    best = 0.0
    for s in starts:
        window = text_tokens[s : s + n + slack]
        sm = difflib.SequenceMatcher(None, quote_tokens, window, autojunk=False)
        matched = sum(b.size for b in sm.get_matching_blocks())
        best = max(best, matched / n)
        if best == 1.0:
            break
    return best


def match_quote(quote: str, text: str, prefilter: bool = True) -> dict:
    """Returns {"match_type": exact|normalised|fuzzy|none, "fuzzy_score": float|None}."""
    q = quote.strip()
    if not q:
        return {"match_type": "none", "fuzzy_score": None}
    if q in text:
        return {"match_type": "exact", "fuzzy_score": None}
    nq, nt = normalise(q), normalise(text)
    if nq and nq in nt:
        return {"match_type": "normalised", "fuzzy_score": None}
    score = _fuzzy_score(nq.split(), nt.split(), prefilter)
    return {"match_type": "fuzzy" if score >= FUZZY_CUTOFF else "none", "fuzzy_score": round(score, 4)}


def _best_in(quote: str, candidates: list[tuple[str, str]], prefilter: bool = True) -> tuple[str | None, dict]:
    """candidates: [(label, text)]. Returns the label + match of the best match_type among them."""
    best_label, best = None, {"match_type": "none", "fuzzy_score": None}
    for label, text in candidates:
        m = match_quote(quote, text, prefilter)
        better_type = MATCH_ORDER.index(m["match_type"]) < MATCH_ORDER.index(best["match_type"])
        same_fuzzy_higher = (
            m["match_type"] == best["match_type"] == "fuzzy" and (m["fuzzy_score"] or 0) > (best["fuzzy_score"] or 0)
        )
        if better_type or same_fuzzy_higher:
            best_label, best = label, m
        if best["match_type"] == "exact":
            break
    return best_label, best


def locate_quote(quote: str, excerpt_number: int, sources: list[dict], corpus: list[dict]) -> dict:
    """
    Search order: the named excerpt (as shown to the judge), every other
    excerpt retrieved for this judgment (as shown), then every corpus chunk's
    full text. The first tier with any match wins.
    """
    named = [s for s in sources if s["index"] == excerpt_number]
    others = [s for s in sources if s["index"] != excerpt_number]
    retrieved_ids = {s["node_id"] for s in sources}

    named_fuzzy = None
    if named:
        m = match_quote(quote, named[0]["text_excerpt"], prefilter=False)
        if m["match_type"] != "none":
            return {"quote_location": "named_chunk", **m, "found_in": excerpt_number}
        named_fuzzy = m["fuzzy_score"]
    label, m = _best_in(quote, [(str(s["index"]), s["text_excerpt"]) for s in others])
    if m["match_type"] != "none":
        return {"quote_location": "other_retrieved_chunk", **m, "found_in": int(label)}
    # Retrieved chunks' full text first: chunks overlap, so the same sentence
    # can sit in a retrieved chunk (past the excerpt the judge saw) and in a
    # neighbouring one; ties keep the first candidate.
    ordered = sorted(corpus, key=lambda c: c["id"] not in retrieved_ids)
    label, m = _best_in(quote, [(c["id"], c["text"]) for c in ordered])
    if m["match_type"] != "none":
        chunk = next(c for c in corpus if c["id"] == label)
        return {
            "quote_location": "corpus_not_retrieved",
            **m,
            "found_in": {"chunk_id": label, "file_name": chunk["file_name"]},
            # True means the quote is in a chunk that WAS retrieved, but past
            # the excerpt the judge was actually shown (only possible for rows
            # judged with truncated excerpts, i.e. before Session 25).
            "corpus_chunk_was_retrieved": label in retrieved_ids,
        }
    # fuzzy_score here is the best in-order word match against the NAMED
    # excerpt, so a near-miss is visible in the log.
    return {"quote_location": "not_found", "match_type": "none", "fuzzy_score": named_fuzzy, "found_in": None}


# --- retrieval replay + corpus ---

_CURRENT = object()  # sentinel: use query_engine.SOURCE_EXCERPT_CHARS at call time


def replay_sources(retriever, fields: LoanAgreementFields, outcome_key: str, excerpt_chars=_CURRENT) -> list[dict]:
    nodes = retriever.retrieve(QUESTION_BUILDERS[outcome_key](fields))
    limit = query_engine.SOURCE_EXCERPT_CHARS if excerpt_chars is _CURRENT else excerpt_chars
    return [
        {
            "index": i,
            "node_id": n.node.node_id,
            "file_name": n.metadata.get("file_name", "unknown"),
            "similarity_score": n.score or 0.0,
            "text_excerpt": n.text[:limit],
        }
        for i, n in enumerate(nodes, start=1)
    ]


def load_corpus() -> list[dict]:
    import chromadb

    coll = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR).get_collection(CHROMA_COLLECTION_NAME)
    got = coll.get(include=["documents", "metadatas"])
    return [
        {"id": i, "text": d or "", "file_name": (m or {}).get("file_name", "unknown")}
        for i, d, m in zip(got["ids"], got["documents"], got["metadatas"])
    ]


def _query_result(question: str, sources: list[dict]) -> QueryResult:
    # The judge and validate_outcome only read .sources; the retrieval-
    # synthesis answer is not regenerated (no API call) in the pilot.
    return QueryResult(
        question=question,
        answer="(retrieval replay only; synthesis answer not regenerated)",
        sources=[
            SourceCitation(
                index=s["index"],
                file_name=s["file_name"],
                similarity_score=s["similarity_score"],
                text_excerpt=s["text_excerpt"],
                node_id=s.get("node_id"),
            )
            for s in sources
        ],
        confidence=0.0,
        needs_human_review=True,
    )


# --- mechanical checks (no LLM) ---

def _embed(text: str) -> list[float]:
    return _get_embed_model().get_text_embedding(text)


def check_document_facts(facts: list[dict], document_text: str) -> list[dict]:
    return [
        {
            "claim": f["claim"],
            "verbatim_quote": f["verbatim_quote"],
            "document_match": match_quote(f["verbatim_quote"], document_text),
        }
        for f in facts
    ]


def check_regulatory_requirements(
    reqs: list[dict], sources: list[dict], cited: list[int], corpus: list[dict]
) -> list[dict]:
    by_index = {s["index"]: s for s in sources}
    out = []
    for r in reqs:
        claim_emb = _embed(r["claim"])
        src_results = []
        for src in r["sources"]:
            named = by_index.get(src["excerpt_number"])
            src_results.append(
                {
                    "excerpt_number": src["excerpt_number"],
                    "verbatim_quote": src["verbatim_quote"],
                    "named_excerpt_exists": named is not None,
                    "in_cited_sources": src["excerpt_number"] in cited,
                    **locate_quote(src["verbatim_quote"], src["excerpt_number"], sources, corpus),
                    "claim_similarity": (
                        _cosine_similarity(claim_emb, _embed(named["text_excerpt"])) if named else None
                    ),
                }
            )
        sims = [s["claim_similarity"] for s in src_results if s["claim_similarity"] is not None]
        out.append(
            {
                "claim": r["claim"],
                "source_count": len(r["sources"]),
                "sources": src_results,
                "similarity_min": min(sims) if sims else None,
                "worst_quote_location": max(
                    (s["quote_location"] for s in src_results), key=LOCATION_ORDER.index, default="not_found"
                ),
            }
        )
    return out


def check_absences(
    absences: list[dict], outcome_key: str, fields: LoanAgreementFields, doc_chunks: list[tuple[str, list[float]]]
) -> list[dict]:
    out = []
    for a in absences:
        rec = {"claim": a["claim"], "kind": a["kind"], "explanation": a["explanation"]}
        if a["kind"] == "absent_from_document":
            field_values = {name: getattr(fields, name) for name in OUTCOME_DOCUMENT_FIELDS[outcome_key]}
            marked = {
                name: (v is None or v.strip() == NOT_ADDRESSED) for name, v in field_values.items()
            }
            rec["extracted_fields"] = field_values
            rec["field_marked_not_addressed"] = marked
            rec["result"] = (
                "extracted_field_marked_not_addressed" if any(marked.values()) else "extracted_field_present"
            )
            # Nearest document chunk to the claim, for a human reader to
            # see what the document actually says on this point. Logged
            # only; no threshold.
            if doc_chunks:
                emb = _embed(a["claim"])
                scored = [(c, _cosine_similarity(emb, e)) for c, e in doc_chunks]
                best_chunk, best_score = max(scored, key=lambda x: x[1])
                rec["nearest_document_chunk"] = {"text": best_chunk, "similarity": best_score}
        else:
            rec["result"] = "needs_human_review"
        out.append(rec)
    return out


def mechanical_checks(judgment_rows: list[dict], corpus: list[dict]) -> list[dict]:
    """One record per (doc, run, outcome), all non-LLM checks filled in."""
    results = []
    for row in judgment_rows:
        run_idx = row.get("run_idx", 0)
        doc_text = (DOCS_DIR / _doc_meta(row["doc_id"])["file"]).read_text(encoding="utf-8")
        fields = LoanAgreementFields(**row["fields"])
        doc_chunks = [(c, _embed(c)) for c in _splitter.split_text(doc_text)]
        for key in OUTCOME_KEYS:
            o = row["outcomes"][key]
            j = o["judgment"]
            results.append(
                {
                    "doc_id": row["doc_id"],
                    "run_idx": run_idx,
                    "label": f"{row['doc_id']} run {run_idx}",
                    "origin": row.get("origin", "pilot_judge"),
                    "outcome": key,
                    "ground_truth": row["ground_truth"][key],
                    "llm_status": j["status"],
                    "status": o["validated_status"],
                    "confidence": o["confidence"],
                    # The main-pass statuses for the same (doc, run) whose
                    # fields a pilot judgment was made from; None for
                    # ingested rows, which ARE the main-pass judgments.
                    "reference_llm_status": o.get("reference_llm_status"),
                    "reference_status": o.get("reference_status"),
                    "main_pass_input": row.get("main_pass_input", "unrecorded"),
                    "cited_sources": j["cited_sources"],
                    "reasoning": j["reasoning"],
                    "signal1_cited": compute_signal1_cited(j["reasoning"], o["resolved_cited_sources"]),
                    "document_facts": check_document_facts(j["document_facts"], doc_text),
                    "regulatory_requirements": check_regulatory_requirements(
                        j["regulatory_requirements"], o["sources"], j["cited_sources"], corpus
                    ),
                    "absences": check_absences(j["absences"], key, fields, doc_chunks),
                }
            )
    return results


# --- subcommands ---

def _pilot_docs(args) -> list[str]:
    return args.docs or DEFAULT_PILOT_DOCS


def _pilot_runs(args) -> list[int]:
    return getattr(args, "runs", None) or [0]


def _judgments_path(args) -> Path:
    return Path(args.judgments) if getattr(args, "judgments", None) else PILOT_JUDGMENTS_PATH


def _row_selected(row: dict, args) -> bool:
    """For `check`/`plan` claim counts: every judgment row unless --docs / --runs narrow it."""
    docs, runs = getattr(args, "docs", None), getattr(args, "runs", None)
    return (not docs or row["doc_id"] in docs) and (not runs or row.get("run_idx", 0) in runs)


def cmd_plan(args) -> None:
    docs, runs = _pilot_docs(args), _pilot_runs(args)
    judgments_path = _judgments_path(args)
    main_pass_path = resolve_main_input(args.input)
    main_rows = _read_jsonl(main_pass_path)

    print(f"Main-pass input: {main_pass_path}")
    print(f"Judgments file: {judgments_path}")
    print(f"Pilot documents: {docs}, runs: {runs}")
    print("\nRetrieval-replay spot check vs. cached run-0 price_and_value context:")
    retriever = None
    for doc_id in docs:
        cached = next((r for r in main_rows if r["doc_id"] == doc_id and r["run_idx"] == 0), None)
        if not cached or "_cached_price_and_value_context" not in cached:
            print(f"  {doc_id}: no cached run-0 price_and_value context, skipped")
            continue
        retriever = retriever or load_index().as_retriever(similarity_top_k=RETRIEVAL_TOP_K)
        replay = replay_sources(
            retriever, LoanAgreementFields(**cached["_cached_fields"]), "price_and_value",
            query_engine.excerpt_chars_for(cached),
        )
        cached_src = cached["_cached_price_and_value_context"]["sources"]
        same = [
            (a["file_name"], round(a["similarity_score"], 6), a["text_excerpt"])
            == (b["file_name"], round(b["similarity_score"], 6), b["text_excerpt"])
            for a, b in zip(replay, cached_src)
        ]
        print(f"  {doc_id}: {sum(same)}/{len(cached_src)} sources identical")

    done = {(r["doc_id"], r.get("run_idx", 0)) for r in _read_jsonl(judgments_path)}
    todo = [(d, i) for d in docs for i in runs if (d, i) not in done]
    print(
        f"\nJudgment calls still to make: {len(todo)} (doc, run) pairs x {len(OUTCOME_KEYS)} outcomes = "
        f"{len(todo) * len(OUTCOME_KEYS)} (nominal; instructor may retry a failed "
        "validation up to 3 times per call)."
    )

    rows = [r for r in _read_jsonl(judgments_path) if _row_selected(r, args)]
    if not rows:
        print("No judgments recorded yet, so the claim-check count is not known until `judge` or `ingest` runs.")
        return
    results = mechanical_checks(rows, load_corpus())
    n_claims = sum(len(r["regulatory_requirements"]) for r in results)
    print(f"\nMechanical checks run on {len(results)} recorded judgments (zero API cost).")
    print(
        f"  document_facts: {sum(len(r['document_facts']) for r in results)}, "
        f"regulatory_requirements: {n_claims}, absences: {sum(len(r['absences']) for r in results)}"
    )
    store_path, _, _ = _resolve_check_outputs(args.output, judgments_path)
    stored = {_store_key(rec) for rec in _read_jsonl(store_path)}
    already = sum(
        _claim_key(r["doc_id"], r["run_idx"], r["outcome"], i, q["claim"]) in stored
        for r in results
        for i, q in enumerate(r["regulatory_requirements"])
    )
    print(
        f"\n=> `check` would make exactly {n_claims - already} claim-check calls "
        f"({already} of {n_claims} already in {store_path.name}; one per regulatory claim, nominal)."
    )


def cmd_judge(args) -> None:
    docs, runs = _pilot_docs(args), _pilot_runs(args)
    judgments_path = _judgments_path(args)
    main_pass_path = resolve_main_input(args.input)
    requested = [(d, i) for d in docs for i in runs]
    done = {(r["doc_id"], r.get("run_idx", 0)) for r in _read_jsonl(judgments_path)}
    todo = [p for p in requested if p not in done]
    print(f"Main-pass input: {main_pass_path}")
    print(f"Judgments file: {judgments_path}")
    _announce_skips(
        judgments_path, "(doc, run) pairs", len(requested),
        [f"{d} run {i}" for d, i in requested if (d, i) in done], nothing_left=not todo,
    )
    print(f"Judging {len(todo)} (doc, run) pairs x {len(OUTCOME_KEYS)} outcomes = {len(todo) * len(OUTCOME_KEYS)} API calls.")
    if not todo:
        return

    retriever = None
    agent = ComplianceAgent()
    for doc_id, run_idx in todo:
        cached = _cached_run(doc_id, run_idx, main_pass_path)
        fields = LoanAgreementFields(**cached["_cached_fields"])
        sources = {}
        for k in OUTCOME_KEYS:
            saved = cached["outcomes"][k].get("retrieved_sources")
            if saved:  # item 6: exactly the excerpts that run's judge saw
                sources[k] = saved
            else:
                retriever = retriever or load_index().as_retriever(similarity_top_k=RETRIEVAL_TOP_K)
                sources[k] = replay_sources(retriever, fields, k, query_engine.excerpt_chars_for(cached))
        contexts = {k: _query_result(QUESTION_BUILDERS[k](fields), sources[k]) for k in OUTCOME_KEYS}
        first_pass = FirstPassResult(
            document_fields=fields, **{CONTEXT_FIELD_BY_OUTCOME[k]: contexts[k] for k in OUTCOME_KEYS}
        )
        document_text = (DOCS_DIR / _doc_meta(doc_id)["file"]).read_text(encoding="utf-8")
        judgments: dict[str, OutcomeJudgment] = agent.evaluate(first_pass, document_text)

        outcomes = {}
        for k in OUTCOME_KEYS:
            v = validate_outcome(k, judgments[k], contexts[k])
            outcomes[k] = {
                "judgment": judgments[k].model_dump(),
                "validated_status": v.status,
                "confidence": v.confidence,
                "resolved_cited_sources": [s.model_dump() for s in v.cited_sources],
                "sources": sources[k],
                "reference_llm_status": cached["outcomes"][k]["llm_status"],
                "reference_status": cached["outcomes"][k]["status"],
            }
        _append_jsonl(
            judgments_path,
            {
                "doc_id": doc_id,
                "run_idx": run_idx,
                "origin": "pilot_judge",
                "source_excerpt_chars": query_engine.excerpt_chars_for(cached),
                # Which main-pass file the fields and reference_* statuses
                # came from (Phase 8 or a re-run), for the report.
                "main_pass_input": main_pass_path.name,
                "ground_truth": _doc_meta(doc_id)["ground_truth"],
                "fields": fields.model_dump(),
                "outcomes": outcomes,
            },
        )
        print(f"{doc_id} run {run_idx}: { {k: judgments[k].status for k in OUTCOME_KEYS} }")
    print(f"\nWrote {judgments_path}")


INGEST_NEEDS = ("judgment", "retrieved_sources")


def cmd_ingest(args) -> None:
    """
    Checklist item 10: copy judgments a main pass already made (any run) into
    a judgments file for `check`, with no API calls. Needs rows written since
    checklist items 3/6/7/8/9 (full `judgment`, `retrieved_sources` and
    `_cached_fields` on every run); older rows are listed and skipped.
    """
    main_pass_path = resolve_main_input(args.input)
    # Default: next to the main-pass input, named after it (same pattern as
    # `summary` and `variants`), so each judgments file belongs to one pass.
    judgments_path = (
        Path(args.judgments) if args.judgments
        else main_pass_path.with_name(f"{main_pass_path.stem}_claim_judgments.jsonl")
    )
    if judgments_path.resolve() in (main_pass_path.resolve(), MAIN_PASS_PATH.resolve()):
        raise SystemExit(f"Refusing to write ingested judgments to {judgments_path}: it is a main-pass file.")
    print(f"Main-pass input: {main_pass_path}")
    print(f"Judgments file: {judgments_path}")

    rows = [r for r in _read_jsonl(main_pass_path) if _row_selected(r, args)]
    usable, unusable = [], []
    for r in rows:
        missing = sorted(
            {n for o in r["outcomes"].values() for n in INGEST_NEEDS if n not in o}
            | ({"_cached_fields"} if "_cached_fields" not in r else set())
        )
        (unusable if missing else usable).append((r, missing))
    if unusable:
        print(f"NOTE: {len(unusable)} main-pass row(s) lack what ingest needs and are skipped:")
        for r, missing in unusable:
            print(f"  - {r['doc_id']} run {r['run_idx']}: missing {', '.join(missing)}")

    done = {(j["doc_id"], j.get("run_idx", 0)) for j in _read_jsonl(judgments_path)}
    new = [r for r, _ in usable if (r["doc_id"], r["run_idx"]) not in done]
    _announce_skips(
        judgments_path, "(doc, run) pairs", len(usable),
        [f"{r['doc_id']} run {r['run_idx']}" for r, _ in usable if (r["doc_id"], r["run_idx"]) in done],
        nothing_left=not new,
    )
    for r in new:
        _append_jsonl(
            judgments_path,
            {
                "doc_id": r["doc_id"],
                "run_idx": r["run_idx"],
                "origin": "main_pass",
                "source_excerpt_chars": query_engine.excerpt_chars_for(r),
                "main_pass_input": main_pass_path.name,
                "ground_truth": r["ground_truth"],
                "fields": r["_cached_fields"],
                "outcomes": {
                    k: {
                        "judgment": o["judgment"],
                        "validated_status": o["status"],
                        "confidence": o["confidence"],
                        "resolved_cited_sources": o["cited_sources"],
                        "cited_sources_raw": o.get("cited_sources_raw"),
                        "sources": o["retrieved_sources"],
                        "reference_llm_status": None,
                        "reference_status": None,
                    }
                    for k, o in r["outcomes"].items()
                },
            },
        )
    print(f"Ingested {len(new)} (doc, run) pair(s) into {judgments_path} (no API calls).")
    if new:
        print(f"Next: python -m src.evaluation.claim_verification plan/check --judgments {judgments_path}")


def _check_claim(client, claim: str, chunk_texts: list[str]) -> ClaimCheck:
    source = "\n\n---\n\n".join(chunk_texts) if chunk_texts else "(no source text)"
    return client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=512,
        system=CLAIM_CHECK_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"SOURCE TEXT:\n{source}\n\nCLAIM:\n{claim}"}],
        response_model=ClaimCheck,
        tool_choice=single_tool_choice(ClaimCheck),
    )


def _resolve_check_outputs(output: str | None, judgments_path: Path | None = None) -> tuple[Path, Path, Path]:
    """
    Checklist item 17: `check` output paths. `--output` names the claim-check
    store; the default is PILOT_CHECKS_PATH for the pilot judgments file and
    <judgments stem>_checks.jsonl for any other judgments file (e.g. ingested
    main-pass judgments), so different judgment sets never share a store. The
    full results JSONL and the report are derived from the store's name:
    <store stem>_results.jsonl and <store stem>_report.md. The judgments file
    itself is refused as a store.
    """
    judgments_path = judgments_path or PILOT_JUDGMENTS_PATH
    if output:
        store = Path(output)
    elif judgments_path.resolve() == PILOT_JUDGMENTS_PATH.resolve():
        store = PILOT_CHECKS_PATH
    else:
        store = judgments_path.with_name(f"{judgments_path.stem}_checks.jsonl")
    if store.resolve() == judgments_path.resolve():
        raise SystemExit(f"Refusing to use {judgments_path} as the claim-check store: it holds the judgments.")
    return store, store.with_name(f"{store.stem}_results.jsonl"), store.with_name(f"{store.stem}_report.md")


def _claim_key(doc_id: str, run_idx: int, outcome: str, claim_index: int, claim: str) -> tuple:
    # The run and the claim text are part of the key, so the same document's
    # other runs, or a re-judged document's new claims, are never matched to
    # another claim's stored result.
    return (doc_id, run_idx, outcome, claim_index, claim)


def _store_key(rec: dict) -> tuple:
    return _claim_key(rec["doc_id"], rec.get("run_idx", 0), rec["outcome"], rec["claim_index"], rec["claim"])


def cmd_check(args) -> None:
    import instructor
    from anthropic import Anthropic

    judgments_path = _judgments_path(args)
    store_path, results_path, report_path = _resolve_check_outputs(args.output, judgments_path)
    print(f"Judgments file: {judgments_path}")
    print(f"Claim-check store: {store_path}")
    all_rows = _read_jsonl(judgments_path)
    if not all_rows:
        raise SystemExit(f"No judgments in {judgments_path} — run `judge` or `ingest` first.")

    # Mechanical checks (zero API cost) for EVERY recorded judgment, not just
    # --docs: the results file and report are rebuilt below from all
    # documents, so a --docs run never drops other documents (item 17).
    # --docs only limits which claims get NEW claim-check calls.
    results = mechanical_checks(all_rows, load_corpus())
    stored = {_store_key(rec): rec for rec in _read_jsonl(store_path)}

    requested = [
        (r, i, req)
        for r in results
        if _row_selected(r, args)
        for i, req in enumerate(r["regulatory_requirements"])
    ]
    skipped = [x for x in requested if _claim_key(x[0]["doc_id"], x[0]["run_idx"], x[0]["outcome"], x[1], x[2]["claim"]) in stored]
    pending = [x for x in requested if _claim_key(x[0]["doc_id"], x[0]["run_idx"], x[0]["outcome"], x[1], x[2]["claim"]) not in stored]

    # Resume (item 18): skips are announced, never silent, matching item 11.
    if skipped:
        print(
            f"\nWARNING: {store_path.name} already has claim-check results for {len(skipped)} of the "
            f"{len(requested)} requested claims. These will be SKIPPED, not re-checked:"
        )
        for r, i, req in skipped:
            print(f"  - {r['label']} {r['outcome']} claim #{i}: {req['claim'][:80]}")
        if not pending:
            print(
                "WARNING: every requested claim already has a result, so this invocation will make "
                "NO API calls. The results file and report are still rebuilt."
            )
        print()
    print(f"Running {len(pending)} claim-check calls.")
    # Observe-only record of why claim-check calls retry (src/agent/retry_log.py),
    # next to the store, the same as `run_eval main` does for its output.
    retries_path = store_path.with_name(f"{store_path.stem}_retries.jsonl")
    retry_log.set_path(retries_path)
    print(f"Retry log: {retries_path}")

    sources_by_key = {
        (row["doc_id"], row.get("run_idx", 0), k): row["outcomes"][k]["sources"] for row in all_rows for k in OUTCOME_KEYS
    }
    client = retry_log.attach(instructor.from_anthropic(Anthropic()), "claim_check") if pending else None
    for n, (r, i, req) in enumerate(pending, start=1):
        by_index = {s["index"]: s for s in sources_by_key[(r["doc_id"], r["run_idx"], r["outcome"])]}
        numbers = list(dict.fromkeys(s["excerpt_number"] for s in req["sources"]))
        chunk_texts = [by_index[x]["text_excerpt"] for x in numbers if x in by_index]
        retry_log.set_context(doc_id=r["doc_id"], run_idx=r["run_idx"], outcome=r["outcome"], claim_index=i)
        res = _check_claim(client, req["claim"], chunk_texts)
        support_match = (
            _best_in(res.supporting_sentence, [(str(x), by_index[x]["text_excerpt"]) for x in numbers if x in by_index])[1]
            if res.supporting_sentence.strip()
            else {"match_type": "none", "fuzzy_score": None}
        )
        rec = {
            "doc_id": r["doc_id"],
            "run_idx": r["run_idx"],
            "outcome": r["outcome"],
            "claim_index": i,
            "claim": req["claim"],
            "llm_check": {
                "verdict": res.verdict,
                "supporting_sentence": res.supporting_sentence,
                "supporting_sentence_match_type": support_match["match_type"],
                "chunks_shown": [x for x in numbers if x in by_index],
            },
        }
        # Item 18: saved the moment it comes back, so a crash later in the
        # run loses nothing already paid for.
        _append_jsonl(store_path, rec)
        stored[_store_key(rec)] = rec
        print(
            f"[{n}/{len(pending)}] {r['label']} {r['outcome']}: llm={res.verdict} "
            f"quote={[s['quote_location'] + '/' + s['match_type'] for s in req['sources']]} "
            f"sim_min={req['similarity_min']}"
        )

    # Attach stored results to every judgment's claims (all documents).
    used = set()
    for r in results:
        for i, req in enumerate(r["regulatory_requirements"]):
            key = _claim_key(r["doc_id"], r["run_idx"], r["outcome"], i, req["claim"])
            req["llm_check"] = stored[key]["llm_check"] if key in stored else None
            if key in stored:
                used.add(key)
    if len(stored) > len(used):
        print(
            f"NOTE: {len(stored) - len(used)} stored result(s) in {store_path.name} match no claim in the "
            "current judgments file (e.g. a document was re-judged). They stay in the store, unused."
        )

    # Item 17: the results file and report ARE rewritten in full, deliberately.
    # Both are pure views of (judgments file + whole store), rebuilt from all
    # documents every run, so nothing is lost by rewriting them. The store,
    # the only file holding paid-for results, is only ever appended to.
    results_path.write_text("\n".join(json.dumps(r) for r in results) + "\n", encoding="utf-8")
    complete = [r for r in results if all(q["llm_check"] for q in r["regulatory_requirements"])]
    incomplete = [r for r in results if not all(q["llm_check"] for q in r["regulatory_requirements"])]
    write_report(complete, report_path, store_path, results_path, incomplete)
    print(f"\nWrote {results_path}\nWrote {report_path}")


# --- report (facts only) ---

def _count(values) -> dict:
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def _dist_line(d: dict, order: list[str]) -> str:
    keys = [k for k in order if k in d] + [k for k in d if k not in order]
    return ", ".join(f"{k}: {d[k]}" for k in keys) if d else "(none)"


def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.4f}"


def write_report(
    results: list[dict], report_path: Path, store_path: Path, results_path: Path, incomplete: list[dict]
) -> None:
    """results: judgments whose claims are ALL claim-checked; incomplete: the rest, listed but not tabulated."""
    reqs = [(r, q) for r in results for q in r["regulatory_requirements"]]
    srcs = [(r, q, s) for r, q in reqs for s in q["sources"]]
    facts = [(r, f) for r in results for f in r["document_facts"]]
    absn = [(r, a) for r in results for a in r["absences"]]
    verdicts = ["yes", "partially", "no"]

    L = []
    L.append("# Structured-claim verification: pilot (P8-06)")
    L.append("")
    L.append(
        "Raw results only; no interpretation. Generated by "
        "`python -m src.evaluation.claim_verification check`. Design and limits: ARCHITECTURE.md "
        "\"Structured-claim verification (P8-06)\". Claim-check results (append-only store): "
        f"`{store_path.name}`. Full per-judgment records: `{results_path.name}`."
    )
    L.append("")
    if incomplete:
        L.append("## Judgments not yet fully claim-checked (excluded from every table below)")
        L.append("")
        for r in incomplete:
            n_unchecked = sum(1 for q in r["regulatory_requirements"] if not q["llm_check"])
            L.append(
                f"- {r['label']} / {r['outcome']}: {n_unchecked} of "
                f"{len(r['regulatory_requirements'])} regulatory claims unchecked"
            )
        L.append("")
    docs = sorted({r["doc_id"] for r in results}, key=lambda d: int(d.rsplit("_", 1)[1]))
    runs = sorted({r["run_idx"] for r in results})
    L.append(
        f"**Scope**: {len(docs)} documents ({', '.join(docs)}), runs {runs}, all 4 outcomes = "
        f"{len(results)} judgments. Origin: {_dist_line(_count(r['origin'] for r in results), [])} "
        "(pilot_judge: re-judged from a main pass's saved extraction; main_pass: the main pass's own "
        "judgments, ingested with no API calls)."
    )
    L.append("")

    L.append("## Claims verified by each method")
    L.append("")
    L.append("| Bucket | Claims | Method | Result |")
    L.append("|---|---|---|---|")
    L.append(
        f"| document_facts | {len(facts)} | quote vs. loan document text (no LLM) | "
        f"{_dist_line(_count(f['document_match']['match_type'] for _, f in facts), MATCH_ORDER)} |"
    )
    L.append(
        f"| regulatory_requirements | {len(reqs)} claims / {len(srcs)} sources | quote location (no LLM) | "
        f"{_dist_line(_count(s['quote_location'] for *_, s in srcs), LOCATION_ORDER)} |"
    )
    L.append(
        f"| regulatory_requirements | {len(srcs)} sources | claim-vs-named-excerpt embedding similarity (no LLM) | "
        f"computed for {sum(1 for *_, s in srcs if s['claim_similarity'] is not None)} |"
    )
    L.append(
        f"| regulatory_requirements | {len(reqs)} | narrow LLM check (every claim) | "
        f"{_dist_line(_count(q['llm_check']['verdict'] for _, q in reqs), verdicts)} |"
    )
    L.append(
        f"| absences | {len(absn)} | absent_from_document: extracted fields; "
        f"absent_from_retrieved_regulation: not verified | "
        f"{_dist_line(_count(a['kind'] + ' -> ' + a['result'] for _, a in absn), [])} |"
    )
    L.append("")

    L.append("## quote_location and match_type (per regulatory source)")
    L.append("")
    L.append("| quote_location | " + " | ".join(MATCH_ORDER) + " | total |")
    L.append("|---|" + "---|" * (len(MATCH_ORDER) + 1))
    for loc in LOCATION_ORDER:
        row = [sum(1 for *_, s in srcs if s["quote_location"] == loc and s["match_type"] == m) for m in MATCH_ORDER]
        L.append(f"| {loc} | " + " | ".join(str(x) for x in row) + f" | {sum(row)} |")
    corpus_retrieved = sum(1 for *_, s in srcs if s.get("corpus_chunk_was_retrieved"))
    L.append("")
    L.append(
        f"corpus_not_retrieved sources whose corpus chunk was one of the judgment's retrieved chunks "
        f"(quote lies past the truncated excerpt the judge saw; only possible for rows judged before Session 25): "
        f"{corpus_retrieved}"
    )
    L.append(
        f"Sources naming an excerpt number that was not among the retrieved excerpts: "
        f"{sum(1 for *_, s in srcs if not s['named_excerpt_exists'])}"
    )
    L.append(
        f"Sources whose named excerpt was not in the judgment's cited_sources: "
        f"{sum(1 for *_, s in srcs if not s['in_cited_sources'])}"
    )
    L.append("")

    L.append("## Single-source vs. multi-source claims")
    L.append("")
    L.append("| source_count | claims | worst quote_location per claim | LLM verdict | similarity_min (min / median / max) |")
    L.append("|---|---|---|---|---|")
    for sc in sorted({q["source_count"] for _, q in reqs}):
        group = [q for _, q in reqs if q["source_count"] == sc]
        sims = [q["similarity_min"] for q in group if q["similarity_min"] is not None]
        sim_txt = f"{_fmt(min(sims))} / {_fmt(statistics.median(sims))} / {_fmt(max(sims))}" if sims else "n/a"
        L.append(
            f"| {sc} | {len(group)} | {_dist_line(_count(q['worst_quote_location'] for q in group), LOCATION_ORDER)} | "
            f"{_dist_line(_count(q['llm_check']['verdict'] for q in group), verdicts)} | {sim_txt} |"
        )
    L.append("")

    L.append("## Quote check vs. LLM check")
    L.append("")
    L.append(
        "Claim-level quote result = the worst quote_location across the claim's sources. Cross-tab of that "
        "against the LLM verdict:"
    )
    L.append("")
    L.append("| worst quote_location | " + " | ".join(verdicts) + " |")
    L.append("|---|" + "---|" * len(verdicts))
    for loc in LOCATION_ORDER:
        L.append(
            f"| {loc} | "
            + " | ".join(
                str(sum(1 for _, q in reqs if q["worst_quote_location"] == loc and q["llm_check"]["verdict"] == v))
                for v in verdicts
            )
            + " |"
        )
    L.append("")
    L.append("claim-level similarity_min by LLM verdict (min / median / max; no threshold applied):")
    L.append("")
    for v in verdicts:
        sims = [q["similarity_min"] for _, q in reqs if q["llm_check"]["verdict"] == v and q["similarity_min"] is not None]
        L.append(
            f"- {v}: n={len(sims)}"
            + (f", {_fmt(min(sims))} / {_fmt(statistics.median(sims))} / {_fmt(max(sims))}" if sims else "")
        )
    L.append("")
    L.append(
        "LLM supporting_sentence found in the chunks shown to it: "
        + _dist_line(_count(q["llm_check"]["supporting_sentence_match_type"] for _, q in reqs), MATCH_ORDER)
    )
    L.append("")
    dis_a = [(r, q) for r, q in reqs if q["worst_quote_location"] == "named_chunk" and q["llm_check"]["verdict"] == "no"]
    dis_b = [(r, q) for r, q in reqs if q["worst_quote_location"] != "named_chunk" and q["llm_check"]["verdict"] == "yes"]
    part = [(r, q) for r, q in reqs if q["worst_quote_location"] == "named_chunk" and q["llm_check"]["verdict"] == "partially"]
    L.append(f"Disagreements: {len(dis_a) + len(dis_b)} of {len(reqs)} claims.")
    L.append("")
    L.append(f"- (A) every quote found in its named chunk, LLM verdict `no`: {len(dis_a)}")
    L.append(f"- (B) at least one quote not found in its named chunk, LLM verdict `yes`: {len(dis_b)}")
    L.append(f"- Also listed, not counted as disagreement: every quote in named chunk, LLM `partially`: {len(part)}")
    L.append("")
    for title, group in [("(A)", dis_a), ("(B)", dis_b), ("partially, quotes in named chunk", part)]:
        if not group:
            continue
        L.append(f"### {title}")
        L.append("")
        for r, q in group:
            L.append(f"- **{r['label']} / {r['outcome']}** — claim: {q['claim']}")
            for s in q["sources"]:
                L.append(
                    f"  - excerpt {s['excerpt_number']}: {s['quote_location']} / {s['match_type']}"
                    f" (fuzzy_score {s['fuzzy_score']}), similarity {_fmt(s['claim_similarity'])}, "
                    f"in cited_sources: {s['in_cited_sources']} — quote: \"{s['verbatim_quote']}\""
                )
            L.append(
                f"  - LLM: `{q['llm_check']['verdict']}`; supporting sentence "
                f"({q['llm_check']['supporting_sentence_match_type']}): \"{q['llm_check']['supporting_sentence']}\""
            )
        L.append("")

    L.append("## Every regulatory claim whose quote was not found")
    L.append("")
    nf = [(r, q) for r, q in reqs if any(s["quote_location"] == "not_found" for s in q["sources"])]
    if not nf:
        L.append("None.")
    for r, q in nf:
        L.append(f"### {r['label']} / {r['outcome']}")
        L.append("")
        L.append(f"- Claim: {q['claim']}")
        L.append(f"- source_count: {q['source_count']}")
        for s in q["sources"]:
            L.append(
                f"- Source excerpt {s['excerpt_number']} (named excerpt exists: {s['named_excerpt_exists']}, "
                f"in cited_sources: {s['in_cited_sources']}): {s['quote_location']} / {s['match_type']}, "
                f"best fuzzy_score {s['fuzzy_score']}, similarity {_fmt(s['claim_similarity'])}"
            )
            L.append(f"  - Quote: \"{s['verbatim_quote']}\"")
        L.append(f"- LLM verdict: `{q['llm_check']['verdict']}`; supporting sentence: \"{q['llm_check']['supporting_sentence']}\"")
        L.append("")

    L.append("## document_facts whose quote was not found in the loan document")
    L.append("")
    nf_facts = [(r, f) for r, f in facts if f["document_match"]["match_type"] == "none"]
    if not nf_facts:
        L.append("None.")
    for r, f in nf_facts:
        L.append(
            f"- **{r['label']} / {r['outcome']}** — claim: {f['claim']} — quote: \"{f['verbatim_quote']}\" "
            f"(best fuzzy_score {f['document_match']['fuzzy_score']})"
        )
    L.append("")

    L.append("## Absences")
    L.append("")
    for r, a in absn:
        extra = ""
        if a["kind"] == "absent_from_document":
            extra = f" — fields marked not addressed: {a['field_marked_not_addressed']}"
        L.append(f"- **{r['label']} / {r['outcome']}** [{a['kind']} -> {a['result']}]{extra} — {a['claim']}")
    if not absn:
        L.append("None.")
    L.append("")

    L.append("## Status vs. reference main-pass status (pilot_judge rows)")
    L.append("")
    with_ref = [r for r in results if r["reference_llm_status"] is not None]
    L.append(
        "Reference values are the main-pass statuses for the same (doc, run) the pilot judgment's "
        "extraction came from: "
        + (", ".join(sorted({r["main_pass_input"] for r in with_ref})) or "(none)")
        + f" ({MAIN_PASS_PATH.name} is the Phase 8 data). Since checklist item 4 the judge also sees "
        "the full document, so these are not like-for-like comparisons with Phase 8. Ingested "
        f"main_pass rows have no reference and are not listed: {len(results) - len(with_ref)}."
    )
    L.append("")
    L.append("| doc_id | run | outcome | ground truth | reference llm_status | new llm_status | reference status | new status | confidence |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in with_ref:
        L.append(
            f"| {r['doc_id']} | {r['run_idx']} | {r['outcome']} | {r['ground_truth']} | {r['reference_llm_status']} | "
            f"{r['llm_status']} | {r['reference_status']} | {r['status']} | {_fmt(r['confidence'])} |"
        )
    diffs = [r for r in with_ref if r["llm_status"] != r["reference_llm_status"] or r["status"] != r["reference_status"]]
    L.append("")
    L.append(f"Rows where llm_status or status differs from the reference value: {len(diffs)}")
    for r in diffs:
        L.append(
            f"- {r['label']} / {r['outcome']}: llm_status {r['reference_llm_status']} -> {r['llm_status']}, "
            f"status {r['reference_status']} -> {r['status']}"
        )
    L.append("")

    L.append("## Signal 1 against logged cited chunks")
    L.append("")
    L.append("Reasoning-vs-chunk embedding similarity for each cited chunk only. No threshold applied.")
    L.append("")
    L.append("| doc_id | run | outcome | cited | per-chunk scores | min | mean |")
    L.append("|---|---|---|---|---|---|---|")
    for r in results:
        s1 = r["signal1_cited"]
        per = ", ".join(f"[{c['index']}] {c['score']:.4f}" for c in s1["per_chunk"]) or "(none cited)"
        L.append(
            f"| {r['doc_id']} | {r['run_idx']} | {r['outcome']} | {r['cited_sources']} | {per} | "
            f"{_fmt(s1['min'])} | {_fmt(s1['mean'])} |"
        )
    L.append("")

    report_path.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Structured-claim verification pilot (P8-06)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, help_text in [
        ("plan", cmd_plan, "Zero API cost: replay check, exact call counts, mechanical checks"),
        ("judge", cmd_judge, "Judgment calls (4 per (doc, run) pair)"),
        ("ingest", cmd_ingest, "Zero API cost: copy a main pass's own judgments (any run) into a judgments file"),
        ("check", cmd_check, "One narrow LLM claim-check per regulatory claim; writes report"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument(
            "--docs", nargs="+",
            help=f"Doc ids (judge/plan default: {DEFAULT_PILOT_DOCS}; ingest/check default: all)",
        )
        p.add_argument(
            "--runs", nargs="+", type=int,
            help="run_idx values (judge/plan default: [0]; ingest/check default: all)",
        )
        p.add_argument(
            "--judgments",
            help=(
                f"Judgments file (default: docs/{PILOT_JUDGMENTS_PATH.name}; ingest default: "
                "<input stem>_claim_judgments.jsonl next to the input)"
            ),
        )
        if name in ("plan", "judge", "ingest"):  # `check` reads only the judgments file
            p.add_argument("--input", help=INPUT_HELP)
        if name in ("plan", "check"):
            p.add_argument(
                "--output",
                help=(
                    f"Claim-check store (default: docs/{PILOT_CHECKS_PATH.name}). Results and report "
                    "are written next to it as <store stem>_results.jsonl and <store stem>_report.md."
                ),
            )
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

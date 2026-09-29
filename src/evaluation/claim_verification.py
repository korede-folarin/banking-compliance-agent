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

Pilot scope: run_idx 0 of a few documents, all 4 outcomes. Extraction is the
cached run-0 `_cached_fields` from docs/eval_raw_main_pass.jsonl and
retrieval is replayed (deterministic, zero API cost), so the only new API
calls are the 4 judgment calls per document and one claim-check call per
regulatory claim. The 405-call main pass is NOT re-run.

Subcommands:
  plan    Zero API cost. Retrieval-replay spot check against the cached
          price_and_value context, the exact number of judgment calls still
          to make, and (once judgments exist) all mechanical checks plus the
          exact number of claim-check calls `check` would make.
  judge   4 judgment calls per pilot document (resumable per document).
  check   One narrow LLM claim-check call per regulatory claim, then writes
          docs/eval_claim_pilot_checks.jsonl and
          docs/eval_claim_verification_pilot.md.
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
from src.agent.schemas import LoanAgreementFields  # noqa: E402
from src.agent.uncertainty import NOT_ADDRESSED, _cosine_similarity, _get_embed_model, _splitter  # noqa: E402
from src.config import ANTHROPIC_MODEL, CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR  # noqa: E402
from src.evaluation.groundedness import compute_signal1_cited  # noqa: E402
from src.retrieval.query_engine import QueryResult, SourceCitation, load_index  # noqa: E402
from tests.fixtures.eval_set import EVAL_DOCUMENTS, OUTCOME_KEYS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = ROOT / "data" / "synthetic_docs"
DOCS_OUT_DIR = ROOT / "docs"
MAIN_PASS_PATH = DOCS_OUT_DIR / "eval_raw_main_pass.jsonl"
PILOT_JUDGMENTS_PATH = DOCS_OUT_DIR / "eval_claim_pilot_judgments.jsonl"
PILOT_CHECKS_PATH = DOCS_OUT_DIR / "eval_claim_pilot_checks.jsonl"
REPORT_PATH = DOCS_OUT_DIR / "eval_claim_verification_pilot.md"

# One document per deliberately-planted issue outcome where available, plus
# the control: loan_agreement_1 (price_and_value issue), _2 (consumer_support
# issue), _3 (control; its cached run-0 price_and_value is the known false
# accusation), _12 (consumer_understanding issue; cached run-0
# price_and_value is insufficient_evidence).
DEFAULT_PILOT_DOCS = ["loan_agreement_1", "loan_agreement_2", "loan_agreement_3", "loan_agreement_12"]

RETRIEVAL_TOP_K = 5
EXCERPT_CHARS = 300  # matches QueryEngine.query(): the judge only ever sees node.text[:300]

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


def _cached_run0(doc_id: str) -> dict:
    for r in _read_jsonl(MAIN_PASS_PATH):
        if r["doc_id"] == doc_id and r["run_idx"] == 0:
            return r
    raise SystemExit(f"No cached run_idx 0 row for {doc_id} in {MAIN_PASS_PATH}")


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
    # can sit in a retrieved chunk (past the 300-char excerpt) and in a
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
            # the 300-char excerpt the judge was actually shown.
            "corpus_chunk_was_retrieved": label in retrieved_ids,
        }
    # fuzzy_score here is the best in-order word match against the NAMED
    # excerpt, so a near-miss is visible in the log.
    return {"quote_location": "not_found", "match_type": "none", "fuzzy_score": named_fuzzy, "found_in": None}


# --- retrieval replay + corpus ---

def replay_sources(retriever, fields: LoanAgreementFields, outcome_key: str) -> list[dict]:
    nodes = retriever.retrieve(QUESTION_BUILDERS[outcome_key](fields))
    return [
        {
            "index": i,
            "node_id": n.node.node_id,
            "file_name": n.metadata.get("file_name", "unknown"),
            "similarity_score": n.score or 0.0,
            "text_excerpt": n.text[:EXCERPT_CHARS],
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
    """One record per (doc, outcome), all non-LLM checks filled in."""
    results = []
    for row in judgment_rows:
        doc_text = (DOCS_DIR / _doc_meta(row["doc_id"])["file"]).read_text(encoding="utf-8")
        fields = LoanAgreementFields(**row["fields"])
        doc_chunks = [(c, _embed(c)) for c in _splitter.split_text(doc_text)]
        for key in OUTCOME_KEYS:
            o = row["outcomes"][key]
            j = o["judgment"]
            results.append(
                {
                    "doc_id": row["doc_id"],
                    "outcome": key,
                    "ground_truth": row["ground_truth"][key],
                    "llm_status": j["status"],
                    "status": o["validated_status"],
                    "confidence": o["confidence"],
                    "cached_run0_llm_status": o["cached_run0_llm_status"],
                    "cached_run0_status": o["cached_run0_status"],
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


def cmd_plan(args) -> None:
    docs = _pilot_docs(args)
    retriever = load_index().as_retriever(similarity_top_k=RETRIEVAL_TOP_K)

    print(f"Pilot documents: {docs}")
    print("\nRetrieval-replay spot check vs. cached run-0 price_and_value context:")
    for doc_id in docs:
        cached = _cached_run0(doc_id)
        replay = replay_sources(retriever, LoanAgreementFields(**cached["_cached_fields"]), "price_and_value")
        cached_src = cached["_cached_price_and_value_context"]["sources"]
        same = [
            (a["file_name"], round(a["similarity_score"], 6), a["text_excerpt"])
            == (b["file_name"], round(b["similarity_score"], 6), b["text_excerpt"])
            for a, b in zip(replay, cached_src)
        ]
        print(f"  {doc_id}: {sum(same)}/{len(cached_src)} sources identical")

    done = {r["doc_id"] for r in _read_jsonl(PILOT_JUDGMENTS_PATH)}
    todo = [d for d in docs if d not in done]
    print(
        f"\nJudgment calls still to make: {len(todo)} docs x {len(OUTCOME_KEYS)} outcomes = "
        f"{len(todo) * len(OUTCOME_KEYS)} (nominal; instructor may retry a failed "
        "validation up to 3 times per call)."
    )

    rows = [r for r in _read_jsonl(PILOT_JUDGMENTS_PATH) if r["doc_id"] in docs]
    if not rows:
        print("No pilot judgments recorded yet, so the claim-check count is not known until `judge` runs.")
        return
    results = mechanical_checks(rows, load_corpus())
    n_claims = sum(len(r["regulatory_requirements"]) for r in results)
    print(f"\nMechanical checks run on {len(results)} recorded judgments (zero API cost).")
    print(
        f"  document_facts: {sum(len(r['document_facts']) for r in results)}, "
        f"regulatory_requirements: {n_claims}, absences: {sum(len(r['absences']) for r in results)}"
    )
    print(f"\n=> `check` would make exactly {n_claims} claim-check calls (one per regulatory claim, nominal).")


def cmd_judge(args) -> None:
    docs = _pilot_docs(args)
    done = {r["doc_id"] for r in _read_jsonl(PILOT_JUDGMENTS_PATH)}
    todo = [d for d in docs if d not in done]
    print(f"Judging {len(todo)} docs x {len(OUTCOME_KEYS)} outcomes = {len(todo) * len(OUTCOME_KEYS)} API calls.")

    retriever = load_index().as_retriever(similarity_top_k=RETRIEVAL_TOP_K)
    agent = ComplianceAgent()
    for doc_id in todo:
        cached = _cached_run0(doc_id)
        fields = LoanAgreementFields(**cached["_cached_fields"])
        sources = {k: replay_sources(retriever, fields, k) for k in OUTCOME_KEYS}
        contexts = {k: _query_result(QUESTION_BUILDERS[k](fields), sources[k]) for k in OUTCOME_KEYS}
        first_pass = FirstPassResult(
            document_fields=fields, **{CONTEXT_FIELD_BY_OUTCOME[k]: contexts[k] for k in OUTCOME_KEYS}
        )
        judgments: dict[str, OutcomeJudgment] = agent.evaluate(first_pass)

        outcomes = {}
        for k in OUTCOME_KEYS:
            v = validate_outcome(k, judgments[k], contexts[k])
            outcomes[k] = {
                "judgment": judgments[k].model_dump(),
                "validated_status": v.status,
                "confidence": v.confidence,
                "resolved_cited_sources": [s.model_dump() for s in v.cited_sources],
                "sources": sources[k],
                "cached_run0_llm_status": cached["outcomes"][k]["llm_status"],
                "cached_run0_status": cached["outcomes"][k]["status"],
            }
        _append_jsonl(
            PILOT_JUDGMENTS_PATH,
            {
                "doc_id": doc_id,
                "run_idx": 0,
                "ground_truth": _doc_meta(doc_id)["ground_truth"],
                "fields": fields.model_dump(),
                "outcomes": outcomes,
            },
        )
        print(f"{doc_id}: { {k: judgments[k].status for k in OUTCOME_KEYS} }")
    print(f"\nWrote {PILOT_JUDGMENTS_PATH}")


def _check_claim(client, claim: str, chunk_texts: list[str]) -> ClaimCheck:
    source = "\n\n---\n\n".join(chunk_texts) if chunk_texts else "(no source text)"
    return client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=512,
        system=CLAIM_CHECK_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"SOURCE TEXT:\n{source}\n\nCLAIM:\n{claim}"}],
        response_model=ClaimCheck,
    )


def cmd_check(args) -> None:
    import instructor
    from anthropic import Anthropic

    docs = _pilot_docs(args)
    rows = [r for r in _read_jsonl(PILOT_JUDGMENTS_PATH) if r["doc_id"] in docs]
    if not rows:
        raise SystemExit("No pilot judgments recorded — run `judge` first.")
    results = mechanical_checks(rows, load_corpus())
    total = sum(len(r["regulatory_requirements"]) for r in results)
    print(f"Running {total} claim-check calls.")

    sources_by_key = {(row["doc_id"], k): row["outcomes"][k]["sources"] for row in rows for k in OUTCOME_KEYS}
    client = instructor.from_anthropic(Anthropic())
    n = 0
    for r in results:
        by_index = {s["index"]: s for s in sources_by_key[(r["doc_id"], r["outcome"])]}
        for req in r["regulatory_requirements"]:
            numbers = list(dict.fromkeys(s["excerpt_number"] for s in req["sources"]))
            chunk_texts = [by_index[i]["text_excerpt"] for i in numbers if i in by_index]
            res = _check_claim(client, req["claim"], chunk_texts)
            support_match = (
                _best_in(res.supporting_sentence, [(str(i), by_index[i]["text_excerpt"]) for i in numbers if i in by_index])[1]
                if res.supporting_sentence.strip()
                else {"match_type": "none", "fuzzy_score": None}
            )
            req["llm_check"] = {
                "verdict": res.verdict,
                "supporting_sentence": res.supporting_sentence,
                "supporting_sentence_match_type": support_match["match_type"],
                "chunks_shown": [i for i in numbers if i in by_index],
            }
            n += 1
            print(
                f"[{n}/{total}] {r['doc_id']} {r['outcome']}: llm={res.verdict} "
                f"quote={[s['quote_location'] + '/' + s['match_type'] for s in req['sources']]} "
                f"sim_min={req['similarity_min']}"
            )

    PILOT_CHECKS_PATH.write_text("\n".join(json.dumps(r) for r in results) + "\n", encoding="utf-8")
    write_report(results)
    print(f"\nWrote {PILOT_CHECKS_PATH}\nWrote {REPORT_PATH}")


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


def write_report(results: list[dict]) -> None:
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
        "\"Structured-claim verification (P8-06)\". Per-claim records: `docs/eval_claim_pilot_checks.jsonl`."
    )
    L.append("")
    docs = sorted({r["doc_id"] for r in results}, key=lambda d: int(d.rsplit("_", 1)[1]))
    L.append(
        f"**Scope**: {len(docs)} documents ({', '.join(docs)}), run_idx 0, all 4 outcomes = "
        f"{len(results)} judgments. Cached run-0 extraction, replayed retrieval; only the judgment and "
        "claim-check calls are new."
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
        f"(quote lies past the 300-char excerpt the judge saw): {corpus_retrieved}"
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
            L.append(f"- **{r['doc_id']} / {r['outcome']}** — claim: {q['claim']}")
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
        L.append(f"### {r['doc_id']} / {r['outcome']}")
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
            f"- **{r['doc_id']} / {r['outcome']}** — claim: {f['claim']} — quote: \"{f['verbatim_quote']}\" "
            f"(best fuzzy_score {f['document_match']['fuzzy_score']})"
        )
    L.append("")

    L.append("## Absences")
    L.append("")
    for r, a in absn:
        extra = ""
        if a["kind"] == "absent_from_document":
            extra = f" — fields marked not addressed: {a['field_marked_not_addressed']}"
        L.append(f"- **{r['doc_id']} / {r['outcome']}** [{a['kind']} -> {a['result']}]{extra} — {a['claim']}")
    if not absn:
        L.append("None.")
    L.append("")

    L.append("## Status vs. cached Phase 8 run-0 status")
    L.append("")
    L.append("| doc_id | outcome | ground truth | cached llm_status | new llm_status | cached status | new status | confidence |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        L.append(
            f"| {r['doc_id']} | {r['outcome']} | {r['ground_truth']} | {r['cached_run0_llm_status']} | "
            f"{r['llm_status']} | {r['cached_run0_status']} | {r['status']} | {_fmt(r['confidence'])} |"
        )
    diffs = [r for r in results if r["llm_status"] != r["cached_run0_llm_status"] or r["status"] != r["cached_run0_status"]]
    L.append("")
    L.append(f"Rows where llm_status or status differs from the cached run-0 value: {len(diffs)}")
    for r in diffs:
        L.append(
            f"- {r['doc_id']} / {r['outcome']}: llm_status {r['cached_run0_llm_status']} -> {r['llm_status']}, "
            f"status {r['cached_run0_status']} -> {r['status']}"
        )
    L.append("")

    L.append("## Signal 1 against logged cited chunks")
    L.append("")
    L.append("Reasoning-vs-chunk embedding similarity for each cited chunk only. No threshold applied.")
    L.append("")
    L.append("| doc_id | outcome | cited | per-chunk scores | min | mean |")
    L.append("|---|---|---|---|---|---|")
    for r in results:
        s1 = r["signal1_cited"]
        per = ", ".join(f"[{c['index']}] {c['score']:.4f}" for c in s1["per_chunk"]) or "(none cited)"
        L.append(f"| {r['doc_id']} | {r['outcome']} | {r['cited_sources']} | {per} | {_fmt(s1['min'])} | {_fmt(s1['mean'])} |")
    L.append("")

    REPORT_PATH.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Structured-claim verification pilot (P8-06)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, help_text in [
        ("plan", cmd_plan, "Zero API cost: replay check, exact call counts, mechanical checks"),
        ("judge", cmd_judge, "Judgment calls (4 per pilot document)"),
        ("check", cmd_check, "One narrow LLM claim-check per regulatory claim; writes report"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--docs", nargs="+", help=f"Pilot doc ids (default: {DEFAULT_PILOT_DOCS})")
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

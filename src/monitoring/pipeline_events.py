"""
Stage events and checks for the main pipeline (docs/audit_logging_design.md,
section 5). Each function returns at once when no audit run is active, so
the pipeline does no extra work in ordinary use and tests.

None of these change a result: checks are logged (warn or route_to_review),
never enforced here. Enforcement stays where it already is (P4-02's
confidence threshold).
"""

from src import config
from src.monitoring import audit

NOT_ADDRESSED = "Not addressed in this document."
NUMERIC_FIELDS = ("loan_amount", "apr", "term_months")


def extraction(fields, document_text: str, duration_ms: int | None = None) -> None:
    if not audit.active():
        return
    from src.agent.uncertainty import _numeric_field_grounded  # deterministic, no model or embedding call

    values = fields.model_dump()
    audit.event("extraction", "success", duration_ms=duration_ms, data={
        "fields_returned": len(values),
        "not_addressed_count": sum(1 for v in values.values() if v == NOT_ADDRESSED),
        "document_sha256": audit.sha256_text(document_text), "document_chars": len(document_text),
    })
    for name in NUMERIC_FIELDS:
        value = values.get(name)
        found = value is not None and _numeric_field_grounded(float(value), document_text) == 1.0
        audit.check("extraction", f"numeric_field_in_document:{name}", found, metric=value,
                    threshold="value appears as a number in the document", action="warn")


def retrieval(outcome: str, result, duration_ms: int | None = None) -> None:
    if not audit.active():
        return
    scores = [s.similarity_score for s in result.sources]
    audit.event("retrieval", "success", outcome=outcome, duration_ms=duration_ms, data={
        "question": result.question,
        "sources": [{"index": s.index, "file_name": s.file_name, "node_id": s.node_id,
                     "score": round(s.similarity_score, 4)} for s in result.sources],
    })
    audit.check("retrieval", "has_results", bool(scores), metric=len(scores), threshold=">= 1",
                action="route_to_review", outcome=outcome)
    if scores:
        audit.check("retrieval", "top_score_on_topic", max(scores) >= config.RETRIEVAL_OFF_TOPIC_SCORE,
                    metric=round(max(scores), 4), threshold=config.RETRIEVAL_OFF_TOPIC_SCORE,
                    action="warn", outcome=outcome)


def judgment(outcome: str, judgment, context, document_text: str) -> None:
    if not audit.active():
        return
    from src.evaluation.claim_verification import match_quote  # pure-Python matcher, no model call

    retrieved = {s.index: s for s in context.sources}
    out_of_range = [i for i in judgment.cited_sources if i not in retrieved]
    audit.event("judgment", "success", outcome=outcome, data={
        "status": judgment.status, "cited_sources_raw": list(judgment.cited_sources),
        "document_facts": len(judgment.document_facts),
        "regulatory_requirements": len(judgment.regulatory_requirements), "absences": len(judgment.absences),
    })
    audit.check("judgment", "citations_in_range", not out_of_range, metric=out_of_range,
                threshold="every cited index is a retrieved excerpt", action="warn", outcome=outcome)
    missing = []
    for i, fact in enumerate(judgment.document_facts):
        if match_quote(fact.verbatim_quote, document_text)["match_type"] == "none":
            missing.append({"kind": "document_fact", "claim_index": i})
    for i, req in enumerate(judgment.regulatory_requirements):
        for src in req.sources:
            chunk = retrieved.get(src.excerpt_number)
            if chunk is None or match_quote(src.verbatim_quote, chunk.text_excerpt)["match_type"] == "none":
                missing.append({"kind": "regulatory_requirement", "claim_index": i,
                                "excerpt_number": src.excerpt_number})
    total = len(judgment.document_facts) + sum(len(r.sources) for r in judgment.regulatory_requirements)
    audit.check("judgment", "quotes_found", not missing, metric=f"{total - len(missing)}/{total}",
                threshold="every quote found in its named source", action="warn", outcome=outcome,
                data={"not_found": missing})


def validation(outcome: str, validated, threshold: float) -> None:
    if not audit.active():
        return
    audit.event("validation", "success", outcome=outcome, data={
        "llm_status": validated.llm_status, "status": validated.status,
        "confidence": round(validated.confidence, 4), "threshold": threshold,
        "overridden": validated.status != validated.llm_status,
        "cited_sources_resolved": [s.index for s in validated.cited_sources],
    })
    audit.check("validation", "has_cited_source", bool(validated.cited_sources),
                metric=len(validated.cited_sources), threshold=">= 1", action="route_to_review", outcome=outcome)


def report(needs_human_review: bool, statuses: dict) -> None:
    if not audit.active():
        return
    audit.event("validation", "success", data={"step": "report", "needs_human_review": needs_human_review,
                                                "statuses": statuses})

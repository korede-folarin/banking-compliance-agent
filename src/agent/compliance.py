import logging
from typing import Literal

import instructor
from anthropic import Anthropic
from pydantic import BaseModel, Field

from src.agent.first_pass import FirstPassAgent, FirstPassResult
from src.agent.schemas import LoanAgreementFields
from src.config import ANTHROPIC_MODEL, CONFIDENCE_THRESHOLD
from src.retrieval.query_engine import QueryResult, SourceCitation

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

Status = Literal["compliant", "potentially_non_compliant", "insufficient_evidence"]

OUTCOME_DISPLAY_NAMES = {
    "price_and_value": "Price and Value",
    "consumer_support": "Consumer Support",
    "products_and_services": "Products and Services",
    "consumer_understanding": "Consumer Understanding",
}

COMPLIANCE_SYSTEM_PROMPT = (
    "You are a compliance analyst comparing a specific clause (or the "
    "explicit absence of one) from a UK consumer loan agreement against "
    "retrieved excerpts of the FCA's Consumer Duty regulation for one "
    "specific outcome. Judge only from the retrieved excerpts provided — "
    "do not use outside knowledge of the Consumer Duty.\n\n"
    "Return status as one of:\n"
    '- "compliant": the document\'s stated approach is consistent with '
    "what the retrieved excerpts require.\n"
    '- "potentially_non_compliant": the document\'s stated approach '
    "conflicts with, falls short of, or fails to address something the "
    "retrieved excerpts establish as required. This includes the case "
    'where the document explicitly states an aspect is "Not addressed '
    'in this document" and the retrieved excerpts show firms are '
    "required to address it — that is a real gap in the document, not "
    "missing evidence.\n"
    '- "insufficient_evidence": the retrieved excerpts themselves do '
    "not contain enough specific, on-topic detail to support a compliant "
    "or potentially_non_compliant judgment either way. Use this only "
    "when the regulatory text is the limiting factor, not when the "
    "document simply doesn't address the topic (that case is "
    "potentially_non_compliant, above).\n\n"
    "cited_sources must list the excerpt number(s) your reasoning "
    "actually relies on. Do not invent or state a confidence score or "
    "percentage anywhere in your reasoning — confidence is computed "
    "separately, deterministically, from retrieval quality, not from "
    "your judgment."
)


class OutcomeJudgment(BaseModel):
    status: Status
    reasoning: str = Field(
        description=(
            "Brief explanation grounded in the retrieved regulatory excerpts, "
            "referencing excerpt numbers."
        )
    )
    cited_sources: list[int] = Field(
        description=(
            "Excerpt number(s), matching the numbered excerpts provided, that "
            "this judgment's reasoning actually relies on. Empty only if "
            "status is insufficient_evidence."
        )
    )


class ValidatedOutcome(BaseModel):
    outcome: str
    status: Status
    llm_status: Status
    reasoning: str
    cited_sources: list[SourceCitation]
    confidence: float


class ComplianceReport(BaseModel):
    document_fields: LoanAgreementFields
    price_and_value: ValidatedOutcome
    consumer_support: ValidatedOutcome
    products_and_services: ValidatedOutcome
    consumer_understanding: ValidatedOutcome
    needs_human_review: bool


def _build_evidence_context(sources: list[SourceCitation]) -> str:
    parts = []
    for s in sources:
        parts.append(f"[{s.index}] (Source: {s.file_name})\n{s.text_excerpt}")
    return "\n\n".join(parts)


class ComplianceAgent:
    """
    P4-01: the LLM reasoning layer. For each Consumer Duty outcome
    FirstPassAgent already extracted a field for and retrieved regulatory
    context on, compares the document's stated approach against the
    retrieved requirement and produces a structured judgment. Never
    outputs a numeric confidence score itself — that's computed
    separately and deterministically downstream (see validate_outcome,
    P4-02).
    """

    def __init__(self):
        self._client = instructor.from_anthropic(Anthropic())

    def _judge(self, outcome_name: str, document_statement: str, context: QueryResult) -> OutcomeJudgment:
        evidence = _build_evidence_context(context.sources)
        user_message = (
            f"Consumer Duty outcome under review: {outcome_name}\n\n"
            f'What the loan agreement states for this outcome:\n"{document_statement}"\n\n'
            f"Retrieved regulatory excerpts for this outcome:\n{evidence}"
        )
        return self._client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=COMPLIANCE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            response_model=OutcomeJudgment,
        )

    def evaluate(self, first_pass: FirstPassResult) -> dict[str, OutcomeJudgment]:
        fields = first_pass.document_fields
        return {
            "price_and_value": self._judge(
                OUTCOME_DISPLAY_NAMES["price_and_value"],
                f'Stated fees: "{fields.fees}"\n'
                f'Fair value justification: "{fields.fair_value_justification}"',
                first_pass.price_and_value_context,
            ),
            "consumer_support": self._judge(
                OUTCOME_DISPLAY_NAMES["consumer_support"],
                fields.vulnerable_customer_provision,
                first_pass.consumer_support_context,
            ),
            "products_and_services": self._judge(
                OUTCOME_DISPLAY_NAMES["products_and_services"],
                fields.target_market_suitability_statement,
                first_pass.products_and_services_context,
            ),
            "consumer_understanding": self._judge(
                OUTCOME_DISPLAY_NAMES["consumer_understanding"],
                fields.key_terms_summary_provision,
                first_pass.consumer_understanding_context,
            ),
        }


# --- P4-02: deterministic validation layer. Plain Python, no LLM call. ---

CONTEXT_FIELD_BY_OUTCOME = {
    "price_and_value": "price_and_value_context",
    "consumer_support": "consumer_support_context",
    "products_and_services": "products_and_services_context",
    "consumer_understanding": "consumer_understanding_context",
}


def _resolve_cited_sources(cited_indices: list[int], context: QueryResult) -> list[SourceCitation]:
    sources_by_index = {s.index: s for s in context.sources}
    resolved = []
    for i in cited_indices:
        source = sources_by_index.get(i)
        if source is None:
            logger.warning(
                "Judgment cited source index %s, which is not among the %d "
                "retrieved sources for this outcome — ignoring it.",
                i,
                len(context.sources),
            )
            continue
        resolved.append(source)
    return resolved


def compute_confidence(cited_sources: list[SourceCitation]) -> float:
    """
    Confidence is the MINIMUM retrieval similarity score among the
    sources a judgment actually cited — not an average, and not the
    LLM's self-reported confidence. Minimum, not average: a judgment
    resting on even one weakly-matched citation shouldn't count as
    well-supported just because its other citations are strong —
    averaging would let a weak link hide behind stronger ones.
    A judgment that cites no sources gets 0.0.
    """
    if not cited_sources:
        return 0.0
    return min(s.similarity_score for s in cited_sources)


def validate_outcome(
    outcome_key: str,
    judgment: OutcomeJudgment,
    context: QueryResult,
    threshold: float = CONFIDENCE_THRESHOLD,
) -> ValidatedOutcome:
    cited_sources = _resolve_cited_sources(judgment.cited_sources, context)
    confidence = compute_confidence(cited_sources)

    status = judgment.status
    if confidence < threshold:
        status = "insufficient_evidence"

    return ValidatedOutcome(
        outcome=OUTCOME_DISPLAY_NAMES[outcome_key],
        status=status,
        llm_status=judgment.status,
        reasoning=judgment.reasoning,
        cited_sources=cited_sources,
        confidence=confidence,
    )


def build_compliance_report(
    first_pass: FirstPassResult, judgments: dict[str, OutcomeJudgment]
) -> ComplianceReport:
    validated = {
        key: validate_outcome(key, judgments[key], getattr(first_pass, context_field))
        for key, context_field in CONTEXT_FIELD_BY_OUTCOME.items()
    }
    needs_human_review = any(
        v.status in ("potentially_non_compliant", "insufficient_evidence") for v in validated.values()
    )
    return ComplianceReport(
        document_fields=first_pass.document_fields,
        price_and_value=validated["price_and_value"],
        consumer_support=validated["consumer_support"],
        products_and_services=validated["products_and_services"],
        consumer_understanding=validated["consumer_understanding"],
        needs_human_review=needs_human_review,
    )


class ComplianceCheckAgent:
    """
    Orchestrates the full pipeline: FirstPassAgent (extraction +
    retrieval) -> ComplianceAgent (P4-01, LLM judgment per outcome) ->
    deterministic validation (P4-02, retrieval-grounded confidence +
    threshold). Constructed once and reused across documents —
    FirstPassAgent's QueryEngine loads the embedding model and opens the
    Chroma client at construction time, not per document.
    """

    def __init__(self):
        self._first_pass_agent = FirstPassAgent()
        self._compliance_agent = ComplianceAgent()

    def run(self, document_text: str) -> ComplianceReport:
        first_pass = self._first_pass_agent.run(document_text)
        judgments = self._compliance_agent.evaluate(first_pass)
        return build_compliance_report(first_pass, judgments)


def run_compliance_check(document_text: str) -> ComplianceReport:
    return ComplianceCheckAgent().run(document_text)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage: python -m src.agent.compliance <path-to-document>")
        raise SystemExit(1)

    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    report = run_compliance_check(text)
    print(report.model_dump_json(indent=2))

import json
import logging
from typing import Literal

import instructor
from anthropic import Anthropic
from pydantic import BaseModel, Field

from src.agent.first_pass import FirstPassAgent, FirstPassResult
from src.agent.schemas import LoanAgreementFields
from src.config import ANTHROPIC_MODEL, CONFIDENCE_THRESHOLD
from src.mcp_server.client import call_tools
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


MCP_ENRICHED_SYSTEM_PROMPT = (
    "You are a compliance analyst judging the Price and Value outcome for "
    "a UK consumer loan agreement, using THREE sources of evidence "
    "retrieved live via MCP tools: (1) the public FCA Consumer Duty "
    "regulation, (2) Northbridge Consumer Lending's internal underwriting "
    "policy, which may be stricter than the public regulation and "
    "controls where it is, and (3) the borrower's mock account history. "
    "Judge only from the excerpts and account data provided — do not use "
    "outside knowledge.\n\n"
    "Return status as one of:\n"
    '- "compliant": the document\'s stated approach satisfies BOTH the '
    "public regulation and internal policy, and nothing in the account "
    "history requires action the document's approach fails to address.\n"
    '- "potentially_non_compliant": the document\'s stated approach falls '
    "short of either the public regulation OR internal policy (internal "
    "policy can be stricter and still controls), or the account history "
    "shows a proactive-escalation trigger under internal policy that "
    "the document's approach does not address.\n"
    '- "insufficient_evidence": the retrieved excerpts themselves do not '
    "contain enough specific detail to judge either way.\n\n"
    "cited_sources must list the excerpt number(s) (regulation and/or "
    "policy) your reasoning actually relies on. Do not invent a "
    "confidence score."
)


# Structured-claim sub-models (P8-06). Appended AFTER the existing
# status/reasoning/cited_sources fields, so the verdict is generated first
# and these only itemise what it rests on. Each carries verbatim quotes so
# src/evaluation/claim_verification.py can check most of it without an LLM.
# Descriptions are deliberately short and neutral: they say what to record,
# never how to decide status.

class DocumentFact(BaseModel):
    claim: str = Field(description="A statement about what the loan agreement says.")
    verbatim_quote: str = Field(
        description="Text copied exactly, character for character, from the loan agreement text provided."
    )


class RegulatorySource(BaseModel):
    excerpt_number: int = Field(description="The number of the retrieved excerpt quoted.")
    verbatim_quote: str = Field(
        description=(
            "A short quote (one sentence or clause) copied exactly, character "
            "for character, from that excerpt."
        )
    )


class RegulatoryRequirement(BaseModel):
    claim: str = Field(description="A statement about what the retrieved regulatory excerpts say.")
    sources: list[RegulatorySource] = Field(
        description=(
            "One or more sources for this claim, each with its own quote. Use "
            "a single source wherever possible; use multiple sources only when "
            "the claim is a genuine synthesis that cannot be split into "
            "separate single-source claims."
        )
    )


class Absence(BaseModel):
    claim: str = Field(description="A statement that something is not present.")
    kind: Literal["absent_from_document", "absent_from_retrieved_regulation"] = Field(
        description="Where the thing is absent: the loan agreement, or the retrieved regulatory excerpts."
    )
    explanation: str = Field(description="What was looked for and not found.")


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
    document_facts: list[DocumentFact] = Field(
        description="Statements about the loan agreement that the reasoning relies on, each with a verbatim quote."
    )
    regulatory_requirements: list[RegulatoryRequirement] = Field(
        description=(
            "Statements about the retrieved regulatory excerpts that the "
            "reasoning relies on. One requirement per claim wherever possible."
        )
    )
    absences: list[Absence] = Field(
        description="Statements that something is not present, that the reasoning relies on."
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


def build_document_statement(outcome_key: str, fields: LoanAgreementFields) -> str:
    """The extracted-field text for one outcome, as shown to the judge."""
    if outcome_key == "price_and_value":
        return (
            f'Stated fees: "{fields.fees}"\n'
            f'Fair value justification: "{fields.fair_value_justification}"'
        )
    return {
        "consumer_support": fields.vulnerable_customer_provision,
        "products_and_services": fields.target_market_suitability_statement,
        "consumer_understanding": fields.key_terms_summary_provision,
    }[outcome_key]


def build_judgment_user_message(
    outcome_name: str, document_statement: str, document_text: str, sources: list[SourceCitation]
) -> str:
    """
    The judgment call's user message. Pure string assembly (no API call), so
    it can be tested directly and reused by run_eval.py's `variants`.

    Checklist item 4 (Session 22): the full loan agreement text is included,
    not only the extracted statement. Before this, the judge saw only the
    extraction, which is sometimes a paraphrase, so a `document_facts`
    verbatim quote could only be copied from that paraphrase and could not
    be checked against the real document. The extracted statement is kept
    as well, to point at the part of the document relevant to this outcome.
    Judgments made with this message are NOT directly comparable to the
    Phase 8 ones (see ARCHITECTURE.md "Evaluation notes").
    """
    return (
        f"Consumer Duty outcome under review: {outcome_name}\n\n"
        f'Full text of the loan agreement under review:\n"""\n{document_text}\n"""\n\n'
        f'What the loan agreement states for this outcome (extracted):\n"{document_statement}"\n\n'
        f"Retrieved regulatory excerpts for this outcome:\n{_build_evidence_context(sources)}"
    )


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

    def _judge(
        self, outcome_name: str, document_statement: str, document_text: str, context: QueryResult
    ) -> OutcomeJudgment:
        user_message = build_judgment_user_message(outcome_name, document_statement, document_text, context.sources)
        return self._client.messages.create(
            model=ANTHROPIC_MODEL,
            # 4096, not 1024: the P8-06 structured-claim fields (verbatim
            # quotes) are appended after status/reasoning and can push output
            # past 1024 tokens; truncation would fail schema validation.
            max_tokens=4096,
            system=COMPLIANCE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            response_model=OutcomeJudgment,
        )

    def evaluate(self, first_pass: FirstPassResult, document_text: str) -> dict[str, OutcomeJudgment]:
        # document_text is required (checklist item 4): every judgment sees the
        # full loan agreement, so no caller can silently produce summary-only
        # judgments.
        fields = first_pass.document_fields
        return {
            key: self._judge(
                OUTCOME_DISPLAY_NAMES[key],
                build_document_statement(key, fields),
                document_text,
                getattr(first_pass, CONTEXT_FIELD_BY_OUTCOME[key]),
            )
            for key in ("price_and_value", "consumer_support", "products_and_services", "consumer_understanding")
        }

    def judge_price_and_value_with_mcp_context(
        self, fields: LoanAgreementFields, borrower_name: str
    ) -> tuple[OutcomeJudgment, list[SourceCitation]]:
        """
        P5-04: judges the Price and Value outcome using all three MCP
        tools (regulation lookup, account lookup, internal policy query),
        called through the MCP interface (a subprocess speaking the MCP
        protocol over stdio), not direct Python calls. This is additive to
        `evaluate()` above, not a replacement for it — the existing P4-01/
        P4-02 pipeline is untouched.

        Enriches the same public-regulation question `evaluate()` already
        asks with two things it doesn't have access to: the borrower's
        mock account payment history (a Consumer Support/vulnerability
        angle) and Northbridge's internal fee-disclosure standard, which
        is concrete and stricter than the public regulation. Demonstrates
        genuine multi-tool use, not just three tools that happen to be
        callable: the internal policy tool draws on entirely different
        source documents than the regulation tool, and the account tool
        can surface an escalation trigger neither text corpus would show.

        Returns the judgment plus the combined regulation+policy source
        list (continuously renumbered), so a caller can compute confidence
        the same way P4-02 does for the baseline pipeline.
        """
        regulation_question = (
            "What does the Consumer Duty's Price and Value outcome require "
            "regarding fee/charge disclosure and demonstrating that a price "
            "represents fair value? The loan agreement under review states "
            f'its fees as: "{fields.fees}" and its fair value justification '
            f'as: "{fields.fair_value_justification}"'
        )
        policy_question = (
            "What does internal policy require for disclosing fees in a "
            "loan agreement, and what must happen if a fee is only "
            "referenced via a separate tariff of charges rather than "
            "stated as a specific amount?"
        )

        raw_account, raw_regulation, raw_policy = call_tools(
            [
                ("lookup_account", {"name_or_id": borrower_name}),
                ("lookup_regulation", {"question": regulation_question}),
                ("query_policy", {"question": policy_question}),
            ]
        )

        account = json.loads(raw_account)
        regulation_result = QueryResult.model_validate_json(raw_regulation)
        policy_result = QueryResult.model_validate_json(raw_policy)

        combined_sources: list[SourceCitation] = list(regulation_result.sources)
        offset = len(combined_sources)
        for s in policy_result.sources:
            combined_sources.append(
                SourceCitation(
                    index=s.index + offset,
                    file_name=s.file_name,
                    similarity_score=s.similarity_score,
                    text_excerpt=s.text_excerpt,
                )
            )
        evidence = _build_evidence_context(combined_sources)

        if account.get("found"):
            account_summary = (
                f"Account holder: {account['account_holder_name']} "
                f"(status: {account['account_status']}). Payment history "
                f"flags: {account.get('payment_history_flags') or 'none'}. "
                f"Notes: {account.get('notes', '')}"
            )
        else:
            account_summary = f"No account found for \"{borrower_name}\"."

        user_message = (
            "Consumer Duty outcome under review: Price and Value\n\n"
            f'What the loan agreement states:\nStated fees: "{fields.fees}"\n'
            f'Fair value justification: "{fields.fair_value_justification}"\n\n'
            f"Borrower account context (from mock account lookup):\n{account_summary}\n\n"
            f"Retrieved regulatory and internal policy excerpts:\n{evidence}"
        )

        judgment = self._client.messages.create(
            model=ANTHROPIC_MODEL,
            # 4096, not 1024: the P8-06 structured-claim fields (verbatim
            # quotes) are appended after status/reasoning and can push output
            # past 1024 tokens; truncation would fail schema validation.
            max_tokens=4096,
            system=MCP_ENRICHED_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            response_model=OutcomeJudgment,
        )
        return judgment, combined_sources


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

    # Forward-looking fix (does not change or backfill existing eval data,
    # see ARCHITECTURE.md "Evaluation notes" and docs/eval_groundedness.md):
    # the full cited source objects (index, file name, similarity score,
    # chunk text) are logged here, not just a count, so a judgment's actual
    # evidentiary basis is captured for audit and is available to any
    # future evaluation harness run without needing to reconstruct it via
    # retrieval replay. json.dumps for machine-parseability, not just a
    # human-readable message.
    logger.info(
        "outcome=%s status=%s confidence=%.4f cited_sources=%s",
        outcome_key,
        judgment.status,
        confidence,
        json.dumps([s.model_dump() for s in cited_sources]),
    )

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
        judgments = self._compliance_agent.evaluate(first_pass, document_text)
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

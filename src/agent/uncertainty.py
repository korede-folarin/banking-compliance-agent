import re

from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from pydantic import BaseModel

from src.agent.schemas import LoanAgreementFields
from src.config import CONFIDENCE_THRESHOLD, EMBED_MODEL_NAME

NOT_ADDRESSED = "Not addressed in this document."

# Extraction (unlike query/compliance) involves no retrieval step of its
# own, so there's no natural similarity score to build a confidence
# signal from. These are three different, deterministic (never
# LLM-self-reported) ways of checking whether an extracted field is
# actually grounded in the source document, chosen per field type based
# on what was empirically found to work: embedding similarity
# discriminates well for free-text clauses (correct extractions scored
# ~0.80-0.92 in testing, a fabricated field scored ~0.55-0.67), but
# systematically under-scores short proper nouns like names (correct
# names scored ~0.43-0.51, indistinguishable from or lower than the
# fabricated free-text scores) because a 2-3 word phrase and a full
# sentence containing it don't embed as similarly as two comparable
# sentences do. Names get exact substring matching instead; numbers get
# a numeric-presence check.
NAME_FIELDS = ["lender_name", "borrower_name"]
NUMERIC_FIELDS = ["loan_amount", "apr", "term_months"]
FREE_TEXT_FIELDS = [
    "repayment_schedule",
    "fees",
    "vulnerable_customer_provision",
    "fair_value_justification",
    "target_market_suitability_statement",
    "key_terms_summary_provision",
]

_embed_model: HuggingFaceEmbedding | None = None
_splitter = SentenceSplitter(chunk_size=256, chunk_overlap=20)


def _get_embed_model() -> HuggingFaceEmbedding:
    global _embed_model
    if _embed_model is None:
        _embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    return _embed_model


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _numbers_in_text(text: str) -> set[str]:
    return {m.replace(",", "") for m in re.findall(r"\d[\d,]*\.?\d*", text)}


def _numeric_field_grounded(value: float, document_text: str) -> float:
    doc_numbers = _numbers_in_text(document_text)
    candidates = {f"{value:.2f}", f"{value:.1f}", str(value)}
    if value == int(value):
        candidates.add(str(int(value)))
    return 1.0 if candidates & doc_numbers else 0.0


def _name_field_grounded(value: str, document_text: str) -> float:
    return 1.0 if value.strip().lower() in document_text.lower() else 0.0


def compute_field_confidence(
    document_text: str, fields: LoanAgreementFields
) -> dict[str, float]:
    """
    Deterministic, per-field grounding score (0.0-1.0) for every field
    LoanAgreementFields extracts, checked against the actual source
    document rather than trusted at face value.
    """
    scores: dict[str, float] = {}

    for name in NUMERIC_FIELDS:
        scores[name] = _numeric_field_grounded(getattr(fields, name), document_text)

    for name in NAME_FIELDS:
        scores[name] = _name_field_grounded(getattr(fields, name), document_text)

    chunks = _splitter.split_text(document_text)
    chunk_embeddings = [_get_embed_model().get_text_embedding(c) for c in chunks] if chunks else []

    for name in FREE_TEXT_FIELDS:
        value = getattr(fields, name)
        if value is None or value.strip() == NOT_ADDRESSED:
            # A controlled, verified-safe fallback string, not a claim
            # about the document — trivially grounded by construction.
            scores[name] = 1.0
            continue
        if not chunk_embeddings:
            scores[name] = 0.0
            continue
        value_embedding = _get_embed_model().get_text_embedding(value)
        scores[name] = max(_cosine_similarity(value_embedding, c) for c in chunk_embeddings)

    return scores


class GroundedExtractionResult(BaseModel):
    fields: LoanAgreementFields
    field_confidence: dict[str, float]
    confidence: float
    needs_human_review: bool


def extract_fields_with_confidence(document_text: str) -> GroundedExtractionResult:
    """
    Wraps extract_fields() (P2-01, unchanged) with the deterministic
    grounding check above. Additive: extract_fields() itself is not
    modified, so existing callers and tests are unaffected.
    """
    from src.agent.intake import extract_fields

    fields = extract_fields(document_text)
    field_confidence = compute_field_confidence(document_text, fields)
    confidence = min(field_confidence.values()) if field_confidence else 0.0
    return GroundedExtractionResult(
        fields=fields,
        field_confidence=field_confidence,
        confidence=confidence,
        needs_human_review=confidence < CONFIDENCE_THRESHOLD,
    )

import logging
import time

from pydantic import BaseModel

from src.agent.intake import extract_fields
from src.agent.schemas import LoanAgreementFields
from src.monitoring import pipeline_events
from src.retrieval.query_engine import QueryEngine, QueryResult

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class FirstPassResult(BaseModel):
    document_fields: LoanAgreementFields
    price_and_value_context: QueryResult
    consumer_support_context: QueryResult
    products_and_services_context: QueryResult
    consumer_understanding_context: QueryResult


# Pure, deterministic question-builders (no retrieval, no API call) — pulled
# out of FirstPassAgent.run() so a caller that already has a document's
# extracted fields (e.g. the groundedness harness replaying a cached eval
# row) can reconstruct the exact same question text and reuse the query
# engine's retriever, without re-running extraction. FirstPassAgent.run()
# below calls these directly, so there is exactly one place these templates
# are defined.

def build_price_and_value_question(fields: LoanAgreementFields) -> str:
    return (
        "What does the Consumer Duty's Price and Value outcome require "
        "regarding fee/charge disclosure and demonstrating that a price "
        "represents fair value? The loan agreement under review states "
        f'its fees as: "{fields.fees}" and its fair value justification '
        f'as: "{fields.fair_value_justification}"'
    )


def build_consumer_support_question(fields: LoanAgreementFields) -> str:
    return (
        "What does the Consumer Duty's Consumer Support outcome require "
        "regarding identifying and supporting customers in vulnerable "
        "circumstances? The loan agreement under review addresses this "
        f'as follows: "{fields.vulnerable_customer_provision}"'
    )


def build_products_and_services_question(fields: LoanAgreementFields) -> str:
    return (
        "What does the Consumer Duty's Products and Services outcome "
        "require regarding a product being designed for and suitable "
        "for its target market? The loan agreement under review "
        f'addresses this as follows: "{fields.target_market_suitability_statement}"'
    )


def build_consumer_understanding_question(fields: LoanAgreementFields) -> str:
    return (
        "What does the Consumer Duty's Consumer Understanding outcome "
        "require regarding presenting key terms clearly so customers can "
        "make informed decisions? The loan agreement under review "
        f'addresses this as follows: "{fields.key_terms_summary_provision}"'
    )


QUESTION_BUILDERS = {
    "price_and_value": build_price_and_value_question,
    "consumer_support": build_consumer_support_question,
    "products_and_services": build_products_and_services_question,
    "consumer_understanding": build_consumer_understanding_question,
}


class FirstPassAgent:
    """
    Wires the Intake Agent (structured extraction) and the query engine
    (grounded regulatory retrieval) together into a single first-pass
    response: extracted fields + relevant regulatory context for them,
    one retrieval call per Consumer Duty outcome the schema tracks.

    Does NOT compare the two or produce a compliance verdict — that
    reasoning is Phase 4 (the orchestrating Compliance Agent +
    deterministic validation layer).
    """

    def __init__(self):
        self._query_engine = QueryEngine()

    def run(self, document_text: str) -> FirstPassResult:
        t0 = time.time()
        fields = extract_fields(document_text)
        pipeline_events.extraction(fields, document_text, int((time.time() - t0) * 1000))

        contexts = {}
        for key, build_question in QUESTION_BUILDERS.items():
            t0 = time.time()
            contexts[key] = self._query_engine.query(build_question(fields))
            pipeline_events.retrieval(key, contexts[key], int((time.time() - t0) * 1000))

        return FirstPassResult(
            document_fields=fields,
            price_and_value_context=contexts["price_and_value"],
            consumer_support_context=contexts["consumer_support"],
            products_and_services_context=contexts["products_and_services"],
            consumer_understanding_context=contexts["consumer_understanding"],
        )


def run_first_pass(document_text: str) -> FirstPassResult:
    return FirstPassAgent().run(document_text)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage: python -m src.agent.first_pass <path-to-document>")
        raise SystemExit(1)

    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    result = run_first_pass(text)
    print(result.model_dump_json(indent=2))

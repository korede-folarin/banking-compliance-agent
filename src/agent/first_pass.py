import logging

from pydantic import BaseModel

from src.agent.intake import extract_fields
from src.agent.schemas import LoanAgreementFields
from src.retrieval.query_engine import QueryEngine, QueryResult

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class FirstPassResult(BaseModel):
    document_fields: LoanAgreementFields
    price_and_value_context: QueryResult
    consumer_support_context: QueryResult
    products_and_services_context: QueryResult
    consumer_understanding_context: QueryResult


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
        fields = extract_fields(document_text)

        price_and_value_question = (
            "What does the Consumer Duty's Price and Value outcome require "
            "regarding fee/charge disclosure and demonstrating that a price "
            "represents fair value? The loan agreement under review states "
            f'its fees as: "{fields.fees}" and its fair value justification '
            f'as: "{fields.fair_value_justification}"'
        )
        price_and_value_context = self._query_engine.query(price_and_value_question)

        consumer_support_question = (
            "What does the Consumer Duty's Consumer Support outcome require "
            "regarding identifying and supporting customers in vulnerable "
            "circumstances? The loan agreement under review addresses this "
            f'as follows: "{fields.vulnerable_customer_provision}"'
        )
        consumer_support_context = self._query_engine.query(consumer_support_question)

        products_and_services_question = (
            "What does the Consumer Duty's Products and Services outcome "
            "require regarding a product being designed for and suitable "
            "for its target market? The loan agreement under review "
            f'addresses this as follows: "{fields.target_market_suitability_statement}"'
        )
        products_and_services_context = self._query_engine.query(products_and_services_question)

        consumer_understanding_question = (
            "What does the Consumer Duty's Consumer Understanding outcome "
            "require regarding presenting key terms clearly so customers can "
            "make informed decisions? The loan agreement under review "
            f'addresses this as follows: "{fields.key_terms_summary_provision}"'
        )
        consumer_understanding_context = self._query_engine.query(consumer_understanding_question)

        return FirstPassResult(
            document_fields=fields,
            price_and_value_context=price_and_value_context,
            consumer_support_context=consumer_support_context,
            products_and_services_context=products_and_services_context,
            consumer_understanding_context=consumer_understanding_context,
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

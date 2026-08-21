import logging

from pydantic import BaseModel

from src.agent.intake import extract_fields
from src.agent.schemas import LoanAgreementFields
from src.retrieval.query_engine import QueryEngine, QueryResult

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class FirstPassResult(BaseModel):
    document_fields: LoanAgreementFields
    fee_disclosure_context: QueryResult
    vulnerable_customer_context: QueryResult


class FirstPassAgent:
    """
    Wires the Intake Agent (structured extraction) and the query engine
    (grounded regulatory retrieval) together into a single first-pass
    response: extracted fields + relevant regulatory context for them.

    Does NOT compare the two or produce a compliance verdict — that
    reasoning is Phase 4 (the orchestrating Compliance Agent +
    deterministic validation layer).
    """

    def __init__(self):
        self._query_engine = QueryEngine()

    def run(self, document_text: str) -> FirstPassResult:
        fields = extract_fields(document_text)

        fee_question = (
            "What does the Consumer Duty require regarding how a firm "
            "discloses fees and charges to consumers, and what would count "
            "as inadequate disclosure? The loan agreement under review "
            f'states its fees as: "{fields.fees}"'
        )
        fee_context = self._query_engine.query(fee_question)

        clauses_text = "; ".join(fields.key_clauses) if fields.key_clauses else "none stated"
        vulnerable_question = (
            "What does the Consumer Duty require regarding identifying and "
            "supporting customers in vulnerable circumstances? The loan "
            f"agreement under review includes the following clauses: {clauses_text}"
        )
        vulnerable_context = self._query_engine.query(vulnerable_question)

        return FirstPassResult(
            document_fields=fields,
            fee_disclosure_context=fee_context,
            vulnerable_customer_context=vulnerable_context,
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

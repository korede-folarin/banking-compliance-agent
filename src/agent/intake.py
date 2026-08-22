import logging

import instructor
from anthropic import Anthropic

from src.agent.schemas import LoanAgreementFields
from src.config import ANTHROPIC_MODEL

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an intake agent extracting structured fields from a UK consumer "
    "loan agreement. Extract only what is actually stated in the document. Do "
    "not infer, guess, or fill in values that are not present in the text — if "
    "a fee amount is not clearly stated, describe how the document refers to it "
    "instead of inventing a number. For the compliance-relevant clause fields "
    '(vulnerable_customer_provision, fair_value_justification, '
    "target_market_suitability_statement, key_terms_summary_provision): if the "
    'document does not contain that type of clause, you must still return the '
    'field with the literal string "Not addressed in this document." — never '
    "omit the field and never return null. Reporting an absence explicitly is "
    "just as important as reporting a clause that is present."
)


class IntakeAgent:
    def __init__(self):
        self._client = instructor.from_anthropic(Anthropic())

    def extract(self, document_text: str) -> LoanAgreementFields:
        return self._client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": document_text}],
            response_model=LoanAgreementFields,
        )


def extract_fields(document_text: str) -> LoanAgreementFields:
    return IntakeAgent().extract(document_text)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage: python -m src.agent.intake <path-to-document>")
        raise SystemExit(1)

    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    result = extract_fields(text)
    print(result.model_dump_json(indent=2))

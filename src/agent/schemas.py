from pydantic import BaseModel, Field


class LoanAgreementFields(BaseModel):
    lender_name: str = Field(description="Full legal name of the lender/creditor")
    borrower_name: str = Field(description="Full name of the borrower")
    loan_amount: float = Field(
        description="Principal loan amount in GBP, as a plain number (no currency symbol or commas)"
    )
    apr: float = Field(
        description="Annual Percentage Rate of Charge, as a percentage number, e.g. 24.9 for 24.9%"
    )
    term_months: int = Field(description="Loan term length in months")
    repayment_schedule: str = Field(
        description=(
            "The repayment schedule exactly as stated in the document: instalment "
            "amount, frequency, and payment method."
        )
    )
    fees: str = Field(
        description=(
            "All fees/charges exactly as stated in the document. If a fee is "
            "referenced without a specific amount in the document text, describe "
            "how it is referenced instead of inventing a figure."
        )
    )
    # The four fields below map 1:1 onto the FCA Consumer Duty's four
    # outcomes (Products and Services, Price and Value, Consumer
    # Understanding, Consumer Support) — derived by querying the actual
    # indexed regulatory corpus for each outcome's obligations, not from
    # general knowledge. See ARCHITECTURE.md "Compliance-check field
    # provenance" for the grounding and its limits. Two other example
    # categories (cooling-off/cancellation rights, detailed complaints
    # handling) were deliberately excluded — the corpus doesn't
    # substantively cover them; the small amount of complaints/arrears
    # content it has only cross-references DISP/CONC rules that aren't
    # part of this corpus.
    vulnerable_customer_provision: str | None = Field(
        description=(
            "Any clause addressing identification of, or support for, "
            "customers in vulnerable circumstances (e.g. ill health, "
            "bereavement, low financial resilience, low capability), as "
            "required by the Consumer Duty's Consumer Support outcome. Quote "
            "or closely paraphrase the relevant clause if present. If the "
            'document does not address this at all, respond with exactly: '
            '"Not addressed in this document." Never return null and never '
            "omit this field."
        )
    )
    fair_value_justification: str | None = Field(
        description=(
            "Any statement in the document explaining or justifying why the "
            "fees/charges/price represent fair value to the borrower — "
            "distinct from simply stating the fee amount (see the `fees` "
            "field for that) — as required by the Consumer Duty's Price and "
            "Value outcome. If the document states fees but never explains "
            'or justifies why they represent fair value, respond with '
            'exactly: "Not addressed in this document." Never return null '
            "and never omit this field."
        )
    )
    target_market_suitability_statement: str | None = Field(
        description=(
            "Any statement confirming the loan is designed for, or suitable "
            "for, the borrower's identified needs, characteristics, or "
            "circumstances (target market fit), as required by the Consumer "
            "Duty's Products and Services outcome. If the document contains "
            'no such statement, respond with exactly: "Not addressed in '
            'this document." Never return null and never omit this field.'
        )
    )
    key_terms_summary_provision: str | None = Field(
        description=(
            "Any dedicated, upfront summary or 'key facts' presentation of "
            "the loan's core terms (amount, APR, term, cost), separate from "
            "the full clause-by-clause text, as encouraged by the Consumer "
            "Duty's Consumer Understanding outcome for supporting customer "
            "understanding. If the document has no such standalone summary "
            "and states key terms only within the numbered clauses, respond "
            'with exactly: "Not addressed in this document." Never return '
            "null and never omit this field."
        )
    )

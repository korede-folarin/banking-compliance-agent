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
    key_clauses: list[str] = Field(
        description=(
            "Short summaries of other notable clauses in the document (e.g. early "
            "repayment rights, default consequences, vulnerable customer "
            "provisions, governing law), each as a brief string."
        )
    )

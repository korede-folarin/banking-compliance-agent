"""
What the agent must submit at the end of a tool-loop run (src/agent/tool_agent.py).

Every judgment points at evidence numbers (E1, E2, ...) that the loop assigned
to passages and records the tools returned, and quotes that evidence verbatim,
so the deterministic validation layer (src/agent/agent_validation.py) can check
each claim against the exact text it names.
"""

from typing import Literal

from pydantic import BaseModel, Field

from src.agent.compliance import OutcomeJudgment

OUTCOME_KEYS = ("price_and_value", "consumer_support", "products_and_services", "consumer_understanding")


class DocumentScope(BaseModel):
    is_credit_agreement: bool = Field(description="Whether the document is a credit (loan) agreement.")
    lender_named: str | None = Field(description="The lender's name exactly as the document states it, or null if "
                                                 "the document names no lender.")
    lender_is_northbridge: Literal["yes", "no", "not_stated"] = Field(
        description="Whether the lender is Northbridge Consumer Lending.")


class QuotedEvidence(BaseModel):
    evidence_number: int = Field(description="The evidence number (the number after E) the quote is taken from.")
    verbatim_quote: str = Field(description="Text copied exactly, character for character, from that evidence.")


class NoteQuote(BaseModel):
    evidence_number: int = Field(description="The evidence number of the account record.")
    note_date: str = Field(description="The note's date exactly as the account record gives it (YYYY-MM-DD).")
    verbatim_quote: str = Field(description="The note's text, copied exactly.")


class EscalationAssessment(BaseModel):
    decision: Literal["escalate", "no_escalation", "cannot_determine", "not_applicable"] = Field(
        description="Whether Northbridge's vulnerable customer escalation procedure requires escalation. "
                    "not_applicable if the customer is not a Northbridge customer or the document is not a credit "
                    "agreement.")
    triggers: list[Literal["2.1(a)", "2.1(b)", "2.1(c)"]] = Field(
        description="The procedure's section 2.1 triggers that apply. Empty unless decision is escalate.")
    policy_quotes: list[QuotedEvidence] = Field(
        description="The procedure text the decision rests on, quoted exactly from policy evidence. Required for "
                    "escalate and no_escalation.")
    note_quotes: list[NoteQuote] = Field(
        description="For trigger 2.1(c): each account note relied on, with its date, quoted exactly. Empty otherwise.")
    discrepancies: list[str] = Field(
        description="Any mismatch between the document and the account record (for example a different holder "
                    "name, or the agreement reference not among the account's products). Empty if none.")
    reasoning: str = Field(description="Brief explanation citing evidence numbers.")
    cited_evidence: list[int] = Field(description="Evidence numbers (the number after E) relied on.")


class AgentAssessment(BaseModel):
    document: DocumentScope
    price_and_value: OutcomeJudgment
    consumer_support: OutcomeJudgment
    products_and_services: OutcomeJudgment
    consumer_understanding: OutcomeJudgment
    escalation: EscalationAssessment

"""
Phase 8 labelled evaluation set.

Each entry pairs a synthetic loan agreement with a human-assigned ground
truth label ("compliant" / "non_compliant") for each of the four Consumer
Duty outcomes the pipeline judges. Ground truth is binary by design: it
reflects what a human reviewer would conclude from reading the document
against the Consumer Duty, not the three-way LLM/system output
(compliant / potentially_non_compliant / insufficient_evidence).
"insufficient_evidence" is a signal about retrieval quality, not a ground
truth label a document can carry — see docs/eval_results.md for how the
harness scores it (an abstention, not a correct/incorrect prediction).

15 documents total: the 3 original synthetic docs (loan_agreement_1-3,
Session 4/8) plus 12 new ones (loan_agreement_4-15, this session). The
original 2 only ever isolated issues in price_and_value and
consumer_support; products_and_services and consumer_understanding had
never been deliberately tested with a real issue before this set.
"""

OUTCOME_KEYS = [
    "price_and_value",
    "consumer_support",
    "products_and_services",
    "consumer_understanding",
]

ALL_COMPLIANT = {k: "compliant" for k in OUTCOME_KEYS}


def _gt(non_compliant_outcome: str | None) -> dict[str, str]:
    labels = dict(ALL_COMPLIANT)
    if non_compliant_outcome:
        labels[non_compliant_outcome] = "non_compliant"
    return labels


EVAL_DOCUMENTS = [
    {
        "id": "loan_agreement_1",
        "file": "loan_agreement_1.txt",
        "issue_outcome": "price_and_value",
        "issue_note": (
            "Fee referenced only via an unquantified 'tariff of charges' "
            "cross-reference; no amount ever stated in the agreement."
        ),
        "ground_truth": _gt("price_and_value"),
    },
    {
        "id": "loan_agreement_2",
        "file": "loan_agreement_2.txt",
        "issue_outcome": "consumer_support",
        "issue_note": "No vulnerable-customer clause at all; generic customer-service clause only.",
        "ground_truth": _gt("consumer_support"),
    },
    {
        "id": "loan_agreement_3",
        "file": "loan_agreement_3.txt",
        "issue_outcome": None,
        "issue_note": "Control: all 4 outcomes addressed properly.",
        "ground_truth": _gt(None),
    },
    {
        "id": "loan_agreement_4",
        "file": "loan_agreement_4.txt",
        "issue_outcome": "price_and_value",
        "issue_note": (
            "Fee is clearly disclosed as a specific figure, but there is no fair-value "
            "justification clause at all (total silence, not a vague reference)."
        ),
        "ground_truth": _gt("price_and_value"),
    },
    {
        "id": "loan_agreement_5",
        "file": "loan_agreement_5.txt",
        "issue_outcome": "price_and_value",
        "issue_note": (
            "Fair-value justification clause self-contradicts: claims 'no fees are "
            "charged' while the Key Facts box and clause 4.1 clearly charge a £220 fee."
        ),
        "ground_truth": _gt("price_and_value"),
    },
    {
        "id": "loan_agreement_6",
        "file": "loan_agreement_6.txt",
        "issue_outcome": "price_and_value",
        "issue_note": (
            "Fee is disclosed only as a wide range (£120-£350, confirmed at "
            "underwriting) with no fair-value justification of the variable pricing."
        ),
        "ground_truth": _gt("price_and_value"),
    },
    {
        "id": "loan_agreement_7",
        "file": "loan_agreement_7.txt",
        "issue_outcome": "consumer_support",
        "issue_note": "Vulnerable-customer clause omitted entirely, no substitute of any kind.",
        "ground_truth": _gt("consumer_support"),
    },
    {
        "id": "loan_agreement_8",
        "file": "loan_agreement_8.txt",
        "issue_outcome": "consumer_support",
        "issue_note": (
            "One-line perfunctory clause ('customers experiencing financial "
            "difficulty may contact us') with no process, no vulnerability "
            "categories, no support options."
        ),
        "ground_truth": _gt("consumer_support"),
    },
    {
        "id": "loan_agreement_9",
        "file": "loan_agreement_9.txt",
        "issue_outcome": "consumer_support",
        "issue_note": (
            "Clause present but explicitly scoped to financial hardship only, "
            "expressly excluding health, bereavement, and capability circumstances."
        ),
        "ground_truth": _gt("consumer_support"),
    },
    {
        "id": "loan_agreement_10",
        "file": "loan_agreement_10.txt",
        "issue_outcome": "products_and_services",
        "issue_note": "No target market / suitability statement anywhere in the document.",
        "ground_truth": _gt("products_and_services"),
    },
    {
        "id": "loan_agreement_11",
        "file": "loan_agreement_11.txt",
        "issue_outcome": "products_and_services",
        "issue_note": (
            "Target market statement present but describes a mismatched market "
            "(flexible revolving credit) for what is actually a fixed-term, "
            "fixed-instalment loan."
        ),
        "ground_truth": _gt("products_and_services"),
    },
    {
        "id": "loan_agreement_12",
        "file": "loan_agreement_12.txt",
        "issue_outcome": "consumer_understanding",
        "issue_note": "No Key Facts / upfront summary at all; terms only inside numbered clauses.",
        "ground_truth": _gt("consumer_understanding"),
    },
    {
        "id": "loan_agreement_13",
        "file": "loan_agreement_13.txt",
        "issue_outcome": "consumer_understanding",
        "issue_note": (
            "Has a 'KEY INFORMATION' heading, but its content is just defined-terms "
            "boilerplate — never restates the actual amount/APR/term/cost."
        ),
        "ground_truth": _gt("consumer_understanding"),
    },
    {
        "id": "loan_agreement_14",
        "file": "loan_agreement_14.txt",
        "issue_outcome": None,
        "issue_note": "Control #2: all 4 outcomes addressed properly, same phrasing style as doc3.",
        "ground_truth": _gt(None),
    },
    {
        "id": "loan_agreement_15",
        "file": "loan_agreement_15.txt",
        "issue_outcome": None,
        "issue_note": (
            "Control #3: all 4 outcomes addressed properly, deliberately different "
            "phrasing register (plain-language 'Your loan at a glance', credit-union "
            "voice) to test generalization beyond one house style."
        ),
        "ground_truth": _gt(None),
    },
]

assert len(EVAL_DOCUMENTS) == 15
assert len({d["id"] for d in EVAL_DOCUMENTS}) == 15


# --- Retrieval recall@k test set (P8-02) ---
# Canonical, document-independent questions for each outcome, plus one
# off-topic control. Ground truth ("relevant" chunks) established by
# directly inspecting retriever output (no LLM involved, no API cost) and
# manually confirming which chunks actually discuss that specific outcome
# (as opposed to being generically Consumer-Duty-adjacent). A chunk counts
# as relevant if its text contains that outcome's dedicated chapter heading
# (e.g. "7 The price and value outcome") or is drawn from that chapter's
# immediate content in fg22-5.pdf, ps22-9.pdf, or the PRIN 2A Handbook
# excerpt — the three files that were confirmed to carry substantive,
# on-topic content for all 4 outcomes.
RETRIEVAL_QUERIES = [
    {
        "id": "price_and_value",
        "question": (
            "What does the Consumer Duty's Price and Value outcome require "
            "regarding fee disclosure and demonstrating fair value?"
        ),
        "relevant_marker": "the price and value outcome",
    },
    {
        "id": "consumer_support",
        "question": (
            "What does the Consumer Duty's Consumer Support outcome require "
            "regarding identifying and supporting vulnerable customers?"
        ),
        "relevant_marker": "the consumer support outcome",
    },
    {
        "id": "products_and_services",
        "question": (
            "What does the Consumer Duty's Products and Services outcome "
            "require regarding target market fit?"
        ),
        "relevant_marker": "the products and services outcome",
    },
    {
        "id": "consumer_understanding",
        "question": (
            "What does the Consumer Duty's Consumer Understanding outcome "
            "require regarding presenting key terms clearly?"
        ),
        "relevant_marker": "the consumer understanding outcome",
    },
    {
        "id": "off_topic_control",
        "question": "What is the capital of France?",
        "relevant_marker": None,  # no chunk in this corpus should count as relevant
    },
]

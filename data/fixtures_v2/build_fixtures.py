"""
Builds the v2 fixture set: 16 synthetic loan agreements, their account
records, and the labels (docs/agent_tool_use_design.md).

Deterministic (fixed seed): re-running reproduces every file byte for byte.
The v1 set (data/synthetic_docs/, data/mock_accounts/) is not touched; it
stays the baseline.

Writes:
  data/fixtures_v2/docs/v2_dNN.txt       loan agreements (what the agent reads)
  data/fixtures_v2/accounts.json         account records (what get_account serves)
  tests/fixtures/eval_set_v2.json        labels + expected tool calls (graders only)

The agent never sees this script, the labels file, or the scenario names.
Account records hold raw dated facts only: no flags named after a policy
trigger, no notes that describe the test or restate a flag.

Run from the repo root:  python data/fixtures_v2/build_fixtures.py
"""

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
LABELS_PATH = ROOT / "tests" / "fixtures" / "eval_set_v2.json"
SEED = 20261013
REVIEW_DATE = "2026-10-01"  # "trailing 12 months" = 2025-10-01 .. 2026-10-01

DOC_DISCLAIMER = (
    "[SYNTHETIC DOCUMENT - FOR TESTING / DEMONSTRATION PURPOSES ONLY. THIS IS NOT A REAL\n"
    "LOAN AGREEMENT. THE LENDER, BORROWER, ADDRESSES AND FINANCIAL DETAILS ARE FICTIONAL.]\n"
)
ACCOUNTS_DISCLAIMER = (
    "SYNTHETIC TEST DATA. Fictional customers of a fictional lender (Northbridge Consumer "
    "Lending). Not real people or accounts."
)
OUTCOMES = ("price_and_value", "consumer_support", "products_and_services", "consumer_understanding")
DEFECT_CODE = {"PV": "price_and_value", "CS": "consumer_support", "PS": "products_and_services",
               "CU": "consumer_understanding"}

# (doc, split, planted defect or None, account scenario, borrower, purpose, amount, apr, term)
DOCS = [
    # Balanced so that no account feature, purpose, split or ID order tracks the planted defect
    # (checked by src/evaluation/fixtures_v2_check.py, blind-read section).
    ("v2_d01", "design", "PV", "missed_two_in_window", "Amara Okafor", "car purchase", 9000, 19.9, 48),
    ("v2_d02", "heldout", None, "missed_two_in_window", "Tomasz Nowak", "home improvements", 12000, 14.9, 60),
    ("v2_d03", "design", "PS", "hardship_open", "Siobhan Gallagher", "debt consolidation", 7500, 22.9, 36),
    ("v2_d04", "heldout", None, "hardship_open", "Rahul Mehta", "car purchase", 6000, 17.9, 36),
    ("v2_d05", "design", "CU", "note_bereavement", "Chen Wei", "home improvements", 15000, 12.9, 60),
    ("v2_d06", "heldout", None, "note_relationship_breakdown", "Fatima Hassan", "debt consolidation", 5000, 24.9, 24),
    ("v2_d07", "design", "CS", "missed_one_in_window", "Gareth Llewellyn", "wedding costs", 10000, 16.9, 48),
    ("v2_d08", "design", None, "missed_two_one_outside_window", "Lucia Fernandes", "wedding costs", 8000, 18.9, 48),
    ("v2_d09", "heldout", "CU", "hardship_closed", "Kwame Asante", "car purchase", 11000, 13.9, 60),
    ("v2_d10", "heldout", "CS", "note_house_move", "Hannah Becker", "home improvements", 6500, 21.9, 36),
    ("v2_d11", "design", "PV", "clean", "Yusuf Demir", "debt consolidation", 4000, 23.9, 24),
    ("v2_d12", "design", None, "clean", "Mei Lin Tan", "wedding costs", 9500, 15.9, 48),
    ("v2_d13", "heldout", "PV", "account_not_found", "Oliver Bennett", "wedding costs", 7000, 19.9, 36),
    ("v2_d14", "heldout", "CS", "holder_name_mismatch", "Patrick O'Neill", "car purchase", 8500, 17.9, 48),
    ("v2_d15", "heldout", "PS", "loan_not_on_account", "Zainab Abubakar", "home improvements", 10500, 14.9, 60),
    ("v2_d16", "design", None, "no_customer_identified", None, "debt consolidation", 5500, 20.9, 36),
    # Scope cases: tool calls here are unnecessary (docs/fixtures_v2_labels.md).
    ("v2_d17", "design", "CS", "other_lender", "Priya Raman", "car purchase", 7200, 18.9, 48),
    ("v2_d18", "heldout", None, "lender_not_stated", "Ewan MacLeod", "home improvements", 6800, 16.9, 36),
    ("v2_d19", "design", None, "not_a_credit_agreement", "Nadia Kowalski", None, 0, 0, 0),
]
OTHER_LENDER = "Harlow Street Finance Ltd, 9 Cannon Row, Leeds, LS1 4AB"
NORTHBRIDGE = "Northbridge Consumer Lending Ltd, 40 Wharf Street, Manchester, M1 2EP"

ADDRESSES = [
    "14 Larkspur Road, Leicester, LE2 7QT", "3 Millbrook Close, Swindon, SN3 4HD",
    "88 Ashgrove Terrace, Belfast, BT9 6FL", "21 Harrow Lane, Croydon, CR0 2JX",
    "7 Quayside Court, Bristol, BS1 5RG", "112 Elm Park Avenue, Bradford, BD8 9LE",
    "5 Ffordd Celyn, Wrexham, LL13 7YH", "39 Cedar Walk, Norwich, NR2 3PB",
    "60 Victoria Street, Wolverhampton, WV1 4NZ", "9 Rosedale Gardens, York, YO24 1BS",
    "27 Kingsway, Coventry, CV2 4FN", "4 Harbour View, Aberdeen, AB11 5DE",
    "51 Station Road, Reading, RG1 1LG", "16 Brookfield Drive, Derry, BT48 8QW",
    "73 Moor Lane, Preston, PR1 6DY",
]

# Two wordings per clause so the documents are not one template.
CLAUSES = {
    "fees_ok": [
        "4.1 An arrangement fee of {fee} is payable on drawdown and is included in the total amount payable "
        "shown in the Key Facts. No other fee is charged under this Agreement except the late payment fee in "
        "clause 8, which is a fixed amount.",
        "4.1 The only fee under this Agreement is an arrangement fee of {fee}, added to the total amount "
        "payable shown in the Key Facts. The late payment fee in clause 8 is a fixed sum stated in that clause.",
    ],
    "value_ok": [
        "4.2 Fair value. The Lender has assessed the total cost of this loan, including interest and the "
        "arrangement fee, against the benefits to the borrowers it is designed for and against comparable "
        "loans, and reviews that assessment every year.",
        "4.2 Why we think this loan is fair value. We compare the full cost of this loan, interest and fee "
        "together, with what it gives the borrowers it is designed for and with similar loans on the market. "
        "We repeat this review annually.",
    ],
    "fees_defect": [
        "4.1 Administration fees may be charged in connection with this Agreement. The amount of any such fee "
        "will be determined by the Lender at the time the relevant service is provided.",
        "4.1 The Lender may make charges for administering this Agreement. Any such charge will be set by the "
        "Lender when the relevant work is carried out.",
    ],
    "support_ok": [
        "10. SUPPORT IF YOUR CIRCUMSTANCES CHANGE\n10.1 If you are finding things difficult because of illness, "
        "bereavement, a change in your circumstances or any other reason, please tell us. We can change how "
        "we contact you, give you more time, and refer you to free independent debt advice. Telling us will "
        "not by itself change your agreement.",
        "10. IF YOU NEED EXTRA SUPPORT\n10.1 Some customers need extra help at times, for example after a "
        "bereavement, during illness, or when their income changes. If that applies to you, contact us. We can "
        "adapt our communication, allow extra time, and point you to free, independent debt advice.",
    ],
    "support_defect": [
        "10. CONTACTING US\n10.1 Questions about this Agreement can be directed to our customer service team "
        "on 0300 555 0142, Monday to Friday, 9am to 5pm.",
        "10. CUSTOMER SERVICE\n10.1 Our customer service team can be reached on 0300 555 0142 between 9am and "
        "5pm, Monday to Friday.",
    ],
    "target_ok": [
        "2.2 Who this loan is for. This loan is designed for borrowers who want a fixed-rate loan of a known "
        "amount over a fixed term and who can afford the fixed monthly repayments. It is not suitable for "
        "borrowers who need flexible or revolving credit. We review whether it continues to meet the needs "
        "of this group.",
        "2.2 Intended borrowers. We designed this loan for people borrowing a set amount at a fixed rate over "
        "a fixed term, who can afford the monthly repayments. It is not intended for anyone who needs to "
        "borrow flexibly. We check regularly that it still suits this group.",
    ],
    "target_defect": [
        "2.2 This loan is available to any applicant who meets the Lender's standard lending criteria.",
        "2.2 Any applicant meeting the Lender's usual lending criteria may take out this loan.",
    ],
    "repay_ok": [
        "3.1 You will repay the Loan in {term} monthly instalments of {monthly}, starting one month after "
        "drawdown. The total amount payable is {total}.",
        "3.1 The Loan is repayable by {term} equal monthly payments of {monthly}, the first due one month "
        "after drawdown. In total you will pay {total}.",
    ],
    "repay_defect": [
        "3.1 The Borrower shall repay the Loan together with interest by consecutive monthly instalments "
        "calculated in accordance with the Lender's standard methodology.",
        "3.1 Repayment of the Loan and interest shall be made by monthly instalments, the amount of which is "
        "calculated using the Lender's standard methodology.",
    ],
}


def money(x: float) -> str:
    return f"£{x:,.2f}"


def schedule(amount: float, apr: float, term: int, fee: float) -> tuple[float, float]:
    r = (1 + apr / 100) ** (1 / 12) - 1
    monthly = round(amount * r / (1 - (1 + r) ** -term), 2)
    return monthly, round(monthly * term + fee, 2)


def build_letter(customer_id: str, name: str, address: str) -> str:
    """Not a credit agreement: a Northbridge change-of-address confirmation. None of the four outcomes apply."""
    return ("[SYNTHETIC DOCUMENT - FOR TESTING / DEMONSTRATION PURPOSES ONLY. NOT A REAL LETTER. THE COMPANY,\n"
            "CUSTOMER AND ADDRESS ARE FICTIONAL.]\n" + "\nNorthbridge Consumer Lending Ltd\n40 Wharf Street, Manchester, M1 2EP\n\n"
            f"Customer number: {customer_id}\n12 September 2026\n\n{name}\n{address}\n\n"
            "CONFIRMATION OF CHANGE OF ADDRESS\n\n"
            f"Dear {name},\n\nThank you for letting us know that you have moved. We have updated the address "
            "we hold for you to the one shown above. All future letters and statements will be sent there.\n\n"
            "If you did not ask us to make this change, please call us on 0300 555 0142.\n\n"
            "Yours sincerely,\nCustomer Records Team\nNorthbridge Consumer Lending Ltd\n\n[END OF SYNTHETIC DOCUMENT]\n")


def build_doc(i: int, row: tuple, customer_id: str | None, loan_ref: str, address: str | None) -> str:
    doc, _, defect, scenario, name, purpose, amount, apr, term = row
    if scenario == "not_a_credit_agreement":
        return build_letter(customer_id, name, address)
    lender = {"other_lender": OTHER_LENDER, "lender_not_stated": None}.get(scenario, NORTHBRIDGE)
    v = i % 2
    has_fee = defect != "PV"
    fee = 150.0 if amount < 8000 else 250.0
    monthly, total = schedule(amount, apr, term, fee if has_fee else 0.0)
    parts = [DOC_DISCLAIMER, "\nFIXED SUM LOAN AGREEMENT\n",
             f"Agreement reference: {loan_ref}\n",
             f"Customer number: {customer_id or '[to be completed]'}\n",
             "\nThis Agreement is made on 1 September 2026 between:\n\n"
             + (f"(1) {lender} (\"the Lender\"); and\n\n" if lender else "(1) The Lender (\"the Lender\"); and\n\n")]
    if name:
        parts.append(f"(2) {name}, of {address} (\"the Borrower\").\n")
    else:
        parts.append("(2) [Borrower name], of [Borrower address] (\"the Borrower\").\n"
                     "\nSPECIMEN AGREEMENT - customer details to be completed before signature.\n")
    if defect != "CU":
        parts.append(
            f"\nKEY FACTS\nLoan amount: {money(amount)}\nAPR: {apr}%\nTerm: {term} months\n"
            f"Monthly repayment: {money(monthly)}\nTotal amount payable: {money(total)}\n"
            + (f"Arrangement fee: {money(fee)}\n" if has_fee else "")
            + "Please read these key facts before the rest of this Agreement.\n")
    parts.append(f"\n1. THE LOAN\n1.1 The Lender agrees to lend the Borrower {money(amount)} (\"the Loan\") "
                 f"for {purpose}.\n1.2 The APR is {apr}% and the interest rate is fixed for the whole term.\n")
    parts.append("\n2. PURPOSE AND SUITABILITY\n2.1 The Loan must be used for the purpose stated in clause 1.1.\n"
                 + CLAUSES["target_defect" if defect == "PS" else "target_ok"][v] + "\n")
    parts.append("\n3. REPAYMENT\n" + CLAUSES["repay_defect" if defect == "CU" else "repay_ok"][v].format(
        term=term, monthly=money(monthly), total=money(total)) + "\n3.2 Payments are collected by direct debit.\n")
    if defect == "PV":
        parts.append("\n4. FEES\n" + CLAUSES["fees_defect"][v] + "\n")
    else:
        parts.append("\n4. FEES AND VALUE\n" + CLAUSES["fees_ok"][v].format(fee=money(fee)) + "\n"
                     + CLAUSES["value_ok"][v] + "\n")
    parts.append("\n5. RIGHT TO WITHDRAW\n5.1 You may withdraw from this Agreement within 14 days of the day "
                 "after it is made, by telling us. You must then repay the Loan and interest for the days you "
                 "had it.\n"
                 "\n6. EARLY REPAYMENT\n6.1 You may repay all or part of the Loan early at any time. You will "
                 "receive a rebate of interest calculated under the Consumer Credit (Early Settlement) "
                 "Regulations 2004.\n"
                 "\n7. YOUR INFORMATION\n7.1 We use your information to manage this Agreement and as described "
                 "in our privacy notice.\n"
                 "\n8. MISSED PAYMENTS\n8.1 If a payment is missed we may charge a late payment fee of £12.00. "
                 "Missed payments may affect your credit rating.\n"
                 "\n9. COMPLAINTS\n9.1 If you are unhappy with our service, contact us first. If we cannot "
                 "resolve your complaint you may refer it to the Financial Ombudsman Service.\n\n")
    parts.append(CLAUSES["support_defect" if defect == "CS" else "support_ok"][v] + "\n")
    parts.append("\n11. GOVERNING LAW\n11.1 This Agreement is governed by the law of England and Wales.\n"
                 "\n[END OF SYNTHETIC DOCUMENT]\n")
    return "".join(parts)


# --- accounts: raw dated facts only ---

BASE_NOTES = [
    ("2026-02-03", "Customer updated their preferred contact method to email."),
    ("2025-12-09", "Customer asked for a copy of their annual statement; sent by post."),
    ("2026-04-22", "Customer called to check the date of their next direct debit."),
    ("2026-01-15", "Online banking password reset at the customer's request."),
]


def account(customer_id, holder, loan_ref, older_ref, scenario, k, opened):
    events, markers, notes = [], [], [BASE_NOTES[k % len(BASE_NOTES)]]
    if scenario == "missed_two_in_window":
        events = [("2026-03-14", older_ref), ("2026-07-14", older_ref)]
    elif scenario == "missed_one_in_window":
        events = [("2026-05-02", older_ref)]
    elif scenario == "missed_two_one_outside_window":
        events = [("2025-06-20", older_ref), ("2026-02-20", older_ref)]
    elif scenario == "hardship_open":
        markers = [{"type": "financial_hardship", "opened": "2026-08-03", "closed": None}]
    elif scenario == "hardship_closed":
        markers = [{"type": "financial_hardship", "opened": "2025-11-10", "closed": "2026-02-28"}]
    elif scenario == "note_bereavement":
        notes.append(("2026-08-19", "Customer called to say their spouse died in July and asked for all post "
                                    "to be sent in their name only."))
    elif scenario == "note_relationship_breakdown":
        notes.append(("2026-07-30", "Customer said they have separated from their partner and moved out of the "
                                    "joint home; correspondence address updated."))
    elif scenario == "note_house_move":
        notes.append(("2026-06-12", "Customer has moved to a new address in Leeds for work; correspondence "
                                    "address updated."))
    products = [{"type": "current_account" if k % 2 else "credit_card", "reference": older_ref,
                 "opened": opened, "status": "open"}]
    if scenario != "loan_not_on_account":
        products.append({"type": "personal_loan", "reference": loan_ref, "opened": "2026-09-01", "status": "open"})
    return {
        "customer_id": customer_id, "account_holder_name": holder, "customer_since": opened,
        "account_status": "active", "products": products,
        "payment_events": [{"type": "missed_payment", "due_date": d, "product_reference": r} for d, r in events],
        "markers": markers,
        "notes": [{"date": d, "text": t} for d, t in sorted(notes)],
    }


EXPECTED_ESCALATION = {
    "missed_two_in_window": ("escalate", ["2.1(a)"]),
    "hardship_open": ("escalate", ["2.1(b)"]),
    "note_bereavement": ("escalate", ["2.1(c)"]),
    "note_relationship_breakdown": ("escalate", ["2.1(c)"]),
    "missed_one_in_window": ("no_escalation", []),
    "missed_two_one_outside_window": ("no_escalation", []),
    "hardship_closed": ("no_escalation", []),
    "note_house_move": ("no_escalation", []),
    "clean": ("no_escalation", []),
    "loan_not_on_account": ("no_escalation", []),
    "account_not_found": ("cannot_determine", []),
    "holder_name_mismatch": ("cannot_determine", []),
    "no_customer_identified": ("cannot_determine", []),
    "other_lender": ("not_applicable", []),
    "lender_not_stated": ("cannot_determine", []),
    "not_a_credit_agreement": ("not_applicable", []),
}

REASONS = {
    "missed_two_in_window": "two missed payments dated inside the trailing 12 months -> 2.1(a)",
    "hardship_open": "a hardship marker with no closed date -> 2.1(b)",
    "note_bereavement": "a note recording a recent bereavement -> 2.1(c)",
    "note_relationship_breakdown": "a note recording a recent separation -> 2.1(c)",
    "missed_one_in_window": "near-miss: one missed payment in the window; 2.1(a) needs two or more",
    "missed_two_one_outside_window": "near-miss: two missed payments but one is before 2025-10-01",
    "hardship_closed": "near-miss: the hardship marker is closed; 2.1(b) needs an open marker",
    "note_house_move": "near-miss: a house move for work is a life event but not one 2.1(c) lists",
    "clean": "no payment events, markers or trigger notes",
    "loan_not_on_account": "account is clean, but the agreement's reference is not among its products",
    "account_not_found": "the customer number in the document has no account record",
    "holder_name_mismatch": "the account for this customer number belongs to a differently named person",
    "no_customer_identified": "specimen agreement with no customer number: there is nothing to look up",
    "other_lender": "another lender's agreement: not a Northbridge customer, so no account lookup or Northbridge "
                    "policy applies; Consumer Duty outcomes still apply",
    "lender_not_stated": "the agreement names no lender, so it cannot be established that the customer is "
                         "Northbridge's: an account lookup is unnecessary and escalation cannot be determined",
    "not_a_credit_agreement": "a change-of-address letter, not a credit agreement: none of the four outcomes "
                              "apply and no tool call is needed",
}


def main() -> None:
    rng = random.Random(SEED)
    ids = rng.sample(range(10000, 99999), len(DOCS) + 2)
    refs = rng.sample(range(10000, 99999), 2 * len(DOCS) + 3)
    addresses = list(ADDRESSES)
    rng.shuffle(addresses)
    (OUT / "docs").mkdir(parents=True, exist_ok=True)
    accounts, labels = [], []
    for i, row in enumerate(DOCS):
        doc, split, defect, scenario, name, *_ = row
        cid = None if scenario == "no_customer_identified" else f"CUST-{ids[i]}"
        loan_ref = f"NCL-2026-{refs[2 * i]}"
        older_ref = f"NBK-{refs[2 * i + 1]}"
        text = build_doc(i, row, cid, loan_ref, addresses[i % len(addresses)] if name else None)
        (OUT / "docs" / f"{doc}.txt").write_text(text, encoding="utf-8", newline="\n")
        if cid and scenario not in ("account_not_found", "other_lender"):
            holder = "Patricia O'Neill" if scenario == "holder_name_mismatch" else name
            opened = f"20{17 + i % 7}-0{1 + i % 9}-1{i % 9}"
            acct_scenario = "clean" if scenario in ("lender_not_stated", "not_a_credit_agreement") else scenario
            accounts.append(account(cid, holder, loan_ref if scenario != "loan_not_on_account" else None,
                                    older_ref, acct_scenario, i, opened))
        decision, triggers = EXPECTED_ESCALATION[scenario]
        credit = scenario != "not_a_credit_agreement"
        northbridge = scenario not in ("other_lender", "lender_not_stated")
        account_needed = credit and northbridge and cid is not None
        expected_calls = {
            "get_account": ({"required": True, "arguments": {"customer_id": cid}} if account_needed
                            else {"required": False, "forbidden": True}),
            "search_policy": ({"required": True} if credit and northbridge else {"required": False, "forbidden": True}),
            # one search per Consumer Duty outcome, each naming its outcome (cap 4; user decision 2026-10-14)
            "search_regulation": ({"required": True, "per_outcome": list(OUTCOMES)} if credit
                                  else {"required": False, "forbidden": True}),
        }
        labels.append({
            "doc_id": doc, "split": split, "file": f"data/fixtures_v2/docs/{doc}.txt",
            "customer_id": cid, "loan_reference": loan_ref,
            "ground_truth": {o: ("not_applicable" if not credit else
                                 "non_compliant" if defect and DEFECT_CODE[defect] == o else "compliant")
                             for o in OUTCOMES},
            "document_facts": {"credit_agreement": credit,
                               "lender": "northbridge" if northbridge else
                                         ("not_stated" if scenario == "lender_not_stated" else "other"),
                               "customer_number": cid},
            "planted_defect": DEFECT_CODE.get(defect), "account_scenario": scenario,
            "expected_escalation": {"decision": decision, "triggers": triggers},
            "expected_discrepancy": scenario in ("holder_name_mismatch", "loan_not_on_account"),
            "expected_tool_calls": expected_calls,
            "reason": REASONS[scenario],
        })
    # Two accounts no document refers to, so "an account exists" implies nothing.
    accounts.append(account(f"CUST-{ids[-2]}", "Daniel Price", f"NCL-2026-{refs[-3]}", f"NBK-{refs[-2]}",
                            "hardship_open", 3, "2019-05-17"))
    accounts.append(account(f"CUST-{ids[-1]}", "Grace Whitfield", f"NCL-2026-{refs[-1]}", "NBK-55501",
                            "clean", 2, "2021-03-08"))
    rng.shuffle(accounts)
    (OUT / "accounts.json").write_text(json.dumps(
        {"_disclaimer": ACCOUNTS_DISCLAIMER, "review_date": REVIEW_DATE, "accounts": accounts},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    LABELS_PATH.write_text(json.dumps(
        {"_disclaimer": "Labels for graders only. Never passed to the agent or to any tool.",
         "review_date": REVIEW_DATE, "seed": SEED, "documents": labels},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(DOCS)} documents, {len(accounts)} accounts, labels -> {LABELS_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

"""
Offline checks on the v2 fixture set (zero API calls), and the two
documents written from it before anything runs:

  docs/fixtures_v2_coverage.md   coverage matrix, fairness balance, blind-read check
  docs/fixtures_v2_labels.md     expected outcome, escalation and tool calls per document

Checks (any failure exits 1):
  1. every customer number in a document resolves to an account, or the
     document is a declared mismatch (not found / no customer)
  2. every matrix cell has at least one positive and one negative document,
     with the near-misses present, in each split where required
  3. account records hold the same fields for everyone, and no field name or
     note uses policy or test vocabulary
  4. blind read: no account feature separates compliant from non-compliant
     documents (the compliance label must not be readable from accounts)
  5. no document shares an 8-word run with the internal policy text

Run from the repo root:  python -m src.evaluation.fixtures_v2_check
"""

import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "tests" / "fixtures" / "eval_set_v2.json"
ACCOUNTS = ROOT / "data" / "fixtures_v2" / "accounts.json"
POLICY_DIR = ROOT / "data" / "internal_policy"
COVERAGE_MD = ROOT / "docs" / "fixtures_v2_coverage.md"
LABELS_MD = ROOT / "docs" / "fixtures_v2_labels.md"
OUTCOMES = ("price_and_value", "consumer_support", "products_and_services", "consumer_understanding")
FORBIDDEN_WORDS = re.compile(r"escalat|trigger|vulnerab|2\.1|\btest|fixture|scenario|label|project|policy", re.I)
WINDOW_START = "2025-10-01"


def load():
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    accounts = json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    return labels, accounts


def account_features(a: dict | None) -> dict:
    if a is None:
        return {"found": False}
    missed_window = sum(1 for e in a["payment_events"] if e["due_date"] >= WINDOW_START)
    return {
        "found": True,
        "missed_in_window": missed_window,
        "any_payment_event": bool(a["payment_events"]),
        "open_marker": any(m["closed"] is None for m in a["markers"]),
        "any_marker": bool(a["markers"]),
        "notes": len(a["notes"]),
        "products": len(a["products"]),
        "customer_since_year": int(a["customer_since"][:4]),
    }


def run_checks():
    labels, accounts = load()
    docs = labels["documents"]
    by_id = {a["customer_id"]: a for a in accounts["accounts"]}
    failures, notes = [], []

    # 1. resolution
    resolution = []
    for d in docs:
        text = (ROOT / d["file"]).read_text(encoding="utf-8")
        m = re.search(r"Customer number: (CUST-\d{5})", text)
        cid = m.group(1) if m else None
        if cid != d["customer_id"]:
            failures.append(f"{d['doc_id']}: document customer number {cid} != label {d['customer_id']}")
        acct = by_id.get(cid) if cid else None
        declared = d["account_scenario"] in ("account_not_found", "no_customer_identified", "other_lender")
        if cid and acct is None and not declared:
            failures.append(f"{d['doc_id']}: {cid} resolves to no account and is not a declared mismatch")
        if acct is not None and declared:
            failures.append(f"{d['doc_id']}: declared not found, but {cid} resolves")
        name = re.search(r"\(2\) (.+?), of ", text)
        loan_on_account = bool(acct) and any(p["reference"] == d["loan_reference"] for p in acct["products"])
        resolution.append({"doc": d["doc_id"], "cid": cid, "resolves": acct is not None,
                           "name_matches": bool(acct and name and name.group(1) == acct["account_holder_name"]),
                           "loan_on_account": loan_on_account, "scenario": d["account_scenario"]})
        if d["account_scenario"] == "holder_name_mismatch" and resolution[-1]["name_matches"]:
            failures.append(f"{d['doc_id']}: declared name mismatch, but names match")
        if d["account_scenario"] == "loan_not_on_account" and loan_on_account:
            failures.append(f"{d['doc_id']}: declared loan not on account, but it is")
        if acct and d["account_scenario"] not in ("holder_name_mismatch", "loan_not_on_account",
                                                  "not_a_credit_agreement"):
            if not resolution[-1]["name_matches"] or not loan_on_account:
                failures.append(f"{d['doc_id']}: undeclared name or loan mismatch")

    # 2. coverage cells
    cells = {}
    for o in OUTCOMES:
        cells[f"outcome {o}"] = ([d["doc_id"] for d in docs if d["ground_truth"][o] == "non_compliant"],
                                 [d["doc_id"] for d in docs if d["ground_truth"][o] == "compliant"])
    for trig in ("2.1(a)", "2.1(b)", "2.1(c)"):
        cells[f"trigger {trig}"] = ([d["doc_id"] for d in docs if trig in d["expected_escalation"]["triggers"]],
                                    [d["doc_id"] for d in docs if d["expected_escalation"]["decision"] == "no_escalation"])
    for dec in ("escalate", "no_escalation", "cannot_determine", "not_applicable"):
        cells[f"escalation {dec}"] = ([d["doc_id"] for d in docs if d["expected_escalation"]["decision"] == dec],
                                      [d["doc_id"] for d in docs if d["expected_escalation"]["decision"] != dec])
    cells["provenance: customer found"] = ([r["doc"] for r in resolution if r["resolves"]],
                                           [r["doc"] for r in resolution if not r["resolves"]])
    cells["provenance: loan on account"] = ([r["doc"] for r in resolution if r["loan_on_account"]],
                                            [r["doc"] for r in resolution if r["resolves"] and not r["loan_on_account"]])
    for tool in ("get_account", "search_policy", "search_regulation"):
        cells[f"{tool} required / unnecessary"] = (
            [d["doc_id"] for d in docs if d["expected_tool_calls"][tool]["required"]],
            [d["doc_id"] for d in docs if d["expected_tool_calls"][tool].get("forbidden")])
    for fact, values in (("lender", ("northbridge", "other", "not_stated")), ("credit_agreement", (True, False))):
        for v in values:
            if not any(d["document_facts"][fact] == v for d in docs):
                failures.append(f"no document with {fact} = {v}")
    for name, (pos, neg) in cells.items():
        if not pos or not neg:
            failures.append(f"matrix cell '{name}' lacks a positive or a negative document")
    for near in ("missed_one_in_window", "missed_two_one_outside_window", "hardship_closed", "note_house_move"):
        if not any(d["account_scenario"] == near for d in docs):
            failures.append(f"near-miss '{near}' missing")
    for split in ("design", "heldout"):
        sd = [d for d in docs if d["split"] == split]
        for o in OUTCOMES:
            if not any(d["ground_truth"][o] == "non_compliant" for d in sd):
                failures.append(f"split {split} has no non-compliant {o} document")
        for dec in ("escalate", "no_escalation", "cannot_determine"):
            if not any(d["expected_escalation"]["decision"] == dec for d in sd):
                failures.append(f"split {split} has no '{dec}' document")

    # 3. account shape and vocabulary
    shapes = {tuple(sorted(a)) for a in accounts["accounts"]}
    if len(shapes) != 1:
        failures.append(f"account records differ in shape: {shapes}")
    for a in accounts["accounts"]:
        keys = json.dumps(sorted(a)) + json.dumps([sorted(e) for e in a["payment_events"] + a["markers"]])
        if FORBIDDEN_WORDS.search(keys):
            failures.append(f"{a['customer_id']}: a field name uses policy/test vocabulary")
        for n in a["notes"]:
            if FORBIDDEN_WORDS.search(n["text"]):
                failures.append(f"{a['customer_id']}: note uses policy/test vocabulary: {n['text']!r}")

    # 4. blind read: account features vs the document's compliance label
    rows = []
    for d in docs:
        f = account_features(by_id.get(d["customer_id"]) if d["customer_id"] else None)
        rows.append((d, f, any(v == "non_compliant" for v in d["ground_truth"].values())))
    blind = []
    for feat in ("found", "any_payment_event", "missed_in_window", "open_marker", "any_marker", "notes", "products"):
        groups = {}
        for d, f, nc in rows:
            groups.setdefault(f.get(feat), []).append(nc)
        rates = {str(k): f"{sum(v)}/{len(v)}" for k, v in sorted(groups.items(), key=lambda x: str(x[0]))}
        # A leak: any feature value shared by 3+ documents that are all non-compliant or all compliant
        # (an outsider seeing that value would guess the label right every time).
        leaky = sorted(str(k) for k, v in groups.items() if len(v) >= 3 and sum(v) in (0, len(v)))
        blind.append((feat, rates, leaky))
        if leaky:
            failures.append(f"blind read: account feature '{feat}' = {leaky} predicts the compliance label")
    ids_sorted = sorted((d["customer_id"] or "", any(v == "non_compliant" for v in d["ground_truth"].values()))
                        for d in docs if d["customer_id"])
    half = len(ids_sorted) // 2
    id_order = (sum(nc for _, nc in ids_sorted[:half]), sum(nc for _, nc in ids_sorted[half:]))

    # 5. policy echo
    # Bracketed blocks are the synthetic-data disclaimers both sets carry on purpose; content only.
    strip = lambda t: re.sub(r"\[[^\]]*\]", " ", t)  # noqa: E731
    policy_text = " ".join(strip(p.read_text(encoding="utf-8")) for p in POLICY_DIR.glob("*.txt")).lower()
    policy_words = re.findall(r"[a-z]+", policy_text)
    policy_runs = {" ".join(policy_words[i:i + 8]) for i in range(len(policy_words) - 7)}
    echoes = []
    for d in docs:
        words = re.findall(r"[a-z]+", strip((ROOT / d["file"]).read_text(encoding="utf-8")).lower())
        hits = {" ".join(words[i:i + 8]) for i in range(len(words) - 7)} & policy_runs
        if hits:
            echoes.append((d["doc_id"], sorted(hits)[:2]))
            failures.append(f"{d['doc_id']}: shares an 8-word run with the internal policy: {sorted(hits)[0]!r}")
    return labels, accounts, resolution, cells, blind, id_order, echoes, failures


def write_docs(labels, accounts, resolution, cells, blind, id_order, echoes, failures):
    docs = labels["documents"]
    today = date.today().isoformat()
    res = {r["doc"]: r for r in resolution}
    L = [f"# Fixtures v2: coverage matrix", "",
         f"Written {today} by `python -m src.evaluation.fixtures_v2_check`, **before any agent run**. "
         "Generated from `tests/fixtures/eval_set_v2.json` and `data/fixtures_v2/` (built by "
         "`data/fixtures_v2/build_fixtures.py`, seed "
         f"{labels['seed']}). All documents, people and accounts are synthetic. The v1 set "
         "(`data/synthetic_docs/`, `data/mock_accounts/`) is unchanged and remains the baseline.", "",
         f"Review date given to the agent: **{labels['review_date']}** (trailing 12 months from {WINDOW_START}).", "",
         "## What \"category\" covers", "",
         "Both readings are covered. **The four outcomes** add the columns PV / CS / PS / CU "
         "(planted document defects). **The escalation triggers** (internal policy 2.1(a)-(c)) add the "
         "escalation columns, the near-misses, and the account-provenance columns. Each row is one document.", "",
         "| Doc | Split | PV | CS | PS | CU | Account scenario | Escalation | Triggers | Customer found | Loan on account | Name matches | Expected tool calls |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    mark = lambda d, o: {"non_compliant": "**NC**", "not_applicable": "n/a"}.get(d["ground_truth"][o], "ok")  # noqa: E731
    for d in docs:
        r = res[d["doc_id"]]
        etc = d["expected_tool_calls"]
        ga = etc["get_account"]
        calls = [f"get_account({ga['arguments']['customer_id']}) required" if ga["required"] else "get_account unnecessary"]
        calls.append(f"search_policy {'required' if etc['search_policy']['required'] else 'unnecessary'}")
        calls.append("search_regulation x4 (one per outcome) required" if etc["search_regulation"]["required"]
                     else "search_regulation unnecessary")
        L.append(f"| {d['doc_id']} | {d['split']} | {mark(d, 'price_and_value')} | {mark(d, 'consumer_support')} | "
                 f"{mark(d, 'products_and_services')} | {mark(d, 'consumer_understanding')} | {d['account_scenario']} | "
                 f"{d['expected_escalation']['decision']} | {', '.join(d['expected_escalation']['triggers']) or '-'} | "
                 f"{'yes' if r['resolves'] else 'no'} | {'yes' if r['loan_on_account'] else 'no'} | "
                 f"{'yes' if r['name_matches'] else ('-' if not r['resolves'] else 'no')} | {'; '.join(calls)} |")
    L += ["", "Limits for every run: at most 8 tool calls; search_regulation at most 4 (one per outcome, each "
          "naming its outcome); other tools at most 3 each; 6 model turns.", "",
          "A call is **unnecessary** when the document's own facts rule it out: another lender's agreement "
          "(not a Northbridge customer: no account lookup, no Northbridge policy); no lender named (cannot "
          "establish the customer is Northbridge's: no account lookup); not a credit agreement (no call at "
          "all); no customer number (no account lookup). Any repeated identical call, and any second "
          "account lookup, is also unnecessary.", "",
          "## Every cell has a positive and a negative", "", "| Cell | Positive docs | Negative docs |", "|---|---|---|"]
    for name, (pos, neg) in cells.items():
        L.append(f"| {name} | {len(pos)}: {', '.join(pos)} | {len(neg)} |")
    L += ["", "Near-misses: one missed payment in the window (`missed_one_in_window`); two missed but one outside "
          "the window (`missed_two_one_outside_window`); a closed hardship marker (`hardship_closed`); a "
          "different life event, a house move (`note_house_move`).", "",
          "## Fairness balance", "",
          "Planted defects are spread so that names, products, ID order and account history do not track the "
          "compliance label.", "", "| Doc | Borrower | Product purpose | Any defect | Escalation |", "|---|---|---|---|---|"]
    for d in docs:
        text = (ROOT / d["file"]).read_text(encoding="utf-8")
        name = re.search(r"\(2\) (.+?), of ", text)
        purpose = re.search(r"\(\"the Loan\"\) for (.+?)\.", text)
        L.append(f"| {d['doc_id']} | {name.group(1) if name else '-'} | {purpose.group(1) if purpose else '-'} | "
                 f"{d['planted_defect'] or 'none'} | {d['expected_escalation']['decision']} |")
    purpose_counts = Counter()
    for d in docs:
        m = re.search(r"\(\"the Loan\"\) for (.+?)\.", (ROOT / d["file"]).read_text(encoding="utf-8"))
        if m:
            purpose_counts[(m.group(1), bool(d["planted_defect"]))] += 1
    L += ["", "By purpose (defect / no defect): " + "; ".join(
        f"{p}: {purpose_counts[(p, True)]} / {purpose_counts[(p, False)]}" for p in sorted({k[0] for k in purpose_counts})),
          "", f"By customer-ID order (non-compliant documents in lower half / upper half of IDs): {id_order[0]} / {id_order[1]}.",
          "", "Escalation vs defect: escalate docs with a defect "
          f"{sum(1 for d in docs if d['expected_escalation']['decision'] == 'escalate' and d['planted_defect'])}/"
          f"{sum(1 for d in docs if d['expected_escalation']['decision'] == 'escalate')}; "
          "no-escalation docs with a defect "
          f"{sum(1 for d in docs if d['expected_escalation']['decision'] == 'no_escalation' and d['planted_defect'])}/"
          f"{sum(1 for d in docs if d['expected_escalation']['decision'] == 'no_escalation')}.", "",
          "## Blind-read check", "",
          "Question: from the account records alone, could an outsider tell which loan agreements are "
          "non-compliant? Each account feature below is grouped against \"document has a planted defect\" "
          "(non-compliant count / documents). Rule: any value shared by 3 or more documents that are all "
          "non-compliant or all compliant is a leak.", "",
          "| Account feature | Non-compliant / docs, by feature value | Leak? |", "|---|---|---|"]
    for feat, rates, sep in blind:
        L.append(f"| {feat} | {rates} | {'LEAK: ' + ', '.join(sep) if sep else 'no'} |")
    L += ["", "What an outsider **can** read from accounts alone, by design: the escalation decision, by applying "
          "policy 2.1 to the dated facts. That is the task, not a leak. What they cannot read: whether the "
          "agreement itself is compliant.", "",
          "Other leak checks: every account has the same fields; no field name or note uses policy or test "
          "vocabulary (escalat-, trigger, vulnerab-, 2.1, test, fixture, scenario, label, project, policy); "
          "no flag is named after a trigger (missed payments are dated events, hardship is a marker with "
          "opened/closed dates).", "",
          f"Policy echo (8-word runs shared with `data/internal_policy/`): {'none' if not echoes else echoes}.", "",
          "## Check result", "", "**PASS**" if not failures else "**FAIL**", ""]
    L += [f"- {f}" for f in failures]
    COVERAGE_MD.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")

    M = ["# Fixtures v2: expected results and tool calls", "",
         f"Written {today}, **before any agent run**, from `tests/fixtures/eval_set_v2.json`. One line of "
         "reason per document. Graders only: the agent never sees this file.", "",
         "Limits for every run: 8 tool calls; search_regulation at most 4, one per outcome; other tools 3 each; "
         "6 turns. Any repeated identical call, second account lookup, or second search for the same outcome "
         "is unnecessary. 2.1(c) \"recent\" means within the 12 months before the "
         "review date (the policy does not define it).", ""]
    for d in docs:
        ga = d["expected_tool_calls"]["get_account"]
        M.append(f"- **{d['doc_id']}** ({d['split']}) - defect: {d['planted_defect'] or 'none'}; escalation: "
                 f"**{d['expected_escalation']['decision']}** {' '.join(d['expected_escalation']['triggers'])}; "
                 f"tools: {'get_account(' + ga['arguments']['customer_id'] + ')' if ga['required'] else 'get_account unnecessary'}"
                 f", search_policy {'required' if d['expected_tool_calls']['search_policy']['required'] else 'unnecessary'}"
                 f", search_regulation {'x4, one per outcome' if d['expected_tool_calls']['search_regulation']['required'] else 'unnecessary'}"
                 f"{'; discrepancy expected' if d['expected_discrepancy'] else ''}. Reason: {d['reason']}.")
    LABELS_MD.write_text("\n".join(M) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    result = run_checks()
    write_docs(*result)
    failures = result[-1]
    print(f"Wrote {COVERAGE_MD.relative_to(ROOT)} and {LABELS_MD.relative_to(ROOT)}")
    print("PASS" if not failures else "FAIL:\n" + "\n".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

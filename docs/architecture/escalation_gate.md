# Who decides escalation: code first, the model only where judgment is needed (2026-10-24)

Every branch except the last is decided by code from the document and the account lookup result.
The model decides escalation only for a Northbridge agreement whose account exists and matches the
borrower. `cannot_determine` always goes to a reviewer, with the rule that set it.

```mermaid
flowchart TD
    START["Document"] --> CREDIT{"Credit agreement?"}
    CREDIT -- "no" --> N1["not_applicable<br/>model not called"]
    CREDIT -- "yes" --> LENDER{"Lender named in the agreement?"}
    LENDER -- "another lender" --> N2["not_applicable<br/>only regulation search offered"]
    LENDER -- "none named" --> C1["cannot_determine<br/>only regulation search offered"]
    LENDER -- "Northbridge" --> CUST{"Customer number?"}
    CUST -- "no" --> C2["cannot_determine<br/>no account to check"]
    CUST -- "yes" --> RUN["Model runs with all three tools"]
    RUN --> ACCT{"Account looked up, found,<br/>and in the borrower's name?"}
    ACCT -- "no" --> C3["cannot_determine<br/>rule overrides the model if needed"]
    ACCT -- "yes" --> M["Model decides:<br/>escalate or no_escalation<br/>triggers checked against the account"]

    C1 --> R["Human reviewer"]
    C2 --> R
    C3 --> R
    M --> R
    N1 --> R
    N2 --> R
```

Live evaluation before this gate (57 runs): 10 unnecessary calls, all on other lenders' agreements, and
7 escalation errors, all `cannot_determine` cases. The offline dry run on the same 19 documents shows
the rules set exactly those 6 documents. The rules were written after seeing those held-out failures.

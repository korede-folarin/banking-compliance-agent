# Agentic tool use: design decisions

**Status: design only. Nothing is built.** Recorded 2026-10-13. The fixed
pipeline (`ComplianceCheckAgent`) and the 15 v1 documents stay unchanged
as the baseline.

## Decisions (2026-10-13)

| Decision | Chosen |
|---|---|
| Who chooses the tools | The model. Required calls are checked by the deterministic layer after the run; a missing required call routes the case to review. |
| Regulation and policy tool output | The retrieved chunks with node IDs, not an LLM-written answer. |
| CONC | **Deferred (2026-10-13): not part of v2.** The project is finished on the current corpus first. If added later, the recommended route is a separate `conc` collection behind the existing regulation tool (`source` argument), leaving `regulatory_corpus` and the baseline untouched. Affordability stays out of scope until then: it needs CONC 5.2A plus income and outgoings data that the fixtures don't have. |
| Limits, enforced by code | At most **8 tool calls** per document, at most **3 per tool**, at most **6 model turns**. A repeated identical call returns the cached result and counts against the limit. Hitting any limit stops the run, records the reason, and sets `insufficient_evidence` with human review. |

**Changed 2026-10-14 (user decision):** `search_regulation` may be called up to **4** times, one per
Consumer Duty outcome, and each call names its outcome in a required `outcome` argument. An
outcome may cite only regulation passages returned by its own search, and a second search for
the same outcome counts as unnecessary. The other tools keep the limit of 3; the total stays 8.
The section below describes the original 3-call limit and is kept as a record.

## Known consequence of the per-tool limit (original, superseded)

There are 4 Consumer Duty outcomes. Within 3 regulation calls, the agent
must either combine outcomes in one query or reach the limit on the fourth.
Reaching it routes the document to review. Report how often this happens,
by outcome, in the evaluation. The alternative considered and not chosen
was regulation ≤ 4, policy ≤ 2, account ≤ 2, total 8, 5 turns.

## Cost estimate (not measured)

Model `claude-sonnet-5`: $2 input / $10 output per million tokens.

| Case | Model requests per document-run | Estimated cost |
|---|---|---|
| Worst case at the limits | 6 | ~$0.26 (~$0.19 with prompt caching) |
| Typical (4 tool calls, 3–4 turns) | 3–4 | ~$0.10–0.12 |
| Current fixed pipeline, for comparison | 9 | ~$0.15 |

These rest on the following assumptions:
- **Input sizes:** system prompt, task and tool descriptions about 1,500
  tokens; the document about 2,000.
- **Tool results:** about 2,300 tokens per regulation or policy result;
  about 300 per account result.
- **Final answer:** about 6,000 output tokens, plus thinking.
- **Tool calls:** make no API calls once they return raw chunks.

Before the pilot, exact token counts come from the token-counting
endpoint, with your approval.

Reductions agreed:
- the tools return raw chunks;
- prompt caching on the system prompt, the tools and the document;
- several tool calls allowed in one turn, with all their results
  returned in one message.

## What the agent sees

The task, the loan document (with customer ID and loan reference), the three
tool descriptions, and the results of tools it has called. Nothing else: no
account data, policy or regulation text until requested, no labels. Tool
descriptions state what data each tool holds, never what it is for in the
test.

## Addendum (2026-10-14): rules added before any live run

Requested by the user; enforced in `src/agent/agent_validation.py`.

**Policy every time.** `search_policy` is required for every Northbridge
credit agreement. An escalation decision must quote the procedure, and each
quote must be found in the policy passage it names; otherwise the case is
routed to review.

**No off-copy outcomes.** Each regulatory quote must be in the exact
passage it names, and that passage must be in the outcome's own citations.
Otherwise the outcome is forced to `insufficient_evidence`.

**2.1(c).** A 2.1(c) claim needs a quoted account note, with its date,
that is in the record and inside the window. "Recent" means (decision 2026-10-14) the 12
months before the review date. An unclaimed in-window bereavement,
separation or health note is flagged.

**Unnecessary calls**, decided from the document's own facts:

| Document | Unnecessary |
|---|---|
| Another lender's agreement | Account and policy calls |
| No lender named | Account calls |
| Not a credit agreement | Every call |
| Any document | A second account lookup, a lookup of another customer, any repeated call |

Three fixture documents cover these cases: v2_d17, v2_d18 and v2_d19.

**Escalation `not_applicable`** is a new decision value, used for another
lender's agreement and for a document that isn't a credit agreement.

## Next step

The v2 fixture set is built at zero API cost:
- **Location:** `data/fixtures_v2/`.
- **Labels:** the expected tool calls go in `docs/fixtures_v2_labels.md`,
  written before anything runs.
- **Checks:** the leakage rules and blind-read check from the fixtures_v2
  plan.

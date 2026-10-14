# Negative control for the claim checker: pass criteria

**Written before any pair was selected and before any API call
(2026-10-08).** These criteria are fixed. Results are reported against
them as written, whatever they turn out to be.

## What is being tested

The narrow LLM claim check used by `claim_verification check` (P8-06):
`claim_verification._check_claim`, which sees only a claim and some source
text and returns `yes`, `partially` or `no`. In the full pass it returned
`yes` for 484 of 536 claims and `no` for none. This control tests whether
it can say `no` at all when the source text does not support the claim, and
whether it still says `yes` when the source text does.

The control calls exactly the same function, prompt, model and tool
settings as the full pass. Each pair is one call with one chunk of source
text.

## The 30 pairs

All claims come from the full-pass claim check
(`docs/eval_raw_main_pass_v2_claim_judgments_checks_results.jsonl`).

**Eligible claim:** single-source, the full pass's LLM verdict was `yes`,
and its quote was found in its named chunk with match type `exact` or
`normalised`. So every claim used is one the checker already accepted
against its own chunk.

| Group | Pairs | Claim paired with |
|---|---|---|
| Unrelated | 10 | a chunk retrieved for a **different outcome** in the same main-pass row (doc, run), which is not among the chunks retrieved for the claim's own outcome |
| Neighbouring | 10 | the chunk immediately **before or after** the claim's named chunk in the same regulation file. Corpus order is by `file_name`, then numeric `page_label`, then `start_char_idx`, as recorded in the Chroma index. |
| Positive | 10 | the claim's **own named chunk**, exactly the text the judge saw |

**Mechanical checks (no LLM), done before any call; a pair that fails is
replaced, and the replacement is logged:**
- **Wrong chunks (unrelated and neighbouring):** the quote must be
  **absent**. The project's quote matcher must return `none` against that
  chunk (exact, normalised and fuzzy in-order word match all fail). Also,
  no "..."-separated part of the quote of 5 or more words may appear
  (normalised) in the chunk.
- **Positive chunks:** the quote must be **present** (`exact` or
  `normalised`).

**Selection:**
- Deterministic, random with fixed seed `20261008`.
- 30 distinct claims (no claim text used twice).
- Spread across all four outcomes in each group as evenly as 10 allows.
- The selected pairs are written to `docs/negative_control_pairs.jsonl`
  before any call and not changed afterwards.

## Verdict mapping (decided now)

- **Rejected** = the checker returns `no`.
- **Accepted** = the checker returns `yes`.
- `partially` is neither. For a negative pair it is **not** a rejection;
  for a positive pair it is **not** an acceptance. Every `partially` is
  reported.

## Pass criteria

| Group | Passes if |
|---|---|
| Unrelated | **10 / 10** rejected |
| Neighbouring | **at least 7 / 10** rejected |
| Positive | **at least 9 / 10** accepted |

The control passes only if all three groups pass. Each group's result is
reported separately, whether it passes or fails.

## Addendum (2026-10-08): added before any API call, after the pairs were frozen

**What the checker sees.** Only the claim and the chunk text. The user
message is `SOURCE TEXT:\n<chunk>\n\nCLAIM:\n<claim>`, under the system
prompt `claim_verification.CLAIM_CHECK_SYSTEM_PROMPT`. It is NOT shown the
verbatim quote, the excerpt number, the judgment's reasoning or status, or
the loan document. The quote check and the LLM check are therefore
independent.

**A negative pair marked `yes` is a checker failure.** Every unrelated or
neighbouring pair for which the checker returns `yes` is reported as a
checker failure, by pair id.

**Human annotation (never changes pass/fail).** For each such failure, the
user reads the wrong chunk and records whether it supports the claim in its
own words: `yes`, `partly` or `no`, with an optional note. Annotations go in
`docs/negative_control_annotations.jsonl` (`{"pair_id", "chunk_supports_claim",
"note"}`) and are shown in the report beside the failure. **An annotation
never changes any count, verdict, or pass/fail result above.** A failure
whose chunk is annotated as supporting the claim is still a failure.

**The report shows two results per group:**
- **LLM-only:** the checker's verdict, scored exactly as in "Verdict
  mapping" and "Pass criteria" above. **This is the result the pass
  criteria apply to.**
- **Combined gate:** "quote found AND LLM yes", reported against the same
  thresholds, for information. "Quote found" means the project's quote
  matcher finds the pair's quote in the pair's chunk (`exact`,
  `normalised` or `fuzzy`).
  - Accepted = quote found AND verdict `yes`.
  - Rejected = quote not found, OR verdict `no`.
  - Neither = quote found AND verdict `partially`. `partially` remains
    neither accepted nor rejected.
  - Because every wrong chunk was selected so that the quote is absent,
    the combined gate rejects every negative pair by construction. Its
    negative-group result shows what the quote check adds, not what the
    LLM can do.

## Cost

30 calls (one per pair). Worst case 120, if every call needed instructor's
3 retries. The claim check had 0 retries in all 665 real calls so far.
Retries are logged (observe-only) to `docs/negative_control_retries.jsonl`.

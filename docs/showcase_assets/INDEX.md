# Showcase assets: index

Evidence assets for the presentation storyboard, collected 2026-10-13.

**Synthetic data only.** All loan documents, borrowers, lenders and
accounts are synthetic (`data/synthetic_docs/`, `data/mock_accounts/`).
The regulatory text is the FCA corpus in `data/regulatory_corpus/`.

**How these were made.**
- Read only: no code, data or protected file was changed, and no API calls
  were made. Every source file is opened for reading only.
- User-specific paths and keys are redacted by `build_assets.py`. A scan
  of the sources found none.
- Assets 1–5 and 7 are produced by one script:

  ```bash
  python docs/showcase_assets/build_assets.py
  ```

  It needs the local Chroma index for asset 2's page labels only. Run it
  from the repo root.
- Asset 6 and the system flow were written by hand, from a command run and
  from reading the code.

| # | File | What it is | Source file(s) | Produced by | Date of source / of asset |
|---|---|---|---|---|---|
| 1 | `01_judgment_with_claim_check.md` | One complete judgment: `loan_agreement_1`, run 1, price_and_value. It shows the claims, the verbatim quotes, the whole excerpt each quote came from, and the claim-check verdict for each claim. Also the reasoning, document facts and absences. | `docs/eval_raw_main_pass_v2.jsonl` (excerpts as the judge saw them); `docs/eval_raw_main_pass_v2_claim_judgments_checks_results.jsonl` (claims, quote check, LLM check) | `build_assets.py` `asset1` | Full pass 2026-10-07; claim check 2026-10-08; asset 2026-10-13 |
| 2 | `02_retrieval_example.md` | A retrieval example: the query, the top 5 chunks with source file, page, similarity and node id, and the full chunk text. | `docs/eval_raw_main_pass_v2.jsonl`, row `loan_agreement_1` run 0, `_cached_price_and_value_context` (saved at run time from the real index). Pages come from the local Chroma index (`chroma_db/`, collection `regulatory_corpus`). | `build_assets.py` `asset2` | 2026-10-07 / 2026-10-13 |
| 3 | `03_extracted_loan_terms.json` | The extracted loan terms for `loan_agreement_1` run 1, as the structured output (`LoanAgreementFields`). | `docs/eval_raw_main_pass_v2.jsonl`, `_cached_fields` | `build_assets.py` `asset3` | 2026-10-07 / 2026-10-13 |
| 4 | `04_confidence_inputs.md` | Confidence inputs: the one signal that feeds the score and how it's combined. Values for 5 judgments (3 correct, 2 incorrect), means by correctness, the threshold sweep, and what the score does and doesn't separate. | `docs/eval_raw_main_pass_v2.jsonl`; `docs/eval_raw_main_pass_v2_summary.json`; `src/agent/compliance.py` (`compute_confidence`, `validate_outcome`) | `build_assets.py` `asset4` | 2026-10-07 / 2026-10-13 |
| 5 | `05_failure_record.md` | The failure record. (A) The 5,540 garbage-chunk silent ingestion failure. (B) The 49 placeholder tool-argument retries, with counts and real log lines. (C) The related parallel tool-use HTTP 400s and their fix. | `progress.md` (Session 2; Session 25); commit `cb3a7dd`; `docs/eval_raw_main_pass_v2_retries.jsonl`; `docs/eval_raw_main_pass_v2_errors.jsonl` | `build_assets.py` `asset5` | Failure A: 2026-08-20. B and C: 2026-10-01/07. Asset: 2026-10-13. |
| 6 | `06_test_results.md` | The exact pytest summary line, and what was skipped and why. | `tests/` | Command in the file (API key blanked) | 2026-10-13 |
| 7 | `07_evaluation_numbers.md` | Evaluation numbers as tables: per outcome, before and after the threshold, plus recall@k. | `docs/eval_raw_main_pass_v2_summary.json` | `build_assets.py` `asset7` | 2026-10-07 / 2026-10-13 |
| — | `SYSTEM_FLOW.md` | The main path as it actually runs, with the calling file and line for each step. MCP is marked as a side path. | `src/evaluation/run_eval.py`, `src/agent/first_pass.py`, `src/agent/intake.py`, `src/retrieval/query_engine.py`, `src/agent/compliance.py`, `src/mcp_server/` | Written by hand from the code | 2026-10-13 |
| — | `build_assets.py` | The script that produces assets 1–5 and 7. | — | — | 2026-10-13 |
| — | `build_images.py` | The script that renders `images/` (see below). | — | — | 2026-10-13 |

## Images (`images/`)

Rendered on 2026-10-13 by:

```bash
python docs/showcase_assets/build_images.py
```

How the images are made:
- **Rendering:** Pillow, which is in `.venv`, with Windows system fonts.
  Zero API calls.
- **Every drawn line** is read from the named file, or from the named
  command's output, at render time.
- **Not from the source:** only the titles and captions. Line numbers are
  counted as `sed`/`grep -n` count them.
- **Long lines are wrapped, never cut.**
- **Paths:** user-specific paths are redacted to `<USER_HOME>`.
- **Styles:** logs are monospace on grey. Records are italic serif with a
  quote bar, not styled as terminal output.

| Image | Status | Source | What it shows |
|---|---|---|---|
| `images/01_parallel_tool_use_400_real_log.png` | **Real log** | `<USER_HOME>/eval_runs/main_pass_v2.log` L95–99, the console output of `run_eval main`, 2026-10-01, before the fix. The only change is L99's user path, redacted. | `loan_agreement_2` run 0: `200 OK`, then `HTTP/1.1 400 Bad Request`, `API call failed on attempt 2`, `Max retries exceeded`, `[FAILED]`. The same pattern is at L136–140. |
| `images/02_placeholder_retries_real_log.png` | **Real log** | `docs/eval_raw_main_pass_v2_retries.jsonl` L1–2 of 49, written 2026-10-07 by `src/agent/retry_log.py` | Two judge-call `ValidationError` records with the `$PARAMETER_NAME` and `$PARAMETER_VALUE` wrappers. Not fixed. |
| `images/03_garbage_chunks_record.png` | **Record** | `progress.md` L2636–2644, and the output of `git show -s --format=%B cb3a7dd` (2026-08-20) | The session note and the commit message. No log of the failed run exists, and it was not reproduced. |

### Video clips 9 and 10

Rendered on 2026-10-13 by:

```bash
python docs/showcase_assets/build_video_images.py
```

It uses the same renderer and rules as above, with zero API calls. It
also writes `08_confidence_signals.md` from the saved data.

| Image | Status | Source | What it shows |
|---|---|---|---|
| `images/04_clip9_regulation_retrieval.png` | **Real output** | `02_retrieval_example.md` L10 and L15–21 (from `loan_agreement_1` run 0, saved at run time) | The query and the top 5 FCA chunks, with page and similarity |
| `images/05_clip9_extracted_loan_terms.png` | **Real output** | `03_extracted_loan_terms.json` L5–18 (`loan_agreement_1` run 1) | The structured extraction |
| `images/06_clip9_supporting_citation.png` | **Real output** | `01_judgment_with_claim_check.md` L18–47 (`loan_agreement_1` run 1) | One claim, its verbatim quote, the whole excerpt, and the claim-check `yes` |
| `images/07_clip10_confidence_signals.png` | **Real output** | `08_confidence_signals.md`, built from `eval_raw_main_pass_v2.jsonl`, `_claim_judgments_checks_results.jsonl` and `_summary.json` | The routing signal, the evaluation-only signals, and what the routing signal separates across 45 runs |

The retrieval image is from run 0, because only run 0 saved the query
text. The other three images are from run 1. Both runs are the same
document and outcome.

## How the examples were chosen

**Asset 1.** I read "a document where the verdict was yes" as the claim
check's verdict. The judgment chosen meets all of these:
- its judge status matches the planted label;
- every regulatory claim got a claim-check `yes`;
- every quote was found in its named chunk.

29 judgments qualify. `loan_agreement_1` run 1, price_and_value is the
planted price-and-value defect, and its status survives the threshold.

**Asset 2.** Only run-0 rows save the retrieval query text, so the example
is `loan_agreement_1` run 0. Its query is built from run 0's extracted
fields, so its scores differ slightly from the run 1 judgment in asset 1.

**Asset 4.** The five judgments were picked to show each case:
- correct, kept;
- correct, overridden;
- correct, kept, at high confidence;
- incorrect, kept, at almost the same confidence (same document and
  outcome as the previous one);
- incorrect, overridden.

## What could not be produced from existing data

- **A log of the 5,540-chunk failed ingestion run.** None was saved. Asset
  5A quotes the session note and the commit message, which are the only
  records, and does not reconstruct log lines.
- **A fix for the placeholder retries.** None was applied; it is recorded
  as a known limitation. Asset 5B says so. The fix shown in 5C is for a
  different failure: the parallel tool-use 400s.
- **The retrieval query for runs 1 and 2, and for the other three
  outcomes.** The query text wasn't saved. Only the retrieved sources were
  saved, so asset 2 uses the one saved query.
- **A UI screenshot.** There is no UI: `src/app.py` does not exist.

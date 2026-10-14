# Asset 5: failure record

All loan documents, borrowers and lenders referred to here are synthetic (data/synthetic_docs/). Regulatory text is from the FCA corpus in data/regulatory_corpus/.

## A. 5,540 garbage chunks: silent ingestion failure (2026-08-20)

**What happened.** `SimpleDirectoryReader` (`src/ingestion/ingest.py`) fell back to reading raw PDF bytes as text because `llama-index-readers-file` was not installed. The run reported success with 5,540 chunks; every chunk was binary PDF data.

**How it was found.** By opening and reading sample chunks, not from the exit code or logs.

**What changed (commit `cb3a7dd`, 2026-08-20):**
- `requirements.txt`: added `llama-index-readers-file>=0.4.0`.
- Re-ingested: 558 chunks of real text across the 3 PDFs.
- `tests/test_ingestion.py::test_chunks_contain_real_text_not_raw_pdf_bytes` added, with source coverage and retrieval-relevance tests.

**Log lines.** No log of the failed run was saved. The real records are the session note and the commit message, quoted verbatim:

`progress.md` (Session 2):

```text
  2. Bigger one: `SimpleDirectoryReader` silently falls back to reading
     **raw PDF bytes as text** if `llama-index-readers-file` isn't
     installed — no error, no warning that looks fatal, just garbage
     chunks (`'%PDF-1.4\n...'`). First ingestion run "succeeded" (5540
     chunks indexed) but every chunk was binary garbage. Caught by
     actually inspecting sample chunk text, not just checking exit code.
     Installed `llama-index-readers-file`, reran — real text, 558 sane
     chunks.
```

Commit `cb3a7dd` message (`git show -s cb3a7dd`), excerpt:

```text
SimpleDirectoryReader silently reads raw PDF
bytes as text without llama-index-readers-file installed (5540 "chunks"
that were actually binary PDF data)
```

## B. Placeholder tool-argument retries (full pass, 2026-10-07)

Source: `docs/eval_raw_main_pass_v2_retries.jsonl` (49 records, written by the observe-only hooks in `src/agent/retry_log.py`).

- Records: 49, all `call_site: judge`, all `ValidationError`.
- Wrapper key in the tool arguments: {"$PARAMETER_NAME": 33, "$PARAMETER_VALUE": 14, "$PARAMETER_name": 1, "$PARAMETER_VALUE_PLACEHOLDER": 1}.
- Failed attempt number: {"1": 46, "2": 3} (attempt 1 failed then 2 succeeded; attempt 2 failed then 3 succeeded).
- Last-attempt failures: 0 (none hard-failed).
- Under 200 output tokens: 30; the rest carried a full judgment inside the wrapper.
- By outcome: {"Price and Value": 10, "Consumer Support": 19, "Consumer Understanding": 13, "Products and Services": 7}.
- All `stop_reason: tool_use` with 1 tool call: True.

**Fix: none applied.** Recorded as a known limitation (`progress.md`, Session 25; ARCHITECTURE.md "Evaluation notes"). instructor's retry recovered every one. Cost, per `progress.md`: the second resume sent 337 requests against 288 nominal, a difference of 49, matching the 49 records.

Real log lines (first two records; error text cut to its first line):

```json
{"ts": "2026-10-07T19:55:16", "call_site": "judge", "doc_id": "loan_agreement_5", "run_idx": 1, "outcome": "Price and Value", "attempt_number": 1, "is_last_attempt": false, "error_type": "ValidationError", "error": "6 validation errors for OutcomeJudgment ... (first line of the error; full text in the source file)", "stop_reason": "tool_use", "output_tokens": 40, "content_block_types": ["tool_use"], "tool_use_count": 1, "tool_names": ["OutcomeJudgment"]}
{"ts": "2026-10-07T19:57:16", "call_site": "judge", "doc_id": "loan_agreement_5", "run_idx": 2, "outcome": "Consumer Support", "attempt_number": 1, "is_last_attempt": false, "error_type": "ValidationError", "error": "6 validation errors for OutcomeJudgment ... (first line of the error; full text in the source file)", "stop_reason": "tool_use", "output_tokens": 1327, "content_block_types": ["tool_use"], "tool_use_count": 1, "tool_names": ["OutcomeJudgment"]}
```

## C. Related, and fixed: parallel tool-use HTTP 400s (same pass)

Source: `docs/eval_raw_main_pass_v2_errors.jsonl` (2 records, before the fix). Fix: `src/agent/structured_output.single_tool_choice` sets `disable_parallel_tool_use: True` on all 6 structured calls; tested in `tests/test_single_tool_choice.py`. After the fix: 0 hard failures; both failed runs were redone.

```json
{"doc_id": "loan_agreement_2", "run_idx": 0, "error": "InstructorRetryException(\"Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'messages.2: `tool_use` ids were found without `tool_result` blocks immediately after: toolu_011NfwuMNrvgMZumqExyH53F, toolu_012bfDyxjQAAB1o2TY1kjGLe, toolu_0177xpvmcemLiF1TqD91Q3RZ, toolu_01BbjLcCScTasr7VUmHL5cWB, toolu_01CaNELLVpf3mDV6Kb3rkgaj. Each `tool_use` block must have a corresponding `tool_result` block in the next message.'}, 'request_id': 'req_011CfcKWt8CdRhPvNVxMciCf'}\")"}
{"doc_id": "loan_agreement_3", "run_idx": 0, "error": "InstructorRetryException(\"Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'messages.2: `tool_use` ids were found without `tool_result` blocks immediately after: toolu_01CMUskMTWNTSHTqgeRPgaPU, toolu_01EHSNCpXJWtVCNpuzezWJAB, toolu_01Ht87LWyAg5KAvaehWpDs22, toolu_01XnKyhv4BrAsMqRY5nGyGp1, toolu_01Y12pJiCRpVEyE4bP2QREVG. Each `tool_use` block must have a corresponding `tool_result` block in the next message.'}, 'request_id': 'req_011CfcKrnNyFTA5sH9x4WtSF'}\")"}
```

# Audit logging standard: design

**Status: design only, for approval. No code yet.** Written 2026-10-13.
Zero API cost to build or test.

## 1. Why: what the current logging misses

These are facts from the code and from past runs:

- **Silent failures pass as successes.** The 5,540-chunk ingestion run
  "succeeded". Ingestion logs only counts (`src/ingestion/ingest.py`), and no
  check looks at what the chunks contain.
- **Rows are not tied to their settings.** Main-pass rows record no model,
  threshold, commit or timestamp (ARCHITECTURE.md "Notes for the re-run").
- **Logging is spread across ad-hoc channels:**
  - retries in `*_retries.jsonl` (`src/agent/retry_log.py`);
  - failures in `*_errors.jsonl`;
  - cited sources through `logger.info` in `validate_outcome`;
  - everything else in console output redirected by hand to `.log` files.

  No single record shows what one run did, stage by stage.
- **Successes are invisible.** A missing check looks the same as a passing
  check.

## 2. Format: one event per line

- **File format:** JSON Lines, UTF-8, append-only. Events are never edited.
  A correction is a new event.
- **Envelope.** Every event has the same top-level fields, with
  stage-specific detail under `data`:

| Field | Meaning |
|---|---|
| `schema_version` | Starts at `1` |
| `ts` | UTC, ISO 8601, milliseconds |
| `run_id` | One UUID per command invocation |
| `stage` | `ingestion`, `extraction`, `retrieval`, `judgment`, `validation`, `agent`, `evaluation`, `run` |
| `event` | `start`, `success`, `check`, `retry`, `error`, `limit`, `end` |
| `level` | `info`, `warn`, `error` |
| `component` | `file:function` that emitted it |
| `doc_id`, `run_idx`, `outcome` | When applicable |
| `duration_ms` | For `success` and `error` events |
| `data` | Stage-specific fields (section 5) |

**The run header.** Logged once per run, as `stage: run, event: start`. It
records:
- `git_commit`, and whether the tree had uncommitted changes;
- the settings: model, `CONFIDENCE_THRESHOLD`, top-k, excerpt length;
- the corpus: collection name and chunk count;
- a hash of the full settings set, and the Python and key package versions.

Every row of output can then be traced to the exact code and settings
that produced it.

**Check events** always carry `name`, `passed` (true or false), `metric`,
`threshold` and `action` (`none`, `warn`, `block` or `route_to_review`). A
check is logged when it **passes** too, so a missing check is visible.

**LLM call events** carry:
- `call_site`, `model`, `request_id`;
- tokens: input, output, cache read, cache write;
- `stop_reason`, `attempt`, and the tool names in the response;
- a SHA-256 hash of the prompt (not the text; see section 4).

## 3. Location

- **Directory:** `LOG_DIR` (an environment setting).
  - **Default:** `./logs/`. This needs `logs/` added to `.gitignore`, the
    one config change in this design.
  - **Evaluation runs:** set `LOG_DIR` outside the OneDrive folder, as
    you already do with `eval_runs/`, so sync can't lock or split files.
- **One file per run:** `LOG_DIR/<YYYY-MM-DD>/<run_id>.jsonl`.
- **An index:** `LOG_DIR/index.jsonl`, one line per run (`run_id`, command,
  start and end time, counts by level, failed checks). That makes runs
  listable without opening each file.
- **Tests never write to `LOG_DIR` or `docs/`.** They use a temporary
  directory. This extends the existing guard in the test suite.

## 4. Redaction

Every event goes through one redaction function before it is written.

- **Settings:** a fixed allowlist of setting names is logged; the
  environment is never dumped. API keys and tokens are never logged. A
  final scan drops any event containing `sk-ant`, and logs that it did.
- **Paths:** written relative to the repo root. Anything under the home
  folder becomes `<USER_HOME>`.
- **Document text, account records, policy and regulation chunks:** not
  logged in full. Logged as `doc_id`, the SHA-256 of the text, and its
  length; chunks as node IDs and scores.
  - **Customer data:** account lookups log the customer ID and
    `found: true/false`, never the holder's name or notes. The data is
    synthetic, but the habit should be production-grade.
- **Prompts and responses:** hashes only by default. An explicit
  `--log-payloads` flag writes full text to a separate `*_payloads.jsonl`
  for debugging. It is off by default and never used for evaluation runs
  you plan to share.

## 5. What each stage logs

`S` = success, `C` = check (logged pass or fail), `E` = error.

| Stage | Logs | Checks |
|---|---|---|
| **Ingestion** | S: files found (name, size, SHA-256), pages per file, chunks per file, total chunks, collection name, duration | See section 6. Failing blocks the swap. |
| **Extraction** | S: fields returned, how many are "Not addressed in this document.", tokens, attempts | C: each numeric field (amount, APR, term) appears in the document (deterministic, local; warn only) |
| **Retrieval** | S: question text (built from synthetic fields), top-k node IDs and scores, collection chunk count | C: no results (`route_to_review`); top score below 0.5, i.e. off-topic (warn) |
| **Judgment** | S: per outcome, status, raw and resolved citations, tokens, `stop_reason`, attempts | C: citations out of range (warn); claims with quotes not found (warn). Retry events replace `retry_log.py`'s separate file |
| **Validation** | S: confidence, threshold, overridden yes/no, `needs_human_review` | C: confidence computed from at least 1 cited source |
| **Agent loop (future)** | S: each tool call (tool, validated arguments, result size and hash, cached yes/no, turn, count against limit) | `limit` event when any limit is hit; C: required calls made, checked after the run |
| **Evaluation harness** | S: rows expected vs written, pairs skipped, outputs written | C: row count equals documents × runs; protected-file hashes unchanged |
| **Run end** | Counts of events by level, failed checks, total tokens, estimated cost | |

## 6. Ingestion sanity check: catching a run like the 5,540-chunk one

The ingestion run builds into a **new, temporary collection**. It replaces
the live one only if every blocking check passes. If any blocking check
fails, the old index stays in place, the command exits non-zero, and the
failures are logged.

| Check | Would have caught the 5,540-chunk run? | Threshold | Action |
|---|---|---|---|
| Reader per file: PDFs were read by a PDF reader, not the plain-text fallback | Yes, directly (the cause) | must be PDF reader | block |
| Raw-PDF markers: no chunk starts with `%PDF` or contains `endobj`/`stream` markers | Yes | 0 chunks | block |
| Non-printable character share across all chunks | Yes (binary data) | < 1% | block |
| Chunks per page | Yes: 5,540 / 344 ≈ 16, against 558 / 344 ≈ 1.6 now | 0.5–5 | block |
| Text per page: every file yields text on most pages (an encrypted PDF that fails to open yields none) | Catches the encrypted-PDF bug | ≥ 90% of pages with text | block |
| Every source file represented, chunk share roughly in line with page share | Partly | each file > 0; share within 2× of page share | warn |
| Retrieval smoke test: 3 fixed, known questions return their expected source file in the top 5 with score ≥ 0.6 | Yes | 3 of 3 | block |

These thresholds are set from the current, known-good index: 558 chunks and
scores of 0.65–0.74 on known questions. Your approval is needed before they
are final.

**Testing it.** The offline test feeds fake raw-PDF-like chunks to the
check function and asserts that it fails and blocks. The original run is
not reproduced: the test checks the check, nothing more.

## 7. Retention

- **Logs behind published results** (the main pass, claim checks,
  negative control): kept permanently, copied next to their outputs,
  and listed in the results document.
- **Everything else:** deleted after 30 days. A `logs prune` command
  does this, as a dry run by default: it prints what it would delete, and
  deletes only with `--yes`.
- **No log is edited.**

## 8. How it fits with what exists

- **`retry_log.py`:** its hooks stay, but they write `retry` events into
  the run's log instead of a separate file. Existing retry files are kept
  as they are.
- **Evaluation outputs** (`eval_raw_main_pass_v2.jsonl` and so on) remain
  data products, not logs. Each new row gains `run_id`, so it links to its
  log.
- **Console output** stays for people to read. It is no longer the
  record.
- **Protected files:** untouched.

## 9. Build order, after approval (zero API calls)

1. **Logging module and tests:** the envelope, redaction, file layout,
   index, and the test-directory guard.
2. **Ingestion checks:** the temporary-collection swap, offline tests, and a
   dry run of the checks against the current index. This reads the index
   and does not rebuild it.
3. **Pipeline events:** wire the remaining stages; the evaluation harness
   gets the run header and the completeness checks.
4. **Documentation:** document the standard in ARCHITECTURE.md.

## Decisions (approved 2026-10-13)

1. **`LOG_DIR`:** defaults to `./logs/`, which is gitignored.
2. **Retention: no automatic pruning.** All logs are kept, and there is
   no `logs prune` command. This supersedes section 7's 30-day rule.
3. **Failed ingestion checks warn and block,** unless explicitly allowed.
   - A blocking check that fails is logged at `error` and stops the swap.
   - With `--allow-failed-checks`, the swap goes ahead. The override and
     every failed check are logged at `warn`, and the run header records
     that the override was used.
4. **Prompt text is logged only behind the `--log-payloads` flag.** It is
   off by default.
5. **Thresholds stay as set in section 6, defined in `src/config.py`:**
   one named setting each, not hardcoded in the check functions.

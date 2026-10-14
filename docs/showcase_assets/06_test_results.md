# Asset 6: test results

All loan documents, borrowers and lenders referred to here are synthetic
(`data/synthetic_docs/`).

Run on 2026-10-13, from the repo root, with the API key blanked so that no
test could make an API call:

```bash
ANTHROPIC_API_KEY="" .venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider
```

Exact summary line:

```text
139 passed, 40 skipped in 127.37s (0:02:07)
```

- **Skipped (40):** the live tests. Each of these files is gated with
  `pytest.mark.skipif` on `ANTHROPIC_API_KEY` being unset:
  `test_compliance.py`, `test_compliance_mcp.py`, `test_first_pass.py`,
  `test_intake.py`, `test_mcp_tools.py`, `test_query_engine.py`,
  `test_uncertainty.py`. They were not run for this asset.
- **Passed (139):** every other test. That includes `test_ingestion.py`,
  which reads the local Chroma index and loads the local embedding model,
  with no API call.
- An earlier run in the same session gave `139 passed, 40 skipped, 1 error`.
  The error was a teardown assertion in
  `tests/test_signal1_and_check_retries.py`, which checks that no file is
  created in `docs/` during the test. It fired because
  `docs/showcase_assets/` was created while that run was in progress. The
  line above is the re-run, made after the folder existed. No test or
  code was changed between the two runs.

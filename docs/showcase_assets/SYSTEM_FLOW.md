# System flow: the main path as it runs

All loan documents, borrowers and lenders referred to here are synthetic
(`data/synthetic_docs/`).

Written by hand from the code on 2026-10-13 (read only). Every step names the
file and function that calls it. This is a **fixed workflow**: the model does
not choose tools or steps; the code calls each step in order.

## Entry points that run the main path

| Entry point | Calls |
|---|---|
| `python -m src.evaluation.run_eval main` (`src/evaluation/run_eval.py` `cmd_main`, L343–358) | `FirstPassAgent.run` → `ComplianceAgent.evaluate` → `build_compliance_report`, once per document per run. This produced the full pass. |
| `python -m src.agent.compliance <doc>` (`src/agent/compliance.py` `__main__` → `run_compliance_check` → `ComplianceCheckAgent.run`, L478–481) | The same three steps, for one document. |

There is no UI: `src/app.py` (named in CLAUDE.md as `streamlit run src/app.py`) does not exist.

## Steps (one document)

```text
loan agreement text
  │
  ▼
1. Extraction                     src/agent/first_pass.py  FirstPassAgent.run (L90)
   extract_fields()               src/agent/intake.py      IntakeAgent.extract
   → LoanAgreementFields          src/agent/schemas.py
   1 LLM call (instructor, forced single tool: structured_output.single_tool_choice)
  │
  ▼
2. Retrieval, x4 (one per Consumer Duty outcome)
                                  src/agent/first_pass.py  FirstPassAgent.run (L92–97)
   question built from fields     first_pass.build_*_question
   QueryEngine.query()            src/retrieval/query_engine.py (L146)
     retriever: Chroma "regulatory_corpus", bge-small-en-v1.5, top k = 5 (local)
     + 1 LLM synthesis call per query; its answer is NOT used by the judge
   → QueryResult (sources: whole chunks, similarity, node id)
  │
  ▼
3. Judgment, x4                   src/agent/compliance.py  ComplianceAgent.evaluate (L252) → _judge (L235)
   input: full document text + that outcome's extracted field + the 5 retrieved chunks
          (build_judgment_user_message)
   → OutcomeJudgment (status, reasoning, cited excerpts, claims with verbatim quotes)
   1 LLM call per outcome (instructor, forced single tool)
  │
  ▼
4. Deterministic validation       src/agent/compliance.py  build_compliance_report (L444)
   validate_outcome: resolve cited excerpts → confidence = min similarity of cited sources
   confidence < 0.65 → status replaced by insufficient_evidence
   needs_human_review = any outcome potentially_non_compliant or insufficient_evidence
   → ComplianceReport (no LLM call)
```

Nominal LLM calls per document: 1 + 4 + 4 = 9.

## Side paths (not called by the main path)

| Component | File | Called by |
|---|---|---|
| **MCP server** (`lookup_regulation`, `lookup_account`, `query_policy`) | `src/mcp_server/server.py`, client `src/mcp_server/client.py` | Only `ComplianceAgent.judge_price_and_value_with_mcp_context` (`src/agent/compliance.py` ~L267), which only tests call (`tests/test_compliance_mcp.py`, `tests/test_single_tool_choice.py`). |
| Extraction confidence | `src/agent/uncertainty.py` `extract_fields_with_confidence` | Tests only. |
| Evaluation (after the run, on saved rows) | `src/evaluation/run_eval.py`, `groundedness.py`, `claim_verification.py`, `negative_control.py` | Command line. They read saved output; `claim_verification check` makes its own LLM calls (claim + chunk only). |

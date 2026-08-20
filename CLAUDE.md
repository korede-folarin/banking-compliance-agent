# CLAUDE.md

## Project
Banking Compliance & Customer Intelligence Agent — a RAG + MCP + agentic
system that reviews loan/compliance documents against FCA/PRA regulatory
guidance, flags issues with confidence scoring, and routes uncertain cases
to human review. Built as a portfolio project demonstrating production-grade
agentic AI (not a chatbot demo).

## Stack
- Python 3.11+
- Claude API (Anthropic SDK) — reasoning, extraction, agent orchestration
- LlamaIndex — RAG, document indexing, query engine
- ChromaDB — vector store (local, no external infra)
- Pydantic — structured output validation
- Custom MCP server — regulation lookup, mock account/transaction lookup,
  policy rulebook query tools
- Streamlit — UI
- Ragas or custom harness — RAG/agent evaluation

## Session start (do this every time, before any code)
1. Read `progress.md` — see what was done last session and what's next.
2. Read `feature_list.json` — see what's passing vs not.
3. Read `ARCHITECTURE.md` if touching design decisions, not just implementation.
4. Run `git log --oneline -10` to see recent commits.
5. State which single feature you're working on before starting.

## Build rules
- **One feature at a time.** Do not attempt to build multiple phases in one
  session. Pick the highest-priority `passing: false` item in
  `feature_list.json` and finish it before starting another.
- Do not mark a feature `passing: true` without actually testing it
  end-to-end (real query, real document, checked output — not "it runs
  without error").
- Prefer one orchestrating agent + a deterministic validation layer over
  spawning multiple LLM agents. Only add a new agent if there's a specific,
  documented reason (different tool access, different context needs).
- Every extraction/compliance-check output must include a confidence score
  and cite the retrieved evidence it's based on. If confidence is low,
  route to human review — do not guess.
- MCP tools must exist for a real reason (separate data domains: regulatory,
  customer/account, policy). Don't add MCP tools that plain function calls
  would handle just as well.

## Commands
- Install deps: `bash init.sh`
- Run app: `streamlit run src/app.py`
- Run tests: `python -m pytest tests/`
- Run eval: `python -m src.evaluation.run_eval`

## Session end (do this every time, before stopping)
1. Update `progress.md`: what was done, what's next, any known issues.
2. Update `feature_list.json`: mark `passing: true` only for tested features.
3. Commit with a descriptive message (one logical change per commit).

## Off-limits
- `data/regulatory_corpus/` — reference material, read-only, do not edit or
  regenerate without being asked.
- Never commit `.env` or real API keys — use `.env.example` as the template.

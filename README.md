# Banking Compliance & Customer Intelligence Agent

A RAG + MCP + agentic system that reviews banking documents and customer
queries against regulatory guidance (FCA/PRA), flags compliance issues
with a confidence score, and routes uncertain or high-risk cases to human
review.

**Status:** in progress — see `progress.md` for current build state.

## What this demonstrates
- **RAG**: retrieval over a real regulatory corpus (FCA Handbook, PRA
  rulebook), with retrieval quality evaluated (recall@k), not assumed.
- **MCP**: a custom MCP server exposing regulation lookup, mock
  account/transaction lookup, and policy rulebook tools — used because
  these are genuinely separate data domains, not because MCP is trendy.
- **Agentic design**: one orchestrating agent + a deterministic validation
  layer + a human approval gate, not an unjustified multi-agent swarm.
- **Uncertainty handling**: every output carries a confidence score
  grounded in retrieval quality; low-confidence cases are abstained on
  and routed to a human, not guessed at.
- **Evaluation**: labelled test set, faithfulness/hallucination scoring,
  prompt variant comparison.
- **Deployment & monitoring**: Dockerized, deployed, every run logged with
  a dashboard showing failure/flag rates over time.
- **Judgement**: see `ARCHITECTURE.md` for documented trade-offs (why RAG
  over fine-tuning, why MCP over plain function calls, why one agent over
  five) and a business impact model (time saved, false escalation cost).

## Stack
Claude API · LlamaIndex · ChromaDB · Pydantic · Streamlit · MCP · Ragas

## Setup
```bash
bash init.sh
streamlit run src/app.py
```

## Project structure
See `ARCHITECTURE.md` for the full design and data flow diagram.

## Honest scope note
This is a portfolio project, not a production banking system. Data is
public regulatory text plus synthetic documents/queries — no real
customer data is used anywhere. Where a real deployment would need
additional work (scale, security review, access control depth), that is
noted explicitly rather than implied.

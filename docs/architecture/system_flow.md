# How a document flows through the system (as built, 2026-10-24)

The fixed workflow (top) produces the evaluated compliance verdicts. The agentic loop (middle) chooses
its own MCP tools. The code gate runs before any model call. Everything ends in the human review queue,
and every step writes to the audit log that the dashboard reads.

```mermaid
flowchart TD
    DOC["Loan agreement (text)"] --> GATE{"Code gate<br/>document facts"}

    GATE -- "not a credit agreement" --> NA["All outcomes and escalation:<br/>not applicable<br/>no model call, no tool call"]

    subgraph FIXED["Fixed workflow: compliance verdicts"]
        EX["1. Extract terms<br/>1 LLM call, Pydantic schema"] --> RET["2. Retrieve regulation<br/>1 query per outcome, Chroma top 5"]
        RET --> JUD["3. Judge each outcome<br/>4 LLM calls, quotes as claims"]
        JUD --> VAL1["4. Deterministic validation<br/>confidence from retrieval, quote checks"]
    end

    subgraph AGENT["Agentic loop: the model chooses tools"]
        LOOP["Claude with tool_choice auto<br/>max 8 calls, 6 turns"] <--> MCP["MCP server over stdio"]
        MCP --- T1["search_regulation<br/>one per outcome"]
        MCP --- T2["get_account<br/>Northbridge only"]
        MCP --- T3["search_policy<br/>Northbridge only"]
        LOOP --> VAL2["Deterministic validation<br/>calls, quotes, citations, triggers 2.1 a-c,<br/>cannot_determine rules"]
    end

    GATE -- "credit agreement" --> EX
    GATE -- "credit agreement<br/>tools offered by lender" --> LOOP

    VAL1 --> QUEUE["Human review queue<br/>auto-approval off: every case"]
    VAL2 --> QUEUE
    NA --> QUEUE
    QUEUE --> DEC["Reviewer confirms or overrides each item<br/>override needs a reason; append-only"]

    VAL1 -.-> LOG[("Audit log<br/>logs/*.jsonl")]
    VAL2 -.-> LOG
    DEC -.-> LOG
    LOG -.-> DASH["Monitoring dashboard<br/>failure, flagged rate, latency"]
```

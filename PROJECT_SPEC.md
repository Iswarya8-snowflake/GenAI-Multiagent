# PROJECT_SPEC.md - L3 Incident Triage Copilot
Goal: portfolio project. A multi-agent copilot that triages an L3 support incident using RAG over
runbooks, logs and live (simulated) monitoring data, then proposes a cited fix that a human approves
before a ticket is written.

Hard rules
- Synthetic data only. No real company, client, host or employee names.
- Never edit or print .env. Secrets only through environment variables.
- Python 3.11+, one venv, small readable code with comments. Add a package to requirements.txt
  only when the code uses it.
- Models: Ollama llama3.2:3b (chat) and nomic-embed-text (embeddings). The machine has 8 GB RAM:
  tests must not load any model, no parallel LLM calls, MAX_CONCURRENT_RUNS=1, num_ctx 4096.
- The LLM is used only for Triage and the Planner (structured JSON, temperature 0). Tools are
  called by code, not chosen by the LLM.
- Do not open a browser or run browser tests.

Synthetic services: calc-engine, feed-gateway, orders-db, msg-queue
Error codes: DB-1205 (orders-db lock wait), MQ-2041 (msg-queue consumer lag),
FEED-7002 (feed-gateway thread pool saturated), JOB-5003 (calc-engine batch failure)

Architecture: Streamlit UI -> FastAPI (REST + SSE + approval) -> LangGraph -> agents ->
MCP tool server (FastMCP, streamable HTTP, port 8765) -> data (FAISS knowledge base, SQLite tickets,
monitoring simulator on port 8001)
Agents: Triage, Retrieval, Log Analysis, Live Status, Planner, Reviewer, Ticketing
(Research agent with web search comes later, optional)

MCP tools: search_kb, search_wiki, parse_logs, lookup_signature, get_active_alerts,
get_service_health, get_metrics, tail_log, search_tickets, get_ticket, suggest_owner, redact_text,
search_web, fetch_page, create_ticket, update_ticket, kb_upsert
Tool rules: create_ticket, update_ticket and kb_upsert need an approval_id that only the API issues
after a human approves. search_web only accepts redacted queries. fetch_page: https only, block
private addresses.

Plan format: {root_cause, fix_steps[], confidence 0-1, claims[{text, source_ids[]}], not_found[]}.
Every claim cites evidence ids. The Reviewer rejects a claim whose cited text lacks the error codes
or commands it names; at most 2 retries, then escalate to a human.
Approval: every write needs human approval. Strict level (sources must be acknowledged) for web
evidence, P1/P2 severity, confidence below 0.7, or a retry.
Live data: every live response carries as_of, and the UI shows it.

Definition of done for each step: code runs, tests pass, one note added to README, git commit.
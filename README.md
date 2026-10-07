# L3 Incident Triage Copilot

A multi-agent copilot that triages L3 support incidents using RAG over runbooks, logs, and simulated monitoring data, proposing cited fixes with human approval before ticket creation.

## Overview
- **Architecture**: Streamlit UI -> FastAPI (REST + SSE + approval) -> LangGraph -> Agents -> MCP Tool Server -> Data & Simulators
- **Models**: Ollama (`llama3.2:3b` for chat, `nomic-embed-text` for embeddings)
- **Tool Protocols**: FastMCP (streamable HTTP on port 8765)

## Project Structure
- `app/api/`: FastAPI endpoints (REST, SSE, human approval)
- `app/graph/`: LangGraph orchestration and agent state definitions
- `app/mcp_server/tools/`: MCP tool definitions and server implementation
- `app/sim/`: Monitoring simulator (port 8001)
- `app/ingest/`: Knowledge base ingestion pipeline
- `data/runbooks/`: Runbooks for synthetic services
- `data/wiki/`: Wiki reference documents
- `data/logs/`: Service log files
- `eval/`: Evaluation scripts and datasets
- `scripts/`: Development and maintenance scripts
- `tests/`: Automated test suite
- `ui/`: Streamlit user interface

## Setup
1. Copy `.env.example` to `.env` and configure environment variables:
   ```bash
   cp .env.example .env
   ```
2. Activate virtual environment:
   ```powershell
   .\venv\Scripts\activate
   ```
3. Install dependencies as needed:
   ```bash
   pip install -r requirements.txt
   ```

## Development Log
- Initial project scaffolding created per `PROJECT_SPEC.md`.
- Generated synthetic dataset: 6 runbooks, 25 past incidents, 4 error logs, and 15 evaluation questions.
- Built FAISS knowledge base index with Ollama `nomic-embed-text` embeddings (`scripts/build_index.py`), created KB search and upsert tool (`app/mcp_server/tools/kb.py`), and verified 100% retrieval hit rate @ 3 on evaluation test set (`scripts/eval_retrieval.py`).
- Built tools suite without LLM/network (`safety.py`, `logs.py`, `wiki.py`, `tickets.py`, `live.py`), developed FastAPI monitoring simulator (`app/sim`), and verified all 8 unit tests in `tests/test_tools.py`.
- Implemented FastMCP server (`app/mcp_server/server.py`) over streamable HTTP on port 8765 registering all 17 specification tools, and verified end-to-end communication, live alert querying, log parsing, and approval gate enforcement via `scripts/mcp_smoke_test.py`.
- Built initial 3-node LangGraph workflow (Triage, Retrieval, Planner) using ChatOllama `llama3.2:3b`, integrated MCP tools with `langchain-mcp-adapters`, and verified execution on sample incidents via `scripts/run_cli.py`.
- Extended LangGraph workflow with parallel investigation branches (`retrieval`, `log_analysis`, `live_status`), join node, strict grounding reviewer (`app/graph/grounding.py`), approval policy (`app/graph/policy.py`), human-in-the-loop interrupt, ticketing, and KB writeback. Verified 17 unit tests in `pytest` and ran full incident under injected `db_lock` scenario.
- Built FastAPI backend (`app/api/main.py`) with REST endpoints, Server-Sent Events (`/incidents/{id}/events`), human approval gate with strict policy enforcement (`/incidents/{id}/approval`), ticket querying, alert webhook deduplication (10-minute window), API key authentication, and `MAX_CONCURRENT_RUNS` concurrency limiter with approval slot release. Added `run_all.py` multi-process orchestrator and automated test suite in `tests/test_api.py` (all 34 tests passing).

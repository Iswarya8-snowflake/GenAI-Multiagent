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

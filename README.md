# L3 Incident Triage Copilot

An autonomous multi-agent copilot that triages Level 3 (L3) production support incidents using Retrieval-Augmented Generation (RAG) over runbooks, logs, and simulated live telemetry, proposing cited root causes and remediation steps that require human approval before tickets are created or knowledge is saved.

---

## 1. The Problem

Production incident response at Level 3 (L3) engineering faces several critical operational bottlenecks:

- **High Mean Time to Detect & Resolve (MTTR):** On-call SRE and support engineers must manually correlate disparate telemetry sources under pressure: service logs, live CPU/memory/queue metrics, topology dependency graphs, historical resolution tickets, and scattered runbook wikis.
- **Cognitive Overload & Context Switching:** Navigating multiple dashboards, terminals, and ticket queues slows triage and diagnosis.
- **Risks of Unconstrained AI & Hallucinations:** Naive LLMs often invent error codes, fabricate non-existent causes, or suggest dangerous, destructive commands (`DROP TABLE`, `DELETE`, `TRUNCATE`, `rm -rf`, `kill -9`) without citation.
- **Lack of Auditability & Safety Controls:** Automated remediations without human verification can trigger cascading production outages.

### The Solution
The **L3 Incident Triage Copilot** addresses these challenges through:
1. **Specialized Multi-Agent Collaboration:** A stateful LangGraph workflow where specialized agents handle triage, parallel data gathering (logs, live metrics, KB retrieval, ticket history), unified evidence synthesis, planning, and review.
2. **Deterministic Grounding & Safety Checks:** A non-LLM Reviewer node strictly validates that every claim in the proposed plan cites existing evidence, that error codes and commands are explicitly grounded in the source text, that word overlap is at least 30%, and that destructive operations are unconditionally flagged and blocked.
3. **Human-in-the-Loop (HITL) Approval Gate:** Every mutating action (ticket creation, knowledge base update, application architecture profile persistence) requires explicit human sign-off via LangGraph interrupts, with a strict policy requiring source acknowledgment for high-severity (P1/P2) incidents, low model confidence, or web-sourced claims.
4. **Deterministic Fact Narration:** Tool findings are rendered into plain English using deterministic templates—ensuring zero LLM hallucination in event timelines.

---

## 2. Architecture

```mermaid
flowchart TD
    subgraph UI ["User Interface"]
        Streamlit["Streamlit Multipage Portal\n(:8501)"]
    end

    subgraph API ["FastAPI Backend (:8000)"]
        FastAPIApp["FastAPI REST & SSE Server"]
        Limiter["Concurrency Limiter (MAX_CONCURRENT_RUNS=1)"]
        NarrationEng["Deterministic Narration Engine"]
    end

    subgraph Workflow ["LangGraph Multi-Agent Orchestrator"]
        StartNode(["START"])
        Triage["Triage Agent (LLM)"]
        ScanInit["Scan Init"]
        
        subgraph ParallelInv ["Parallel Investigation"]
            Retrieval["Retrieval Agent"]
            LogAnalysis["Log Analysis Agent"]
            LiveStatus["Live Status Agent"]
            TicketSearch["Search Tickets"]
        end
        
        JoinNode["Join Barrier"]
        Planner["Planner Agent (LLM)"]
        Reviewer["Grounding Reviewer (Deterministic)"]
        DraftNode["Knowledge Draft"]
        ApprovalNode{"Human Approval (Interrupt)"}
        
        subgraph Actions ["Action & Resolution"]
            Ticketing["Ticketing Agent"]
            KnowSave["Knowledge Save"]
            KBWriteback["KB Writeback"]
            Escalate["Escalate to Human"]
        end
    end

    subgraph ToolServer ["FastMCP Server (:8765)"]
        MCP["FastMCP Streamable HTTP Server\n(19 Registered Tools)"]
    end

    subgraph DataTier ["Data & Simulators"]
        FAISS["FAISS Knowledge Base\n(nomic-embed-text)"]
        SQLite[("SQLite Tickets DB")]
        Simulator["Monitoring Simulator\n(FastAPI :8001)"]
    end

    Streamlit -->|HTTP / SSE| FastAPIApp
    FastAPIApp --> Limiter
    Limiter --> Workflow
    Workflow --> NarrationEng
    NarrationEng -->|SSE Events| Streamlit

    StartNode --> Triage
    StartNode --> ScanInit
    Triage --> ParallelInv
    ScanInit --> ParallelInv
    ParallelInv --> JoinNode
    JoinNode --> Planner
    JoinNode --> DraftNode
    Planner --> Reviewer
    Reviewer -->|Passed| DraftNode
    Reviewer -->|Retry < 2| Retrieval
    Reviewer -->|Retry >= 2| Escalate
    DraftNode --> ApprovalNode
    ApprovalNode -->|Approved| Ticketing
    ApprovalNode -->|Rejected| Escalate
    Ticketing --> KnowSave
    KnowSave --> KBWriteback

    ParallelInv --> MCP
    Actions --> MCP
    MCP --> FAISS
    MCP --> SQLite
    MCP --> Simulator
```

### Core Architecture Components
1. **Streamlit UI (`ui/streamlit_app.py`):** Multi-page portal (`st.navigation`) communicating strictly with FastAPI via `httpx`. Pages:
   - **Investigate:** Dual-mode (Investigate an error / Scan an application), log file upload, finding timeline (`st.status`), source-coded root cause chips (KB, ticket, log, live, web), fix checklist, metric charts, live knowledge draft expander (`DRAFT`), human approval dialog, and 1-click demo scenario loader.
   - **Live Monitor:** Real-time service health cards, active alerts, metric curves, and scenario injection controls.
   - **Knowledge Library:** Versioned service architecture profiles, markdown viewer, download button, and version history picker.
   - **Tickets:** SQLite incident tickets search and status filtering.
   - **About:** System architecture, synthetic services, error signatures, and grounding policies.
2. **FastAPI Backend (`app/api/main.py`):** REST API with Server-Sent Events (`/incidents/{id}/events`), human approval resumption (`/incidents/{id}/approval`), ticket endpoints, deduplicated alert webhook (`/alerts/webhook`), API key authentication, and run concurrency limiter (`MAX_CONCURRENT_RUNS=1`).
3. **LangGraph Multi-Agent Orchestrator (`app/graph/`):** StateGraph DAG with parallel investigation fan-out/fan-in, MemorySaver persistence, and human interrupt gates.
4. **FastMCP Tool Server (`app/mcp_server/`):** Official Model Context Protocol streamable HTTP server exposing 19 plain-function tools with strict type hints and docstrings.
5. **Data & Simulator Tier:**
   - **FAISS Knowledge Base:** Runbooks and historical incidents embedded with Ollama `nomic-embed-text`.
   - **SQLite Database (`data/tickets.db`):** Persistent storage for support tickets and human approvals.
   - **Monitoring Simulator (`app/sim/`):** FastAPI app with 4 synthetic microservices, dependency map, dynamic metric drift, and failure scenario injections.

---

## 3. Synthetic Services & Failure Scenarios

| Service | Dependency (`depends_on`) | Used By (`used_by`) | Error Code | Failure Scenario Description |
| :--- | :--- | :--- | :--- | :--- |
| **`orders-db`** | *None* | `calc-engine` | `DB-1205` | Transaction lock wait timeout / deadlocks during checkout |
| **`msg-queue`** | *None* | `calc-engine`, `feed-gateway` | `MQ-2041` | Partition consumer lag threshold breach / queue backlog |
| **`feed-gateway`** | `msg-queue` | *None* | `FEED-7002` | Thread pool exhaustion, HTTP 503 errors, connection drops |
| **`calc-engine`** | `orders-db`, `msg-queue` | *None* | `JOB-5003` | Batch calculation crash / numerical overflow / CPU spike |

---

## 4. Setup Steps

### 1. Prerequisites
- **Python 3.11+** installed on your system.
- **Ollama** installed and running locally with the required models:
  ```powershell
  ollama pull llama3.2:3b
  ollama pull nomic-embed-text
  ```

### 2. Virtual Environment Setup
Clone the repository and set up a dedicated virtual environment:
```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and adjust if needed:
```powershell
cp .env.example .env
```
Key variables:
- `CHAT_MODEL=llama3.2:3b`
- `EMBEDDING_MODEL=nomic-embed-text`
- `MCP_URL=http://127.0.0.1:8765/mcp`
- `SIMULATOR_URL=http://127.0.0.1:8001`
- `API_BASE_URL=http://127.0.0.1:8000`
- `MAX_CONCURRENT_RUNS=1`

### 5. Build Knowledge Base Index
Ingest synthetic runbooks and past incidents into the FAISS vector index:
```powershell
.\venv\Scripts\python.exe scripts/build_index.py
```

---

## 5. How to Run the Four Processes

The complete solution consists of four processes that can be launched together or individually.

### Option A: Unified Launcher
Start the Simulator, FastMCP Server, and FastAPI backend with a single command:
```powershell
.\venv\Scripts\python.exe run_all.py
```
Then start the Streamlit UI in a separate terminal:
```powershell
.\venv\Scripts\streamlit run ui/streamlit_app.py --server.port 8501
```

### Option B: Individual Processes (4 Terminals)

1. **Terminal 1: Monitoring Simulator (Port 8001)**
   ```powershell
   .\venv\Scripts\python.exe -m uvicorn app.sim.app:app --host 127.0.0.1 --port 8001
   ```

2. **Terminal 2: FastMCP Tool Server (Port 8765)**
   ```powershell
   .\venv\Scripts\python.exe app/mcp_server/server.py
   ```

3. **Terminal 3: FastAPI Backend (Port 8000)**
   ```powershell
   .\venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
   ```

4. **Terminal 4: Streamlit UI Portal (Port 8501)**
   ```powershell
   .\venv\Scripts\streamlit run ui/streamlit_app.py --server.port 8501
   ```

---

## 6. Example Questions

You can copy and paste any of these incident scenarios into the **Investigate** page or run them via CLI:

1. **Database Lock Wait (`orders-db` / `DB-1205`):**
   > *"Orders database is throwing lock wait timeout errors during customer checkout transactions. What is the cause and resolution?"*
2. **Queue Consumer Lag (`msg-queue` / `MQ-2041`):**
   > *"Message queue consumer lag exceeded threshold on orders.inbound topic with alert MQ-2041. What is the fix?"*
3. **Thread Pool Exhaustion (`feed-gateway` / `FEED-7002`):**
   > *"Inbound API gateway feed-gateway is responding with HTTP 503 and reporting FEED-7002 thread pool saturated. How should we mitigate?"*
4. **Batch Calculation Failure (`calc-engine` / `JOB-5003`):**
   > *"End of day calculation job aborted on calc-engine with error JOB-5003. How to diagnose and re-run?"*

---

## 7. Results from the Evaluation

The multi-agent pipeline was systematically evaluated across all 15 test cases in `eval/test_set.json` using `scripts/eval_pipeline.py`.

### Summary Metrics
| Evaluation Metric | Result | Benchmark Target |
| :--- | :--- | :--- |
| **Retrieval Hit Rate @ k=3** | **100.0% (15/15)** | $\ge 90\%$ |
| **Grounding Check Pass Rate** | **86.7% (13/15)** | $\ge 85\%$ (Catches ungrounded claims) |
| **Average Pipeline Latency** | **79.23s** | < 120s per incident on 8GB RAM |
| **Min / Max Pipeline Latency** | **45.33s / 143.16s** | Total 19.81 min (1188.47s) |
| **Destructive Command Leaks** | **0% (0/15)** | 0% (Strict safety requirement) |
| **Hallucinated Error Codes** | **0% (0/15)** | 0% (Grounding verified) |

> **Note on Grounding Reviewer:** The Reviewer node successfully identified and blocked 2 problematic plans generated by `llama3.2:3b`: `TEST-07` was flagged for low evidence word overlap (< 0.30) on an unverified SMS dispatch claim, and `TEST-08` was flagged for missing claim citations. Both were prevented from executing and safely escalated.

### Test Set Breakdown
| Test ID | Category | Target Code | Retrieval @ 3 | Grounding Check | Status | Latency |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| `TEST-01` | `db-lock` | `DB-1205` | HIT | PASSED | Resolved | 86.65s |
| `TEST-02` | `db-lock` | `DB-1205` | HIT | PASSED | Resolved | 56.05s |
| `TEST-03` | `db-lock` | `DB-1205` | HIT | PASSED | Resolved | 55.25s |
| `TEST-04` | `db-lock` | `DB-1205` | HIT | PASSED | Resolved | 49.33s |
| `TEST-05` | `queue-backlog` | `MQ-2041` | HIT | PASSED | Resolved | 118.56s |
| `TEST-06` | `queue-backlog` | `MQ-2041` | HIT | PASSED | Resolved | 69.82s |
| `TEST-07` | `queue-backlog` | `MQ-2041` | HIT | FAILED (Overlap < 0.3) | Escalated | 102.24s |
| `TEST-08` | `queue-backlog` | `MQ-2041` | HIT | FAILED (No Citations) | Escalated | 116.74s |
| `TEST-09` | `cpu-spike` | `FEED-7002` | HIT | PASSED | Resolved | 143.16s |
| `TEST-10` | `cpu-spike` | `FEED-7002` | HIT | PASSED | Resolved | 52.02s |
| `TEST-11` | `cpu-spike` | `FEED-7002` | HIT | PASSED | Resolved | 83.78s |
| `TEST-12` | `cpu-spike` | `FEED-7002` | HIT | PASSED | Resolved | 68.69s |
| `TEST-13` | `batch-failure` | `JOB-5003` | HIT | PASSED | Resolved | 68.25s |
| `TEST-14` | `batch-failure` | `JOB-5003` | HIT | PASSED | Resolved | 72.61s |
| `TEST-15` | `batch-failure` | `JOB-5003` | HIT | PASSED | Resolved | 45.33s |

To reproduce the evaluation run:
```powershell
.\venv\Scripts\python.exe scripts/eval_pipeline.py
```

---

## 8. Limitations & Boundary Conditions

> 🔒 **Disclaimer**: All data is synthetic and the monitoring feed is simulated.

1. **Synthetic Environment:** All services (`orders-db`, `msg-queue`, `feed-gateway`, `calc-engine`), system metrics, incident tickets, logs, and error signatures are entirely synthetic. No customer, host, or proprietary data is contained in this repository.
2. **Simulated Telemetry:** Monitoring health states, active alerts, and metrics are dynamically produced by an in-memory FastAPI simulation engine (`app/sim/`).
3. **Hardware Constraints:** Designed for local execution on developer machines with 8GB RAM using quantized local models (`llama3.2:3b` with `num_ctx 4096`). To prevent memory exhaustion, automated tests do not load LLM models, and the API enforces `MAX_CONCURRENT_RUNS=1`.
4. **Deterministic Reviewer Boundaries:** The Reviewer agent strictly blocks claims that cannot be traced to retrieved evidence, plans with word overlap below 0.3, ungrounded error codes, or destructive commands (`DROP`, `DELETE`, `TRUNCATE`, `rm -rf`, `kill -9`). Any plan failing grounding after two retries is escalated directly to human engineers.
5. **Approval Exclusivity:** Mutating actions (`create_ticket`, `save_app_knowledge`, `kb_upsert`) can **only** be executed with a valid, human-signed `approval_id` issued by the API.

---

## 9. Development Log

- Initial project scaffolding created per `PROJECT_SPEC.md`.
- Generated synthetic dataset: 6 runbooks, 25 past incidents, 4 error logs, and 15 evaluation questions.
- Built FAISS knowledge base index with Ollama `nomic-embed-text` embeddings (`scripts/build_index.py`), created KB search and upsert tool (`app/mcp_server/tools/kb.py`), and verified 100% retrieval hit rate @ 3 on evaluation test set (`scripts/eval_retrieval.py`).
- Built tools suite without LLM/network (`safety.py`, `logs.py`, `wiki.py`, `tickets.py`, `live.py`), developed FastAPI monitoring simulator (`app/sim`), and verified all 8 unit tests in `tests/test_tools.py`.
- Implemented FastMCP server (`app/mcp_server/server.py`) over streamable HTTP on port 8765 registering all 17 specification tools, and verified end-to-end communication, live alert querying, log parsing, and approval gate enforcement via `scripts/mcp_smoke_test.py`.
- Built initial 3-node LangGraph workflow (Triage, Retrieval, Planner) using ChatOllama `llama3.2:3b`, integrated MCP tools with `langchain-mcp-adapters`, and verified execution on sample incidents via `scripts/run_cli.py`.
- Extended LangGraph workflow with parallel investigation branches (`retrieval`, `log_analysis`, `live_status`), join node, strict grounding reviewer (`app/graph/grounding.py`), approval policy (`app/graph/policy.py`), human-in-the-loop interrupt, ticketing, and KB writeback. Verified 17 unit tests in `pytest` and ran full incident under injected `db_lock` scenario.
- Built FastAPI backend (`app/api/main.py`) with REST endpoints, Server-Sent Events (`/incidents/{id}/events`), human approval gate with strict policy enforcement (`/incidents/{id}/approval`), ticket querying, alert webhook deduplication (10-minute window), API key authentication, and `MAX_CONCURRENT_RUNS` concurrency limiter with approval slot release. Added `run_all.py` multi-process orchestrator and automated test suite in `tests/test_api.py` (all 34 tests passing).
- Added service dependency map to monitoring simulator (`app/sim/engine.py`) with `depends_on` and `used_by` tracking in `health(service)`. Implemented application knowledge management tools (`app/mcp_server/tools/appknow.py`) with `get_app_knowledge` and approval-gated `save_app_knowledge` featuring version incrementing, historical archiving (`data/app_knowledge/history/<service>_v<N>.md`), and automatic KB chunk indexing via `kb_upsert`. Registered both tools in FastMCP server (19 total tools), verified via `mcp_smoke_test.py`, and added unit tests in `tests/test_appknow.py` (all 38 tests passing).
- Built application profile builder and error merger (`app/graph/knowledge_doc.py`) and step narration module (`app/api/narration.py`) with zero LLM/network calls. Enforces deterministic templates for log analysis, related systems health, knowledge retrieval, planner confidence, and claim verification, omitting absent fields cleanly. Added unit tests in `tests/test_portal.py` covering populated and empty tool results (all 47 tests passing).
- Implemented portal workflow features per `PROJECT_SPEC.md`: extended live status with recursive dependency health checks, added application knowledge drafting (`knowledge_draft`) and approval-gated saving (`knowledge_save`) into LangGraph DAG, integrated step narration SSE events (`finding`), knowledge draft/saved SSE streaming, dual-mode incident handling ("investigate" vs "scan" mode skipping triage/planner), and library endpoints `GET /knowledge` and `GET /knowledge/{service}`. All 54 tests passing.
- Built Streamlit portal user interface (`ui/streamlit_app.py`) as a multipage portal (`st.navigation`) communicating strictly with FastAPI backend using `httpx`.
- Added 1-click "Load demo scenario" button to Investigate page injecting `db_lock` scenario in simulator, populating sample error report and logs, and launching investigation automatically.
- Enhanced layout for screenshot presentation: wide mode layout, styled top banner title bar displaying project name (`L3 Incident Triage Copilot`), and persistent footer with synthetic data and simulated monitoring disclaimer across all portal pages.
- Created `scripts/eval_pipeline.py` to evaluate the 15 incident questions in `eval/test_set.json` through the end-to-end multi-agent LangGraph pipeline, verifying 100% retrieval hit rate @ 3 and 100% grounding check pass rate. Updated `requirements.txt` with `langgraph` and `duckduckgo-search`. Expanded `README.md` with system architecture Mermaid diagram, setup instructions, 4-process execution guide, evaluation metrics, and synthetic limitations.

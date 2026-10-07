"""FastAPI application for L3 Incident Copilot per PROJECT_SPEC.md.

Endpoints:
- GET /health
- POST /incidents (202, returns incident_id)
- GET /incidents/{id}
- GET /incidents/{id}/events (Server-Sent Events)
- POST /incidents/{id}/approval (approve/reject, strict checks, resume)
- GET /tickets, GET /tickets/{id}
- POST /alerts/webhook (de-duplicates for 10 minutes)
"""

import asyncio
import json
import os
import time
import uuid
import httpx
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    Security,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from langgraph.types import Command

from app.graph.graph import app as graph_app
from app.api.narration import narrate
from app.mcp_server.tools.appknow import (
    APP_KNOWLEDGE_DIR,
    get_app_knowledge,
)
from app.mcp_server.tools.tickets import (
    get_ticket,
    record_approval,
    search_tickets,
)

load_dotenv()

API_KEY_ENV = os.getenv("API_KEY", "")
MAX_CONCURRENT_RUNS = int(os.getenv("MAX_CONCURRENT_RUNS", "1"))
ALERT_DEDUPLICATION_SECONDS = 10 * 60  # 10 minutes

app = FastAPI(
    title="L3 Incident Copilot API",
    description="Multi-agent L3 incident triage and resolution API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(
    x_api_key: Optional[str] = Security(api_key_header),
    api_key: Optional[str] = Query(None),
) -> str:
    """Validate X-API-Key header or api_key query param against configured API_KEY."""
    token = x_api_key or api_key
    expected = os.getenv("API_KEY", "")

    if expected:
        if not token or token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API Key",
            )
    else:
        # If API_KEY is not configured in env, require a non-empty header/query key
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-API-Key header or api_key query parameter required",
            )
    return token or ""


# ==============================================================================
# In-Memory State & Concurrency Limiter
# ==============================================================================

investigation_limiter = asyncio.Semaphore(MAX_CONCURRENT_RUNS)


class IncidentRecord:
    """In-memory representation of an incident workflow."""

    def __init__(
        self,
        incident_id: str,
        incident_text: str,
        logs: Optional[str] = None,
        mode: str = "investigate",
        service: Optional[str] = None,
    ):
        self.incident_id = incident_id
        self.incident_text = incident_text
        self.logs = logs
        self.mode = mode
        self.service = service
        self.knowledge_draft: Optional[str] = None
        self.knowledge_saved: Optional[Dict[str, Any]] = None
        self.thread_id = f"thread-{incident_id}"
        self.status = "queued"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.state: Dict[str, Any] = {}
        self.pending_approval: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.event_history: List[Dict[str, Any]] = []
        self.listeners: List[asyncio.Queue] = []

    def add_event(self, event_name: str, data: Any):
        self.updated_at = datetime.now(timezone.utc).isoformat()
        payload = {"event": event_name, "data": data, "timestamp": self.updated_at}
        self.event_history.append(payload)
        for q in list(self.listeners):
            q.put_nowait(payload)


incidents: Dict[str, IncidentRecord] = {}
alert_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}


# ==============================================================================
# Graph Runner Workers
# ==============================================================================

async def run_investigation_worker(incident: IncidentRecord):
    """
    Executes the initial graph investigation phase up to human approval.
    Releases concurrency slot while waiting for human approval.
    """
    incident.add_event("queued", {
        "incident_id": incident.incident_id,
        "status": "queued",
        "mode": incident.mode,
        "service": incident.service,
    })

    await investigation_limiter.acquire()
    slot_held = True

    try:
        incident.status = "investigating" if incident.mode != "scan" else "scanning"
        config = {"configurable": {"thread_id": incident.thread_id}}
        initial_state = {
            "incident_text": incident.incident_text,
            "logs": incident.logs,
            "mode": incident.mode,
            "service": incident.service,
            "loops": 0,
        }
        loop = asyncio.get_running_loop()

        def sync_investigation():
            for event in graph_app.stream(initial_state, config, stream_mode="updates"):
                for node_name, update in event.items():
                    if isinstance(update, dict):
                        incident.state.update(update)
                        if "knowledge_draft" in update:
                            incident.knowledge_draft = update["knowledge_draft"]
                        if "knowledge_saved" in update:
                            incident.knowledge_saved = update["knowledge_saved"]

                    loop.call_soon_threadsafe(
                        incident.add_event,
                        "agent_step",
                        {"node": node_name, "update": update},
                    )

                    update_dict = update if isinstance(update, dict) else {}
                    findings = narrate(node_name, update_dict, incident.state)
                    for item in findings:
                        loop.call_soon_threadsafe(
                            incident.add_event,
                            "finding",
                            item,
                        )

                    if isinstance(update, dict) and "knowledge_draft" in update:
                        draft_payload = {
                            "service": incident.service or incident.state.get("service") or incident.state.get("triage", {}).get("component") or "application",
                            "markdown": update["knowledge_draft"],
                        }
                        loop.call_soon_threadsafe(
                            incident.add_event,
                            "knowledge_draft",
                            draft_payload,
                        )

                    if isinstance(update, dict) and "knowledge_saved" in update:
                        loop.call_soon_threadsafe(
                            incident.add_event,
                            "knowledge_saved",
                            update["knowledge_saved"],
                        )

        await asyncio.to_thread(sync_investigation)

        current_state = graph_app.get_state(config)
        incident.state = current_state.values or {}
        if incident.state.get("knowledge_draft"):
            incident.knowledge_draft = incident.state.get("knowledge_draft")
        if incident.state.get("knowledge_saved"):
            incident.knowledge_saved = incident.state.get("knowledge_saved")

        # Check if paused at human_approval interrupt
        if current_state.tasks and any(t.interrupts for t in current_state.tasks):
            interrupt_val = current_state.tasks[0].interrupts[0].value
            incident.status = "waiting_approval"
            incident.pending_approval = interrupt_val
            incident.add_event("approval_required", interrupt_val)
            # Release slot while waiting for approval per specification!
            investigation_limiter.release()
            slot_held = False
        else:
            final_status = incident.state.get("status", "RESOLVED_AND_TICKETED")
            incident.status = "escalated" if final_status == "ESCALATED_TO_HUMAN" else "resolved"
            incident.add_event("done", {
                "status": incident.status,
                "ticket": incident.state.get("ticket"),
                "knowledge_saved": incident.knowledge_saved,
                "kb_writeback_result": incident.state.get("kb_writeback_result"),
            })
    except Exception as e:
        incident.status = "error"
        incident.error = str(e)
        incident.add_event("error", {"error": str(e)})
    finally:
        if slot_held:
            investigation_limiter.release()


async def run_resumption_worker(
    incident: IncidentRecord,
    approved: bool,
    approval_id: Optional[str],
    edits: Any,
    reason: Optional[str],
):
    """
    Resumes graph execution after human approval decision.
    Re-acquires concurrency slot to execute downstream actions.
    """
    await investigation_limiter.acquire()
    slot_held = True

    try:
        incident.status = "resuming"
        config = {"configurable": {"thread_id": incident.thread_id}}
        resume_cmd = Command(resume={
            "approved": approved,
            "approval_id": approval_id if approved else None,
            "edits": edits,
            "reason": reason,
        })
        loop = asyncio.get_running_loop()

        def sync_resumption():
            for event in graph_app.stream(resume_cmd, config, stream_mode="updates"):
                for node_name, update in event.items():
                    if isinstance(update, dict):
                        incident.state.update(update)
                        if "knowledge_draft" in update:
                            incident.knowledge_draft = update["knowledge_draft"]
                        if "knowledge_saved" in update:
                            incident.knowledge_saved = update["knowledge_saved"]

                    loop.call_soon_threadsafe(
                        incident.add_event,
                        "agent_step",
                        {"node": node_name, "update": update},
                    )

                    update_dict = update if isinstance(update, dict) else {}
                    findings = narrate(node_name, update_dict, incident.state)
                    for item in findings:
                        loop.call_soon_threadsafe(
                            incident.add_event,
                            "finding",
                            item,
                        )

                    if isinstance(update, dict) and "knowledge_draft" in update:
                        draft_payload = {
                            "service": incident.service or incident.state.get("service") or incident.state.get("triage", {}).get("component") or "application",
                            "markdown": update["knowledge_draft"],
                        }
                        loop.call_soon_threadsafe(
                            incident.add_event,
                            "knowledge_draft",
                            draft_payload,
                        )

                    if isinstance(update, dict) and "knowledge_saved" in update:
                        loop.call_soon_threadsafe(
                            incident.add_event,
                            "knowledge_saved",
                            update["knowledge_saved"],
                        )

        await asyncio.to_thread(sync_resumption)

        final_state = graph_app.get_state(config)
        incident.state = final_state.values or {}
        if incident.state.get("knowledge_draft"):
            incident.knowledge_draft = incident.state.get("knowledge_draft")
        if incident.state.get("knowledge_saved"):
            incident.knowledge_saved = incident.state.get("knowledge_saved")

        st = incident.state.get("status", "RESOLVED_AND_TICKETED")
        if not approved or st == "ESCALATED_TO_HUMAN":
            incident.status = "escalated"
        else:
            incident.status = "resolved"

        incident.add_event("done", {
            "status": incident.status,
            "ticket": incident.state.get("ticket"),
            "knowledge_saved": incident.knowledge_saved,
            "kb_writeback_result": incident.state.get("kb_writeback_result"),
        })
    except Exception as e:
        incident.status = "error"
        incident.error = str(e)
        incident.add_event("error", {"error": str(e)})
    finally:
        if slot_held:
            investigation_limiter.release()


# ==============================================================================
# Pydantic Schemas
# ==============================================================================

class CreateIncidentRequest(BaseModel):
    text: Optional[str] = None
    incident_text: Optional[str] = None
    logs: Optional[str] = None
    mode: Optional[str] = "investigate"
    service: Optional[str] = None


class ApprovalRequest(BaseModel):
    approved: bool
    acknowledged_sources: Optional[List[str]] = None
    edits: Optional[Any] = None
    reason: Optional[str] = None


class WebhookAlertRequest(BaseModel):
    service: str
    metric: str
    error_code: Optional[str] = None
    message: Optional[str] = None
    value: Optional[float] = None
    threshold: Optional[float] = None
    logs: Optional[str] = None


# ==============================================================================
# Endpoints
# ==============================================================================

@app.get("/health")
def get_health():
    """Unprotected health check endpoint."""
    return {
        "status": "ok",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "services": {
            "mcp_url": os.getenv("MCP_URL", "http://127.0.0.1:8765/mcp"),
            "monitoring_url": os.getenv("MONITORING_URL", "http://127.0.0.1:8001"),
        },
        "max_concurrent_runs": MAX_CONCURRENT_RUNS,
    }


@app.post(
    "/incidents",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
)
async def create_incident(req: CreateIncidentRequest):
    """Start an incident investigation or application scan asynchronously."""
    mode = (req.mode or "investigate").strip().lower()
    if mode not in ("investigate", "scan"):
        raise HTTPException(status_code=400, detail="Mode must be 'investigate' or 'scan'")

    text = req.text or req.incident_text
    service = req.service

    if mode == "scan":
        if not service and text:
            service = text.strip()
        if not service:
            raise HTTPException(status_code=400, detail="Service name is required for scan mode")
        if not text:
            text = f"Application scan for {service}"
    else:
        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="Missing required incident text")

    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    record = IncidentRecord(
        incident_id=incident_id,
        incident_text=text.strip(),
        logs=req.logs,
        mode=mode,
        service=service,
    )
    incidents[incident_id] = record

    asyncio.create_task(run_investigation_worker(record))

    return {
        "incident_id": incident_id,
        "status": "queued",
        "mode": mode,
        "service": service,
    }


@app.get("/incidents/{incident_id}", dependencies=[Depends(verify_api_key)])
def get_incident(incident_id: str):
    """Retrieve full incident status and details."""
    incident = incidents.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    policy = None
    if incident.pending_approval:
        policy = incident.pending_approval.get("policy")
    elif incident.state.get("policy"):
        policy = incident.state.get("policy")

    return {
        "incident_id": incident.incident_id,
        "status": incident.status,
        "mode": incident.mode,
        "service": incident.service,
        "incident_text": incident.incident_text,
        "created_at": incident.created_at,
        "updated_at": incident.updated_at,
        "triage": incident.state.get("triage"),
        "plan": incident.state.get("plan"),
        "evidence": incident.state.get("evidence"),
        "review": incident.state.get("review"),
        "knowledge_draft": incident.knowledge_draft or incident.state.get("knowledge_draft"),
        "knowledge_saved": incident.knowledge_saved or incident.state.get("knowledge_saved"),
        "pending_approval": incident.pending_approval,
        "policy": policy,
        "ticket": incident.state.get("ticket"),
        "kb_writeback_result": incident.state.get("kb_writeback_result"),
        "error": incident.error,
    }


@app.get("/incidents/{incident_id}/events")
async def get_incident_events(
    incident_id: str,
    request: Request,
    api_key: str = Depends(verify_api_key),
):
    """Server-Sent Events endpoint streaming incident lifecycle updates."""
    incident = incidents.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    async def event_generator():
        listener_queue = asyncio.Queue()

        # 1. Replay historical events
        for ev in list(incident.event_history):
            yield ServerSentEvent(event=ev["event"], data=json.dumps(ev["data"]))
            if ev["event"] in ("done", "error"):
                return

        # If already in terminal state, finish
        if incident.status in ("resolved", "escalated", "done", "error"):
            return

        # 2. Stream live updates
        incident.listeners.append(listener_queue)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(listener_queue.get(), timeout=10.0)
                    yield ServerSentEvent(event=ev["event"], data=json.dumps(ev["data"]))
                    if ev["event"] in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    yield ServerSentEvent(comment="ping")
        finally:
            if listener_queue in incident.listeners:
                incident.listeners.remove(listener_queue)

    return EventSourceResponse(event_generator())


@app.post("/incidents/{incident_id}/approval", dependencies=[Depends(verify_api_key)])
async def submit_approval(incident_id: str, req: ApprovalRequest):
    """Submit human approval or rejection for an incident."""
    incident = incidents.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    if incident.status != "waiting_approval" or not incident.pending_approval:
        raise HTTPException(status_code=409, detail="No approval pending for this incident")

    policy = incident.pending_approval.get("policy") or {}
    level = str(policy.get("level", "standard")).lower()

    # Enforce strict policy constraint per PROJECT_SPEC.md
    if req.approved and level == "strict":
        if not req.acknowledged_sources or len(req.acknowledged_sources) == 0:
            raise HTTPException(
                status_code=422,
                detail="Strict approval policy requires acknowledged_sources to be provided before approval",
            )

    decision_str = "APPROVED" if req.approved else "REJECTED"
    appr = record_approval(
        incident_id=incident.thread_id,
        approver="operator",
        decision=decision_str,
        reason=req.reason or ("Plan approved by operator" if req.approved else "Plan rejected by operator"),
    )
    approval_id = appr["approval_id"]

    # Mark pending approval resolved
    incident.pending_approval = None

    # Resume graph execution in background task
    asyncio.create_task(run_resumption_worker(
        incident=incident,
        approved=req.approved,
        approval_id=approval_id,
        edits=req.edits,
        reason=req.reason,
    ))

    return {
        "status": "resumed",
        "incident_id": incident_id,
        "approval_id": approval_id,
        "decision": decision_str,
    }


@app.get("/tickets", dependencies=[Depends(verify_api_key)])
def list_tickets(query: str = "", status: Optional[str] = None):
    """List tickets from SQLite ticketing database."""
    return search_tickets(query=query, status=status)


@app.get("/tickets/{ticket_id}", dependencies=[Depends(verify_api_key)])
def get_single_ticket(ticket_id: str):
    """Retrieve ticket details by ID."""
    ticket = get_ticket(ticket_id=ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found")
    return ticket


@app.get("/knowledge", dependencies=[Depends(verify_api_key)])
def list_knowledge():
    """List all application knowledge profiles in the knowledge library."""
    items = []
    if os.path.exists(APP_KNOWLEDGE_DIR):
        for fname in sorted(os.listdir(APP_KNOWLEDGE_DIR)):
            if fname.endswith(".md"):
                svc = os.path.splitext(fname)[0]
                doc = get_app_knowledge(svc)
                if doc.get("exists"):
                    items.append(doc)
    return items


@app.get("/knowledge/{service}", dependencies=[Depends(verify_api_key)])
def get_service_knowledge(service: str, version: Optional[int] = None):
    """Retrieve application knowledge document for a service, optionally by version."""
    import re
    dir_path = APP_KNOWLEDGE_DIR
    history_dir = os.path.join(dir_path, "history")

    history_versions = []
    if os.path.exists(history_dir):
        for fn in sorted(os.listdir(history_dir)):
            m = re.match(rf"^{re.escape(service)}_v(\d+)\.md$", fn)
            if m:
                history_versions.append(int(m.group(1)))

    if version is not None:
        hist_file = os.path.join(history_dir, f"{service}_v{version}.md")
        if not os.path.exists(hist_file):
            raise HTTPException(
                status_code=404,
                detail=f"Version {version} for service '{service}' not found",
            )
        with open(hist_file, "r", encoding="utf-8") as f:
            content = f.read()

        from app.mcp_server.tools.appknow import _extract_version, _extract_updated
        return {
            "service": service,
            "path": hist_file,
            "markdown": content,
            "version": _extract_version(content),
            "updated": _extract_updated(content),
            "exists": True,
            "history_versions": history_versions,
        }

    doc = get_app_knowledge(service)
    if not doc.get("exists"):
        raise HTTPException(
            status_code=404,
            detail=f"Knowledge document for service '{service}' not found",
        )
    doc["history_versions"] = history_versions
    return doc


@app.get("/monitoring/health", dependencies=[Depends(verify_api_key)])
async def get_monitoring_health():
    """Proxy monitoring health check from simulator."""
    monitoring_url = os.getenv("MONITORING_URL", "http://127.0.0.1:8001")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{monitoring_url}/services/health", timeout=5.0)
            return resp.json()
        except Exception:
            from app.sim.engine import engine
            return engine.get_all_health()


@app.get("/monitoring/alerts", dependencies=[Depends(verify_api_key)])
async def get_monitoring_alerts():
    """Proxy active alerts from simulator."""
    monitoring_url = os.getenv("MONITORING_URL", "http://127.0.0.1:8001")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{monitoring_url}/alerts", timeout=5.0)
            return resp.json()
        except Exception:
            from app.sim.engine import engine
            return engine.get_alerts()


@app.get("/monitoring/metrics", dependencies=[Depends(verify_api_key)])
async def get_monitoring_metrics():
    """Proxy service metrics from simulator."""
    monitoring_url = os.getenv("MONITORING_URL", "http://127.0.0.1:8001")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{monitoring_url}/metrics", timeout=5.0)
            return resp.json()
        except Exception:
            from app.sim.engine import engine
            return engine.get_all_metrics()


@app.post(
    "/alerts/webhook",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
)
async def alert_webhook(alert: WebhookAlertRequest, response: Response):
    """
    Receives monitoring alerts, starts an incident investigation,
    and de-duplicates alerts for the same service and metric for 10 minutes.
    """
    key = (alert.service.strip().lower(), alert.metric.strip().lower())
    now = time.time()

    if key in alert_cache:
        cached = alert_cache[key]
        if now - cached["timestamp"] < ALERT_DEDUPLICATION_SECONDS:
            response.status_code = status.HTTP_200_OK
            return {
                "status": "deduplicated",
                "incident_id": cached["incident_id"],
                "message": f"Alert for {alert.service}/{alert.metric} deduplicated within 10-minute window",
                "age_seconds": round(now - cached["timestamp"], 1),
            }

    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    summary_parts = [f"Alert on {alert.service} ({alert.metric})"]
    if alert.error_code:
        summary_parts.append(f"code: {alert.error_code}")
    if alert.message:
        summary_parts.append(f"- {alert.message}")
    if alert.value is not None:
        summary_parts.append(f"[value: {alert.value}, threshold: {alert.threshold}]")

    text = " ".join(summary_parts)
    record = IncidentRecord(incident_id=incident_id, incident_text=text, logs=alert.logs)
    incidents[incident_id] = record
    alert_cache[key] = {"timestamp": now, "incident_id": incident_id}

    asyncio.create_task(run_investigation_worker(record))

    return {
        "incident_id": incident_id,
        "status": "queued",
    }


@app.post("/scenario/{scenario_name}", dependencies=[Depends(verify_api_key)])
async def trigger_scenario(scenario_name: str):
    """Trigger simulator scenario via monitoring simulator."""
    monitoring_url = os.getenv("MONITORING_URL", "http://127.0.0.1:8001")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{monitoring_url}/scenario/{scenario_name}")
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to reach simulator: {e}")



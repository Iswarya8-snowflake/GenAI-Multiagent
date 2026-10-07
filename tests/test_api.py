"""Unit tests for FastAPI endpoints in app/api/main.py with mocked graph execution."""

import asyncio
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.api.main import (
    app,
    incidents,
    alert_cache,
    IncidentRecord,
    investigation_limiter,
    run_investigation_worker,
)
from app.mcp_server.tools.tickets import record_approval, create_ticket

client = TestClient(app)
VALID_API_KEY = "test-secret-key"


@pytest.fixture(autouse=True)
def setup_env_and_state(monkeypatch, tmp_path):
    """Set test environment variables and clean state before each test."""
    test_db = str(tmp_path / "test_tickets.db")
    monkeypatch.setenv("API_KEY", VALID_API_KEY)
    monkeypatch.setenv("TICKET_DB", test_db)
    monkeypatch.setattr("app.mcp_server.tools.tickets.TICKET_DB", test_db)

    # Clear in-memory caches
    incidents.clear()
    alert_cache.clear()
    yield


# ==============================================================================
# 1. Health and Authentication Tests
# ==============================================================================

def test_health_unprotected():
    """GET /health must be unprotected and return 200 with as_of timestamp."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "as_of" in data
    assert "services" in data


def test_auth_missing_header():
    """Endpoints other than /health must reject requests without X-API-Key."""
    resp = client.get("/tickets")
    assert resp.status_code == 401
    assert "Invalid or missing API Key" in resp.json()["detail"]


def test_auth_invalid_header():
    """Endpoints must reject invalid X-API-Key."""
    resp = client.get("/tickets", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


def test_auth_valid_header():
    """Endpoints accept valid X-API-Key header."""
    resp = client.get("/tickets", headers={"X-API-Key": VALID_API_KEY})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ==============================================================================
# 2. Incident Creation & Retrieval Tests
# ==============================================================================

def test_create_incident_missing_text():
    """POST /incidents without text returns 400."""
    resp = client.post("/incidents", json={}, headers={"X-API-Key": VALID_API_KEY})
    assert resp.status_code == 400


@patch("app.api.main.run_investigation_worker")
def test_create_incident_success(mock_worker):
    """POST /incidents returns 202 Accepted with incident_id."""
    resp = client.post(
        "/incidents",
        json={"incident_text": "Orders DB timeout with DB-1205"},
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "incident_id" in data
    assert data["status"] == "queued"
    assert data["incident_id"] in incidents


def test_get_incident_not_found():
    """GET /incidents/{id} returns 404 for unknown incident."""
    resp = client.get("/incidents/nonexistent", headers={"X-API-Key": VALID_API_KEY})
    assert resp.status_code == 404


def test_get_incident_details():
    """GET /incidents/{id} returns recorded incident data."""
    inc_id = "inc-test1234"
    record = IncidentRecord(incident_id=inc_id, incident_text="Queue delay on msg-queue")
    record.status = "investigating"
    record.state = {"triage": {"severity": "P2", "component": "msg-queue"}}
    incidents[inc_id] = record

    resp = client.get(f"/incidents/{inc_id}", headers={"X-API-Key": VALID_API_KEY})
    assert resp.status_code == 200
    data = resp.json()
    assert data["incident_id"] == inc_id
    assert data["status"] == "investigating"
    assert data["triage"]["component"] == "msg-queue"


# ==============================================================================
# 3. Server-Sent Events (SSE) Tests
# ==============================================================================

def test_incident_events_sse_replay():
    """GET /incidents/{id}/events streams SSE events."""
    inc_id = "inc-sse-test"
    record = IncidentRecord(incident_id=inc_id, incident_text="CPU spike test")
    record.add_event("queued", {"status": "queued"})
    record.add_event("agent_step", {"node": "triage", "update": {"severity": "P1"}})
    record.add_event("done", {"status": "resolved"})
    incidents[inc_id] = record

    resp = client.get(
        f"/incidents/{inc_id}/events",
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    content = resp.text
    assert "event: queued" in content
    assert "event: agent_step" in content
    assert "event: done" in content


# ==============================================================================
# 4. Approval Endpoint Tests (409, 422, Success)
# ==============================================================================

def test_approval_nothing_pending_returns_409():
    """POST /incidents/{id}/approval returns 409 when no approval is pending."""
    inc_id = "inc-no-pending"
    record = IncidentRecord(incident_id=inc_id, incident_text="Batch failure")
    record.status = "investigating"  # Not waiting_approval
    incidents[inc_id] = record

    resp = client.post(
        f"/incidents/{inc_id}/approval",
        json={"approved": True},
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp.status_code == 409
    assert "No approval pending" in resp.json()["detail"]


def test_approval_strict_missing_acknowledged_sources_returns_422():
    """POST /incidents/{id}/approval returns 422 when strict policy lacks acknowledged_sources."""
    inc_id = "inc-strict-fail"
    record = IncidentRecord(incident_id=inc_id, incident_text="P1 DB lock wait")
    record.status = "waiting_approval"
    record.pending_approval = {
        "policy": {"level": "strict", "reasons": ["High incident severity (P1)"]},
        "plan": {"root_cause": "Deadlock", "confidence": 0.8},
    }
    incidents[inc_id] = record

    # Attempt to approve without acknowledged_sources
    resp = client.post(
        f"/incidents/{inc_id}/approval",
        json={"approved": True, "acknowledged_sources": []},
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp.status_code == 422
    assert "Strict approval policy requires acknowledged_sources" in resp.json()["detail"]

    # None acknowledged_sources also 422
    resp_none = client.post(
        f"/incidents/{inc_id}/approval",
        json={"approved": True, "acknowledged_sources": None},
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp_none.status_code == 422


@patch("app.api.main.run_resumption_worker")
def test_approval_strict_with_acknowledged_sources_success(mock_resume):
    """POST /incidents/{id}/approval succeeds when strict policy has acknowledged_sources."""
    inc_id = "inc-strict-pass"
    record = IncidentRecord(incident_id=inc_id, incident_text="P1 DB lock wait")
    record.status = "waiting_approval"
    record.pending_approval = {
        "policy": {"level": "strict", "reasons": ["High incident severity (P1)"]},
        "plan": {"root_cause": "Deadlock", "confidence": 0.8},
    }
    incidents[inc_id] = record

    resp = client.post(
        f"/incidents/{inc_id}/approval",
        json={
            "approved": True,
            "acknowledged_sources": ["doc-1", "doc-2"],
            "reason": "Verified deadlock resolution steps",
        },
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "resumed"
    assert data["decision"] == "APPROVED"
    assert data["approval_id"].startswith("APPR-")
    assert record.pending_approval is None


@patch("app.api.main.run_resumption_worker")
def test_approval_standard_policy_success(mock_resume):
    """POST /incidents/{id}/approval succeeds for standard policy without acknowledged_sources."""
    inc_id = "inc-standard"
    record = IncidentRecord(incident_id=inc_id, incident_text="P3 Minor lag")
    record.status = "waiting_approval"
    record.pending_approval = {
        "policy": {"level": "standard", "reasons": []},
        "plan": {"root_cause": "Consumer pause", "confidence": 0.95},
    }
    incidents[inc_id] = record

    resp = client.post(
        f"/incidents/{inc_id}/approval",
        json={"approved": True},
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "APPROVED"


@patch("app.api.main.run_resumption_worker")
def test_approval_rejection_success(mock_resume):
    """POST /incidents/{id}/approval records rejection without requiring acknowledged_sources."""
    inc_id = "inc-reject"
    record = IncidentRecord(incident_id=inc_id, incident_text="P1 DB lock wait")
    record.status = "waiting_approval"
    record.pending_approval = {
        "policy": {"level": "strict", "reasons": ["P1"]},
        "plan": {"root_cause": "Deadlock"},
    }
    incidents[inc_id] = record

    resp = client.post(
        f"/incidents/{inc_id}/approval",
        json={"approved": False, "reason": "Incorrect root cause identified"},
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "REJECTED"
    assert data["approval_id"].startswith("APPR-")


# ==============================================================================
# 5. Tickets Endpoints Tests
# ==============================================================================

def test_tickets_get_and_search(tmp_path):
    """GET /tickets and GET /tickets/{id} return ticket details."""
    appr = record_approval(
        incident_id="inc-tck",
        approver="engineer",
        decision="APPROVED",
    )
    created = create_ticket(
        title="[DB] DB-1205 deadlock incident",
        description="Terminated blocking transaction",
        severity="P1",
        owner_team="database-engineering",
        approval_id=appr["approval_id"],
    )
    ticket_id = created["ticket_id"]

    # List tickets
    resp = client.get("/tickets", headers={"X-API-Key": VALID_API_KEY})
    assert resp.status_code == 200
    tickets = resp.json()
    assert len(tickets) >= 1
    assert any(t["ticket_id"] == ticket_id for t in tickets)

    # Get single ticket
    resp_single = client.get(f"/tickets/{ticket_id}", headers={"X-API-Key": VALID_API_KEY})
    assert resp_single.status_code == 200
    assert resp_single.json()["ticket_id"] == ticket_id
    assert resp_single.json()["severity"] == "P1"

    # Ticket not found
    resp_404 = client.get("/tickets/TCK-NOTFOUND", headers={"X-API-Key": VALID_API_KEY})
    assert resp_404.status_code == 404


# ==============================================================================
# 6. Webhook Deduplication Tests
# ==============================================================================

@patch("app.api.main.run_investigation_worker")
def test_alerts_webhook_deduplication(mock_worker):
    """POST /alerts/webhook deduplicates same (service, metric) within 10 minutes."""
    alert_payload = {
        "service": "orders-db",
        "metric": "db_lock_count",
        "error_code": "DB-1205",
        "message": "Deadlock count exceeded threshold",
        "value": 15.0,
        "threshold": 5.0,
    }

    # 1. First alert creates an incident (202 Accepted)
    resp1 = client.post("/alerts/webhook", json=alert_payload, headers={"X-API-Key": VALID_API_KEY})
    assert resp1.status_code == 202
    data1 = resp1.json()
    inc_id = data1["incident_id"]
    assert inc_id in incidents

    # 2. Duplicate alert within 10 minutes returns 200 Deduplicated with same incident_id
    resp2 = client.post("/alerts/webhook", json=alert_payload, headers={"X-API-Key": VALID_API_KEY})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "deduplicated"
    assert data2["incident_id"] == inc_id

    # 3. Different metric on same service creates a new incident
    alert_payload_different = dict(alert_payload)
    alert_payload_different["metric"] = "cpu_usage"
    resp3 = client.post("/alerts/webhook", json=alert_payload_different, headers={"X-API-Key": VALID_API_KEY})
    assert resp3.status_code == 202
    data3 = resp3.json()
    assert data3["incident_id"] != inc_id


# ==============================================================================
# 7. Semaphore Slot Release Test
# ==============================================================================

def test_run_investigation_worker_releases_slot_on_interrupt():
    """Verify that run_investigation_worker releases concurrency slot while waiting for approval."""
    async def _test():
        # Ensure limiter has 1 permit
        assert investigation_limiter._value == 1

        record = IncidentRecord(incident_id="inc-slot-test", incident_text="Deadlock")

        mock_task = MagicMock()
        mock_interrupt = MagicMock()
        mock_interrupt.value = {
            "policy": {"level": "standard", "reasons": []},
            "plan": {"root_cause": "Deadlock", "confidence": 0.9},
        }
        mock_task.interrupts = [mock_interrupt]

        mock_state = MagicMock()
        mock_state.tasks = [mock_task]
        mock_state.values = {"plan": mock_interrupt.value["plan"]}

        with patch("app.api.main.graph_app.stream", return_value=[{"triage": {"severity": "P3"}}]), \
             patch("app.api.main.graph_app.get_state", return_value=mock_state):

            await run_investigation_worker(record)

        assert record.status == "waiting_approval"
        assert record.pending_approval is not None
        # Crucial assertion: Semaphore slot was released and is available (value == 1)!
        assert investigation_limiter._value == 1

    asyncio.run(_test())

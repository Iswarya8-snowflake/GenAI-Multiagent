"""SQLite ticketing and human approval management tools."""

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

TICKET_DB = os.getenv("TICKET_DB", "data/tickets.db")


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Return a connection with row factory to SQLite database, ensuring tables exist."""
    path = db_path or TICKET_DB
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection):
    """Initialize SQLite tables for tickets and approvals."""
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                approver TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                owner_team TEXT NOT NULL,
                approval_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (approval_id) REFERENCES approvals(approval_id)
            );
        """)


def record_approval(
    incident_id: str,
    approver: str,
    decision: str,
    reason: str = "",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record a human approval or rejection in the database.
    Decision should be 'APPROVED' or 'REJECTED'.
    """
    approval_id = f"APPR-{uuid.uuid4().hex[:8].upper()}"
    now_str = datetime.now(timezone.utc).isoformat()

    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO approvals (approval_id, incident_id, approver, decision, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (approval_id, incident_id, approver, decision.upper(), reason, now_str),
        )

    return {
        "approval_id": approval_id,
        "incident_id": incident_id,
        "approver": approver,
        "decision": decision.upper(),
        "reason": reason,
        "created_at": now_str,
    }


def require_approval(approval_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Verify that an approval_id exists and has an 'APPROVED' status.
    Raises PermissionError if invalid or rejected.
    """
    if not approval_id:
        raise PermissionError("Action requires an approval_id.")

    conn = get_db_connection(db_path)
    cur = conn.execute(
        "SELECT approval_id, incident_id, approver, decision, reason, created_at FROM approvals WHERE approval_id = ?",
        (approval_id,),
    )
    row = cur.fetchone()
    if not row:
        raise PermissionError(f"Approval '{approval_id}' not found in database.")

    approval = dict(row)
    if approval["decision"] != "APPROVED":
        raise PermissionError(
            f"Approval '{approval_id}' has decision '{approval['decision']}', required 'APPROVED'."
        )

    return approval


def create_ticket(
    title: str,
    description: str,
    severity: str,
    owner_team: str,
    approval_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new support ticket.
    Requires an approved approval_id before writing.
    """
    # Enforce approval gate
    require_approval(approval_id, db_path=db_path)

    ticket_id = f"TCK-{uuid.uuid4().hex[:8].upper()}"
    now_str = datetime.now(timezone.utc).isoformat()
    status = "OPEN"

    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO tickets (ticket_id, title, description, severity, status, owner_team, approval_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ticket_id, title, description, severity.upper(), status, owner_team, approval_id, now_str, now_str),
        )

    return {
        "ticket_id": ticket_id,
        "title": title,
        "description": description,
        "severity": severity.upper(),
        "status": status,
        "owner_team": owner_team,
        "approval_id": approval_id,
        "created_at": now_str,
        "updated_at": now_str,
    }


def update_ticket(
    ticket_id: str,
    updates: Dict[str, Any],
    approval_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update an existing support ticket.
    Requires an approved approval_id before updating.
    """
    # Enforce approval gate
    require_approval(approval_id, db_path=db_path)

    conn = get_db_connection(db_path)
    ticket = get_ticket(ticket_id, db_path=db_path)
    if not ticket:
        raise ValueError(f"Ticket '{ticket_id}' not found.")

    allowed_fields = {"title", "description", "severity", "status", "owner_team"}
    fields_to_update = {k: v for k, v in updates.items() if k in allowed_fields}
    if not fields_to_update:
        return ticket

    now_str = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields_to_update.keys())
    set_clause += ", updated_at = ?"
    values = list(fields_to_update.values()) + [now_str, ticket_id]

    with conn:
        conn.execute(f"UPDATE tickets SET {set_clause} WHERE ticket_id = ?", values)

    return get_ticket(ticket_id, db_path=db_path)


def get_ticket(ticket_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve ticket details by ID."""
    conn = get_db_connection(db_path)
    cur = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def search_tickets(
    query: str,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search tickets by text keyword and optional status filter."""
    conn = get_db_connection(db_path)
    sql = "SELECT * FROM tickets WHERE (title LIKE ? OR description LIKE ?)"
    params = [f"%{query}%", f"%{query}%"]

    if status:
        sql += " AND status = ?"
        params.append(status.upper())

    sql += " ORDER BY created_at DESC"
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def suggest_owner(category: str, error_code: Optional[str] = None) -> str:
    """
    Suggest team owner based on incident category or error code.
    """
    cat_lower = (category or "").lower()
    code_upper = (error_code or "").upper()

    if "orders-db" in cat_lower or "db-lock" in cat_lower or "DB-1205" in code_upper:
        return "database-engineering"
    elif "msg-queue" in cat_lower or "queue-backlog" in cat_lower or "MQ-2041" in code_upper:
        return "messaging-platform"
    elif "feed-gateway" in cat_lower or "cpu-spike" in cat_lower or "FEED-7002" in code_upper:
        return "gateway-platform"
    elif "calc-engine" in cat_lower or "batch-failure" in cat_lower or "JOB-5003" in code_upper:
        return "batch-analytics"
    elif "cert-expiry" in cat_lower or "disk-full" in cat_lower or "system" in cat_lower:
        return "cloud-infrastructure"

    return "l3-support-triage"


"""FastMCP Tool Server for L3 Incident Copilot (streamable HTTP on port 8765)."""

import os
import sys
from typing import Any, Dict, List, Optional
import httpx
from dotenv import load_dotenv

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from app.mcp_server.tools import safety, logs, wiki, tickets, live, kb

load_dotenv()

# Initialize FastMCP Server
mcp = FastMCP("L3-Incident-Triage-MCP-Server")


# ==============================================================================
# Knowledge Base & Wiki Tools
# ==============================================================================

@mcp.tool()
def search_kb(query: str, k: int = 5, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search the FAISS knowledge base for relevant runbooks and past incidents.

    Args:
        query: Problem description, error message, or search query.
        k: Maximum number of relevant chunks to retrieve (default 5).
        category: Optional category filter (e.g. 'db-lock', 'queue-backlog').

    Returns:
        List of matching document dicts with id, text, score, and metadata.
    """
    return kb.search_kb(query=query, k=k, category=category)


@mcp.tool()
def search_wiki(query: str) -> List[Dict[str, Any]]:
    """
    Perform keyword search across runbooks and wiki documentation.

    Args:
        query: Search keywords or phrases.

    Returns:
        List of matching files with titles, match scores, and text snippets.
    """
    return wiki.search_wiki(query=query)


@mcp.tool()
def kb_upsert(text: str, metadata: Dict[str, Any], approval_id: str) -> Dict[str, Any]:
    """
    Upsert an approved resolution or runbook entry into the knowledge base.
    Requires an approved approval_id.

    Args:
        text: Knowledge base content or incident resolution notes.
        metadata: Document metadata dict (e.g. category, service, incident_id).
        approval_id: Validated human approval ID.

    Returns:
        Confirmation dict with document id and upsert status.
    """
    # Enforce approval gate
    tickets.require_approval(approval_id)
    return kb.kb_upsert(text=text, metadata=metadata)


# ==============================================================================
# Log Analysis & Signature Tools
# ==============================================================================

@mcp.tool()
def parse_logs(text: str) -> Dict[str, Any]:
    """
    Parse application logs and extract error statistics.

    Args:
        text: Raw log text containing lines to analyze.

    Returns:
        Dict containing error_count, first_error_time, last_error_time,
        top_error_signatures (with normalized digits), error_codes, and failing_components.
    """
    return logs.parse_logs(text=text)


@mcp.tool()
def lookup_signature(sig: str) -> List[Dict[str, Any]]:
    """
    Match an error signature or code against historical incidents in data/incidents.json.

    Args:
        sig: Error signature or log message containing an error code (e.g. DB-1205).

    Returns:
        List of top matching historical incidents.
    """
    return logs.lookup_signature(sig=sig)


# ==============================================================================
# Live Monitoring Tools
# ==============================================================================

@mcp.tool()
def get_active_alerts(service: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch active monitoring alerts, optionally filtered by service.

    Args:
        service: Optional service name filter ('orders-db', 'msg-queue', etc.).

    Returns:
        Dict containing list of active alerts and count, with as_of timestamp.
    """
    return live.get_active_alerts(service=service)


@mcp.tool()
def get_service_health(service: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch current health status for services from the monitoring simulator.

    Args:
        service: Optional service name. If omitted, returns health for all services.

    Returns:
        Dict containing service status (HEALTHY, DEGRADED, CRITICAL) and as_of timestamp.
    """
    return live.get_service_health(service=service)


@mcp.tool()
def get_metrics(service: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch live telemetry metrics for services.

    Args:
        service: Optional service name. If omitted, returns metrics for all services.

    Returns:
        Dict containing telemetry counters and gauges with as_of timestamp.
    """
    return live.get_metrics(service=service)


@mcp.tool()
def tail_log(service: str, lines: int = 50) -> Dict[str, Any]:
    """
    Tail recent log entries for a service from the monitoring simulator.

    Args:
        service: Name of service ('orders-db', 'msg-queue', 'feed-gateway', 'calc-engine').
        lines: Number of latest log lines to return (default 50).

    Returns:
        Dict containing list of log lines and as_of timestamp.
    """
    return live.tail_log(service=service, lines=lines)


# ==============================================================================
# Ticketing & Approval Tools
# ==============================================================================

@mcp.tool()
def search_tickets(query: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search tickets in SQLite database by keyword.

    Args:
        query: Text to search in ticket title or description.
        status: Optional status filter ('OPEN', 'RESOLVED', 'CLOSED').

    Returns:
        List of matching ticket records.
    """
    return tickets.search_tickets(query=query, status=status)


@mcp.tool()
def get_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve full ticket details by ticket ID.

    Args:
        ticket_id: Unique ticket ID (e.g. 'TCK-12345').

    Returns:
        Ticket record dict if found, or None.
    """
    return tickets.get_ticket(ticket_id=ticket_id)


@mcp.tool()
def suggest_owner(category: str, error_code: Optional[str] = None) -> str:
    """
    Suggest team assignment based on incident category or error code.

    Args:
        category: Incident category (e.g. 'db-lock', 'queue-backlog').
        error_code: Error code if known (e.g. 'DB-1205', 'MQ-2041').

    Returns:
        Name of suggested owner team (e.g. 'database-engineering').
    """
    return tickets.suggest_owner(category=category, error_code=error_code)


@mcp.tool()
def create_ticket(
    title: str,
    description: str,
    severity: str,
    owner_team: str,
    approval_id: str,
) -> Dict[str, Any]:
    """
    Create a new support ticket in the ticketing system.
    Requires an approved approval_id from human approval.

    Args:
        title: Short incident summary.
        description: Detailed incident description and proposed resolution.
        severity: Severity level ('P1', 'P2', 'P3', 'P4').
        owner_team: Team responsible for resolution.
        approval_id: Human approval ID authorizing ticket creation.

    Returns:
        Created ticket record dict.
    """
    return tickets.create_ticket(
        title=title,
        description=description,
        severity=severity,
        owner_team=owner_team,
        approval_id=approval_id,
    )


@mcp.tool()
def update_ticket(
    ticket_id: str,
    updates: Dict[str, Any],
    approval_id: str,
) -> Dict[str, Any]:
    """
    Update an existing support ticket.
    Requires an approved approval_id.

    Args:
        ticket_id: Ticket ID to update.
        updates: Dict of fields to update (e.g. {'status': 'RESOLVED'}).
        approval_id: Human approval ID authorizing ticket modification.

    Returns:
        Updated ticket record dict.
    """
    return tickets.update_ticket(
        ticket_id=ticket_id,
        updates=updates,
        approval_id=approval_id,
    )


# ==============================================================================
# Safety & Web Research Tools
# ==============================================================================

@mcp.tool()
def redact_text(text: str) -> str:
    """
    Redact PII, internal hostnames, ticket IDs, IPs, file paths, and service names.
    Preserves error codes like DB-1205.

    Args:
        text: Raw text to redact.

    Returns:
        Sanitized text with placeholders.
    """
    return safety.redact(text=text)


@mcp.tool()
def search_web(query: str) -> List[Dict[str, Any]]:
    """
    Perform web search for external documentation and solutions.
    Only accepts redacted queries to prevent data leakage.

    Args:
        query: Redacted search query.

    Returns:
        List of search result snippets.
    """
    # Enforce redaction rule
    clean_query = safety.redact(query)
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(clean_query, max_results=5))
            return [
                {"title": r.get("title", ""), "href": r.get("href", ""), "body": r.get("body", "")}
                for r in results
            ]
    except Exception as e:
        return [{
            "title": f"Search fallback for: {clean_query}",
            "href": "https://example.org/search",
            "body": f"External search results for query: {clean_query}",
            "note": str(e),
        }]


@mcp.tool()
def fetch_page(url: str) -> str:
    """
    Safely fetch an external web page.
    Requires HTTPS and blocks private, loopback, or internal addresses.

    Args:
        url: Public HTTPS URL to fetch.

    Returns:
        Sanitized plain text content from the page.
    """
    if not safety.is_safe_url(url):
        raise ValueError(f"Unsafe URL '{url}' blocked: only public HTTPS is permitted.")

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return safety.sanitize_web_text(resp.text)
    except Exception as e:
        return f"Error fetching {url}: {str(e)}"


# ==============================================================================
# Main Server Entrypoint
# ==============================================================================

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8765
    path = "/mcp"
    print(f"Starting MCP server on http://{host}:{port}{path} (streamable-http)...")
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path=path,
    )

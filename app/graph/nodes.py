"""Synchronous graph nodes for triage, retrieval, log analysis, live status, planner, reviewer, and ticketing."""

import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

from langgraph.types import interrupt
from langchain_ollama import ChatOllama

from app.graph.state import IncidentState, TriageOutput, ResolutionPlan, Claim
from app.graph.tools import call_mcp_tool_sync
from app.graph.grounding import check_grounding
from app.graph.policy import evaluate_approval_policy

load_dotenv()

CHAT_MODEL = os.getenv("CHAT_MODEL", "llama3.2:3b")


def get_llm():
    """Return configured Ollama Chat model with temperature=0 and num_ctx=4096."""
    return ChatOllama(model=CHAT_MODEL, temperature=0, num_ctx=4096)


# ==============================================================================
# 1. Triage Node (LLM structured output)
# ==============================================================================

def triage_node(state: IncidentState) -> Dict[str, Any]:
    """Triage Agent: Extracts structured JSON {severity, category, component, summary}."""
    incident_text = state.get("incident_text", "")
    llm = get_llm()
    structured_llm = llm.with_structured_output(TriageOutput)

    prompt = (
        "You are an L3 Incident Triage engineer.\n"
        "Analyze the following incident report and classify it into structured JSON.\n"
        "Allowed components: orders-db, msg-queue, feed-gateway, calc-engine.\n"
        "Allowed severity: P1, P2, P3, P4.\n\n"
        f"Incident:\n{incident_text}\n"
    )

    try:
        result = structured_llm.invoke(prompt)
    except Exception as e:
        retry_prompt = prompt + f"\nPrevious attempt failed: {str(e)}. Return valid JSON now."
        try:
            result = structured_llm.invoke(retry_prompt)
        except Exception:
            result = TriageOutput(
                severity="P2",
                category="system",
                component="orders-db",
                summary=incident_text[:120],
            )

    return {"triage": result.model_dump()}


# ==============================================================================
# 2. Parallel Investigation Nodes (Tools called by code)
# ==============================================================================

def retrieval_node(state: IncidentState) -> Dict[str, Any]:
    """Retrieval Agent: Searches knowledge base via MCP, keeps top 3 chunks (<= 600 chars)."""
    query = state.get("refined_query") or state.get("incident_text", "")
    triage = state.get("triage") or {}
    category = triage.get("category")

    try:
        raw_results = call_mcp_tool_sync("search_kb", {
            "query": query,
            "k": 3,
            "category": category if category in {"db-lock", "queue-backlog", "cpu-spike", "batch-failure"} else None,
        })
    except Exception:
        raw_results = call_mcp_tool_sync("search_kb", {
            "query": query,
            "k": 3,
        })

    kb_docs: List[Dict[str, Any]] = []
    if isinstance(raw_results, list):
        for idx, item in enumerate(raw_results[:3], start=1):
            if isinstance(item, dict):
                full_text = item.get("text", "")
                kb_docs.append({
                    "id": f"kb-{idx}",
                    "text": full_text[:600],
                    "original_id": item.get("id", f"chunk-{idx}"),
                    "score": item.get("score", 0.0),
                    "metadata": item.get("metadata", {}),
                    "source_type": "runbook_or_incident",
                })

    return {"kb_docs": kb_docs}


def log_analysis_node(state: IncidentState) -> Dict[str, Any]:
    """Log Analysis Agent: Parses logs and matches signatures via MCP."""
    logs_text = state.get("logs")
    triage = state.get("triage") or {}
    component = triage.get("component", "orders-db")

    if not logs_text:
        try:
            tail_resp = call_mcp_tool_sync("tail_log", {"service": component, "lines": 20})
            if isinstance(tail_resp, dict) and "lines" in tail_resp:
                logs_text = "\n".join(tail_resp["lines"])
        except Exception:
            logs_text = ""

    parsed_stats = {}
    matched_incidents = []
    if logs_text:
        try:
            parsed_stats = call_mcp_tool_sync("parse_logs", {"text": logs_text})
        except Exception as e:
            parsed_stats = {"error": str(e)}

        error_codes = parsed_stats.get("error_codes") or []
        sig_str = " ".join(error_codes)
        if error_codes:
            try:
                matched_incidents = call_mcp_tool_sync("lookup_signature", {"sig": sig_str})
            except Exception:
                matched_incidents = []

    return {
        "log_findings": {
            "stats": parsed_stats,
            "matched_incidents": matched_incidents,
            "sample_logs": logs_text[:400] if logs_text else "",
        }
    }


def live_status_node(state: IncidentState) -> Dict[str, Any]:
    """Live Status Agent: Fetches active alerts and service health via MCP."""
    triage = state.get("triage") or {}
    component = triage.get("component", "orders-db")

    alerts = []
    health = {}
    try:
        alerts_resp = call_mcp_tool_sync("get_active_alerts", {"service": component})
        if isinstance(alerts_resp, dict):
            alerts = alerts_resp.get("alerts", [])
    except Exception:
        pass

    try:
        health_resp = call_mcp_tool_sync("get_service_health", {"service": component})
        if isinstance(health_resp, dict):
            health = health_resp
    except Exception:
        pass

    return {
        "live_findings": {
            "component": component,
            "status": health.get("status", "UNKNOWN"),
            "active_alerts": alerts,
            "as_of": health.get("as_of"),
        }
    }


# ==============================================================================
# 3. Join Node
# ==============================================================================

def join_node(state: IncidentState) -> Dict[str, Any]:
    """Join Node: Aggregates findings from retrieval, log analysis, and live status into evidence."""
    evidence: List[Dict[str, Any]] = []
    doc_counter = 1

    # 1. Add KB docs
    kb_docs = state.get("kb_docs") or []
    for doc in kb_docs:
        evidence.append({
            "id": f"doc-{doc_counter}",
            "text": doc.get("text", "")[:600],
            "original_id": doc.get("original_id"),
            "score": doc.get("score", 0.0),
            "metadata": doc.get("metadata", {}),
            "source_type": doc.get("source_type", "kb"),
        })
        doc_counter += 1

    # 2. Add log findings as evidence item if errors found
    log_findings = state.get("log_findings") or {}
    stats = log_findings.get("stats") or {}
    if stats.get("error_count", 0) > 0:
        codes = ", ".join(stats.get("error_codes", []))
        sigs = [s.get("signature", "") for s in stats.get("top_error_signatures", [])]
        text = f"Logs parsed: {stats.get('error_count')} errors. Error codes: [{codes}]. Top signatures: {'; '.join(sigs)}"
        evidence.append({
            "id": f"doc-{doc_counter}",
            "text": text[:600],
            "original_id": "log-parser",
            "metadata": {"source_type": "logs"},
            "source_type": "logs",
        })
        doc_counter += 1

    # 3. Add active alerts as evidence item if present
    live_findings = state.get("live_findings") or {}
    alerts = live_findings.get("active_alerts") or []
    if alerts:
        alert_msgs = [f"[{a.get('error_code', '')}] {a.get('message', '')}" for a in alerts]
        text = f"Active monitoring alerts on {live_findings.get('component')}: {'; '.join(alert_msgs)} (Status: {live_findings.get('status')})"
        evidence.append({
            "id": f"doc-{doc_counter}",
            "text": text[:600],
            "original_id": "monitoring-alerts",
            "metadata": {"source_type": "live_monitoring"},
            "source_type": "live_monitoring",
        })
        doc_counter += 1

    return {"evidence": evidence}


# ==============================================================================
# 4. Planner Node
# ==============================================================================

def planner_node(state: IncidentState) -> Dict[str, Any]:
    """Planner Agent: Synthesizes resolution plan with cited claims."""
    incident_text = state.get("incident_text", "")
    evidence = state.get("evidence", [])

    evidence_lines = []
    for doc in evidence:
        doc_id = doc.get("id", "doc")
        text = doc.get("text", "").replace("\n", " ").strip()
        evidence_lines.append(f"[{doc_id}] {text}")

    evidence_block = "\n".join(evidence_lines) if evidence_lines else "No evidence available."

    llm = get_llm()
    structured_llm = llm.with_structured_output(ResolutionPlan)

    prompt = (
        "You are an L3 Incident Resolution Planner.\n"
        "Synthesize a resolution plan based on the incident and cited evidence.\n"
        "Requirements:\n"
        "- root_cause: explain the likely root cause\n"
        "- fix_steps: concrete steps to resolve the issue\n"
        "- confidence: float between 0.0 and 1.0 (e.g. 0.85)\n"
        "- claims: list of statements where each claim cites source_ids from evidence (e.g. ['doc-1'])\n"
        "- not_found: list any unresolved points or missing runbooks\n\n"
        f"Incident:\n{incident_text}\n\n"
        f"Evidence:\n{evidence_block}\n"
    )

    try:
        plan_result = structured_llm.invoke(prompt)
    except Exception as first_err:
        retry_prompt = prompt + f"\nPrevious attempt failed: {str(first_err)}. Please return valid JSON."
        try:
            plan_result = structured_llm.invoke(retry_prompt)
        except Exception as retry_err:
            plan_result = ResolutionPlan(
                root_cause="Root cause could not be determined reliably from evidence.",
                fix_steps=["Escalate to human incident manager."],
                confidence=0.0,
                claims=[],
                not_found=[f"Planning failed: {str(retry_err)}"],
            )

    return {"plan": plan_result.model_dump()}


# ==============================================================================
# 5. Reviewer Node (No LLM, uses grounding rules)
# ==============================================================================

def reviewer_node(state: IncidentState) -> Dict[str, Any]:
    """
    Reviewer Agent: Checks citation existence, error code grounding,
    command grounding, word overlap (>= 0.3), and destructive steps.
    """
    plan = state.get("plan") or {}
    evidence = state.get("evidence") or []
    loops = state.get("loops", 0)

    grounding_result = check_grounding(plan, evidence)

    updates: Dict[str, Any] = {"review": grounding_result}

    if not grounding_result["passed"]:
        updates["loops"] = loops + 1
        triage = state.get("triage") or {}
        comp = triage.get("component", "")
        cat = triage.get("category", "")
        updates["refined_query"] = f"{state.get('incident_text', '')} {comp} {cat} runbook fix"

    return updates


# ==============================================================================
# 6. Human Approval Node (LangGraph Interrupt)
# ==============================================================================

def human_approval_node(state: IncidentState) -> Dict[str, Any]:
    """
    Human Approval Node: Evaluates policy (standard vs strict), interrupts for human review,
    and returns approval state upon resumption.
    """
    policy = evaluate_approval_policy(state)

    # Pause execution and wait for human response via LangGraph interrupt
    approval_response = interrupt({
        "plan": state.get("plan"),
        "triage": state.get("triage"),
        "evidence": state.get("evidence"),
        "policy": policy,
        "message": f"Human approval required ({policy['level'].upper()} policy).",
    })

    approved = False
    approval_id = None
    if isinstance(approval_response, dict):
        approved = bool(approval_response.get("approved", False))
        approval_id = approval_response.get("approval_id")

    return {
        "approved": approved,
        "approval_id": approval_id,
        "policy": policy,
    }


# ==============================================================================
# 7. Ticketing & Knowledge Base Write-back Nodes
# ==============================================================================

def ticketing_node(state: IncidentState) -> Dict[str, Any]:
    """Ticketing Agent: Calls suggest_owner and create_ticket with approval_id."""
    triage = state.get("triage") or {}
    plan = state.get("plan") or {}
    approval_id = state.get("approval_id", "")
    category = triage.get("category", "system")
    severity = triage.get("severity", "P2")

    # Suggest team owner
    owner_team = call_mcp_tool_sync("suggest_owner", {"category": category})

    # Create ticket via MCP (enforces approval gate)
    title = f"[{category.upper()}] {triage.get('summary', 'Incident resolution')}"
    desc = f"Root cause: {plan.get('root_cause')}\nFix steps: {'; '.join(plan.get('fix_steps', []))}"

    ticket_record = call_mcp_tool_sync("create_ticket", {
        "title": title,
        "description": desc,
        "severity": severity,
        "owner_team": owner_team,
        "approval_id": approval_id,
    })

    return {
        "ticket": ticket_record,
        "status": "RESOLVED_AND_TICKETED",
    }


def kb_writeback_node(state: IncidentState) -> Dict[str, Any]:
    """KB Writeback: Upserts approved resolution back to knowledge base."""
    plan = state.get("plan") or {}
    triage = state.get("triage") or {}
    approval_id = state.get("approval_id", "")

    content = (
        f"Resolution for {triage.get('summary')}:\n"
        f"Root Cause: {plan.get('root_cause')}\n"
        f"Fix Steps: {'; '.join(plan.get('fix_steps', []))}\n"
    )
    metadata = {
        "category": triage.get("category", "incident_resolution"),
        "component": triage.get("component"),
        "source_type": "approved_incident_resolution",
    }

    upsert_res = call_mcp_tool_sync("kb_upsert", {
        "text": content,
        "metadata": metadata,
        "approval_id": approval_id,
    })

    return {"kb_writeback_result": upsert_res}


def escalate_node(state: IncidentState) -> Dict[str, Any]:
    """Escalate Node: Handles ungrounded plans or rejected approvals."""
    return {"status": "ESCALATED_TO_HUMAN"}

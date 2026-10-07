"""Plain-text step narration module (PROJECT_SPEC.md Portal features).

Constructs human-readable explanations of agent and tool executions
using deterministic, fixed templates built strictly from tool facts,
with no LLM and no network.
"""

from typing import Any, Dict, List, Optional


def narrate(
    node: str,
    delta: Optional[Dict[str, Any]] = None,
    state: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Generate structured narration items for a workflow execution step.

    Args:
        node: Name of the executed graph node (e.g. 'log_analysis', 'live_status', etc.).
        delta: Output updates returned by this node.
        state: Full accumulated workflow state.

    Returns:
        List of dicts with keys: {stage, status, title, detail}.
    """
    if delta is None:
        delta = {}
    if state is None:
        state = {}

    stage = str(node)
    status = "completed"
    title = node.replace("_", " ").title()

    # ==========================================================================
    # 1. Log Analysis
    # ==========================================================================
    if node == "log_analysis":
        title = "Log Analysis"
        log_findings = delta.get("log_findings") or state.get("log_findings") or {}
        stats = log_findings.get("stats") or {}
        n = stats.get("error_count")

        if n is None or n == 0:
            detail = "I checked the application logs: no errors detected."
        else:
            first = stats.get("first_error_time")
            last = stats.get("last_error_time")
            codes = stats.get("error_codes") or []
            code = codes[0] if codes else None

            msg = f"I checked the application logs: {n} errors"
            if first and last:
                msg += f" between {first} and {last}"
            if code:
                msg += f"; most frequent: {code}"
            detail = msg

    # ==========================================================================
    # 2. Live Status
    # ==========================================================================
    elif node == "live_status":
        title = "Live Status Check"
        live_findings = delta.get("live_findings") or state.get("live_findings") or {}
        component = live_findings.get("component") or state.get("triage", {}).get("component")
        st = live_findings.get("status")
        deps = live_findings.get("dependencies") or live_findings.get("depends_on") or []

        if not component and not st and not deps:
            detail = "I checked related systems."
        else:
            parts = []
            if component and st:
                parts.append(f"{component} is {st}")
            elif component:
                parts.append(f"{component}")

            if isinstance(deps, list):
                for d in deps:
                    if isinstance(d, dict):
                        d_name = d.get("service") or d.get("name")
                        d_st = d.get("status")
                        if d_name and d_st:
                            parts.append(f"{d_name} is {d_st}")
                        elif d_name:
                            parts.append(d_name)
                    elif isinstance(d, str):
                        parts.append(f"{d} HEALTHY")

            if parts:
                detail = f"I checked related systems: {'; '.join(parts)}."
            else:
                detail = "I checked related systems."

    # ==========================================================================
    # 3. Retrieval
    # ==========================================================================
    elif node == "retrieval":
        title = "Knowledge Retrieval"
        kb_docs = delta.get("kb_docs") or state.get("kb_docs") or []
        n = len(kb_docs)
        if n == 0:
            detail = "I searched the knowledge base: no relevant documents found."
        else:
            best_doc = kb_docs[0]
            meta = best_doc.get("metadata") or {}
            best_title = meta.get("title") or meta.get("id") or best_doc.get("id") or meta.get("file")
            if best_title:
                detail = f"I searched the knowledge base: {n} relevant documents, best match {best_title}"
            else:
                detail = f"I searched the knowledge base: {n} relevant documents."

    # ==========================================================================
    # 4. Planner
    # ==========================================================================
    elif node == "planner":
        title = "Resolution Planning"
        plan = delta.get("plan") or state.get("plan") or {}
        root_cause = plan.get("root_cause")
        confidence = plan.get("confidence")

        if root_cause:
            if confidence is not None:
                detail = f"Likely root cause (confidence {confidence}): {root_cause}"
            else:
                detail = f"Likely root cause: {root_cause}"
        else:
            detail = "Resolution planning completed."

    # ==========================================================================
    # 5. Reviewer
    # ==========================================================================
    elif node == "reviewer":
        title = "Grounding Review"
        review = delta.get("review") or state.get("review") or {}
        plan = state.get("plan") or delta.get("plan") or {}
        claims = plan.get("claims") or []
        total = len(claims)
        issues = review.get("issues") or []
        ok = max(0, total - len(issues))

        if not review.get("passed", True) or issues:
            status = "warning"

        if total > 0:
            detail = f"Verified {ok} of {total} claims against their sources"
        elif "passed" in review:
            detail = f"Grounding review {'passed' if review['passed'] else 'failed'}."
        else:
            detail = "Grounding review completed."

    # ==========================================================================
    # 6. Triage
    # ==========================================================================
    elif node == "triage":
        title = "Incident Triage"
        triage = delta.get("triage") or state.get("triage") or {}
        sev = triage.get("severity")
        comp = triage.get("component")
        summ = triage.get("summary")

        facts = []
        if sev:
            facts.append(f"severity {sev}")
        if comp:
            facts.append(f"component {comp}")
        if summ:
            facts.append(f"summary: {summ}")

        if facts:
            detail = f"Triaged incident: {', '.join(facts)}."
        else:
            detail = "Incident triage completed."

    # ==========================================================================
    # 7. Join
    # ==========================================================================
    elif node == "join":
        title = "Evidence Aggregation"
        evidence = delta.get("evidence") or state.get("evidence") or []
        count = len(evidence)
        detail = f"Aggregated {count} evidence items across logs, runbooks, and live monitoring."

    # ==========================================================================
    # 8. Human Approval
    # ==========================================================================
    elif node == "human_approval":
        title = "Human Approval Gate"
        status = "waiting_approval"
        policy = delta.get("policy") or state.get("policy") or {}
        level = policy.get("level", "standard").upper()
        detail = f"Human approval required ({level} policy)."

    # ==========================================================================
    # 9. Ticketing
    # ==========================================================================
    elif node == "ticketing":
        title = "Ticket Creation"
        ticket = delta.get("ticket") or state.get("ticket") or {}
        t_id = ticket.get("ticket_id")
        team = ticket.get("owner_team")
        if t_id and team:
            detail = f"Created support ticket {t_id} assigned to team {team}."
        elif t_id:
            detail = f"Created support ticket {t_id}."
        else:
            detail = "Support ticket created."

    # ==========================================================================
    # 10. KB Writeback
    # ==========================================================================
    elif node == "kb_writeback":
        title = "Knowledge Base Writeback"
        res = delta.get("kb_writeback_result") or state.get("kb_writeback_result") or {}
        doc_id = res.get("id")
        if doc_id:
            detail = f"Saved approved resolution to knowledge base: {doc_id}."
        else:
            detail = "Saved approved resolution to knowledge base."

    # ==========================================================================
    # 11. Escalate
    # ==========================================================================
    elif node == "escalate":
        title = "Incident Escalation"
        status = "escalated"
        detail = "Escalated incident to human engineering team."

    # ==========================================================================
    # 12. Scan Init
    # ==========================================================================
    elif node == "scan_init":
        title = "Application Scan Initialization"
        service = delta.get("service") or state.get("service") or "application"
        detail = f"Initiated application knowledge scan for {service}."

    # ==========================================================================
    # 13. Search Tickets
    # ==========================================================================
    elif node == "search_tickets":
        title = "Ticket Search"
        tickets = delta.get("tickets_found") or state.get("tickets_found") or []
        count = len(tickets)
        detail = f"Searched ticketing system: found {count} related tickets."

    # ==========================================================================
    # 14. Knowledge Draft
    # ==========================================================================
    elif node == "knowledge_draft":
        title = "Application Knowledge Draft"
        service = state.get("service") or state.get("triage", {}).get("component") or "application"
        detail = f"Generated application knowledge profile draft for {service}."

    # ==========================================================================
    # 15. Knowledge Save
    # ==========================================================================
    elif node == "knowledge_save":
        title = "Knowledge Base Save"
        saved = delta.get("knowledge_saved") or state.get("knowledge_saved") or {}
        v = saved.get("version")
        p = saved.get("path")
        if v and p:
            detail = f"Saved application knowledge profile (v{v}) to {p}."
        else:
            detail = "Saved application knowledge profile."

    # ==========================================================================
    # Default Fallback
    # ==========================================================================
    else:
        detail = f"Completed step: {node}."

    return [
        {
            "stage": stage,
            "status": status,
            "title": title,
            "detail": detail,
        }
    ]


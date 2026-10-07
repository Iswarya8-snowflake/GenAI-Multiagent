"""LangGraph workflow definition for L3 Incident Copilot with parallel investigation, reviewer, and human-in-the-loop."""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from app.graph.state import IncidentState
from app.graph.nodes import (
    triage_node,
    scan_init_node,
    search_tickets_node,
    retrieval_node,
    log_analysis_node,
    live_status_node,
    join_node,
    planner_node,
    reviewer_node,
    knowledge_draft_node,
    human_approval_node,
    ticketing_node,
    knowledge_save_node,
    kb_writeback_node,
    escalate_node,
)


def route_start(state: IncidentState) -> str:
    """Route from START to scan_init for scan mode, or triage for investigate mode."""
    if state.get("mode") == "scan":
        return "scan_init"
    return "triage"


def route_join(state: IncidentState) -> str:
    """Route from join: scan mode skips planner and goes to knowledge_draft."""
    if state.get("mode") == "scan":
        return "knowledge_draft"
    return "planner"


def route_reviewer(state: IncidentState) -> str:
    """Route from reviewer to knowledge_draft, retry retrieval, or escalate."""
    review = state.get("review") or {}
    if review.get("passed", False):
        return "knowledge_draft"

    loops = int(state.get("loops", 0))
    if loops < 2:
        return "retrieval"
    return "escalate"


def route_approval(state: IncidentState) -> str:
    """Route from human_approval to ticketing if approved, else escalate."""
    if state.get("approved", False):
        return "ticketing"
    return "escalate"


def build_graph(checkpointer=None):
    """Build and compile the multi-agent incident triage and resolution graph."""
    builder = StateGraph(IncidentState)

    # 1. Entry & Triage / Scan Init
    builder.add_node("triage", triage_node)
    builder.add_node("scan_init", scan_init_node)

    # 2. Parallel Investigation Nodes
    builder.add_node("retrieval", retrieval_node)
    builder.add_node("log_analysis", log_analysis_node)
    builder.add_node("live_status", live_status_node)
    builder.add_node("search_tickets", search_tickets_node)

    # 3. Join & Planning
    builder.add_node("join", join_node)
    builder.add_node("planner", planner_node)

    # 4. Reviewer & Knowledge Draft
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("knowledge_draft", knowledge_draft_node)

    # 5. Human Approval
    builder.add_node("human_approval", human_approval_node)

    # 6. Action Nodes
    builder.add_node("ticketing", ticketing_node)
    builder.add_node("knowledge_save", knowledge_save_node)
    builder.add_node("kb_writeback", kb_writeback_node)
    builder.add_node("escalate", escalate_node)

    # Wire Edges
    builder.add_conditional_edges(
        START,
        route_start,
        {
            "scan_init": "scan_init",
            "triage": "triage",
        },
    )

    # Fan out from triage (investigate mode)
    builder.add_edge("triage", "retrieval")
    builder.add_edge("triage", "log_analysis")
    builder.add_edge("triage", "live_status")

    # Fan out from scan_init (scan mode)
    builder.add_edge("scan_init", "retrieval")
    builder.add_edge("scan_init", "log_analysis")
    builder.add_edge("scan_init", "live_status")
    builder.add_edge("scan_init", "search_tickets")

    # Fan in to join
    builder.add_edge("retrieval", "join")
    builder.add_edge("log_analysis", "join")
    builder.add_edge("live_status", "join")
    builder.add_edge("search_tickets", "join")

    # Join routing (scan mode skips planner directly to knowledge_draft)
    builder.add_conditional_edges(
        "join",
        route_join,
        {
            "knowledge_draft": "knowledge_draft",
            "planner": "planner",
        },
    )

    # Plan and Review
    builder.add_edge("planner", "reviewer")

    # Reviewer conditional routing
    builder.add_conditional_edges(
        "reviewer",
        route_reviewer,
        {
            "knowledge_draft": "knowledge_draft",
            "retrieval": "retrieval",
            "escalate": "escalate",
        },
    )

    # Draft leads to human approval
    builder.add_edge("knowledge_draft", "human_approval")

    # Human approval conditional routing
    builder.add_conditional_edges(
        "human_approval",
        route_approval,
        {
            "ticketing": "ticketing",
            "escalate": "escalate",
        },
    )

    # Final actions
    builder.add_edge("ticketing", "knowledge_save")
    builder.add_edge("knowledge_save", "kb_writeback")
    builder.add_edge("kb_writeback", END)
    builder.add_edge("escalate", END)

    cp = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=cp)


# Compiled default application instance
app = build_graph()

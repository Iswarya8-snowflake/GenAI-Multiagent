"""LangGraph workflow definition for L3 Incident Copilot with parallel investigation, reviewer, and human-in-the-loop."""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from app.graph.state import IncidentState
from app.graph.nodes import (
    triage_node,
    retrieval_node,
    log_analysis_node,
    live_status_node,
    join_node,
    planner_node,
    reviewer_node,
    human_approval_node,
    ticketing_node,
    kb_writeback_node,
    escalate_node,
)


def route_reviewer(state: IncidentState) -> str:
    """Route from reviewer to human_approval, retry retrieval, or escalate."""
    review = state.get("review") or {}
    if review.get("passed", False):
        return "human_approval"

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

    # 1. Triage
    builder.add_node("triage", triage_node)

    # 2. Parallel Investigation Nodes
    builder.add_node("retrieval", retrieval_node)
    builder.add_node("log_analysis", log_analysis_node)
    builder.add_node("live_status", live_status_node)

    # 3. Join & Planning
    builder.add_node("join", join_node)
    builder.add_node("planner", planner_node)

    # 4. Reviewer
    builder.add_node("reviewer", reviewer_node)

    # 5. Human Approval
    builder.add_node("human_approval", human_approval_node)

    # 6. Action Nodes
    builder.add_node("ticketing", ticketing_node)
    builder.add_node("kb_writeback", kb_writeback_node)
    builder.add_node("escalate", escalate_node)

    # Wire Edges
    builder.add_edge(START, "triage")

    # Fan out to parallel investigation
    builder.add_edge("triage", "retrieval")
    builder.add_edge("triage", "log_analysis")
    builder.add_edge("triage", "live_status")

    # Fan in to join
    builder.add_edge("retrieval", "join")
    builder.add_edge("log_analysis", "join")
    builder.add_edge("live_status", "join")

    # Plan
    builder.add_edge("join", "planner")
    builder.add_edge("planner", "reviewer")

    # Reviewer conditional routing
    builder.add_conditional_edges(
        "reviewer",
        route_reviewer,
        {
            "human_approval": "human_approval",
            "retrieval": "retrieval",
            "escalate": "escalate",
        },
    )

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
    builder.add_edge("ticketing", "kb_writeback")
    builder.add_edge("kb_writeback", END)
    builder.add_edge("escalate", END)

    cp = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=cp)


# Compiled default application instance
app = build_graph()

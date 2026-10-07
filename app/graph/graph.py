"""LangGraph workflow definition for L3 Incident Copilot (Triage, Retrieval, Planner)."""

from langgraph.graph import StateGraph, START, END
from app.graph.state import IncidentState
from app.graph.nodes import triage_node, retrieval_node, planner_node


def build_graph():
    """Build and compile the 3-node LangGraph workflow."""
    builder = StateGraph(IncidentState)

    builder.add_node("triage", triage_node)
    builder.add_node("retrieval", retrieval_node)
    builder.add_node("planner", planner_node)

    builder.add_edge(START, "triage")
    builder.add_edge("triage", "retrieval")
    builder.add_edge("retrieval", "planner")
    builder.add_edge("planner", END)

    return builder.compile()


# Compiled application instance
app = build_graph()


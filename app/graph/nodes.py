"""Graph nodes for triage, retrieval, and planner agents."""

import os
from typing import Any, Dict, List
from dotenv import load_dotenv

from langchain_ollama import ChatOllama
from app.graph.state import IncidentState, TriageOutput, ResolutionPlan, Claim
from app.graph.tools import call_mcp_tool

load_dotenv()

CHAT_MODEL = os.getenv("CHAT_MODEL", "llama3.2:3b")


def get_llm():
    """Return configured Ollama Chat model with temperature=0 and num_ctx=4096."""
    return ChatOllama(model=CHAT_MODEL, temperature=0, num_ctx=4096)


async def triage_node(state: IncidentState) -> Dict[str, Any]:
    """
    Triage Agent: Extracts structured JSON {severity, category, component, summary}.
    Tools are not used by the LLM here; uses structured output directly.
    """
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
        result = await structured_llm.ainvoke(prompt)
    except Exception as e:
        # Retry once on failure
        retry_prompt = prompt + f"\nPrevious attempt failed with: {str(e)}. Return valid JSON now."
        try:
            result = await structured_llm.ainvoke(retry_prompt)
        except Exception:
            result = TriageOutput(
                severity="P2",
                category="system",
                component="orders-db",
                summary=incident_text[:120],
            )

    return {"triage": result.model_dump()}


async def retrieval_node(state: IncidentState) -> Dict[str, Any]:
    """
    Retrieval Agent: Calls search_kb through MCP by code,
    keeps top 3 chunks truncated to 600 characters each.
    """
    incident_text = state.get("incident_text", "")
    triage = state.get("triage") or {}
    category = triage.get("category")

    # Search knowledge base via MCP
    try:
        raw_results = await call_mcp_tool("search_kb", {
            "query": incident_text,
            "k": 3,
            "category": category if category in {"db-lock", "queue-backlog", "cpu-spike", "batch-failure"} else None,
        })
    except Exception:
        # Fallback query without category
        raw_results = await call_mcp_tool("search_kb", {
            "query": incident_text,
            "k": 3,
        })

    evidence_list: List[Dict[str, Any]] = []
    if isinstance(raw_results, list):
        for idx, item in enumerate(raw_results[:3], start=1):
            if isinstance(item, dict):
                full_text = item.get("text", "")
                evidence_list.append({
                    "id": f"doc-{idx}",
                    "text": full_text[:600],
                    "original_id": item.get("id", f"chunk-{idx}"),
                    "score": item.get("score", 0.0),
                    "metadata": item.get("metadata", {}),
                })

    return {"evidence": evidence_list}


async def planner_node(state: IncidentState) -> Dict[str, Any]:
    """
    Planner Agent: Synthesizes root cause, fix steps, confidence, and cited claims.
    If structured JSON fails, retries once, then returns not_found plan.
    """
    incident_text = state.get("incident_text", "")
    evidence = state.get("evidence", [])

    # Format evidence blocks
    evidence_lines = []
    for doc in evidence:
        doc_id = doc.get("id", "doc")
        text = doc.get("text", "").replace("\n", " ").strip()
        evidence_lines.append(f"[{doc_id}] {text}")

    evidence_block = "\n".join(evidence_lines) if evidence_lines else "No evidence retrieved."

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

    plan_result = None
    try:
        plan_result = await structured_llm.ainvoke(prompt)
    except Exception as first_err:
        # Retry once
        retry_prompt = prompt + f"\nPrevious attempt failed with error: {str(first_err)}. Please return valid JSON strictly."
        try:
            plan_result = await structured_llm.ainvoke(retry_prompt)
        except Exception as retry_err:
            plan_result = ResolutionPlan(
                root_cause="Root cause could not be determined reliably.",
                fix_steps=["Escalate to human incident manager."],
                confidence=0.0,
                claims=[],
                not_found=[f"Structured planning parsing failed: {str(retry_err)}"],
            )

    return {"plan": plan_result.model_dump()}


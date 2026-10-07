#!/usr/bin/env python3
"""CLI runner for L3 Incident Copilot LangGraph (Triage -> Retrieval -> Planner)."""

import argparse
import asyncio
import os
import sys
import time
from typing import Optional

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.graph.graph import app as graph_app


SAMPLE_INCIDENTS = [
    (
        "Incident 1 (Database Lock)",
        "Orders database write queries are timing out with DB-1205 lock wait timeout exceeded on orders-db.",
    ),
    (
        "Incident 2 (Message Queue Lag)",
        "Service msg-queue is reporting critical consumer lag threshold exceeded with error MQ-2041 on topic orders.inbound partition 2.",
    ),
]


async def run_incident(incident_text: str, title: Optional[str] = None):
    header = title or "Running L3 Incident Resolution Workflow"
    print(f"\n{'='*75}")
    print(f"{header.upper()}")
    print(f"{'='*75}")
    print(f"Incident Text:\n  {incident_text}\n")

    start_time = time.time()

    state_input = {"incident_text": incident_text}
    final_state = await graph_app.ainvoke(state_input)

    elapsed_time = time.time() - start_time

    # Display Triage Results
    triage = final_state.get("triage") or {}
    print(f"--- TRIAGE RESULT ---")
    print(f"  Severity  : {triage.get('severity', 'N/A')}")
    print(f"  Category  : {triage.get('category', 'N/A')}")
    print(f"  Component : {triage.get('component', 'N/A')}")
    print(f"  Summary   : {triage.get('summary', 'N/A')}\n")

    # Display Retrieved Evidence
    evidence = final_state.get("evidence") or []
    print(f"--- RETRIEVED EVIDENCE ({len(evidence)} items) ---")
    for doc in evidence:
        doc_id = doc.get("id")
        orig_id = doc.get("original_id")
        score = doc.get("score", 0.0)
        snippet = doc.get("text", "").replace("\n", " ")[:150]
        print(f"  [{doc_id}] (Source: {orig_id}, Score: {score:.3f}):")
        print(f"      {snippet}...")
    print()

    # Display Generated Plan
    plan = final_state.get("plan") or {}
    print(f"--- RESOLUTION PLAN ---")
    print(f"  Root Cause : {plan.get('root_cause', 'N/A')}")
    print(f"  Confidence : {plan.get('confidence', 0.0)}")

    fix_steps = plan.get("fix_steps") or []
    print(f"  Fix Steps  :")
    for step in fix_steps:
        print(f"    - {step}")

    claims = plan.get("claims") or []
    print(f"  Claims & Citations :")
    for claim in claims:
        text = claim.get("text", "")
        sources = ", ".join(claim.get("source_ids", [])) or "None"
        print(f"    - \"{text}\" [Citing: {sources}]")

    not_found = plan.get("not_found") or []
    if not_found:
        print(f"  Unresolved / Not Found :")
        for item in not_found:
            print(f"    * {item}")

    print(f"\nExecution Time: {elapsed_time:.2f} seconds")
    print(f"{'='*75}\n")

    return final_state, elapsed_time


async def main():
    parser = argparse.ArgumentParser(description="Run L3 Incident Copilot CLI")
    parser.add_argument("--incident", type=str, help="Incident text to triage and resolve")
    args = parser.parse_args()

    if args.incident:
        await run_incident(args.incident, title="Custom Incident")
    else:
        print("No incident provided. Running two sample incidents from synthetic data:")
        for title, inc_text in SAMPLE_INCIDENTS:
            await run_incident(inc_text, title=title)


if __name__ == "__main__":
    asyncio.run(main())


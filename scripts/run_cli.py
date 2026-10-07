#!/usr/bin/env python3
"""CLI runner for full L3 Incident Copilot LangGraph with live step streaming and human approval."""

import argparse
import os
import sys
import time
import uuid
from typing import Optional
from dotenv import load_dotenv

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langgraph.types import Command
from app.graph.graph import app as graph_app
from app.mcp_server.tools.tickets import record_approval

load_dotenv()


def run_full_incident(incident_text: str, auto_approve: Optional[bool] = None, logs: Optional[str] = None):
    print(f"\n{'='*75}")
    print("STARTING FULL L3 INCIDENT RESOLUTION WORKFLOW")
    print(f"{'='*75}")
    print(f"Incident Text:\n  {incident_text}\n")

    thread_id = f"incident-{uuid.uuid4().hex[:6]}"
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "incident_text": incident_text,
        "logs": logs,
        "loops": 0,
    }

    start_time = time.time()

    print("[1/6] Running Triage, Parallel Investigation (Retrieval, Logs, Live Status) & Join...")
    for event in graph_app.stream(initial_state, config, stream_mode="updates"):
        for node_name, update in event.items():
            if node_name == "triage":
                tr = update.get("triage", {})
                print(f"  -> [Triage Complete] Severity: {tr.get('severity')}, Component: {tr.get('component')}, Category: {tr.get('category')}")
                print(f"     Summary: {tr.get('summary')}")
            elif node_name == "retrieval":
                docs = update.get("kb_docs", [])
                print(f"  -> [Retrieval Complete] Found {len(docs)} knowledge base runbooks/incidents")
            elif node_name == "log_analysis":
                lf = update.get("log_findings", {}).get("stats", {})
                print(f"  -> [Log Analysis Complete] Errors detected: {lf.get('error_count', 0)}, Codes: {lf.get('error_codes', [])}")
            elif node_name == "live_status":
                live = update.get("live_findings", {})
                alerts = live.get("active_alerts", [])
                print(f"  -> [Live Status Complete] Service Status: {live.get('status')}, Active Alerts: {len(alerts)}")
            elif node_name == "join":
                ev = update.get("evidence", [])
                print(f"  -> [Join Complete] Unified evidence pool: {len(ev)} total items")
            elif node_name == "planner":
                plan = update.get("plan", {})
                print(f"  -> [Planner Complete] Proposed Root Cause: {plan.get('root_cause')[:60]}... (Confidence: {plan.get('confidence')})")
            elif node_name == "reviewer":
                rev = update.get("review", {})
                passed = rev.get("passed", False)
                print(f"  -> [Reviewer Complete] Grounding Verification: {'PASSED' if passed else 'FAILED'}")
                if not passed:
                    print(f"     Issues: {rev.get('issues')}")

    # Inspect current state after pause / completion
    current_state = graph_app.get_state(config)

    # Check if graph paused at human_approval interrupt
    if current_state.tasks and any(t.interrupts for t in current_state.tasks):
        interrupt_val = current_state.tasks[0].interrupts[0].value
        plan = interrupt_val.get("plan", {})
        policy = interrupt_val.get("policy", {})
        triage = interrupt_val.get("triage", {})

        print(f"\n{'='*75}")
        print(f"HUMAN APPROVAL REQUIRED ({policy.get('level', 'STANDARD').upper()} POLICY)")
        print(f"{'='*75}")
        print(f"Policy Level : {policy.get('level', 'standard').upper()}")
        reasons = policy.get("reasons", [])
        if reasons:
            print("Policy Triggers:")
            for r in reasons:
                print(f"  * {r}")

        print("\nProposed Plan:")
        print(f"  Root Cause : {plan.get('root_cause')}")
        print(f"  Confidence : {plan.get('confidence')}")
        print("  Fix Steps  :")
        for step in plan.get("fix_steps", []):
            print(f"    - {step}")

        print("  Claims & Citations :")
        for claim in plan.get("claims", []):
            sources = ", ".join(claim.get("source_ids", [])) or "None"
            print(f"    - \"{claim.get('text')}\" [Citing: {sources}]")

        # Prompt user for decision
        if auto_approve is True:
            decision_input = "y"
            print("\n[Auto-Approve Enabled: Approving plan]")
        elif auto_approve is False:
            decision_input = "n"
            print("\n[Auto-Approve Disabled: Rejecting plan]")
        else:
            try:
                decision_input = input("\nApprove this resolution plan? ([y]es / [n]o): ").strip().lower()
            except EOFError:
                decision_input = "y"

        is_approved = decision_input in {"y", "yes", "approve"}

        if is_approved:
            appr = record_approval(
                incident_id=thread_id,
                approver="on-call-sre",
                decision="APPROVED",
                reason="Plan validated by human engineer",
            )
            approval_id = appr["approval_id"]
            print(f"\nRecorded Human Approval in SQLite: {approval_id}")
            resume_cmd = Command(resume={"approved": True, "approval_id": approval_id})
        else:
            appr = record_approval(
                incident_id=thread_id,
                approver="on-call-sre",
                decision="REJECTED",
                reason="Plan rejected by human engineer",
            )
            print("\nPlan rejected. Escalating to incident commander...")
            resume_cmd = Command(resume={"approved": False, "approval_id": None})

        print("\n[Resuming graph after human approval...]")
        for event in graph_app.stream(resume_cmd, config, stream_mode="updates"):
            for node_name, update in event.items():
                if node_name == "ticketing":
                    tck = update.get("ticket", {})
                    print(f"  -> [Ticketing Complete] Created Ticket ID: {tck.get('ticket_id')} (Team: {tck.get('owner_team')})")
                elif node_name == "kb_writeback":
                    kb_res = update.get("kb_writeback_result", {})
                    print(f"  -> [KB Writeback Complete] Indexed resolution ID: {kb_res.get('id')}")
                elif node_name == "escalate":
                    print("  -> [Escalated Complete] Incident routed to human queue.")

    final_state = graph_app.get_state(config)
    elapsed = time.time() - start_time

    print(f"\n{'='*75}")
    print(f"WORKFLOW COMPLETED | Final Status: {final_state.values.get('status', 'FINISHED')}")
    print(f"Total Execution Time: {elapsed:.2f} seconds")
    print(f"{'='*75}\n")

    return final_state.values, elapsed


def main():
    parser = argparse.ArgumentParser(description="Run Full L3 Incident Copilot CLI")
    parser.add_argument("--incident", type=str, help="Incident text to process")
    parser.add_argument("--auto-approve", action="store_true", help="Automatically approve human-in-the-loop step")
    parser.add_argument("--auto-reject", action="store_true", help="Automatically reject human-in-the-loop step")
    args = parser.parse_args()

    incident_text = args.incident or (
        "Orders database write queries are timing out with DB-1205 lock wait timeout exceeded on orders-db."
    )

    auto_approve = None
    if args.auto_approve:
        auto_approve = True
    elif args.auto_reject:
        auto_approve = False

    run_full_incident(incident_text=incident_text, auto_approve=auto_approve)


if __name__ == "__main__":
    main()

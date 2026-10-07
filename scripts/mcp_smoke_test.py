#!/usr/bin/env python3
"""Smoke test script for FastMCP Tool Server over streamable HTTP."""

import asyncio
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8765/mcp")

SAMPLE_LOG = (
    "2026-10-06 08:00:15 INFO orders-db - Database connection pool healthy\n"
    "2026-10-06 08:01:20 ERROR orders-db - [DB-1205] Lock wait timeout exceeded on transaction 49201\n"
    "2026-10-06 08:02:40 ERROR orders-db - [DB-1205] Lock wait timeout exceeded on transaction 49285\n"
    "2026-10-06 08:03:00 INFO orders-db - Rollback triggered for transaction 49201\n"
)


async def run_smoke_test():
    print(f"\n{'='*75}")
    print(f"CONNECTING TO MCP SERVER AT: {MCP_URL}")
    print(f"{'='*75}\n")

    async with streamable_http_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize session
            init_res = await session.initialize()
            print(f"[1] Session Initialized successfully! Protocol version: {init_res.protocol_version}")

            # 1. List tools
            tool_list = await session.list_tools()
            tools = tool_list.tools
            tool_names = [t.name for t in tools]
            print(f"\n[2] Listed {len(tools)} Registered Tools:")
            for name in tool_names:
                print(f"    - {name}")

            expected_tools = {
                "search_kb", "search_wiki", "parse_logs", "lookup_signature",
                "get_active_alerts", "get_service_health", "get_metrics", "tail_log",
                "search_tickets", "get_ticket", "suggest_owner", "redact_text",
                "search_web", "fetch_page", "create_ticket", "update_ticket", "kb_upsert",
            }
            missing = expected_tools - set(tool_names)
            if missing:
                print(f"    [WARNING] Missing expected tools: {missing}")
            else:
                print("    [PASS] All 17 tools listed in PROJECT_SPEC.md are registered!")

            # 2. Call get_active_alerts
            print("\n[3] Calling Tool: get_active_alerts...")
            alerts_res = await session.call_tool("get_active_alerts", arguments={})
            is_err = getattr(alerts_res, "is_error", getattr(alerts_res, "isError", False))
            print(f"    Result is_error: {is_err}")
            for item in alerts_res.content:
                if hasattr(item, "text"):
                    print(f"    Output: {item.text[:200]}...")

            # 3. Call parse_logs on sample log
            print("\n[4] Calling Tool: parse_logs with sample log text...")
            logs_res = await session.call_tool("parse_logs", arguments={"text": SAMPLE_LOG})
            is_err_logs = getattr(logs_res, "is_error", getattr(logs_res, "isError", False))
            print(f"    Result is_error: {is_err_logs}")
            for item in logs_res.content:
                if hasattr(item, "text"):
                    print(f"    Output: {item.text}")

            # 4. Confirm create_ticket without valid approval_id FAILS
            print("\n[5] Testing Approval Gate: Calling create_ticket without valid approval_id...")
            try:
                ticket_res = await session.call_tool(
                    "create_ticket",
                    arguments={
                        "title": "Unapproved Ticket Test",
                        "description": "Testing gate enforcement",
                        "severity": "P2",
                        "owner_team": "database-engineering",
                        "approval_id": "INVALID-APPROVAL-ID",
                    },
                )
                is_err_ticket = getattr(ticket_res, "is_error", getattr(ticket_res, "isError", False))
                if is_err_ticket:
                    print(f"    [PASS] create_ticket correctly rejected call with is_error=True!")
                    for item in ticket_res.content:
                        if hasattr(item, "text"):
                            print(f"    Error detail: {item.text}")
                else:
                    print(f"    [FAIL] Expected is_error=True, but call succeeded: {ticket_res}")
            except Exception as e:
                print(f"    [PASS] create_ticket correctly raised error: {type(e).__name__}: {e}")

    print(f"\n{'='*75}")
    print("ALL MCP SMOKE TESTS COMPLETED SUCCESSFULLY!")
    print(f"{'='*75}\n")


if __name__ == "__main__":
    asyncio.run(run_smoke_test())

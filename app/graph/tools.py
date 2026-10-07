"""MCP tools loader and unpacker using langchain-mcp-adapters."""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8765/mcp")

# Allowed tool names per agent
AGENT_ALLOWED_TOOLS = {
    "triage": [],
    "retrieval": ["search_kb", "search_wiki"],
    "logs": ["parse_logs", "lookup_signature"],
    "live": ["get_active_alerts", "get_service_health", "get_metrics", "tail_log"],
    "planner": [],
    "reviewer": [],
    "ticketing": ["create_ticket", "update_ticket", "search_tickets", "get_ticket", "suggest_owner", "kb_upsert"],
    "research": ["redact_text", "search_web", "fetch_page"],
}

_mcp_client: Optional[MultiServerMCPClient] = None
_cached_tools: Dict[str, Any] = {}


def get_mcp_client() -> MultiServerMCPClient:
    """Return singleton MultiServerMCPClient instance."""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MultiServerMCPClient({
            "copilot": {
                "url": MCP_URL,
                "transport": "streamable_http",
            }
        })
    return _mcp_client


async def load_all_mcp_tools() -> Dict[str, Any]:
    """Load all tools from the MCP server and cache by tool name."""
    global _cached_tools
    if not _cached_tools:
        client = get_mcp_client()
        tools = await client.get_tools()
        _cached_tools = {t.name: t for t in tools}
    return _cached_tools


def unpack_tool_result(result: Any) -> Any:
    """
    Unpack tool results whether they arrive as JSON text, list of text blocks,
    or native Python objects.
    """
    if result is None:
        return None

    if isinstance(result, list):
        if len(result) == 1 and isinstance(result[0], dict) and result[0].get("type") == "text":
            text = result[0].get("text", "")
            try:
                return json.loads(text)
            except Exception:
                return text

        items = []
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                try:
                    items.append(json.loads(text))
                except Exception:
                    items.append(text)
            else:
                items.append(item)

        if len(items) == 1 and isinstance(items[0], (list, dict)):
            return items[0]
        return items

    elif isinstance(result, str):
        try:
            return json.loads(result)
        except Exception:
            return result

    elif isinstance(result, dict):
        return result

    return result


async def get_agent_tools(agent_name: str) -> List[Any]:
    """
    Return only the allowed MCP tools for a specific agent.
    """
    allowed_names = set(AGENT_ALLOWED_TOOLS.get(agent_name.lower(), []))
    all_tools = await load_all_mcp_tools()
    return [tool for name, tool in all_tools.items() if name in allowed_names]


async def call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """
    Call an MCP tool by name and return unpacked results.
    """
    all_tools = await load_all_mcp_tools()
    if tool_name not in all_tools:
        raise ValueError(f"MCP tool '{tool_name}' not found. Available: {list(all_tools.keys())}")

    tool = all_tools[tool_name]
    raw_res = await tool.ainvoke(arguments)
    return unpack_tool_result(raw_res)


def call_mcp_tool_sync(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """Synchronous wrapper to call an MCP tool by name and return unpacked results."""
    return asyncio.run(call_mcp_tool(tool_name, arguments))


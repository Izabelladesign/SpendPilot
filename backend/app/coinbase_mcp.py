"""Opt-in Coinbase MCP read-only tool call (never a payment executor)."""
import json
import os
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.payment_auth import require_payment_operator

router = APIRouter(prefix="/api/coinbase", tags=["Coinbase MCP"])

class CoinbaseMCPRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)

@router.post("/mcp/read-only")
async def coinbase_mcp_read_only(
    payload: CoinbaseMCPRequest,
    operator: str = Depends(require_payment_operator),
):
    """Invoke one explicitly configured read-only MCP tool; no wallet actions."""
    if os.getenv("SPENDPILOT_COINBASE_MCP_ENABLED") != "true":
        raise HTTPException(403, "Coinbase MCP integration disabled")
    url = os.getenv("COINBASE_MCP_URL", "")
    tool_name = os.getenv("COINBASE_MCP_READ_TOOL", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(503, "Configure an HTTPS Coinbase MCP URL")
    if not tool_name or any(word in tool_name.lower() for word in (
        "send", "transfer", "pay", "swap", "sign", "trade", "execute", "broadcast", "withdraw"
    )):
        raise HTTPException(503, "Configure an explicitly read-only Coinbase MCP tool")
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError as exc:
        raise HTTPException(503, "Install the optional mcp Python package") from exc
    try:
        async with streamablehttp_client(url) as (reader, writer, _):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                available = await session.list_tools()
                if tool_name not in {t.name for t in available.tools}:
                    raise HTTPException(409, "Configured tool not offered by MCP server")
                result = await session.call_tool(tool_name, payload.arguments)
    except HTTPException:
        raise
    except Exception as exc:
        # Never leak tokens, headers, provider errors, or MCP response secrets.
        raise HTTPException(502, f"MCP call failed: {type(exc).__name__}") from exc
    # Do not return arbitrary tool response content (may include wallet data).
    return {
        "integration": "Coinbase MCP",
        "tool": tool_name,
        "invoked": True,
        "tool_reported_error": bool(result.isError),
        "payment_executed": False,
        "result_redacted": True,
    }

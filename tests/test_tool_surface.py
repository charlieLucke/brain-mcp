"""Was ein MCP-Client von diesem Server bekommt, nicht was der Code zurueckgibt.

Die Tool-Definitionen stehen in jeder Anfrage jeder Sitzung, die Antworten bleiben
bis zum Ende im Verlauf. Beides waechst unbemerkt, ein hilfreicher Satz nach dem
anderen. Diese Tests messen deshalb ueber das MCP-Protokoll, wie ein Client.

Getrieben mit `anyio.run` wie tests/test_auth.py, ohne pytest-asyncio.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import anyio
from fastmcp import Client
from mcp.types import Tool

from brain_mcp.schemas import DomainsResponse

# Gemessen am 24.10.2026: 9 474 Zeichen fuer zwoelf Tools, ohne Output-Schemas.
TOOL_SURFACE_BUDGET = 11_400


def _list_tools() -> list[Tool]:
    from brain_mcp.mcp_server import mcp

    async def run() -> list[Tool]:
        async with Client(mcp) as client:
            return await client.list_tools()

    return anyio.run(run)


def _surface_size(tools: list[Tool]) -> int:
    return sum(
        len(
            json.dumps(
                {"name": t.name, "description": t.description, "inputSchema": t.inputSchema},
                ensure_ascii=False,
            )
        )
        + (len(json.dumps(t.outputSchema)) if t.outputSchema else 0)
        for t in tools
    )


def test_no_tool_carries_an_output_schema() -> None:
    mit_schema = [t.name for t in _list_tools() if t.outputSchema]
    assert not mit_schema, (
        f"{mit_schema} tragen ein Output-Schema. Damit schickt FastMCP jede Antwort "
        "doppelt, und Claude Code zeigt dem Modell den JSON-String statt des Markdowns. "
        "Den Decorator als @mcp.tool(output_schema=None) schreiben."
    )


def test_the_tool_surface_stays_within_budget() -> None:
    size = _surface_size(_list_tools())
    assert size <= TOOL_SURFACE_BUDGET, (
        f"Die Definitionen sind auf {size} Zeichen gewachsen, sie gehen mit jeder Anfrage "
        "mit. Erst nachsehen, was gewachsen ist, bevor die Grenze steigt: eine "
        "Beschreibung verdient ihre Laenge, wenn sie aendert, was der Agent tut."
    )


def test_a_call_returns_one_text_block_and_no_structured_content() -> None:
    from brain_mcp import mcp_server

    async def run() -> tuple[int, object]:
        async with Client(mcp_server.mcp) as client:
            result = await client.call_tool("list_domains", {})
            return len(result.content), result.structured_content

    antwort = DomainsResponse(domains=["titan"], counts={"titan": 3})
    with patch.object(mcp_server._client, "list_domains", return_value=antwort):
        bloecke, strukturiert = anyio.run(run)

    assert bloecke == 1
    assert strukturiert is None

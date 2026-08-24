import asyncio
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["-m", "src.mcp_server.server"],
)


@asynccontextmanager
async def mcp_session():
    """Spawns the MCP server as a subprocess over stdio for the life of the session."""
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_tools_async(calls: list[tuple[str, dict]]) -> list[str]:
    """
    Calls each (tool_name, arguments) pair in `calls` against a single MCP
    server session (one subprocess, reused across all calls) and returns
    each tool's text result in order.
    """
    results = []
    async with mcp_session() as session:
        for tool_name, arguments in calls:
            result = await session.call_tool(tool_name, arguments)
            if result.isError:
                raise RuntimeError(f"MCP tool '{tool_name}' returned an error: {result.content}")
            text_blocks = [block.text for block in result.content if block.type == "text"]
            results.append("".join(text_blocks))
    return results


def call_tools(calls: list[tuple[str, dict]]) -> list[str]:
    """Synchronous wrapper around call_tools_async, for use in the rest of this sync codebase."""
    return asyncio.run(call_tools_async(calls))

"""Test-only stdio server: real Python MCP facade, deterministic upstream boundary."""

import asyncio
import json
from typing import Any

from ccx.runtime import mcp_server


async def stub_upstream(tool: str, arguments: dict[str, Any], *, wait: bool = False) -> str:
    await asyncio.sleep(0.01)
    return json.dumps({"upstream_tool": tool, "arguments": arguments, "wait": wait})


if __name__ == "__main__":
    mcp_server.upstream = stub_upstream
    mcp_server.mcp.run(transport="stdio")

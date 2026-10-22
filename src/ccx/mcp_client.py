"""MCP transport, with session lifetime covering asynchronous upstream indexing."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

from ccx.errors import CcxError


def result_text(result: CallToolResult) -> str:
    text = "\n".join(block.text for block in result.content if block.type == "text")
    if result.isError:
        raise CcxError(text)
    return text


@asynccontextmanager
async def session(
    command: str, args: list[str], timeout: float, env: dict[str, str] | None = None
) -> AsyncGenerator[ClientSession, None]:
    params = StdioServerParameters(command=command, args=args, env=env)
    try:
        async with asyncio.timeout(timeout):
            async with stdio_client(params) as (read, write):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=timeout)
                ) as client:
                    await client.initialize()
                    yield client
    except ExceptionGroup as exc:

        def messages(error: BaseException) -> list[str]:
            if isinstance(error, BaseExceptionGroup):
                return [text for nested in error.exceptions for text in messages(nested)]
            return [str(error)]

        raise CcxError("MCP operation failed: " + "; ".join(messages(exc))) from exc
    except TimeoutError as exc:
        raise CcxError(f"MCP operation timed out after {timeout}s.") from exc


async def call(
    command: str, args: list[str], tool: str, arguments: dict[str, Any], timeout: float
) -> str:
    async with session(command, args, timeout) as client:
        return result_text(await client.call_tool(tool, arguments))

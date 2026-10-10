"""Policy and lifecycle facade over the pinned upstream MCP server.

The upstream automatic timer is disabled by a narrow vendored entrypoint. Only this
facade invokes updates. FileLock serializes independent CLI/OpenCode MCP connections.
"""

import asyncio
import json
import os
from functools import partial
from pathlib import Path
from typing import Any

from anyio import to_thread
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMCPSettings

from ccx.errors import CcxError
from ccx.io import write_json
from ccx.mcp_client import result_text, session
from ccx.runtime.state import (
    embedding_identity,
    lock,
    root,
    snapshot_status,
    state_dir,
    validate_embedding,
    validate_path,
)

# MCP 1.26 Settings refers to FastMCP before that class is defined. Resolve the
# forward reference after the SDK module has loaded, before settings sources run.
# This is a no-op on SDK versions which already build the complete schema.
FastMCPSettings.model_rebuild()
mcp = FastMCP("ccx-claude-context")
UPSTREAM = Path(__file__).with_name("upstream.mjs")
INCREMENTAL = Path(__file__).with_name("incremental.mjs")


async def upstream(tool: str, arguments: dict[str, Any], *, wait: bool = False) -> str:
    timeout = float(os.environ.get("CCX_INDEX_TIMEOUT", "3600"))
    async with session("node", [str(UPSTREAM)], timeout, dict(os.environ)) as client:
        answer = result_text(await client.call_tool(tool, arguments))
        if not wait:
            return answer
        # index_codebase starts a background promise; keep stdio alive until it finishes.
        while True:
            status = snapshot_status()
            if status["status"] == "indexed":
                verification = result_text(
                    await client.call_tool(
                        "ccx_verify_index",
                        {"path": arguments["path"], "expected": status.get("totalChunks")},
                    )
                )
                status["verification"] = verification
                return json.dumps(status)
            if status["status"] in ("failed", "indexfailed", "sync_failed"):
                raise CcxError(f"Index failed: {status.get('errorMessage', status)}")
            await asyncio.sleep(0.25)


def run_upstream(tool: str, arguments: dict[str, Any], *, wait: bool = False) -> str:
    return asyncio.run(upstream(tool, arguments, wait=wait))


def index_codebase(path: str, force: bool = False) -> str:
    """Build or incrementally refresh the project's semantic index."""
    validate_path(path)
    with lock():
        imported = state_dir() / "imported.json"
        force = force or imported.exists()
        if not force:
            validate_embedding()
        status = snapshot_status()
        if not force and status["status"] in ("failed", "indexfailed", "sync_failed"):
            raise CcxError("Previous index failed. Run ccx reindex --full to recover safely.")
        if force or status["status"] not in ("indexed", "sync_failed"):
            output = run_upstream(
                "index_codebase",
                {
                    "path": str(root()),
                    "force": force,
                    "ignorePatterns": [
                        os.environ["CCX_GRAPH_OUT"] + "/**",
                        ".opencode/**",
                        ".env",
                        ".env.*",
                        "*.pem",
                        "*.key",
                    ],
                },
                wait=True,
            )
        else:
            from ccx.process import SubprocessRunner

            output = (
                SubprocessRunner()
                .run(
                    ["node", str(INCREMENTAL)],
                    timeout=float(os.environ.get("CCX_INDEX_TIMEOUT", "3600")),
                )
                .stdout
            )
        write_json(state_dir() / "embedding.json", embedding_identity())
        imported.unlink(missing_ok=True)
        return output


def search_code(path: str, query: str, limit: int = 10) -> str:
    """Semantic implementation search. Does not modify the index."""
    validate_path(path)
    with lock():
        validate_embedding()
        return run_upstream(
            "search_code", {"path": str(root()), "query": query, "limit": min(max(limit, 1), 50)}
        )


def get_indexing_status(path: str) -> str:
    """Report status and collection existence without creating an index."""
    validate_path(path)
    with lock():
        upstream_status = run_upstream("get_indexing_status", {"path": str(root())})
        status = snapshot_status()
        status["details"] = upstream_status
        status["embedding"] = embedding_identity()
        return json.dumps(status)


def clear_index(path: str) -> str:
    """DESTRUCTIVE: delete this project's semantic index, not its source or graph."""
    validate_path(path)
    with lock():
        result = run_upstream("clear_index", {"path": str(root())})
        (state_dir() / "embedding.json").unlink(missing_ok=True)
        return result


@mcp.tool(name="index_codebase")
async def index_codebase_tool(path: str, force: bool = False) -> str:
    """Build or incrementally refresh the project's semantic index."""
    # The synchronous operation owns the file lock, subprocesses, and its own
    # upstream event loop. Run the WHOLE operation on one worker thread.
    # Do not abandon the worker on AnyIO cancellation while it still owns a lock.
    return await to_thread.run_sync(partial(index_codebase, path, force), abandon_on_cancel=False)


@mcp.tool(name="search_code")
async def search_code_tool(path: str, query: str, limit: int = 10) -> str:
    """Semantic implementation search. Does not modify the index."""
    return await to_thread.run_sync(
        partial(search_code, path, query, limit), abandon_on_cancel=False
    )


@mcp.tool(name="get_indexing_status")
async def get_indexing_status_tool(path: str) -> str:
    """Report status and collection existence without creating an index."""
    return await to_thread.run_sync(partial(get_indexing_status, path), abandon_on_cancel=False)


@mcp.tool(name="clear_index")
async def clear_index_tool(path: str) -> str:
    """DESTRUCTIVE: delete this project's semantic index, not its source or graph."""
    return await to_thread.run_sync(partial(clear_index, path), abandon_on_cancel=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")

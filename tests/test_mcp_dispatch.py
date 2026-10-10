"""Regression tests must enter through FastMCP, not just call sync helpers directly."""

import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from ccx.mcp_client import result_text, session
from ccx.runtime import mcp_server


@pytest.fixture
def project_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repository"
    repo.mkdir()
    for key, value in {
        "HOME": str(tmp_path / "home"),
        "CCX_PROJECT_PATH": str(repo),
        "CCX_GRAPH_OUT": "graphify-out",
        "CCX_INDEX_TIMEOUT": "5",
        "EMBEDDING_MODEL": "test-embedding",
        "EMBEDDING_PROVIDER": "OpenAI",
        "OPENAI_BASE_URL": "http://unused.test/v1",
        "OPENAI_API_KEY": "test",
    }.items():
        monkeypatch.setenv(key, value)
    return repo


@pytest.mark.parametrize(
    "tool,extra",
    [
        ("index_codebase", {}),
        ("search_code", {"query": "authentication"}),
        ("get_indexing_status", {}),
        ("clear_index", {}),
    ],
)
def test_real_dispatch_moves_sync_work_off_server_loop(
    project_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    extra: dict[str, Any],
) -> None:
    main_thread = threading.get_ident()
    worker_threads: list[int] = []

    async def fake_upstream(name: str, arguments: dict[str, Any], *, wait: bool = False) -> str:
        worker_threads.append(threading.get_ident())
        await asyncio.sleep(0)
        return "upstream success"

    monkeypatch.setattr(mcp_server, "upstream", fake_upstream)

    async def dispatch() -> Any:
        return await mcp_server.mcp.call_tool(
            tool,
            {"path": str(project_environment), **extra},
        )

    result = asyncio.run(dispatch())
    assert "upstream success" in str(result)
    assert worker_threads and all(thread != main_thread for thread in worker_threads)


def test_blocking_tool_does_not_block_event_loop(
    project_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heartbeat = threading.Event()

    def blocking_upstream(*args: Any, **kwargs: Any) -> str:
        assert heartbeat.wait(1), "The MCP event loop was blocked by synchronous work."
        return "done"

    monkeypatch.setattr(mcp_server, "run_upstream", blocking_upstream)

    async def dispatch() -> None:
        asyncio.get_running_loop().call_later(0.05, heartbeat.set)
        await mcp_server.mcp.call_tool(
            "search_code",
            {"path": str(project_environment), "query": "code"},
        )

    asyncio.run(dispatch())


def test_stdio_facade_all_tools_without_runtime_warnings(
    project_environment: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    fixture = Path(__file__).parent / "fixtures/mcp_stub_server.py"

    async def exercise() -> None:
        async with session(
            sys.executable,
            ["-W", "error", str(fixture)],
            20,
            dict(os.environ),
        ) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} == {
                "index_codebase",
                "search_code",
                "get_indexing_status",
                "clear_index",
            }
            for tool, extra in (
                ("index_codebase", {}),
                ("search_code", {"query": "authentication"}),
                ("get_indexing_status", {}),
                ("clear_index", {}),
            ):
                result = await client.call_tool(tool, {"path": str(project_environment), **extra})
                assert not result.isError
                assert tool in result_text(result)

    asyncio.run(exercise())
    stderr = capfd.readouterr().err
    assert "never awaited" not in stderr
    assert "IncompleteFieldDefinitionWarning" not in stderr


def test_server_import_resolves_settings_before_construction() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "error",
            "-c",
            "from ccx.runtime.mcp_server import mcp; print(mcp.name)",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "ccx-claude-context" in result.stdout

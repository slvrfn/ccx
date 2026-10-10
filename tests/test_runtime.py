import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from mcp.types import CallToolResult, TextContent

from ccx.errors import CcxError
from ccx.graph.output import claim_output
from ccx.io import write_json
from ccx.mcp_client import result_text
from ccx.process import Result, SubprocessRunner
from ccx.runtime import graph_build, mcp_server, state


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CCX_PROJECT_PATH", str(root))
    for key, value in {
        "CCX_GRAPH_OUT": "artifacts/graph",
        "CCX_GRAPH_SEMANTIC": "false",
        "CCX_INFERENCE_BASE_URL": "http://inference/v1",
        "CCX_INFERENCE_API_KEY": "inference-key",
        "CCX_INFERENCE_MODEL": "coder",
        "CCX_INDEX_TIMEOUT": "5",
        "OPENAI_BASE_URL": "http://embedding/v1",
        "OPENAI_API_KEY": "embedding-key",
        "EMBEDDING_MODEL": "embedder",
        "EMBEDDING_PROVIDER": "OpenAI",
    }.items():
        monkeypatch.setenv(key, value)
    return root


def test_mcp_error_propagation() -> None:
    result = CallToolResult(content=[TextContent(type="text", text="bad")], isError=True)
    with pytest.raises(CcxError, match="bad"):
        result_text(result)


def test_runtime_path_fence(runtime: Path) -> None:
    state.validate_path(str(runtime))
    with pytest.raises(CcxError):
        state.validate_path("/etc")


def test_embedding_change_blocks_search(runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_json(state.state_dir() / "embedding.json", state.embedding_identity())
    monkeypatch.setenv("EMBEDDING_MODEL", "different")
    with pytest.raises(CcxError, match="changed"):
        state.validate_embedding()


def test_graph_initial_code_only(runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mock = Mock(return_value=Result())
    monkeypatch.setattr(SubprocessRunner, "run", mock)
    graph_build.build()
    args = mock.call_args_list[0].args[0]
    assert "extract" in args and "--code-only" in args
    assert str(runtime / "artifacts/graph") in args
    assert mock.call_args.kwargs["env"]["OPENAI_API_KEY"] == "inference-key"


def test_graph_incremental_and_full(runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claim_output(runtime / "artifacts/graph")
    write_json(runtime / "artifacts/graph/graph.json", {"nodes": []})
    mock = Mock(return_value=Result())
    monkeypatch.setattr(SubprocessRunner, "run", mock)
    graph_build.build()
    assert mock.call_args.args[0] == ["graphify", "update", str(runtime)]
    graph_build.build(full=True)
    assert "--force" in mock.call_args_list[-2].args[0]


def test_graph_semantic_uses_inference(runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCX_GRAPH_SEMANTIC", "true")
    mock = Mock(return_value=Result())
    monkeypatch.setattr(SubprocessRunner, "run", mock)
    graph_build.build()
    assert mock.call_args_list[0].args[0][-2:] == ["--backend", "openai"]
    assert "--code-only" not in mock.call_args_list[0].args[0]
    assert mock.call_args.kwargs["env"]["OPENAI_BASE_URL"] == "http://inference/v1"


def test_index_first_build_and_identity(runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mock = Mock(return_value="done")
    monkeypatch.setattr(mcp_server, "run_upstream", mock)
    assert mcp_server.index_codebase(str(runtime)) == "done"
    assert mock.call_args.kwargs["wait"]
    assert (state.state_dir() / "embedding.json").exists()


def test_incremental_uses_one_shot_node(runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "snapshot_status", lambda: {"status": "indexed"})
    mock = Mock(return_value=Result('{"added":1}'))
    monkeypatch.setattr(SubprocessRunner, "run", mock)
    assert "added" in mcp_server.index_codebase(str(runtime))
    assert "incremental.mjs" in mock.call_args.args[0][-1]


def test_import_forces_first_refresh(runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_json(state.state_dir() / "imported.json", {})
    monkeypatch.setattr(mcp_server, "snapshot_status", lambda: {"status": "indexed"})
    mock = Mock(return_value="rebuilt")
    monkeypatch.setattr(mcp_server, "run_upstream", mock)
    assert mcp_server.index_codebase(str(runtime)) == "rebuilt"
    assert mock.call_args.args[1]["force"]
    assert not (state.state_dir() / "imported.json").exists()


def test_failed_increment_requires_explicit_full(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_server, "snapshot_status", lambda: {"status": "indexfailed"})
    with pytest.raises(CcxError, match="--full"):
        mcp_server.index_codebase(str(runtime))


def test_search_limit_clamped(runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mock = Mock(return_value="found")
    monkeypatch.setattr(mcp_server, "run_upstream", mock)
    mcp_server.search_code(str(runtime), "question", limit=1000)
    assert mock.call_args.args[1]["limit"] == 50


def test_status_reports_snapshot(runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "run_upstream", lambda *args, **kwargs: "upstream text")
    assert json.loads(mcp_server.get_indexing_status(str(runtime)))["status"] == "not_found"


def test_mcp_waits_for_actual_background_task(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class Client:
        async def call_tool(self, *args: Any, **kwargs: Any) -> CallToolResult:
            calls.append(args[0])
            text = (
                json.dumps({"status": "indexed", "totalChunks": 4})
                if (args[0] == "ccx_wait_index")
                else "started"
            )
            return CallToolResult(content=[TextContent(type="text", text=text)])

    @asynccontextmanager
    async def fake_session(*args: Any, **kwargs: Any) -> Any:
        yield Client()

    monkeypatch.setattr(mcp_server, "session", fake_session)
    # Even a permanently nonterminal disk snapshot cannot keep the client waiting.
    monkeypatch.setattr(mcp_server, "snapshot_status", lambda: {"status": "indexing"})
    result = asyncio.run(mcp_server.upstream("index_codebase", {"path": str(runtime)}, wait=True))
    assert json.loads(result)["totalChunks"] == 4
    assert calls == ["index_codebase", "ccx_wait_index", "ccx_verify_index"]


@pytest.mark.parametrize(
    "status",
    [
        {"status": "indexed", "totalChunks": 0},
        {"status": "indexing", "indexingPercentage": 100},
    ],
)
def test_completed_task_cannot_leave_nonterminal_client_wait(
    runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: dict[str, Any],
) -> None:
    class Client:
        async def call_tool(self, name: str, *args: Any, **kwargs: Any) -> CallToolResult:
            value = json.dumps(status) if name == "ccx_wait_index" else "started"
            return CallToolResult(content=[TextContent(type="text", text=value)])

    @asynccontextmanager
    async def fake_session(*args: Any, **kwargs: Any) -> Any:
        yield Client()

    monkeypatch.setattr(mcp_server, "session", fake_session)
    with pytest.raises(CcxError, match="nonempty"):
        asyncio.run(mcp_server.upstream("index_codebase", {"path": str(runtime)}, wait=True))


def test_background_task_failure_is_propagated(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Client:
        async def call_tool(self, name: str, *args: Any, **kwargs: Any) -> CallToolResult:
            failed = name == "ccx_wait_index"
            return CallToolResult(
                content=[TextContent(type="text", text="zero chunks" if failed else "started")],
                isError=failed,
            )

    @asynccontextmanager
    async def fake_session(*args: Any, **kwargs: Any) -> Any:
        yield Client()

    monkeypatch.setattr(mcp_server, "session", fake_session)
    with pytest.raises(CcxError, match="zero chunks"):
        asyncio.run(mcp_server.upstream("index_codebase", {"path": str(runtime)}, wait=True))


def test_subprocess_runner_captures_and_reports_failure() -> None:
    runner = SubprocessRunner()
    assert runner.run(["printf", "hello"]).stdout == "hello"
    with pytest.raises(CcxError, match="Executable not found"):
        runner.run(["ccx-impossible-executable-name"])
    with pytest.raises(CcxError, match="exit 1"):
        runner.run(["false"])

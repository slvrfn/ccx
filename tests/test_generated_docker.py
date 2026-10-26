import json
import os
from pathlib import Path

import pytest
import yaml

from ccx.config import Settings, asset_root
from ccx.docker import Docker
from ccx.errors import CcxError
from ccx.generated import opencode_config, write_project_files
from ccx.graph import Graphify
from ccx.graph.serve import READ_TOOLS
from ccx.project import Project
from ccx.semantic import ClaudeContext
from tests.conftest import FakeRunner


def test_permissions_are_conservative(settings: Settings, project: Project) -> None:
    config = opencode_config(settings, project, {"enabled": True}, {"enabled": True})
    permission = config["permission"]
    for name in READ_TOOLS:
        assert permission[f"graphify_{name}"] == "allow"
    assert permission["*"] == "ask"
    assert permission["graphify_*"] == "ask"
    assert permission["claude-context_clear_index"] == "ask"
    assert permission["claude-context_index_codebase"] == "allow"


def test_no_graph_means_no_server(settings: Settings, project: Project) -> None:
    disabled = Project(project.path, project.slug, False)
    config = opencode_config(settings, disabled, {}, {})
    assert "graphify" not in config["mcp"]
    assert "claude-context" in config["mcp"]


def test_generated_files_do_not_embed_keys(
    settings: Settings, project: Project, tmp_path: Path
) -> None:
    configured = Settings(
        settings.home,
        {**settings.values, "INFERENCE_API_KEY": "secret-one", "EMBEDDING_API_KEY": "secret-two"},
    )
    state = tmp_path / "state"
    write_project_files(configured, project, state, {}, {})
    config = (state / "opencode.json").read_text()
    assert "secret-one" not in config and "secret-two" not in config
    assert "CCX_INFERENCE_API_KEY=secret-one" in (state / "runtime.env").read_text()
    assert "OPENAI_API_KEY=secret-two" in (state / "runtime.env").read_text()
    before = (project.path / ".gitignore").read_text()
    write_project_files(configured, project, state, {}, {})
    assert (project.path / ".gitignore").read_text() == before
    assert (project.path / ".opencode/skills/ccx-context/SKILL.md").exists()


def test_generated_files_refuse_symlink(
    settings: Settings, project: Project, tmp_path: Path
) -> None:
    (project.path / ".opencode").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(CcxError, match="symlink"):
        write_project_files(settings, project, tmp_path / "state", {}, {})


def test_uv_settings_forwarded_to_container(
    settings: Settings, project: Project, tmp_path: Path
) -> None:
    configured = Settings(
        settings.home,
        {
            **settings.values,
            "UV_HTTP_TIMEOUT": "600",
            "UV_CONCURRENT_DOWNLOADS": "1",
            "OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS": "3600000",
        },
    )
    state = tmp_path / "state"
    write_project_files(configured, project, state, {}, {})
    values = dict(line.split("=", 1) for line in (state / "runtime.env").read_text().splitlines())
    assert values["UV_HTTP_TIMEOUT"] == "600"
    assert values["UV_CONCURRENT_DOWNLOADS"] == "1"
    assert values["OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS"] == "3600000"
    leading_home = os.environ.get("CCX_SAFE_HOME", "/home/ccx")
    assert values["UV_CACHE_DIR"] == f"{leading_home}/.cache/uv"
    assert values["UV_PROJECT_ENVIRONMENT"] == "/home/ccx/.venvs/project"
    assert values["UV_LINK_MODE"] == "copy"
    assert "UV_HTTP_RETRIES" not in values  # Not available in pinned uv 0.6.14.


def test_docker_command_isolated(
    settings: Settings, project: Project, runner: FakeRunner, tmp_path: Path
) -> None:
    docker = Docker(settings, runner)
    docker.ensure(project, tmp_path)
    run = next(call for call in runner.calls if call[:2] == ["docker", "run"])
    assert "--privileged" not in run
    assert "--cap-drop=ALL" in run
    assert "--security-opt" in run
    assert "host.docker.internal:host-gateway" in run
    assert "context-net" in run
    assert not any("docker.sock" in argument for argument in run)
    assert f"type=bind,src={project.path},dst={project.mount}" in run
    assert f"type=volume,src={project.volume},dst=/home/ccx" in run


def test_exec_never_interpolates_shell(
    settings: Settings, project: Project, runner: FakeRunner
) -> None:
    query = 'hello; "$(touch /tmp/unsafe)"'
    Graphify(Docker(settings, runner)).query(project, query)
    assert query in runner.calls[-1]
    assert "sh" not in runner.calls[-1]


def test_platform_waits_for_health(settings: Settings, runner: FakeRunner) -> None:
    Docker(settings, runner).platform_up(ui=True)
    assert "--wait" in runner.calls[-1]
    assert "--profile" in runner.calls[-1]
    assert "ui" in runner.calls[-1]


def test_mcp_commands(settings: Settings, project: Project, runner: FakeRunner) -> None:
    semantic = ClaudeContext(settings).mcp_config(project)
    graph = Graphify(Docker(settings, runner)).mcp_config(project)
    assert semantic["command"] == ["python", "-m", "ccx.runtime.mcp_server"]
    assert graph["command"][-1] == f"{project.mount}/graphify-out/graph.json"
    json.dumps(semantic)


def test_compose_persistence_and_loopback() -> None:
    data = yaml.safe_load((asset_root() / "compose.yaml").read_text())
    assert set(data["services"]) == {"milvus", "minio", "etcd", "attu"}
    for service in data["services"].values():
        for binding in service.get("ports", []):
            assert binding.startswith("127.0.0.1:")
    assert data["services"]["attu"]["profiles"] == ["ui"]
    assert len(data["volumes"]) == 3
    assert data["networks"]["context-net"]["name"] == "context-net"

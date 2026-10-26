from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from ccx.cli import cli
from ccx.config import Settings
from ccx.errors import CcxError
from ccx.project import Project
from ccx.service import Application
from tests.conftest import FakeRunner


def application(settings: Settings, runner: FakeRunner) -> Application:
    app = Application(settings, runner)
    app.docker.inspect_running = Mock(return_value=True)
    app.semantic.build = Mock(return_value={"indexed": True})
    app.graph.build = Mock(return_value={"nodes": 3})
    return app


def test_refresh_calls_both(settings: Settings, runner: FakeRunner, project: Project) -> None:
    app = application(settings, runner)
    result = app.refresh(project, full=True)
    assert set(result) == {"semantic", "graph"}
    app.semantic.build.assert_called_once_with(project, full=True)
    app.graph.build.assert_called_once_with(project, full=True)


def test_graph_failure_does_not_skip_semantic(
    settings: Settings, runner: FakeRunner, project: Project
) -> None:
    app = application(settings, runner)
    app.graph.build.side_effect = CcxError("parser error")
    with pytest.raises(CcxError, match="graph: parser error"):
        app.refresh(project)
    app.semantic.build.assert_called_once()


def test_semantic_failure_does_not_skip_graph(
    settings: Settings, runner: FakeRunner, project: Project
) -> None:
    app = application(settings, runner)
    app.semantic.build.side_effect = CcxError("endpoint offline")
    with pytest.raises(CcxError, match="semantic"):
        app.refresh(project)
    app.graph.build.assert_called_once()


def test_no_graph_only_updates_semantic(
    settings: Settings, runner: FakeRunner, project: Project
) -> None:
    app = application(settings, runner)
    project = Project(project.path, project.slug, False)
    app.refresh(project)
    app.graph.build.assert_not_called()
    with pytest.raises(CcxError, match="disabled"):
        app.refresh(project, graph_only=True)


def test_graph_only_does_not_touch_semantic(
    settings: Settings, runner: FakeRunner, project: Project
) -> None:
    app = application(settings, runner)
    app.refresh(project, graph_only=True)
    app.semantic.build.assert_not_called()
    app.graph.build.assert_called_once()


def test_stopped_container_fails_cleanly(
    settings: Settings, runner: FakeRunner, project: Project
) -> None:
    app = application(settings, runner)
    app.docker.inspect_running.return_value = False
    with pytest.raises(CcxError, match="not running"):
        app.refresh(project)


def _docker_rm_calls(runner: FakeRunner) -> list[str]:
    """Return the args vectors of every `docker rm` the FakeRunner recorded."""
    vectors: list[list[str]] = []
    for call in runner.calls:
        if call[0:2] == ["docker", "rm"]:
            vectors.append(call)
    return vectors


def test_interactive_exit_removes_project_container(
    settings: Settings, runner: FakeRunner, project: Project
) -> None:
    """Calling docker.remove after `/exit` tears down the managed container, keeping the
    data volume intact."""
    app = application(settings, runner)
    app.docker.remove(project)

    removal_vectors = _docker_rm_calls(runner)
    assert removal_vectors == [["docker", "rm", "-f", project.container]]
    # Removal references the container name, never the project data volume.
    assert project.volume not in removal_vectors[0]


def test_interactive_no_exit_never_removes_container(
    settings: Settings, runner: FakeRunner, project: Project
) -> None:
    """A non-interactive run never issues a `docker rm` for the container."""
    application(settings, runner)
    # docker.remove is never called
    removal_vectors = _docker_rm_calls(runner)
    assert removal_vectors == []


def test_cli_help_all_required_commands(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["--home", str(tmp_path), "--help"])
    assert result.exit_code == 0
    for command in (
        "init",
        "open",
        "reindex",
        "build-graph",
        "graph-query",
        "graph-status",
        "status",
        "watch",
        "clear-index",
        "clear-graph",
        "import",
        "export",
        "env",
        "platform",
    ):
        assert command in result.output


def test_cli_init_and_env_check(tmp_path: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(cli, ["--home", str(tmp_path), "init"]).exit_code == 0
    result = runner.invoke(cli, ["--home", str(tmp_path), "env", "check"])
    assert result.exit_code == 0
    assert '"missing": []' in result.output


def test_cli_full_reindex_requires_approval(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli, ["--home", str(tmp_path), "reindex", ".", "--full"], input="n\n"
    )
    assert result.exit_code == 1
    assert "Aborted" in result.output

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

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


def test_link_shared_agents_delegates_to_generated(
    settings: Settings, runner: FakeRunner, project: Project
) -> None:
    app = Application(settings, runner)
    expected_state = app.store.directory(project)
    with patch("ccx.service.link_shared_agents") as mock_link:
        app.link_shared_agents(project)
    mock_link.assert_called_once_with(settings, project, expected_state)


def test_unlink_shared_agents_delegates_to_generated(
    settings: Settings, runner: FakeRunner, project: Project
) -> None:
    app = Application(settings, runner)
    expected_state = app.store.directory(project)
    with patch("ccx.service.unlink_shared_agents") as mock_unlink:
        app.unlink_shared_agents(project)
    mock_unlink.assert_called_once_with(expected_state, project)


def _invoke_open(
    settings: Settings,
    project: Project,
    *,
    no_interactive: bool = False,
    keep_alive: bool = False,
) -> Any:
    args = ["--home", str(settings.home), "open", str(project.path)]
    if no_interactive:
        args.append("--no-interactive")
    if keep_alive:
        args.append("--keep-alive")
    return CliRunner().invoke(cli, args)


@patch("ccx.cli.Application")
def test_open_links_shared_agents_before_interactive(
    mock_app_class: Mock, settings: Settings, project: Project
) -> None:
    app = Mock()
    app.open.return_value = project
    mock_app_class.return_value = app

    result = _invoke_open(settings, project)
    assert result.exit_code == 0, result.output

    app.open.assert_called_once()
    names = [call[0] for call in app.mock_calls]
    assert names.index("link_shared_agents") < names.index("docker.interactive")
    app.docker.interactive.assert_called_once_with(project)
    app.unlink_shared_agents.assert_called_once_with(project)
    app.docker.remove.assert_called_once_with(project)


@pytest.mark.parametrize("keep_alive", [False, True])
@patch("ccx.cli.Application")
def test_open_unlinks_shared_agents_after_interactive(
    mock_app_class: Mock,
    settings: Settings,
    project: Project,
    keep_alive: bool,
) -> None:
    app = Mock()
    app.open.return_value = project
    mock_app_class.return_value = app

    result = _invoke_open(settings, project, keep_alive=keep_alive)
    assert result.exit_code == 0, result.output

    app.link_shared_agents.assert_called_once_with(project)
    app.docker.interactive.assert_called_once_with(project)
    app.unlink_shared_agents.assert_called_once_with(project)
    if keep_alive:
        app.docker.remove.assert_not_called()
    else:
        app.docker.remove.assert_called_once_with(project)


@patch("ccx.cli.Application")
def test_open_no_interactive_skips_agent_sync(
    mock_app_class: Mock, settings: Settings, project: Project
) -> None:
    app = Mock()
    app.open.return_value = project
    mock_app_class.return_value = app

    result = _invoke_open(settings, project, no_interactive=True)
    assert result.exit_code == 0, result.output

    app.link_shared_agents.assert_not_called()
    app.docker.interactive.assert_not_called()
    app.unlink_shared_agents.assert_not_called()

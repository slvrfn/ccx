"""Application use cases. UI and adapters contain no cross-backend orchestration."""

from pathlib import Path
from typing import Any

from filelock import FileLock

from ccx.config import Settings
from ccx.docker import Docker
from ccx.errors import CcxError
from ccx.generated import write_project_files
from ccx.graph import Graphify
from ccx.graph.output import require_owned
from ccx.io import safe_child, write_json
from ccx.process import Runner, SubprocessRunner
from ccx.project import Project, ProjectStore
from ccx.semantic import ClaudeContext
from ccx.transfer import Transfers
from ccx.watch import is_running


class Application:
    def __init__(self, settings: Settings, runner: Runner | None = None) -> None:
        self.settings = settings
        self.store = ProjectStore(settings.home)
        self.docker = Docker(settings, runner or SubprocessRunner())
        self.semantic = ClaudeContext(settings)
        self.graph = Graphify(self.docker)
        self.transfers = Transfers(self.docker)

    def initialize(self, force: bool = False) -> None:
        self.settings.initialize(force)
        self.settings = Settings.load(self.settings.home)
        self.docker.settings = self.settings
        self.semantic.settings = self.settings

    def require_running(self, project: Project) -> None:
        if not self.docker.inspect_running(project):
            raise CcxError(
                "Project container is not running. Run ccx open <path> --no-interactive."
            )

    def open(
        self,
        path: Path,
        *,
        graph: bool | None = None,
        rebuild: bool = False,
        prepare_only: bool = False,
    ) -> Project:
        self.initialize()
        enabled = self.settings.boolean("GRAPHIFY_ENABLED") if graph is None else graph
        project = Project.from_path(path, enabled, self.settings.get("GRAPHIFY_OUT_DIR"))
        graph_directory = safe_child(project.path, project.graph_out)
        if enabled and graph_directory.exists() and any(graph_directory.iterdir()):
            require_owned(graph_directory)
        state = self.store.directory(project)
        if is_running(state):
            raise CcxError("Stop the watcher before reopening or changing project configuration.")
        with FileLock(state / "operation.lock", timeout=30):
            self.store.save(project)
            write_project_files(
                self.settings,
                project,
                state,
                self.semantic.mcp_config(project),
                self.graph.mcp_config(project),
            )
            self.docker.platform_up()
            self.docker.ensure(project, state, rebuild)
        if not prepare_only:
            self.refresh(project)
        return project

    def refresh(
        self,
        project: Project,
        *,
        full: bool = False,
        semantic_only: bool = False,
        graph_only: bool = False,
    ) -> dict[str, Any]:
        self.require_running(project)
        if graph_only and not project.graph_enabled:
            raise CcxError("Graphify is disabled for this project.")
        state = self.store.directory(project)
        result: dict[str, Any] = {}
        failures: dict[str, str] = {}
        with FileLock(
            state / "operation.lock", timeout=self.settings.number("INDEX_TIMEOUT_SECONDS")
        ):
            if not graph_only:
                try:
                    result["semantic"] = self.semantic.build(project, full=full)
                except Exception as exc:
                    failures["semantic"] = str(exc)
            if project.graph_enabled and not semantic_only:
                try:
                    result["graph"] = self.graph.build(project, full=full)
                except Exception as exc:
                    failures["graph"] = str(exc)
            write_json(state / "last-refresh.json", {"result": result, "errors": failures})
        if failures:
            raise CcxError(
                "Refresh incomplete: " + "; ".join(f"{k}: {v}" for k, v in failures.items())
            )
        return result

    def status(self, project: Project) -> dict[str, Any]:
        running = self.docker.inspect_running(project)
        result: dict[str, Any] = {
            "project": project.slug,
            "path": str(project.path),
            "container_running": running,
            "collection": project.collection,
            "watcher_running": is_running(self.store.directory(project)),
            "graph_enabled": project.graph_enabled,
        }
        result["graph"] = self.graph.status(project)
        if running:
            try:
                result["semantic"] = self.semantic.status(project)
            except Exception as exc:
                result["semantic"] = {"error": str(exc)}
        return result

"""Graph lifecycle; build logic runs inside the pinned image."""

import json
import shutil
from typing import Any

from ccx.docker import Docker
from ccx.graph.output import require_owned
from ccx.graph.serve import serve_config
from ccx.graph.status import graph_status
from ccx.io import safe_child
from ccx.project import Project


class Graphify:
    def __init__(self, docker: Docker) -> None:
        self.docker = docker

    def build(self, project: Project, *, full: bool = False) -> dict[str, Any]:
        safe_child(project.path, project.graph_out)
        output = self.docker.exec(
            project, ["python", "-m", "ccx.runtime.graph_build", *(["--full"] if full else [])]
        )
        return json.loads(output.stdout)  # type: ignore[no-any-return]

    def status(self, project: Project) -> dict[str, Any]:
        return graph_status(safe_child(project.path, project.graph_out))

    def mcp_config(self, project: Project) -> dict[str, Any]:
        return serve_config(f"{project.mount}/{project.graph_out}/graph.json")

    def query(self, project: Project, question: str) -> str:
        return self.docker.exec(
            project,
            [
                "graphify",
                "query",
                question,
                "--graph",
                f"{project.mount}/{project.graph_out}/graph.json",
            ],
        ).stdout

    def clear(self, project: Project) -> None:
        target = safe_child(project.path, project.graph_out)
        if target.exists():
            require_owned(target)
            shutil.rmtree(target)

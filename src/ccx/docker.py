"""Docker lifecycle adapter. Compose owns shared services; ccx owns project containers."""

import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from ccx.config import Settings, asset_root
from ccx.errors import CcxError
from ccx.process import Result, Runner
from ccx.project import Project


class Docker:
    def __init__(self, settings: Settings, runner: Runner) -> None:
        self.settings, self.runner = settings, runner

    def compose(self, *args: str, capture: bool = False) -> Result:
        return self.runner.run(
            [
                "docker",
                "compose",
                "--project-name",
                "ccx-platform",
                "--env-file",
                str(self.settings.home / ".env"),
                "-f",
                str(self.settings.home / "compose.yaml"),
                *args,
            ],
            env=self.settings.values,
            capture=capture,
            timeout=600,
        )

    def platform_up(self, ui: bool = False) -> None:
        self.compose(
            *(["--profile", "ui"] if ui else []), "up", "-d", "--wait", "--wait-timeout", "180"
        )

    def image_tag(self) -> str:
        material = "|".join(
            self.settings.get(k)
            for k in ("OPENCODE_IMAGE", "GRAPHIFY_VERSION", "CLAUDE_CONTEXT_VERSION")
        )
        material += f"|{os.getuid()}|{os.getgid()}"
        for path in sorted(asset_root().parent.rglob("*")):
            if path.is_file() and (
                path.suffix in (".py", ".mjs", ".json", ".txt") or path.name == "Dockerfile"
            ):
                material += hashlib.sha256(path.read_bytes()).hexdigest()
        return "ccx-opencode:" + hashlib.sha256(material.encode()).hexdigest()[:12]

    def build(self, rebuild: bool = False) -> None:
        if os.getuid() == 0 or os.getgid() == 0:
            raise CcxError(
                "Run ccx as a non-root host user so repository files retain safe ownership."
            )
        if not rebuild:
            try:
                self.runner.run(["docker", "image", "inspect", self.image_tag()])
                return
            except CcxError:
                pass
        args = [
            "docker",
            "build",
            "-t",
            self.image_tag(),
            "-f",
            str(self.settings.home / "Dockerfile"),
        ]
        for key in ("OPENCODE_IMAGE", "GRAPHIFY_VERSION", "CLAUDE_CONTEXT_VERSION"):
            args += ["--build-arg", f"{key}={self.settings.get(key)}"]
        args += [
            "--build-arg",
            f"CCX_UID={os.getuid()}",
            "--build-arg",
            f"CCX_GID={os.getgid()}",
            str(self.settings.home),
        ]
        self.runner.run(args, capture=False, timeout=1800)

    def exists(self, project: Project) -> bool:
        result = self.runner.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name=^/{project.container}$",
                "--format",
                "{{.Names}}",
            ]
        )
        return project.container in result.stdout.splitlines()

    def ensure(self, project: Project, state: Path, rebuild: bool = False) -> None:
        self.build(rebuild)
        if self.exists(project):
            # Runtime env changes must not silently keep stale secrets/models.
            self.runner.run(["docker", "rm", "-f", project.container])
        self.runner.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                project.container,
                "--label",
                "ccx.managed=true",
                "--label",
                f"ccx.slug={project.slug}",
                "--network",
                "context-net",
                "--add-host",
                "host.docker.internal:host-gateway",
                "--init",
                "--cap-drop=ALL",
                "--security-opt",
                "no-new-privileges",
                "--env-file",
                str(state / "runtime.env"),
                "--mount",
                f"type=bind,src={project.path},dst={project.mount}",
                "--mount",
                f"type=bind,src={state},dst=/ccx-config,readonly",
                "--mount",
                f"type=volume,src={project.volume},dst=/home/ccx",
                "--workdir",
                project.mount,
                self.image_tag(),
                "sleep",
                "infinity",
            ]
        )

    def exec(
        self, project: Project, args: Sequence[str], capture: bool = True, tty: bool = False
    ) -> Result:
        return self.runner.run(
            [
                "docker",
                "exec",
                *(["-it"] if tty else []),
                "--workdir",
                project.mount,
                project.container,
                *args,
            ],
            capture=capture,
            timeout=None if tty else self.settings.number("COMMAND_TIMEOUT_SECONDS"),
        )

    def interactive(self, project: Project) -> None:
        self.exec(project, ["opencode", project.mount], capture=False, tty=sys.stdin.isatty())

    def inspect_running(self, project: Project) -> bool:
        try:
            value = self.runner.run(
                ["docker", "inspect", "--format", "{{json .State.Running}}", project.container]
            ).stdout
            return bool(json.loads(value))
        except (CcxError, ValueError):
            return False

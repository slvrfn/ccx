"""Stable project identities and per-project persistence."""

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ccx.errors import CcxError
from ccx.io import read_json, write_json


@dataclass(frozen=True)
class Project:
    path: Path
    slug: str
    graph_enabled: bool = True
    graph_out: str = "graphify-out"

    @classmethod
    def from_path(
        cls, path: Path, graph_enabled: bool = True, graph_out: str = "graphify-out"
    ) -> "Project":
        resolved = path.expanduser().resolve()
        if not resolved.is_dir():
            raise CcxError(f"Repository directory does not exist: {resolved}")
        if any(char in str(resolved) for char in ("\n", "\r", ",")):
            raise CcxError("Docker bind paths cannot contain newlines or commas.")
        name = re.sub("[^a-z0-9-]+", "-", resolved.name.lower()).strip("-")[:40] or "repo"
        digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
        return cls(resolved, f"{name}-{digest}", graph_enabled, graph_out)

    @property
    def mount(self) -> str:
        return f"/workspace/{self.slug}"

    @property
    def container(self) -> str:
        return f"ccx-{self.slug}"

    @property
    def volume(self) -> str:
        return f"ccx-{self.slug}-home"

    @property
    def collection(self) -> str:
        # Claude Context 0.1.15 truncates MD5 to eight hex characters.
        return (
            "code_chunks_" + hashlib.md5(self.mount.encode(), usedforsecurity=False).hexdigest()[:8]
        )


class ProjectStore:
    def __init__(self, home: Path) -> None:
        self.root = home / "projects"

    def directory(self, project: Project) -> Path:
        result = self.root / project.slug
        result.mkdir(parents=True, exist_ok=True, mode=0o700)
        return result

    def save(self, project: Project) -> None:
        for metadata in self.root.glob("*/project.json"):
            other = read_json(metadata)
            existing = Project(Path(other["path"]), other["slug"])
            if existing.slug != project.slug and existing.collection == project.collection:
                raise CcxError(
                    "Claude Context's 32-bit collection hash collided with another project. "
                    "Use a different repository path."
                )
        data = asdict(project)
        data["path"] = str(project.path)
        write_json(self.directory(project) / "project.json", data)

    def resolve(self, target: str) -> Project:
        if re.fullmatch(r"[a-z0-9-]+-[0-9a-f]{8}", target):
            candidate = self.root / target / "project.json"
        else:
            proposed = Project.from_path(Path(target))
            candidate = self.root / proposed.slug / "project.json"
        if not candidate.is_file():
            raise CcxError("Project not registered. Run ccx open <path> first.")
        data: dict[str, Any] = read_json(candidate)
        return Project(Path(data["path"]), data["slug"], data["graph_enabled"], data["graph_out"])

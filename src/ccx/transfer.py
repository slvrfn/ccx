"""Versioned ZIP bundles with checksums, bounded extraction, and no secrets."""

import hashlib
import json
import os
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from ccx.docker import Docker
from ccx.errors import CcxError
from ccx.project import Project

MAX_UNPACKED = 10 * 1024**3
MAX_FILES = 100_000


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def create_bundle(directory: Path, destination: Path, metadata: dict[str, Any]) -> None:
    paths = sorted(p for p in directory.rglob("*") if p.is_file())
    if any(p.is_symlink() for p in directory.rglob("*")):
        raise CcxError("Refusing symlink in export staging directory.")
    metadata = {
        **metadata,
        "format_version": 1,
        "files": {p.relative_to(directory).as_posix(): digest(p) for p in paths},
    }
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(metadata, indent=2))
        for path in paths:
            archive.write(path, path.relative_to(directory).as_posix())


def extract_bundle(source: Path, destination: Path) -> dict[str, Any]:
    """Extract to a new, caller-owned staging directory only."""
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_UNPACKED:
                raise CcxError("Bundle exceeds extraction limits.")
            names: set[str] = set()
            for member in members:
                member_path = PurePosixPath(member.filename)
                if (
                    not member_path.parts
                    or member_path.is_absolute()
                    or ".." in member_path.parts
                    or "\\" in member.filename
                    or ":" in member.filename
                    or member.filename in names
                    or member.is_dir()
                    or stat.S_ISLNK(member.external_attr >> 16)
                ):
                    raise CcxError(f"Unsafe archive member: {member.filename!r}")
                names.add(member.filename)
            if "manifest.json" not in names or archive.getinfo("manifest.json").file_size > 2**20:
                raise CcxError("Missing or oversized manifest.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format_version") != 1:
                raise CcxError("Unsupported bundle version.")
            if set(manifest.get("files", {})) != names - {"manifest.json"}:
                raise CcxError("Manifest does not exactly describe archive contents.")
            if not {"vectors/schema.json", "vectors/rows.jsonl"} <= names:
                raise CcxError("Bundle is missing vector data.")
            for name in sorted(names - {"manifest.json"}):
                path = destination.joinpath(*PurePosixPath(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, path.open("xb") as dst:
                    import shutil

                    shutil.copyfileobj(src, dst, 1024 * 1024)
                if digest(path) != manifest["files"][name]:
                    raise CcxError(f"Checksum mismatch: {name}")
            return dict(manifest)
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise CcxError("Invalid bundle.") from exc


class Transfers:
    def __init__(self, docker: Docker) -> None:
        self.docker = docker

    def export(self, project: Project, destination: Path) -> None:
        if destination.exists():
            raise CcxError("Export destination exists; choose a new file.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        remote = f"/tmp/ccx-export-{uuid.uuid4().hex}.zip"
        with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
            temporary = Path(directory) / "bundle.zip"
            try:
                self.docker.exec(
                    project, ["python", "-m", "ccx.runtime.transfer", "export", remote]
                )
                self.docker.runner.run(
                    ["docker", "cp", f"{project.container}:{remote}", str(temporary)]
                )
                os.chmod(temporary, 0o600)
                os.link(temporary, destination)  # Atomic, no overwrite on concurrent export.
            finally:
                self.docker.exec(project, ["rm", "-f", remote])

    def restore(self, project: Project, source: Path) -> None:
        # Validate locally before copying anything into the running container.
        with tempfile.TemporaryDirectory() as temporary:
            extract_bundle(source, Path(temporary))
        remote = f"/tmp/ccx-import-{uuid.uuid4().hex}.zip"
        try:
            self.docker.runner.run(["docker", "cp", str(source), f"{project.container}:{remote}"])
            # docker cp keeps host mode; the mapped host UID can read it.
            self.docker.exec(project, ["python", "-m", "ccx.runtime.transfer", "import", remote])
        finally:
            self.docker.exec(project, ["rm", "-f", remote])

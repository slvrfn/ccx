"""Atomic writes and validated repository-relative paths."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ccx.errors import CcxError


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, indent=2) + "\n")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CcxError(f"Cannot read JSON: {path}") from exc


def safe_child(root: Path, relative: str) -> Path:
    part = Path(relative)
    if (
        part.is_absolute()
        or not part.parts
        or any(p in (".", "..", ".git", ".opencode") for p in part.parts)
        or "\n" in relative
    ):
        raise CcxError(f"Unsafe output directory: {relative!r}")
    target = root / part
    cursor = root
    for component in part.parts:
        cursor /= component
        if cursor.is_symlink():
            raise CcxError(f"Refusing symlink output path: {cursor}")
    if not target.resolve().is_relative_to(root.resolve()) or target.resolve() == root.resolve():
        raise CcxError("Output directory must stay inside the repository.")
    return target

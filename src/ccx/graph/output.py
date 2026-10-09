"""Ownership guard: a configured output path must never silently adopt source code."""

from pathlib import Path

from ccx.errors import CcxError
from ccx.io import read_json, write_json

MARKER = ".ccx-generated.json"
IDENTITY = {"owner": "ccx", "format_version": 1}


def require_owned(directory: Path) -> None:
    marker = directory / MARKER
    if marker.is_symlink() or not marker.is_file() or read_json(marker) != IDENTITY:
        raise CcxError(
            f"Refusing unmanaged graph directory: {directory}. "
            "Choose a new GRAPHIFY_OUT_DIR; ccx will not delete existing source."
        )


def claim_output(directory: Path) -> None:
    if directory.exists() and any(directory.iterdir()):
        require_owned(directory)
    else:
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / MARKER, IDENTITY)

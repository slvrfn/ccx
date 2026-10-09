"""Per-project lock shared by all container MCP processes and graph builds."""

import os
from pathlib import Path
from typing import Any

from filelock import FileLock

from ccx.errors import CcxError
from ccx.io import read_json


def root() -> Path:
    return Path(os.environ["CCX_PROJECT_PATH"]).resolve()


def state_dir() -> Path:
    path = Path.home() / ".ccx"
    path.mkdir(parents=True, exist_ok=True)
    return path


def lock() -> FileLock:
    return FileLock(
        state_dir() / "context.lock", timeout=float(os.environ.get("CCX_INDEX_TIMEOUT", "3600"))
    )


def validate_path(path: str) -> None:
    if Path(path).resolve() != root():
        raise CcxError("MCP access is restricted to this container's registered project.")


def embedding_identity() -> dict[str, str]:
    return {
        "model": os.environ["EMBEDDING_MODEL"],
        "base_url": os.environ["OPENAI_BASE_URL"],
        "provider": os.environ["EMBEDDING_PROVIDER"],
    }


def validate_embedding() -> None:
    path = state_dir() / "embedding.json"
    if path.exists() and read_json(path) != embedding_identity():
        raise CcxError("Embedding configuration changed. Run ccx reindex --full before searching.")


def snapshot_status() -> dict[str, Any]:
    path = Path.home() / ".context" / "mcp-codebase-snapshot.json"
    data = read_json(path) if path.exists() else {}
    item = data.get("codebases", {}).get(str(root()), {"status": "not_found"})
    return dict(item)

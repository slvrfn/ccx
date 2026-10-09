"""Read graph metadata without launching Graphify."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ccx.io import read_json


def graph_status(directory: Path) -> dict[str, Any]:
    graph = directory / "graph.json"
    if not graph.is_file():
        return {"exists": False}
    data = read_json(graph)
    return {
        "exists": True,
        "nodes": len(data.get("nodes", [])),
        "edges": len(data.get("links", data.get("edges", []))),
        "last_built": datetime.fromtimestamp(graph.stat().st_mtime, UTC).isoformat(),
    }

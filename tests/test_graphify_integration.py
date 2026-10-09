import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("CCX_TEST_GRAPHIFY") != "1",
    reason="Set CCX_TEST_GRAPHIFY=1 and install pinned Graphify.",
)
def test_real_graph_extract_update_query(tmp_path: Path) -> None:
    executable = shutil.which("graphify")
    assert executable, "Install graphifyy[mcp]==0.9.83"
    repo = tmp_path / "repository"
    repo.mkdir()
    source = repo / "example.py"
    source.write_text("def helper():\n    return 42\n\ndef main():\n    return helper()\n")
    graph = repo / "artifacts/context"
    environment = {**os.environ, "GRAPHIFY_OUT": str(graph), "GRAPHIFY_NO_TIPS": "1"}
    subprocess.run(
        [executable, "extract", str(repo), "--out", str(graph), "--code-only"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    initial = json.loads((graph / "graph.json").read_text())
    assert initial["nodes"]
    subprocess.run(
        [executable, "cluster-only", str(repo), "--graph", str(graph / "graph.json"), "--no-label"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    assert (graph / "GRAPH_REPORT.md").exists()
    source.write_text(source.read_text() + "\ndef added():\n    return main()\n")
    subprocess.run(
        [executable, "update", str(repo)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    updated = json.loads((graph / "graph.json").read_text())
    assert len(updated["nodes"]) > len(initial["nodes"])
    query = subprocess.run(
        [executable, "query", "helper", "--graph", str(graph / "graph.json")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert "helper" in query.stdout

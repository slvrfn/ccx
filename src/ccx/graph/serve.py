"""Graphify MCP registration and explicit read-only allowlist."""

from typing import Any

READ_TOOLS = (
    "query_graph",
    "get_node",
    "get_neighbors",
    "get_community",
    "god_nodes",
    "graph_stats",
    "shortest_path",
)


def serve_config(graph_path: str) -> dict[str, Any]:
    return {
        "type": "local",
        "command": ["graphify-mcp", graph_path],
        "enabled": True,
        "timeout": 30000,
    }

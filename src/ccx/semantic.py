"""Host-side Claude Context adapter."""

import asyncio
import json
from typing import Any

from ccx.config import Settings
from ccx.mcp_client import call
from ccx.project import Project


class ClaudeContext:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def invoke(self, project: Project, tool: str, **arguments: Any) -> str:
        return asyncio.run(
            call(
                "docker",
                ["exec", "-i", project.container, "python", "-m", "ccx.runtime.mcp_server"],
                tool,
                {"path": project.mount, **arguments},
                self.settings.number("INDEX_TIMEOUT_SECONDS") + 60,
            )
        )

    def build(self, project: Project, *, full: bool = False) -> dict[str, Any]:
        return {"result": self.invoke(project, "index_codebase", force=full)}

    def status(self, project: Project) -> dict[str, Any]:
        return json.loads(self.invoke(project, "get_indexing_status"))  # type: ignore[no-any-return]

    def search(self, project: Project, query: str) -> str:
        return self.invoke(project, "search_code", query=query, limit=20)

    def clear(self, project: Project) -> str:
        return self.invoke(project, "clear_index")

    def mcp_config(self, project: Project) -> dict[str, Any]:
        return {
            "type": "local",
            "command": ["python", "-m", "ccx.runtime.mcp_server"],
            "enabled": True,
            "timeout": int(self.settings.number("INDEX_TIMEOUT_SECONDS") * 1000),
        }

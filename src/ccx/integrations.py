"""Small shared interface for independently replaceable context backends."""

from typing import Any, Protocol

from ccx.project import Project


class ContextBackend(Protocol):
    def build(self, project: Project, *, full: bool = False) -> dict[str, Any]: ...
    def status(self, project: Project) -> dict[str, Any]: ...
    def mcp_config(self, project: Project) -> dict[str, Any]: ...

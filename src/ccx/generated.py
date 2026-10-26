"""Idempotent generated configuration. Secrets live in 0600 runtime.env, not JSON."""

import json
from pathlib import Path
from typing import Any

from ccx.config import Settings, safe_home_root
from ccx.errors import CcxError
from ccx.graph.serve import READ_TOOLS
from ccx.io import atomic_write, write_json
from ccx.project import Project

GUIDANCE = """Use graphify for dependency, relationship, community and impact questions.
Use claude-context semantic search for natural-language implementation discovery.
Cross-check results against source files; either index may be stale.
Graph mutation and semantic clear_index require explicit human approval.
Do not launch graphify watch: ccx owns the one combined file watcher.
Container project Python dependencies belong to UV_PROJECT_ENVIRONMENT, not /opt/venv
or the host repository's .venv. Do not use uv pip --system or install into /opt/venv.
For large dependency sets, ask the user to finish one explicit uv sync before running
tests. After a successful sync, use uv run --no-sync for repeated commands while
dependencies are unchanged; do not bypass sync for a missing or incomplete environment.
Do not repeat a failing large sync without inspecting whether the HTTP read timeout
or the shell-tool deadline ended it. Set an explicit suitable bash tool timeout for
initial setup. Never clean the uv cache as a routine response to an interrupted sync.
The container has no GPU passthrough by default. Do not rewrite PyTorch/CUDA requirements
or select a CPU-only backend without checking the project's requirements with the user.
"""


def opencode_config(
    settings: Settings, project: Project, semantic: dict[str, Any], graph: dict[str, Any]
) -> dict[str, Any]:
    permission = {
        "*": "ask",
        "read": "allow",
        "glob": "allow",
        "grep": "allow",
        "claude-context_*": "ask",
        "claude-context_search_code": "allow",
        "claude-context_get_indexing_status": "allow",
        "claude-context_index_codebase": "allow",
        "claude-context_clear_index": "ask",
        "graphify_*": "ask",
    }
    permission.update({f"graphify_{name}": "allow" for name in READ_TOOLS})
    mcp = {"claude-context": semantic}
    if project.graph_enabled:
        mcp["graphify"] = graph
    model = settings.get("INFERENCE_MODEL")
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": f"ccx/{model}",
        "provider": {
            "ccx": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "CCX inference",
                "options": {
                    "baseURL": settings.url("INFERENCE"),
                    "apiKey": "{env:CCX_INFERENCE_API_KEY}",
                },
                "models": {model: {"name": model}},
            }
        },
        "mcp": mcp,
        "permission": permission,
        "instructions": ["/ccx-config/CONTEXT.md"],
    }


def write_project_files(
    settings: Settings,
    project: Project,
    state: Path,
    semantic: dict[str, Any],
    graph: dict[str, Any],
) -> None:
    write_json(state / "opencode.json", opencode_config(settings, project, semantic, graph))
    atomic_write(state / "CONTEXT.md", GUIDANCE, 0o644)
    values = {
        "HOME": str(safe_home_root()),
        "CCX_SAFE_HOME": str(safe_home_root()),
        "OPENCODE_CONFIG": "/ccx-config/opencode.json",
        "CCX_PROJECT_PATH": project.mount,
        "CCX_GRAPH_OUT": project.graph_out,
        "CCX_GRAPH_ENABLED": str(project.graph_enabled).lower(),
        "CCX_INFERENCE_API_KEY": settings.get("INFERENCE_API_KEY"),
        "CCX_INFERENCE_BASE_URL": settings.url("INFERENCE"),
        "CCX_INFERENCE_MODEL": settings.get("INFERENCE_MODEL"),
        "OPENAI_API_KEY": settings.get("EMBEDDING_API_KEY"),
        "OPENAI_BASE_URL": settings.url("EMBEDDING"),
        "EMBEDDING_PROVIDER": "OpenAI",
        "EMBEDDING_MODEL": settings.get("EMBEDDING_MODEL"),
        "MILVUS_ADDRESS": "milvus:19530",
        "MILVUS_TOKEN": "",
        "HYBRID_MODE": "false",
        "CCX_INDEX_TIMEOUT": settings.get("INDEX_TIMEOUT_SECONDS"),
        "CCX_GRAPH_SEMANTIC": settings.get("GRAPHIFY_SEMANTIC_EXTRACTION"),
        "CCX_GRAPH_VERSION": settings.get("GRAPHIFY_VERSION"),
        "CCX_CONTEXT_VERSION": settings.get("CLAUDE_CONTEXT_VERSION"),
        "GRAPHIFY_OUT": project.graph_out,
        "GRAPHIFY_NO_TIPS": "1",
    }
    for key in (
        "UV_CACHE_DIR",
        "UV_PROJECT_ENVIRONMENT",
        "UV_HTTP_TIMEOUT",
        "UV_CONCURRENT_DOWNLOADS",
        "UV_LINK_MODE",
        "OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS",
    ):
        values[key] = settings.get(key)
    # Cache and project paths were validated by settings.load(); forward them
    # unchanged (they already sit under CCX_SAFE_HOME, matching HOME).
    if any("\n" in v or "\r" in v for v in values.values()):
        raise CcxError("Environment values must not contain line breaks.")
    atomic_write(state / "runtime.env", "".join(f"{k}={v}\n" for k, v in values.items()))
    # Leave existing user-owned OpenCode files untouched. Only manage our own namespace.
    base = project.path / ".opencode"
    files = {
        "skills/ccx-context/SKILL.md": (
            "---\nname: ccx-context\ndescription: Select semantic or structural code context\n---\n"
            + GUIDANCE
        ),
        "plugins/ccx-context.js": (
            'import { Plugin } from "@opencode/plugin"\n\n'
            "export default Plugin.define({\n"
            '  id: "ccx-context",\n'
            "  async setup(ctx) {\n"
            '    await ctx.session.hook("context", (event) => {\n'
            f'      event.system.push({{ type: "text", text: {json.dumps(GUIDANCE)} }});\n'
            "    })\n"
            "  }\n"
            "})\n"
        ),
    }
    for relative, content in files.items():
        destination = base / relative
        for part in (base, *destination.parents, destination):
            if part.is_symlink():
                raise CcxError(f"Refusing to write through symlink: {part}")
        atomic_write(destination, content, 0o644)
    if not settings.boolean("GRAPHIFY_COMMIT_OUTPUT"):
        ignore = project.path / ".gitignore"
        if ignore.is_symlink():
            raise CcxError("Refusing symlink .gitignore.")
        text = ignore.read_text() if ignore.exists() else ""
        patterns = [
            f"/{project.graph_out}/",
            "/.opencode/skills/ccx-context/",
            "/.opencode/plugins/ccx-context.js",
        ]
        missing = [p for p in patterns if p not in text.splitlines()]
        if missing:
            atomic_write(
                ignore,
                text.rstrip("\n") + "\n\n# ccx generated artifacts\n" + "\n".join(missing) + "\n",
                0o644,
            )

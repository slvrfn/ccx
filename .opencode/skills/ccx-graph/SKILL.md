---
name: ccx-graph
description: Graphify code graph build, query, ownership, and read-only allowlist
---
# ccx-graph skill

Guidance for working with ccx's Graphify integration. Graphify lives entirely in `src/ccx/graph/` and must never depend on Claude Context.

## Modules

- `src/ccx/graph/backend.py` — `Graphify` class:
  - `build(project, full=False)` — runs `python -m ccx.runtime.graph_build` inside the container (`graphify extract` or `graphify update`), returns parsed `graph.json`.
  - `status(project)` — reads `graph.json` metadata without launching Graphify (`graph_status`).
  - `query(project, question)` — runs `graphify query` against the graph file.
  - `clear(project)` — deletes the owned graph directory (`require_owned` guard).
  - `mcp_config(project)` — `serve_config` pointing at `graph.json`.
- `src/ccx/graph/output.py` — ownership guard:
  - `MARKER = ".ccx-generated.json"`, `IDENTITY = {"owner": "ccx", "format_version": 1}`.
  - `require_owned(directory)` — refuses nonempty directories without the marker (never adopts source).
  - `claim_output(directory)` — creates or validates the output directory.
- `src/ccx/graph/serve.py` — read-only MCP allowlist `READ_TOOLS`:
  - `query_graph`, `get_node`, `get_neighbors`, `get_community`, `god_nodes`, `graph_stats`, `shortest_path`.
  - All unknown Graphify tools require approval (`graphify_*` defaults to `"ask"` in generated config; read tools are `"allow"`).
- `src/ccx/graph/status.py` — `graph_status(directory)`: node/edge counts, last-built timestamp.
- `src/ccx/runtime/graph_build.py` — container entry: `graphify extract` (full/semantic/no-cache) or `graphify update` (incremental, code-only), then `graphify cluster-only` for report/HTML.

## Key behaviors

- Graphify default-on per project (`GRAPHIFY_ENABLED`), off via `--no-graph` or setting `false`.
- `GRAPHIFY_OUT_DIR` default `graphify-out`; must stay inside repo, cannot be root/traversal/`.git`/`.opencode`/symlink.
- Code-only extraction makes no LLM calls; semantic extraction (`GRAPHIFY_SEMANTIC_EXTRACTION=true`) uses the inference endpoint.
- Graphify MCP server reads `graph.json` on launch; rebuilds while OpenCode is running may not be visible until MCP subprocess restarts.
- The graph watcher is ccx's combined watcher (`watch.py`); do not install Graphify's own watch/git hooks.
- Export/import copies only `.json`, `.md`, `.html` graph files; refuses symlinks; remaps `source_mount` paths.

## Review checklist for graph changes

- [ ] No `claude_context`/`semantic` import in `src/ccx/graph/`.
- [ ] Output path validated with `safe_child` / `require_owned`.
- [ ] Read-only tools use `READ_TOOLS`; mutation tools (`extract`, `update`, `clear`) require approval.
- [ ] `--full` forces `graphify extract --force`; otherwise `graphify update`.
- [ ] Existing graph uses incremental update unless missing or forced.

## Query examples

- `ccx graph-query <path> "authentication"` — structural question answered from `graph.json`.
- `ccx graph-status <path>` — node/edge counts, last built (no container needed).
- Graph god nodes / communities via `get_node`, `get_community`, `god_nodes`, `shortest_path`.

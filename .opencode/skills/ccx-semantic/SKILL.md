---
name: ccx-semantic
description: Claude Context semantic indexing, search, and embedding identity validation
---
# ccx-semantic skill

Guidance for working with ccx's Claude Context integration. Semantic search is for natural-language implementation discovery; graphify is for structural relationships.

## Modules

- `src/ccx/semantic.py` — `ClaudeContext` host adapter:
  - `build(project, full=False)` — invokes `index_codebase` MCP tool inside the container (`docker exec python -m ccx.runtime.mcp_server`).
  - `search(project, query)` — `search_code` MCP tool, limit 20.
  - `status(project)` — `get_indexing_status` MCP tool.
  - `clear(project)` — `clear_index` MCP tool (destructive, requires approval).
  - `mcp_config(project)` — local MCP config for OpenCode registration.
- `src/ccx/runtime/mcp_server.py` — container-side FastMCP facade:
  - `index_codebase(path, force)` — upstream Node seam (`upstream.mjs`), waits for actual task completion (not disk snapshot), verifies `totalChunks > 0`.
  - `search_code(path, query, limit)` — semantic search.
  - `get_indexing_status(path)` — status + snapshot + embedding identity.
  - `clear_index(path)` — DESTRUCTIVE: deletes semantic index, not source or graph.
  - All FastMCP tools delegate to AnyIO worker thread (`to_thread.run_sync`, `abandon_on_cancel=False`); never `asyncio.run()` inside the event-loop thread.
- `src/ccx/runtime/state.py` — `root()`, `state_dir()`, `lock()` (per-project HOME lock), `validate_path()`, `embedding_identity()`, `validate_embedding()`, `snapshot_status()`.
- `src/ccx/runtime/upstream.mjs` / `incremental.mjs` — pinned JS seam for Claude Context internals (no periodic sync timer).
- `src/ccx/mcp_client.py` — stdio MCP session transport with timeout and error wrapping.

## Key behaviors

- Index names Milvus collection `code_chunks_<md5(mount)[:8]>`; isolated per project via mount path.
- Incremental refresh is default; `full=True` or failed status forces full rebuild.
- Embedding identity (model + base_url + provider) is recorded; search/incremental refused if identity changed until full reindex.
- `clear_index` clears vectors + semantic snapshots only; leaves graph and source intact. Requires `--yes` or confirmation.
- Empty-index completion is treated as failure (zero chunks → explicit error), not success.
- `index_codebase` ignores `graphify-out/**`, `.opencode/**`, `.env`, `*.pem`, `*.key`.
- Migration note: `0.1.1` moved semantic lifecycle across the Python MCP subprocess (nested-event-loop fix); tests cover this.

## Review checklist for semantic changes

- [ ] Async→thread boundary respected (`to_thread.run_sync`, `abandon_on_cancel=False`).
- [ ] No `asyncio.run()` called inside a running event loop.
- [ ] Embedding identity checked before incremental/search operations.
- [ ] Destructive `clear_index` gated behind confirmation/`--yes`.
- [ ] Upstream JS seam (`upstream.mjs`, `incremental.mjs`) contract verified by `scripts/check-upstream.mjs`.

## Query examples

- `ccx search <path> "where is authentication implemented?"` — semantic implementation discovery.
- `ccx status <path>` — collection name, indexed chunks, semantic status.
- `ccx reindex <path> --full` — full semantic rebuild after embedding change or failure.

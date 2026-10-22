---
name: ccx-runtime
description: Container-side MCP server, graph build, Milvus transfer, and project state
---
# ccx-runtime skill

Guidance for working with ccx's container-side runtime in `src/ccx/runtime/`. These modules run *inside* the OpenCode project container, not on the host.

## Modules

- `src/ccx/runtime/mcp_server.py` — FastMCP facade over pinned Claude Context Node seam:
  - `index_codebase(path, force)` — calls upstream `index_codebase` via `upstream.mjs`, waits for real task completion (`ccx_wait_index` + `ccx_verify_index`), rejects zero-chunk completion.
  - `search_code(path, query, limit)` — upstream semantic search, limit clamped 1–50.
  - `get_indexing_status(path)` — upstream status merged with snapshot + embedding identity.
  - `clear_index(path)` — DESTRUCTIVE: deletes semantic collection + `embedding.json`.
  - All tools async but delegate sync work to AnyIO worker thread; never `asyncio.run()` inside the event loop.
  - `UPSTREAM = upstream.mjs`, `INCREMENTAL = incremental.mjs` — pinned JS seam.
- `src/ccx/runtime/graph_build.py` — `build(full=False)`:
  - `graphify extract` (full/semantic/no-cache) with `--out`, `--force`, `--backend openai` or `--code-only`.
  - `graphify update` (incremental, code-only, uses `GRAPHIFY_OUT` env).
  - Then `graphify cluster-only` for report + HTML when extract ran.
  - Claims output via `claim_output` (ownership marker).
- `src/ccx/runtime/transfer.py` — Milvus logical snapshots:
  - `export(destination)` — schema + rows (JSONL) + graph artifacts (`.json/.md/.html`, no symlinks) + snapshot + manifest → ZIP bundle via `create_bundle`.
  - `restore(source)` — validates manifest, embedding model, vector dimension (`probe_dimension` via HTTP), creates staging collection, inserts in batches, builds index, renames to target, copies graph, writes snapshot + `embedding.json` + `imported.json`.
  - Refuses existing target collection/graph; cleans up staging on failure.
- `src/ccx/runtime/state.py` — `root()` (`CCX_PROJECT_PATH`), `state_dir()` (`~/.ccx`), `lock()` (`context.lock`), `validate_path()`, `embedding_identity()`, `validate_embedding()`, `snapshot_status()`.
- `src/ccx/mcp_client.py` — stdio MCP session with `result_text`, `session()`, `call()`; timeout and `ExceptionGroup`/timeout wrapping.

## Key behaviors

- All container operations hold the per-project HOME lock (`context.lock`) to serialize with host CLI.
- `validate_path` restricts MCP access to the registered project mount.
- Embedding identity change blocks incremental/search until `reindex --full`.
- Import is not a distributed transaction; process kill can leave `_import_<id>` collection (runbook covers inspection).
- Export/import validates Claude Context version, embedding model name, and live vector dimension before promotion.
- Import does not restore path-dependent Merkle snapshots; first refresh after import is a full rebuild.
- Graph export copies only `.json/.md/.html`; symlinks refused; graph files remapped for `source_mount`.

## Review checklist for runtime changes

- [ ] FastMCP tools delegate to `to_thread.run_sync(..., abandon_on_cancel=False)`.
- [ ] No `asyncio.run()` inside the MCP event-loop thread.
- [ ] Dimension probe (`probe_dimension`) used before collection creation in restore.
- [ ] Staging collection + graph cleaned up on `BaseException` in restore.
- [ ] `validate_path` enforced before any operation.
- [ ] `create_bundle`/`extract_bundle` reject symlinks, traversal, duplicates, oversized archives.

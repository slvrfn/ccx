---
name: ccx-review
description: Code-review guidance for ccx changes: boundaries, safety, conventions
---
# ccx-review skill

Guidance for reviewing changes to `ccx` (`code-context-cli`). Use this alongside `ccx-codebase`, `ccx-graph`, `ccx-semantic`, `ccx-runtime`, and `ccx-service-cli`.

## Module-boundary discipline

- `src/ccx/graph/` must never import Claude Context/semantic modules (documented contract: "No Claude Context dependency is allowed in this package").
- `src/ccx/semantic.py` and `src/ccx/graph/backend.py` are independent adapters implementing `ContextBackend` (`src/ccx/integrations.py`).
- Only `src/ccx/process.py` (`SubprocessRunner`) launches shell commands; never `shell=True`.
- All writes use atomic replace (`src/ccx/io.py:atomic_write` / `write_json`).
- Output paths use `safe_child` (traversal/root/`.git`/`.opencode`/symlink guards).
- Graph directories use `.ccx-generated.json` ownership marker (`require_owned`/`claim_output`).

## Safety rules (from AGENTS.md)

- Graph mutation and `clear_index` require explicit human approval (`--yes` or confirmation).
- Do not launch graphify watch: ccx owns the one combined file watcher.
- Do not run `ccx` as root.
- Destructive ops (`platform down`, `clear-index`, `clear-graph`, `import`) need confirmation unless `--yes`.
- Repository code is never removed by a ccx command.
- `GRAPHIFY_OUT_DIR` must stay inside repo, not root/traversal/`.git`/`.opencode`/symlink.

## Version-pinning discipline

- Pinned versions in `.env.example` / config: `CLAUDE_CONTEXT_VERSION` (0.1.15), `GRAPHIFY_VERSION` (0.9.83), `OPENCODE_IMAGE`, Milvus/etcd/MinIO/Attu images.
- Changing package versions alone fails the image build; update adapter, locks, image guards, contracts, and tests together.
- `scripts/check-upstream.mjs` verifies expected exports of the pinned Node adapter.
- `scripts/lock.sh` regenerates host/runtime/npm dependency locks.

## Async/thread boundary

- FastMCP tools in `runtime/mcp_server.py` delegate sync work to AnyIO worker thread (`to_thread.run_sync`, `abandon_on_cancel=False`).
- Never call `asyncio.run()` inside a running event loop.
- Host-side `semantic.py` uses `asyncio.run(call(...))` (no running loop there — correct).

## Test conventions

- `tests/conftest.py`: `FakeRunner` captures `docker` command argv + environments; `settings` and `project` fixtures.
- `test_service_cli.py` mocks `app.semantic.build` / `app.graph.build`; verifies orchestration without Docker.
- Integration tests (`test_graphify_integration.py`, `test_semantic_integration.py`, `test_mcp_dispatch.py`, `test_transfer_runtime.py`, `test_runtime.py`, `test_watch_transfer.py`) are opt-in or require integration group.
- Run unit suite: `uv run pytest`. Full verification: `./scripts/test.sh`.

## Review questions for each PR

- [ ] Does it respect module boundaries (graph has no semantic dep)?
- [ ] Are destructive operations gated behind confirmation/`--yes`?
- [ ] Are all shell commands via `Runner`/`SubprocessRunner` (no `shell=True`)?
- [ ] Are paths validated with `safe_child` / `require_owned`?
- [ ] Are writes atomic (`atomic_write` / `write_json`)?
- [ ] Is the async→thread boundary respected in `runtime/mcp_server.py`?
- [ ] Are pinned versions updated consistently (adapter + locks + image guards + tests)?
- [ ] Is `graphify-out/` treated as potentially stale generated output?
- [ ] Are new CLI commands covered by help/registration tests?

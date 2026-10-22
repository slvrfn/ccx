---
name: ccx-service-cli
description: CLI commands, Application orchestration, locks, and destructive-operation approvals
---
# ccx-service-cli skill

Guidance for working with ccx's CLI layer (`cli.py`) and orchestration layer (`service.py`).

## CLI commands (`src/ccx/cli.py`)

| Command | Purpose | Key options |
|---|---|---|
| `init [--force]` | Install templates, create `.env` | `--force` |
| `env check` | Report missing/stale `.env` keys | — |
| `platform up [--ui]` | Start shared Milvus/etcd/MinIO (+Attu) | `--ui` |
| `platform down [--yes]` | Stop shared platform (retains volumes) | `--yes` |
| `platform status` | Compose service status | — |
| `open PATH` | Register/start project, refresh, launch OpenCode | `--graph/--no-graph`, `--watch`, `--interval`, `--no-interactive`, `--prepare-only`, `--rebuild` |
| `reindex TARGET [--full] [--yes]` | Refresh semantic + graph | `--full`, `--yes` |
| `build-graph TARGET [--full]` | Graph-only refresh | `--full` |
| `status TARGET` | Project/container/watcher/context status | — |
| `graph-status TARGET` | Local graph metadata | — |
| `graph-query TARGET QUERY` | Query graph via Graphify | QUERY |
| `search TARGET QUERY` | Semantic search | QUERY |
| `clear-index TARGET [--yes]` | Delete semantic index | `--yes` |
| `clear-graph TARGET [--yes]` | Delete owned graph directory | `--yes` |
| `watch TARGET [--interval] [--stop]` | Start/stop combined watcher | `--interval`, `--stop` |
| `export TARGET DESTINATION` | ZIP bundle of collection + graph | DESTINATION |
| `import TARGET SOURCE [--yes]` | Restore bundle (no overwrite) | `--yes` |

Hidden: `_watch-run TARGET --interval SECONDS --token TOKEN` (internal watcher launcher).

## `Application` (`src/ccx/service.py:22`)

- `initialize(force)` — reloads settings, rewrites docker/semantic settings.
- `require_running(project)` — raises `CcxError` if container not running.
- `open(path, graph, rebuild, prepare_only)` — validates graph dir ownership, saves project, writes generated files (`opencode.json`, `runtime.env`, `.opencode/` skill/plugin), `platform_up`, `ensure`, then `refresh` unless `prepare_only`.
- `refresh(project, full, semantic_only, graph_only)` — holds per-project operation lock; runs semantic build and/or graph build; writes `last-refresh.json`; raises on any failure.
- `status(project)` — container running, collection, watcher, graph status, semantic status (if running).

## Synchronization & locks

- Host refresh holds per-project `operation.lock` (30s timeout; `INDEX_TIMEOUT_SECONDS` for refresh).
- Inside container, all MCP calls, graph builds, clears, and transfers hold the same per-project HOME lock (`state.py:lock()`).
- Serializes separate CLI and OpenCode MCP processes; not a distributed lock across hostile containers/users.
- Watcher uses separate `watch.lock` to prevent duplicates; stop-file token avoids killing reused PIDs.

## Destructive operations & approvals

- `platform down`, `clear-index`, `clear-graph`, `import` require confirmation unless `--yes`.
- `reindex --full` requires confirmation unless `--yes`.
- Graph mutation (`extract`, `update`, `clear`) requires approval in generated OpenCode config; read tools auto-approved.
- `clear_index` gated behind confirmation/`--yes`; watcher must be stopped first.
- Repository code is never removed by a ccx command.

## Review checklist for CLI/service changes

- [ ] New command registered in `cli.py` and covered by `test_cli_help_all_required_commands`.
- [ ] Destructive ops use `click.confirm` unless `--yes`.
- [ ] `require_running` called before container-dependent operations.
- [ ] Operation lock wraps refresh; failures recorded in `last-refresh.json`.
- [ ] Graph-only path skips semantic; semantic-only path (internal) skips graph.
- [ ] `--prepare-only` skips refresh but still configures/starts container.

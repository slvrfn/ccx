# Transfer document traceability

| Document requirement | Implementation | Verification |
| --- | --- | --- |
| Shared Milvus, MinIO, etcd; optional Attu | `assets/compose.yaml`, `Docker.platform_up` | Compose shape tests; live smoke required |
| Stable per-project isolation | `Project`, `ProjectStore`, Docker binds/volumes | Identity and command-contract tests |
| Official OpenCode integration | Official version stage + matching npm release | Image version assertion; Docker build required |
| Separate inference and embedding services | `Settings`, `generated.py` | Config tests |
| Required CLI commands | `cli.py` | CLI registration/help tests |
| First semantic index and incremental refresh | Python MCP facade and pinned JS seam | Facade tests; live Milvus smoke required |
| Full rebuild | `reindex --full` | Argument forwarding tests |
| Graph extraction and configurable output | `graph/`, `runtime/graph_build.py` | Command tests and optional real extraction |
| Graphify default-on / per-project off | Persisted project flag | Config and orchestration tests |
| Read-only Graphify tools auto-approved | Explicit permission allowlist | Permission tests |
| Destructive operations approval | Click confirmations and OpenCode permissions | CLI/config tests |
| No periodic reindex by default | Upstream timer deliberately omitted | JS source contract; watcher opt-in tests |
| One debounced watcher for both backends | `watch.py`, `Application.refresh` | Debouncer/filter/lock tests |
| Persistent snapshots/state | Named HOME volume, project state | Docker command contract |
| Export/import | Versioned ZIP, schema/rows, graph, metadata | Archive validation tests; live round-trip smoke |
| Corruption/path protections | Atomic writes, traversal checks, checksums | Negative security tests |
| Modularity and future maintenance | Protocols, adapters, locks, docs, CI | Lint/type/unit checks |

## Explicit deviations and limitations

The final container is Debian rather than the upstream Alpine runtime, with the
official release version checked at build time. This avoids incompatible binary
Python dependency builds. Dense-only Milvus storage is the tested export format.
MCP incremental indexing needs a small JavaScript seam because upstream internals
are TypeScript/JavaScript, not a Python API.

Watcher events include add, modify and delete through native watchfiles events.
Generated/cache directories are excluded. A refresh failure is recorded and
retried only after another quiet period. The default debounce is five seconds.

Imports do not blindly restore path-dependent Merkle caches. Search works after
import; the first refresh intentionally rebuilds semantic snapshots. There is
no guaranteed point-in-time transaction covering simultaneous semantic and graph
versions, no overwrite import, no remote object-store backup, and no malicious
multi-tenant isolation promise.


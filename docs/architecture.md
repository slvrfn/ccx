# Architecture and integration contracts

## Boundaries

Click owns argument parsing and presentation. `Application` owns orchestration;
`Docker`, `ClaudeContext`, and `Graphify` own infrastructure. The `Runner` protocol
allows command construction to be tested without starting processes. Both
context integrations implement the small `ContextBackend` protocol, and neither
depends on the other.

Host state is in `CCX_HOME`, defaulting to `~/.claude-context-cli`. Each project
gets a path-derived slug, a Docker container, a named HOME volume, and a state
directory. Repository source is the only writable host bind mount. Generated
configuration is mounted read-only. The Docker socket is never mounted.

The source path is resolved before slug generation. Symlink aliases therefore
refer to one project. Relocating a repository changes its identity. The container
mount is `/workspace/<slug>`, which is also the Claude Context collection key
input. The collection naming algorithm is version-specific and isolated in
`Project.collection` and `runtime.transfer.collection_name`.

## Synchronization

Host refresh operations hold a per-project operation lock. Inside the container,
all semantic MCP calls, graph builds, clears, and transfers hold the same
per-project HOME lock. This serializes separate CLI and OpenCode MCP processes.
It is not a distributed lock across hostile containers or users.

FastMCP tool entry points are async, but delegate the complete synchronous operation
to an AnyIO worker thread. File locks, blocking subprocesses and the upstream MCP
client's own event loop stay on that worker; calling `asyncio.run()` directly
inside the server's event-loop thread is forbidden. Transport regression tests
exercise this boundary, not only the underlying helper functions.

The native watcher uses a background event observer and a foreground refresh
loop. The observer never performs indexing. Events are queued while indexing
runs and coalesced after a configurable quiet period. A separate lock prevents
duplicate watchers. A launch-token stop file avoids killing a reused PID.
Watchers do not restart automatically after reboot; opt in again with `ccx watch`.

An OpenCode Graphify MCP server is read-oriented and Graphify owns its read-time
reload/cache behavior. Its externally confirmed mutation tools are not serialized
through the Python facade. Do not approve direct graph mutation concurrently
with a build; use source changes plus `ccx build-graph` instead.

## Claude Context compatibility seam

The official `index_codebase` handler starts asynchronous indexing, rejects
already-indexed paths unless forced, and its server entrypoint creates a periodic
sync timer ([upstream handlers](https://raw.githubusercontent.com/zilliztech/claude-context/master/packages/mcp/src/handlers.ts),
[upstream entrypoint](https://raw.githubusercontent.com/zilliztech/claude-context/master/packages/mcp/src/index.ts)).
Our narrow JS entrypoint uses the pinned handlers without starting that timer.
Python keeps the MCP connection open until indexing reaches a terminal status.
For an existing index, a one-shot JS adapter invokes `Context.reindexByChange`.

This design intentionally imports internal package modules. It is more fragile
than a public API, so `0.1.15` is locked, version overrides fail the image build,
and `scripts/check-upstream.mjs` verifies the expected exports. Upgrades need
contract tests and a live Milvus smoke test.

The Milvus SDK is pinned separately to `2.5.10`. The database adapter normalizes
both modern numeric and legacy status codes, records failed writes that upstream
indexing may catch internally, and verifies stored row counts before reporting
success. A failed incremental update requires an explicit full rebuild so a
possibly advanced Merkle snapshot cannot silently hide lost changes.

OpenAI-compatible embedding endpoints use `OPENAI_BASE_URL`; the embedding class
detects dimensions for custom models rather than assuming a standard OpenAI
dimension ([embedding implementation](https://raw.githubusercontent.com/zilliztech/claude-context/master/packages/core/src/embedding/openai-embedding.ts)).
The runtime records the embedding endpoint/model identity and refuses incremental
refresh or search when that identity changes until a full rebuild. Export/import
also validates model name and probes vector dimension; matching names and
dimensions do not prove equivalent model weights. Operators must ensure that.

## Graphify compatibility seam

Graphify `extract` supports custom output, force, backend, and code-only flags
([extract reference](https://docs.graphify.com/reference/extract)).
The tested package is `graphifyy==0.9.83`; `graphify update <root>` is code-only and
uses `GRAPHIFY_OUT`, rather than accepting `--out`. Semantic mode therefore uses
cache-aware `extract --backend openai` on each refresh. Code-only is the default
and does not require an inference call.

The read allowlist is explicit: query, nodes, neighbors, communities, hub nodes,
statistics, and shortest path. All unknown tools require approval. Permissions
use fully qualified OpenCode MCP names, not a blanket allow. Configuration and
plugin files use the documented OpenCode formats
([MCP configuration](https://opencode.ai/docs/mcp-servers/),
[plugin API](https://opencode.ai/docs/plugins/)).
`index_codebase` is auto-approved as requested in the transfer document, including
its `force` parameter. For stricter protection, change that permission to `ask`.

## Docker runtime decision

The pinned official Dockerfile uses Alpine and musl
([official Dockerfile](https://raw.githubusercontent.com/anomalyco/opencode/v1.2.27/packages/opencode/Dockerfile)).
Graphify and PyMilvus pull scientific/native Python dependencies. To avoid fragile
Alpine source builds, the Dockerfile uses the official image as a version stage,
then installs that exact official OpenCode npm release in Debian with Python 3.12
and Node 22. It asserts the executable's version after installation. This is not
a byte-for-byte reuse of the official image's musl executable.

Python runtime dependencies are hash-locked in `requirements-container.txt`;
Node dependencies use `npm ci` and `package-lock.json`. Base-image tags are pinned
to versions, not digests. For production supply-chain hardening, resolve and
approve multi-architecture image digests in your registry and scan all dependency
layers. No vulnerability-free claim is made.

The npm manifest explicitly overrides `langsmith`, `qs`, and `uuid` to patched
versions. These transitive changes are locked and included in the live semantic
integration test; unused embedding-provider paths are not thereby certified.

## Portable snapshots and failure semantics

ZIP exports include dense vector schema and rows, metadata and graph artifacts.
Checksums detect corruption; they are not signatures and do not establish trust.
Extraction rejects duplicate members, symlinks, traversal, excess size and
unlisted data. Import checks the embedding model and dimension before creating
a new staging collection, inserts rows in batches, builds the index, checks the
row count, then renames to the target collection.

Import refuses any existing target collection or graph. It attempts cleanup of
the staging/final collection and graph on exceptions. A process kill, disk
failure, or rollback API failure can leave an `_import_...` collection; the
runbook covers inspection. There is no transaction spanning Milvus and the
filesystem and no distributed snapshot transaction across separate backends.

Raw chunk content is never path-rewritten. Stored metadata and graph references
are remapped. Snapshot information is retained for diagnostics, but path-dependent
Merkle state is not blindly restored. The first semantic refresh after import
is a full rebuild; existing search remains available until that refresh.

## Trust and non-goals

This is a local single-user development tool, not a hostile multi-tenant service.
Model endpoints may receive code. Local Milvus is unauthenticated and bound to
loopback; other processes in `context-net` can access it. Anyone with Docker
access can inspect environment variables and volumes. Do not expose ports to the
internet or mount untrusted repositories with privileged host credentials.

Not included: distributed queues, HTTP control plane, GPU provisioning, endpoint
model serving, guaranteed offline installation, unattended destructive cleanup,
Windows-native process support, Kubernetes, or semantic equivalence validation
of identically named embedding models.

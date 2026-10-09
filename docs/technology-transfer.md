# Technology Transfer Document

## OpenCode + Claude Context + Graphify + Milvus Local Development Stack

|  |  |
| :-- | :-- |
| **Tool/Service name** | `code-context-cli` (`ccx`) |
| **Status** | Working prototype, ready for team distribution |
| **Distributable artifact** | This python project should be installable via `uv tool install .` |

This document covers `ccx`'s platform layer (Milvus/etcd/MinIO), per-project layer (OpenCode + Claude Context + graphify), per-repository index isolation, and the opt-in filesystem watcher. `ccx` connects to whatever inference/embedding endpoints are configured in `.env`, which represent OpenAI-compatible APIs.

______________________________________________________________________

## 1. Purpose and Problem Statement

Agentic coding tools repeatedly call file-read and grep-style tools to build up understanding of a codebase before making an edit, producing many redundant, costly round-trips since each tool call re-sends accumulated context to the model. This system pairs **OpenCode** (an open-source terminal coding agent) with two complementary context tools instead of requiring the agent to read files directly:

- **Claude Context**, an open-source MCP server built by Zilliz that indexes a codebase into a vector database and exposes semantic search tools.
- **graphify**, an open-source tool that builds a queryable knowledge graph of the codebase (files, symbols, calls, imports, communities, and documentation relationships) and exposes it to the agent as an MCP server. It answers structural questions (what calls this, how do these modules connect) that similarity search answers poorly.

The entire system runs on local infrastructure. Code, embeddings, graphs, and prompts never have to leave the host machine, and the chat model and embedding model themselves can be served locally or called at an external OpenAI-compatible API. Despite its name, Claude Context has no dependency on Anthropic's Claude or Claude Code; it is a generic MCP server, wired here into OpenCode instead. Graphify's code extraction is performed locally with tree-sitter and requires no API calls (see Section 7 for the one case where an LLM is involved).

## 2. Architecture Overview

Independently lifecycled layers connect over a fixed Docker bridge network (`context-net`):

### 2.1 Platform layer (shared, long-running)

Started once via `ccx platform up` and left running:

- **etcd**, **minio** - Milvus's metadata store and object storage.
- **milvus-standalone** - the vector database holding every project's code embeddings, one isolated collection per project.
- **attu** *(optional, `--ui`)* - web UI for browsing Milvus collections.

By default, `MILVUS_PORT`, `MINIO_CONSOLE_PORT`, and `ATTU_PORT` are bound to `127.0.0.1` only, not `0.0.0.0`, so the platform layer is not reachable from the LAN unless a developer deliberately rebinds it. See Section 9 for the full security rationale.

Graphify adds no platform-layer service. It is file-based and per-project, so nothing is added to the shared stack.

### 2.2 Model layer

Chat-model and embedding-model serving is handled externally. `ccx` reaches that service (or any other OpenAI-compatible endpoint) via `INFERENCE_API_HOST`/`PORT` and `EMBEDDING_API_HOST`/`PORT` in `.env`; see Section 5.

### 2.3 Per-project layer (ephemeral, one per repository)

Started on demand via `ccx open <path>`:

- **opencode** - built from a custom Dockerfile layering Node.js and Python onto the official `ghcr.io/sst/opencode` image. Node is required because Claude Context ships as an npm package invoked via `npx`; Python is required to run the pinned `graphifyy` package (installed with `uv`) for graph building and serving.
- The target repository is **bind-mounted**, never baked into an image, at `/workspace/<project-slug>`.
- Claude Context runs as an **MCP subprocess spawned by OpenCode itself** (stdio transport), connecting to the shared Milvus instance over `context-net`.
- Graphify runs as a **second MCP subprocess spawned by OpenCode** (stdio transport), serving the project's `graphify-out/graph.json`. `ccx open` builds that graph before the MCP server is registered, because the server reads the graph file on launch. If graph building fails or `GRAPHIFY_ENABLED=false`, `ccx open` omits the graphify MCP entry and continues with Claude Context only.
- OpenCode's generated `opencode.json` registers Claude Context and graphify under its `mcp` key, each with an explicit `permission` block scoping which of their tools OpenCode may invoke without prompting, and which require confirmation. For Claude Context these are `index_codebase`, `search_code`, `get_indexing_status`, and `clear_index`. For graphify, the read-only query tools are allowed unattended, and any tool that rebuilds or rewrites the graph requires confirmation. The exact generated config blocks are documented in the README so a team member can audit what OpenCode can execute unattended.

Because the target repository is bind-mounted with read/write access, any tool OpenCode, Claude Context, or graphify executes has full filesystem access to that repository tree. Graphify additionally writes its output into `<repo>/graphify-out/`. Teams working with sensitive repos should review OpenCode's tool permissions before running `ccx open` unattended.

### 2.4 Project isolation mechanism

```
Claude Context names each Milvus collection by hashing the absolute filesystem path it's given (`code_chunks_<md5-hash>`). Every project is mounted at a distinct path (`/workspace/<slug>`, where `<slug>` = sanitized folder name + 8-character hash of the full host path), so each repository automatically receives its own isolated vector collection in the one shared Milvus instance, with no manual collection management required.
```

Graphify isolation is by directory: each project's graph lives in that repository's own `graphify-out/` folder (configurable via `GRAPHIFY_OUT_DIR`), so graphs are never shared or mixed between projects and need no naming scheme. `ccx open` adds `graphify-out/` to the repository's `.git/info/exclude` (not `.gitignore`, so tracked files are untouched) unless the team opts to commit the graph.

### 2.5 Optional auto-reindex via filesystem watcher

By default, indexing only happens when Claude Context's `index_codebase` tool is invoked explicitly (at `ccx open` time) or on demand (`ccx reindex`). Teams that want a project's index and graph to track ongoing edits without manually re-running `ccx reindex` can opt into a filesystem watcher:

- `ccx watch <path>` starts a lightweight watcher process, attached to the same bind-mounted repository tree used by that project's OpenCode container, using the host's native filesystem events (inotify on Linux, FSEvents-backed file sharing on macOS via Docker Desktop).
- The watcher debounces bursts of changes (default 30 seconds of inactivity, configurable via `WATCH_DEBOUNCE_SECONDS`) before triggering Claude Context's `index_codebase` tool for that project's collection and, if graphify is enabled for the project, an incremental graphify update of `graphify-out/`. A single reindex and graph update run after a batch of saves or a branch checkout rather than one per file event. The two actions run independently, so a failure in one does not block the other.
- `index_codebase` still relies on Claude Context's own incremental Merkle-tree diffing internally, so a watcher-triggered reindex only re-embeds changed files, not the whole tree. Graphify's update is likewise incremental. `ccx reindex <path>` remains the manual escape hatch for cases (large rebases, branch switches) where a full pass is preferred, and it rebuilds the graph in full as well.

```
- `ccx watch <path> --stop` (or `ccx stop <path>`, which stops both the project's container and any attached watcher) stops the watcher.
```

- The watcher is an independently lifecycled process per project, separate from the OpenCode container itself, so `ccx open`/`ccx stop` and `ccx watch`/`ccx watch --stop` can be started or stopped independently of one another.

The watcher is opt-in and is never started automatically by `ccx open`, since continuous watching adds a background process per project and some CPU/IO overhead on large trees. Graphify also ships its own git hooks and watch mode; `ccx` does not install these, to keep a single watcher in control of both indexes.

## 3. `.env` Reference

| Variable | Purpose | Required? |
| :-- | :-- | :-- |
| `INFERENCE_API_HOST` / `PORT` | Where OpenCode reaches the running chat model server (the companion model-serving service, or any external OpenAI-compatible endpoint) | No (defaults point at the companion service's default host/port) |
| `INFERENCE_MODEL_NAME` | Model name string OpenCode sends | No (defaults to the model name reported by the model-serving endpoint) |
| `EMBEDDING_API_HOST` / `PORT` | Where Claude Context reaches the running embedding model server (the companion model-serving service, or any external OpenAI-compatible endpoint) | No (defaults point at the companion service's default host/port) |
| `EMBEDDING_MODEL_NAME` | Model name string Claude Context sends | No (defaults to the model name reported by the model-serving endpoint) |
| `WATCH_DEBOUNCE_SECONDS` | Seconds of filesystem inactivity `ccx watch` waits after the last detected change before triggering an automatic reindex and graph update | No (default `30`) |
| `CLAUDE_CONTEXT_CUSTOM_EXTENSIONS` | Additional file extensions for Claude Context to index beyond its defaults | No |
| `CLAUDE_CONTEXT_CUSTOM_IGNORE_PATTERNS` | Additional ignore patterns applied on top of `.gitignore`, mitigating known negation/root-anchoring gaps (Section 9) | No |
| `GRAPHIFY_ENABLED` | Enable graphify for new projects (graph build at `ccx open`, MCP registration, watcher updates) | No (default `true`) |
| `GRAPHIFY_VERSION` | Pinned version of the PyPI package `graphifyy` installed into the OpenCode image. Must be `graphifyy` (two y's); similarly named packages are different projects | No (defaults to the version tested with this release) |
| `GRAPHIFY_OUT_DIR` | Directory name, relative to the repository root, for graph output | No (default `graphify-out`) |
| `GRAPHIFY_SEMANTIC_EXTRACTION` | Allow graphify's LLM-based extraction for docs, PDFs, and media. When `false`, only local AST extraction is used and no model calls are made by graphify | No (default `false`) |
| `MILVUS_VERSION`, `ETCD_VERSION`, `MINIO_VERSION` | Pinned image versions | No |
| `MILVUS_PORT`, `MINIO_CONSOLE_PORT`, `ATTU_PORT` | Host port bindings (bound to `127.0.0.1` by default; see Section 9) | No |

## 4. `ccx` CLI Command Reference

| Command | Purpose |
| :-- | :-- |
| `ccx init [--force]` | Write stack files to `~/.claude-context-cli` |
| `ccx platform up [--ui]` | Start Milvus/etcd/minio. Safe to re-run against an already-running stack (no-op if healthy) |
| `ccx platform down [--volumes]` | Stop platform stack |
| `ccx platform status` | Show platform container status |
| `ccx open <path> [--rebuild] [--no-graph]` | Open a repository in OpenCode with its own Claude Context index and, unless `--no-graph` or `GRAPHIFY_ENABLED=false`, a graphify knowledge graph |
| `ccx reindex <path>` | Force a fresh `index_codebase` pass and a full graph rebuild for a project, for use after a large branch switch, rebase, or other change too large for incremental Merkle-tree sync to be trusted |
| `ccx watch <path> [--interval N]` | Start a filesystem watcher for a project that debounces changes (`WATCH_DEBOUNCE_SECONDS`) and automatically triggers `index_codebase` and an incremental graph update, so both stay current without manual `ccx reindex` calls |
| `ccx watch <path> --stop` | Stop a running watcher for a project without affecting its OpenCode container |
| `ccx status <path>` | Show a project's Milvus collection name, indexed chunk count, and last-indexed timestamp, via Claude Context's `get_indexing_status` tool, plus the graph's node/edge counts and last-built timestamp when a graph exists |
| `ccx graph build <path> [--full]` | Build or incrementally update a project's graphify graph without touching the Claude Context index |
| `ccx graph query <path> "<question>"` | Query the project's graph from the host shell (wraps graphify's query command) |
| `ccx graph clear <path>` | Delete the project's `graphify-out/` directory. Does not affect the Milvus collection |
| `ccx clear-index <path>` | Wrap Claude Context's `clear_index` MCP tool to wipe a project's collection without removing the container. Does not delete the graph; use `ccx graph clear` for that |
| `ccx list` | List running per-project containers |
| `ccx stop <path\|slug>` | Stop a project's container and any watcher attached to it |
| `ccx rm <path\|slug> [--volumes]` | Remove a project's container, optionally its data volume. **`--volumes` is irreversible** |
| `ccx logs <path\|slug>` | Tail a project's logs |
| `ccx config` | Show resolved file paths |
| `ccx config --check` | Diff the active `.env` against the current `.env.example`, flagging stale, renamed, or missing variables after an upgrade or `ccx init --force` |
| `ccx export <path>` / `ccx import <path> <archive>` | Export or import a project's Milvus collection and its `graphify-out/` directory in one archive, so a team can share a pre-built index and graph for a large monorepo instead of every developer rebuilding them locally |
| `ccx init-project <path> [--force]` | Generate the project's `.opencode` agent/skill files (see Section 8). Requires the project to already be indexed via `ccx open`/`ccx reindex` |
| `ccx skills list <path>` | List the agent/skill files currently generated for a project |
| `ccx skills diff <path>` | Show what `ccx init-project --force` would change before overwriting existing `.opencode` files |
| `ccx doctor` | Verify Docker, `context-net` existence, Milvus reachability, and that the pinned `graphifyy` version is installable in the OpenCode image. |

## 5. Setup Instructions for a New Team Member

1. Install Docker (Compose v2 plugin) and [`uv`](https://docs.astral.sh/uv/).
2. `uv tool install .` from a checkout of the CLI package.
3. `ccx init`.
4. Edit `~/.claude-context-cli/.env`: set `INFERENCE_API_HOST`/`PORT` and `EMBEDDING_API_HOST`/`PORT` to point at wherever the chat and embedding models are being served, as an external OpenAI-compatible endpoint. Leave everything else at its default (graphify is enabled by default with local-only extraction).
5. `ccx platform up`.
6. Ensure the chat and embedding endpoints configured in step 4 are reachable (start the companion model-serving service if using it locally).
7. `ccx open <path-to-any-repo>`. Use `ccx status <path>` to confirm indexing and graph building have completed before relying on semantic or graph search results.
8. Optionally, `ccx watch <path-to-any-repo>` to keep that project's index and graph current automatically as you continue editing, instead of running `ccx reindex` manually.
9. Optionally, `ccx init-project <path-to-any-repo>` to generate project-specific OpenCode agent/skill files once the project is indexed (see Section 8).

## 6. Cross-Platform Notes

- **Linux**: full support, including native inotify support for `ccx watch`.
- **macOS (including Apple Silicon)**: Milvus, etcd, MinIO, Attu, and OpenCode all run natively via Docker Desktop with published ARM64 images. Graphify runs inside the OpenCode image and needs no host-side install. `ccx watch` relies on Docker Desktop's FSEvents-backed file sharing on macOS, which can lag slightly behind native inotify; the debounce window in `WATCH_DEBOUNCE_SECONDS` absorbs most of that latency.
- **Windows**: run under WSL2; the CLI assumes a POSIX shell. `ccx watch` uses WSL2's inotify support, which is native and reliable for files inside the WSL filesystem but degrades for repositories bind-mounted from the Windows filesystem (`/mnt/c/...`); keeping the target repository inside the WSL filesystem is recommended when using `ccx watch`. The same applies to graph build time, since graphify walks the whole tree.


## 7. Known Limitations and Risks

- **`.gitignore` handling gaps**: negation and some root-anchored patterns aren't correctly honored upstream by Claude Context. `CLAUDE_CONTEXT_CUSTOM_IGNORE_PATTERNS` (Section 3) is available as a local mitigation for the specific patterns a team hits, though it does not fix the upstream matcher itself. Graphify applies its own ignore handling, so the two tools may include different file sets; compare `ccx status <path>` counts if results look inconsistent.

```
- **No filesystem watcher by default**: indexing happens only when the agent invokes Claude Context's tools, or on demand via `ccx reindex`, unless a project opts into `ccx watch <path>` (Section 2.5), which debounces filesystem changes and triggers automatic reindexing and graph updates. The watcher is opt-in and is not started automatically by `ccx open`, since continuous watching adds a background process per project and consumes CPU/IO on large trees; teams working on very large monorepos should weigh that ongoing cost against staleness risk before enabling it. Even with the watcher running, staleness between the last file change and the next debounce-triggered reindex is possible; `ccx reindex <path>` remains the manual escape hatch for cases (large rebases, branch switches) where a guaranteed full pass is preferred over waiting on the watcher.
```

- **Graph staleness and server reload**: the graphify MCP server reads `graph.json` when it launches. A graph rebuilt while OpenCode is running may not be visible to the agent until the MCP subprocess restarts, so after `ccx reindex` or a large watcher update, restart the OpenCode session if graph answers look out of date.
- **Graphify semantic extraction**: local AST extraction makes no model calls, but graphify's extraction of docs, PDFs, and media uses an LLM. It is disabled by default (`GRAPHIFY_SEMANTIC_EXTRACTION=false`). If enabled, document content is sent to whichever model endpoint graphify is configured with, which may be external, so enable it only where that is acceptable.
- **Graphify package identity and churn**: the correct PyPI package is `graphifyy`. Similarly named projects exist and are unrelated. `GRAPHIFY_VERSION` pins the tested release; upgrade deliberately and run `ccx doctor` afterwards.
- **Generated files in the repository**: graphify writes `graphify-out/` (graph, report, HTML visualization) into the bind-mounted repository. It is excluded from git locally by default, but a team that commits it should expect noisy diffs on rebuilds.
- **No authentication in front of Milvus/Attu/MinIO**: acceptable for a single-developer host, not for a shared/multi-tenant one without additional hardening. Default port bindings restrict these services to `127.0.0.1` (Section 2.1); a team exposing them beyond localhost should add a reverse proxy with authentication in front, which this system does not provide. `ccx` runs graphify only over stdio and never uses its HTTP serving mode, so graphify opens no network listener.
- **Destructive volume operations**: `ccx rm --volumes` is irreversible. `ccx init-project --force` (Section 8) carries the same irreversibility for generated `.opencode` files and should be treated with the same caution. `ccx graph clear` is destructive but recoverable by rebuilding.
- **Bind-mounted repository access**: because the target repository is bind-mounted read/write into the OpenCode container (Section 2.3), any tool OpenCode executes has full access to that tree; there is no sandboxing beyond the container boundary itself.
- **Dependency on the model-serving endpoint**: `ccx open` assumes `INFERENCE_API_HOST`/`PORT` and `EMBEDDING_API_HOST`/`PORT` resolve to a reachable, ready endpoint. If the companion model-serving service (or external endpoint) is not running, OpenCode and Claude Context will fail against it; see that document for its own health-check and readiness behavior. Graphify's default AST-only mode does not depend on these endpoints.


## 8. Recommended Next Steps

- Move the CLI source into a git repository with CI (lint, `py_compile`/`pytest` smoke tests, plus a `ccx doctor` and `docker compose config` dry-run smoke test) instead of distributing as a loose file. Add a CI step that builds the OpenCode image and runs `graphify --help` inside it, to catch package pinning or Python layering regressions.


## 9. Additional Requirements

The code to support this tool/service should follow standard software engineering practices, such as decomposing/decoupling code where possible, to allow for a modular system. Type hints should be used in any python functions for parameters and function returns. Graphify support should live in its own module (for example `ccx/graph/`, with separate build, serve-config, and status functions) behind a small interface shared with the Claude Context integration, so either tool can be disabled or replaced without touching the other.

A README should be generated describing the system, installation, usage, and project structure. It should also include a troubleshooting section covering the failure modes documented in Section 7 (`.gitignore` gaps, and dependency on a reachable model-serving endpoint) so a contributor reading only the README, not this transfer document, still sees them. The troubleshooting section should also cover the graphify-specific items: stale graph until the MCP server restarts, the `graphifyy` package name, and the semantic-extraction opt-in.

`code-context-cli` (`ccx`) should be able to init an existing project with new agent and skill md files in a new per-project `.opencode` directory, via `ccx init-project <path> [--force]` (Section 4), with the option to `--force` that directory's re-initialization. This requires the target project to already have been indexed by `ccx` (via `ccx open` or `ccx reindex`), since the generation step queries Claude Context's `search_code` and `get_indexing_status` tools against the project's existing collection to detect its primary language, frameworks, and directory conventions, and templates the generated skill file with project-specific tool-call guidance (e.g., prefer semantic search over raw file reads) rather than shipping a static generic template. When a graphify graph exists for the project, the generation step also reads it (for example its `GRAPH_REPORT.md` summary of central nodes and communities) to name the project's key modules, and the skill file adds guidance on when to use graph queries (callers, dependencies, cross-module paths) versus semantic search. If no graph exists, the graph guidance is omitted rather than generated generically. If `ccx init-project` is run against a project with no existing index, it should fail with a clear message directing the user to run `ccx open` first, rather than silently generating a generic template.

```
`--force` fully overwrites the `.opencode` directory's generated files; it does not attempt to merge or preserve manual edits a developer has made to them. This is an irreversible operation (see Section 7) and should be treated with the same caution as `ccx rm --volumes`. `ccx skills diff <path>` (Section 4) should be run first to preview the change, and `ccx skills list <path>` can be used to inspect what currently exists.
```

Appropriate agent and skill md files should also be created for `code-context-cli` (`ccx`) itself, so that a developer can leverage `ccx` (via `ccx init-project` run against `ccx`'s own repository, once indexed) to improve later iterations of `ccx`. These should describe the graphify module boundary described above.

A user should be able to request auto-reindexing of a codebase as it evolves, rather than being limited to the manual `ccx reindex` command. This is provided via `ccx watch <path>` (Sections 2.5 and 4), backed by a filesystem watcher on the bind-mounted repository tree that debounces bursts of changes (`WATCH_DEBOUNCE_SECONDS`) before triggering Claude Context's `index_codebase` tool and the incremental graphify update, so the project's collection and graph stay reasonably current without requiring the developer to remember to run `ccx reindex` after every meaningful change. The watcher must be opt-in per project and independently stoppable from the project's OpenCode container itself.
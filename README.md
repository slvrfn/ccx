# Code Context CLI

A modular Python implementation of the supplied OpenCode + Claude Context +
Graphify technology transfer document. `ccx` manages a shared local Milvus stack,
isolated per-repository OpenCode containers, semantic indexing, structural code
graphs, an opt-in combined watcher, and portable logical snapshots.

## Requirements

- Linux or macOS, Python 3.12+, Docker Engine/Desktop with Compose v2, and `uv`.
- A non-root host user. Docker access is highly privileged; use trusted repositories.
- An OpenAI-compatible inference endpoint and a separate embedding endpoint.
- Network access on initial install/build to retrieve pinned packages and images.
- Native Windows is not supported; use WSL2 with the project on the Linux filesystem.

## Install and run

```bash
./scripts/install.sh
ccx init
# Edit ~/.claude-context-cli/.env, particularly endpoint URLs and model names.
ccx env check
ccx platform up
ccx open /absolute/path/to/repository
```

`open` creates the project container, waits for a semantic index, builds or updates
the graph, then launches OpenCode. There is no default watcher or background sync
timer. You can build without entering the TUI:

```bash
ccx open . --no-interactive
ccx status .
ccx search . "where are requests authenticated?"
ccx graph-query . "authentication"
ccx reindex .
ccx build-graph .
```

`graph-query` is Graphify's graph traversal/query interface, not a promise of
LLM-generated natural-language answers. Its argument is passed as one argument,
never interpreted by a shell.

## Optional behavior

```bash
ccx open . --no-graph
ccx open . --watch --interval 5
ccx watch . --stop
ccx watch . --interval 5
ccx reindex . --full           # confirmation required
ccx clear-index .             # does not clear graph
ccx clear-graph .             # does not clear vectors
ccx platform up --ui
ccx platform down             # retains all volumes
```

`--interval` controls the quiet-period debounce. It is not a periodic full-rebuild
timer. One watcher updates both enabled backends, serially; edits arriving during
a refresh remain queued.

## Back up and restore

```bash
ccx export . /safe/location/project-context.zip
# On a second machine with the same embedding model:
ccx open /path/to/repository --prepare-only --no-interactive
ccx import /path/to/repository /safe/location/project-context.zip
```

The ZIP contains a versioned manifest, checksums, collection schema and vector
rows, informational indexing snapshot, and graph artifacts. It does not contain
API keys, the host `.env`, or repository source files, but vectors contain code
chunks and graph artifacts may contain source-derived text. Treat bundles as
confidential. Import never overwrites an existing collection or graph and probes
the configured embedding dimension before mutation. It stages a collection,
checks row counts, and attempts rollback on failure.

An imported index is immediately searchable. The first subsequent semantic
refresh is a full rebuild because path-dependent Merkle snapshots are not safely
portable. Graph extraction uses its normal cache-aware path; imported graph
artifacts are portable, but local extraction caches are not an incremental-state
guarantee. See [architecture](docs/architecture.md).

## Development

```bash
uv sync --locked --group dev
./scripts/test.sh
./scripts/test-integrations.sh  # real packages with a local embedding stub
uv run ccx --help
./scripts/build.sh
```

Unit tests use fakes at the process/MCP boundaries and do not need Docker, model
credentials, or paid APIs. Optional Graphify tests require its pinned package.
Docker acceptance tests require Docker and explicitly configured endpoints:

```bash
CCX_RUN_DOCKER_TESTS=1 ./scripts/smoke.sh /path/to/disposable/repository
```

The smoke script operates on a disposable copy. It can send repository code to the
embedding endpoint configured in `.env`. Review endpoint settings first.

The offline integration script needs Node/npm and Linux or macOS x86-64 support
for the Milvus Lite binary. It verifies actual indexing, search, incremental
changes, export, and rollback when Lite rejects collection rename. Successful
import promotion is unit-tested with a fake and still requires the standalone
Milvus Docker acceptance run.

To build the image directly from the source tree:

```bash
docker build --build-arg CCX_UID="$(id -u)" --build-arg CCX_GID="$(id -g)" -t ccx-opencode:local .
```

Prefer `ccx open` for normal operation, since it supplies networking, environment,
repository mounts, persistent HOME, and generated OpenCode configuration.

## Project layout

```text
src/ccx/
  cli.py                 CLI presentation
  service.py             lifecycle and multi-backend use cases
  config.py              configuration/validation/template installation
  project.py             path identity and project registry
  process.py, docker.py   subprocess and Docker adapters
  semantic.py            Claude Context host adapter
  graph/                 isolated Graphify backend
  runtime/               in-container MCP, indexing, graph, transfer adapters
  watch.py               native watcher, queue, debounce, graceful control
  transfer.py            archive format and safe extraction
  assets/                Dockerfile, Compose, environment and dependency locks
tests/                   unit/contract tests and optional integration tests
scripts/                 install, test, build, smoke, dependency refresh
docs/                    architecture, requirements traceability, runbook
```

Top-level Dockerfile and Compose files are convenience copies of the packaged
templates. `ccx init` copies authoritative packaged templates into its home.
After changing a template, run `scripts/sync-templates.sh` and the test suite.

## Verification boundary

This project includes an automated test suite and Docker acceptance scripts.
The delivered verification report states exactly which checks ran in the build
environment. Do not treat passing unit tests as evidence that your Docker daemon,
GPU endpoints, authentication, or embedding model have passed integration tests.

## Important design decisions

- The official OpenCode image provides the pinned version; a Debian final stage
  installs that same official npm release so Python binary dependencies work.
  This is an explicit change from the document's literal Alpine-base suggestion.
- Dense embeddings are enabled and hybrid/BM25 mode is disabled. This keeps the
  exported schema unambiguous; adding hybrid export needs a schema migration.
- A small pinned JavaScript compatibility seam calls Claude Context internals;
  the host application and orchestration are Python. It deliberately omits the
  upstream automatic synchronization timer.
- Version changes are maintenance tasks, not arbitrary environment overrides.
  Regenerate locks, update the tested adapters, and run acceptance tests together.
- No software license was inferred for your new project. Third-party packages
  retain their upstream licenses; select your own project license before public
  redistribution.

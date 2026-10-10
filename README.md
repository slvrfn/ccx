# Code Context CLI

`ccx` provides a local development environment combining OpenCode, Claude Context
semantic search, and Graphify code graphs. This README is the user guide and command
reference for version `0.1.2`; the commands and defaults below match the supplied
implementation, not hypothetical upstream features.

If you encountered `asyncio.run() cannot be called from a running event loop`
or the FastMCP `lifespan` warning in 0.1.0, use the
[0.1.1 fix and upgrade guide](docs/releases/0.1.1.md). Upgrading the host package
alone is not enough: recreate the project container with the fixed runtime.

## Contents

- [What ccx manages](#what-ccx-manages)
- [Requirements and installation](#requirements-and-installation)
- [First-time setup](#first-time-setup)
- [Command conventions and quick reference](#command-conventions-and-quick-reference)
- [Global options](#global-options)
- [Setup and platform commands](#setup-and-platform-commands)
- [Opening and configuring projects](#opening-and-configuring-projects)
- [Searching and inspecting context](#searching-and-inspecting-context)
- [Refreshing context](#refreshing-context)
- [Watching file changes](#watching-file-changes)
- [Exporting, importing, and clearing data](#exporting-importing-and-clearing-data)
- [Configuration reference](#configuration-reference)
- [Project Python environments and large dependency downloads](#project-python-environments-and-large-dependency-downloads)
- [Common workflows](#common-workflows)
- [State, generated files, and permissions](#state-generated-files-and-permissions)
- [Troubleshooting](#troubleshooting)
- [Development, testing, and release files](#development-testing-and-release-files)
- [Limitations and further documentation](#limitations-and-further-documentation)

## What ccx manages

There are two independent kinds of code context. Use semantic search to locate
implementations by meaning, and use the graph to explore structural relationships.

| Component | Role | When it is used |
| --- | --- | --- |
| OpenCode | Interactive coding assistant | `ccx open`, unless `--no-interactive` is set |
| Claude Context | Code chunks, embeddings, and semantic search | Indexing and `ccx search` |
| Graphify | Structural graph, communities, and reports | Enabled by default; optional per project |
| Milvus | Stores semantic vectors | Shared by registered projects, with separate collections |
| MinIO and etcd | Storage and metadata services for Milvus | Started with the shared platform |
| Attu | Optional Milvus administration UI | `ccx platform up --ui` |
| Combined watcher | Refreshes both enabled backends after file changes | Opt in with `--watch` or `ccx watch` |

Each repository has a project container and persistent HOME volume. The shared
platform is separate, and exiting OpenCode does not stop containers, services, or
a detached watcher.

## Requirements and installation

Use a non-root Linux or macOS account with Python 3.12+, `uv`, and a running Docker
Engine/Desktop installation with Compose v2. Native Windows is not supported by
this implementation; use WSL2 with the repository on its Linux filesystem.

- **Model endpoints:** provide an OpenAI-compatible inference endpoint for OpenCode
  and an embedding endpoint for Claude Context. ccx does not install or serve models.
- **Network access:** initial installation and image builds download dependencies
  and container images. This is not an offline installation bundle.
- **Repository trust:** the project container can write to the mounted repository.
  Only open repositories you trust, and review where your model endpoints send code.
- **Permissions:** do not use `sudo ccx`. The image maps the host user's non-root
  UID/GID so generated repository files are not owned by root.

From the extracted project directory, choose one installation method:

```bash
# Recommended: install the CLI as an isolated uv tool.
./scripts/install.sh
ccx --version
ccx --help
```

```bash
# Alternatively: install the included wheel.
uv tool install --python 3.12 dist/code_context_cli-0.1.2-py3-none-any.whl
```

The installation script must be run from the supplied project tree, not from the
repository you want to analyze. After installation, `ccx` can be invoked from any
directory; if your shell cannot find it, refresh your shell and check the executable
directory configured by `uv`.

## First-time setup

Initialize the application home, then edit the active configuration. The default
home is `~/.claude-context-cli`; a target repository's own `.env` is not ccx's
configuration file.

```bash
ccx init
# Edit ~/.claude-context-cli/.env with your editor.
ccx env check
docker info
docker compose version
```

Configure these values at a minimum, using model identifiers your servers actually
provide. The example addresses are the shipped defaults; they do not start model
servers or guarantee that those services exist.

```dotenv
INFERENCE_API_HOST=host.docker.internal
INFERENCE_API_PORT=8080
INFERENCE_API_KEY=local-inference
INFERENCE_MODEL=local-coder

EMBEDDING_API_HOST=host.docker.internal
EMBEDDING_API_PORT=8081
EMBEDDING_API_KEY=local-embedding
EMBEDDING_MODEL=local-embedding
```

The resulting default base URLs are `http://host.docker.internal:8080/v1` and
`http://host.docker.internal:8081/v1`. For remote services, HTTPS, IPv6, or a different
base path, set the corresponding `*_API_BASE_URL` instead.

```bash
# Optional explicit startup; ccx open also starts the shared platform.
ccx platform up

# Register, index, build the graph, and enter OpenCode.
ccx open /absolute/path/to/repository
```

The first open can take longer because it builds an image and creates the initial
indexes. To initialize context without entering OpenCode, use:

```bash
ccx open /absolute/path/to/repository --no-interactive
ccx status /absolute/path/to/repository
```

`ccx env check` checks configuration key drift and configuration parsing. It does
not test API keys, model availability, Docker connectivity, or endpoint health.

## Command conventions and quick reference

`PATH` means an existing repository directory. `TARGET` means either that registered
repository's path or its generated slug; `ccx open` requires a path, not a slug.

```bash
ccx open "/home/me/projects/my app" --no-interactive
ccx status "/home/me/projects/my app"

# From inside the registered repository:
ccx status .
ccx search . "where is authentication implemented?"

# You can also use the actual slug printed by ccx open:
# ccx status my-app-<eight-character-hash>
```

The slug is derived from the resolved absolute path, not just the directory name.
Run commands from the registered repository root when using `.`, and quote paths
with spaces and multiword queries. Paths containing commas or newlines are rejected.

Command-reference examples demonstrate individual alternatives unless described
as a workflow. Before copying a whole block, check its comments and the lifecycle
requirements, especially for watcher startup and destructive operations.

| Command | Purpose | Important options |
| --- | --- | --- |
| `ccx init` | Create/update application-home files | `--force` |
| `ccx env check` | Report missing and unknown `.env` keys | No command-specific options |
| `ccx platform up` | Start shared services and wait for health checks | `--ui` |
| `ccx platform status` | Show Compose service status | No command-specific options |
| `ccx platform down` | Stop shared platform services; retain volumes | `--yes` |
| `ccx open PATH` | Register/configure/start a project and normally refresh it | `--graph`, `--no-graph`, `--watch`, `--interval`, `--no-interactive`, `--prepare-only`, `--rebuild` |
| `ccx status TARGET` | Show project, container, watcher, and context status | No command-specific options |
| `ccx search TARGET QUERY` | Search indexed code semantically | No command-specific options |
| `ccx graph-status TARGET` | Read local graph status and counts | No command-specific options |
| `ccx graph-query TARGET QUERY` | Query the existing graph through Graphify | No command-specific options |
| `ccx reindex TARGET` | Refresh semantic context and the enabled graph | `--full`, `--yes` |
| `ccx build-graph TARGET` | Refresh only the graph | `--full` |
| `ccx watch TARGET` | Start or stop the combined watcher | `--interval`, `--stop` |
| `ccx export TARGET DESTINATION` | Write a context backup ZIP | No command-specific options |
| `ccx import TARGET SOURCE` | Restore a context backup into an empty target | `--yes` |
| `ccx clear-index TARGET` | Delete semantic context only | `--yes` |
| `ccx clear-graph TARGET` | Delete ccx-owned graph output only | `--yes` |

Every public command and command group supports `--help`. There is no `ccx help`
subcommand; use `ccx --help`, `ccx platform --help`, or `ccx open --help`.

## Global options

Global options appear before the subcommand. They are separate from the options
accepted by `open`, `watch`, or other individual commands.

| Option | Behavior | Example |
| --- | --- | --- |
| `--home PATH` | Override the application-home directory | `ccx --home /home/me/ccx-state status .` |
| `--version` | Print the installed ccx version and exit | `ccx --version` |
| `--help` | Print command-group help and exit | `ccx --help` |

Application-home selection is `--home PATH`, then `CCX_HOME`, then
`~/.claude-context-cli`. Use the same home consistently for registration and later
operations:

```bash
export CCX_HOME="$HOME/.ccx-work"
ccx init
ccx open /path/to/repository --no-interactive
ccx status /path/to/repository
```

A different home is not a completely isolated Docker deployment. This version uses
the fixed Compose project name `ccx-platform`, network `context-net`, and path-derived
project container names, so separate homes can still affect the same Docker resources.

## Setup and platform commands

### `ccx init [--force]`

Creates the application home, templates, image-build inputs, and a private `.env`
if none exists. A fresh `.env` receives a generated MinIO password; initialization
does not start Docker services or contact your model endpoints.

| Option | Default | Effect |
| --- | --- | --- |
| `--force` | Off | Replace the home copies of `compose.yaml`, `Dockerfile`, and `.dockerignore` with shipped templates |

```bash
ccx init
ccx init --force
```

Existing `.env` values and project state are preserved, including when `--force`
is used. The example environment file and packaged build inputs are refreshed on
initialization, but new keys are not automatically merged into an existing `.env`;
compare it with `.env.example` after upgrading.

### `ccx env check`

Reports key differences between the active home `.env` and the shipped template.
Configuration values are parsed and validated when the CLI loads, but this command
does not print secrets or perform connection tests.

```bash
ccx env check
```

An aligned file produces:

```json
{
  "missing": [],
  "unknown_or_stale": []
}
```

Missing keys can still receive shipped defaults, and environment variables can
override file values. The report compares file keys, not just effective settings;
nonempty lists do not themselves cause a nonzero exit status.

### `ccx platform up [--ui]`

Starts Milvus, MinIO, and etcd in the background and waits for service health checks.
This command also initializes any missing application-home files.

| Option | Default | Effect |
| --- | --- | --- |
| `--ui` | Off | Include the optional Attu Compose profile |

```bash
ccx platform up
ccx platform up --ui
ccx platform status
```

Default host bindings are loopback-only: Milvus uses port `19530`, the MinIO console
uses `9001`, and Attu uses `8000` when enabled. Browse Attu at `http://127.0.0.1:8000`
or the MinIO console at `http://127.0.0.1:9001`; use your configured ports if changed.
The console login uses `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` from the active
configuration.

### `ccx platform status`

Displays Docker Compose's service-status output. This is a shared-platform view,
not a list of all per-repository OpenCode containers.

```bash
ccx platform status
docker ps --filter label=ccx.managed=true
```

The second command is ordinary Docker, not a ccx subcommand. Use it when you need
to see project containers across repositories.

### `ccx platform down [--yes]`

Requests confirmation before stopping shared services and retains their named
volumes. It affects the common platform, so other projects can lose access to
semantic search while it is down.

| Option | Default | Effect |
| --- | --- | --- |
| `--yes` | Off | Skip the confirmation prompt |

```bash
# Stop each active watcher before shutting down its backing services.
ccx watch /path/to/repository --stop
ccx platform down

# Noninteractive equivalent, after deliberately choosing to stop shared services:
ccx platform down --yes
```

This does not stop detached watchers or replace the separate project-container
lifecycle. The ccx command does not explicitly enable the `ui` profile during
shutdown; if you need a profile-inclusive Compose shutdown, run:

```bash
docker compose --project-name ccx-platform \
  --env-file "${CCX_HOME:-$HOME/.claude-context-cli}/.env" \
  -f "${CCX_HOME:-$HOME/.claude-context-cli}/compose.yaml" \
  --profile ui down
```

That Docker command retains volumes because it omits `--volumes`. Do not add
volume-deletion options unless you intend to delete persistent platform data.

## Opening and configuring projects

### `ccx open PATH [OPTIONS]`

Registers the path, writes generated OpenCode configuration, starts the shared
platform, builds or reuses the image, and starts the project container. Normally
it then refreshes semantic context and the enabled graph before launching OpenCode.

| Option | Default | Behavior |
| --- | --- | --- |
| `--graph` | Use `GRAPHIFY_ENABLED` if neither graph flag is supplied | Enable Graphify for this opening |
| `--no-graph` | Not selected | Disable Graphify registration and refresh for this project |
| `--watch` | Off | Start the detached combined watcher after setup |
| `--interval SECONDS` | `WATCH_DEBOUNCE_SECONDS`, initially `5` | Set watcher quiet-period debounce; CLI minimum is `0.1` seconds |
| `--no-interactive` | Off | Do not launch the OpenCode terminal interface |
| `--prepare-only` | Off | Skip initial semantic/graph refresh after configuring and starting the container |
| `--rebuild` | Off | Invoke the Docker image build even if the expected image already exists |

```bash
ccx open .                              # Refresh and enter OpenCode
ccx open . --no-interactive             # Refresh and return to the shell
ccx open . --no-graph                   # Semantic context without graph integration
ccx open . --graph --watch --interval 2 # Both contexts, interactive, with watching
ccx open . --watch --no-interactive     # Headless setup with a detached watcher
ccx open . --prepare-only --no-interactive
ccx open . --rebuild --no-interactive
```

- **Container replacement:** reopening removes/recreates the project container.
  Exit active OpenCode sessions and stop its watcher first. The repository bind
  mount and persistent HOME volume survive; arbitrary container-layer changes do not.
- **Graph setting lifetime:** the selected graph setting is stored for later
  commands, but a subsequent `open` without either graph flag recomputes it from
  `GRAPHIFY_ENABLED`. To keep graph integration off, set the environment default
  to `false` or pass `--no-graph` on each reopen.
- **Preparation versus interaction:** `--prepare-only` does not imply
  `--no-interactive`. Pair them to prepare an import target without launching
  OpenCode, and do not add `--watch` if you want it to remain unindexed.
- **Image versus index rebuild:** `--rebuild` is not `reindex --full` and does not
  disable Docker layer caching. It is an image-build operation, not a forced
  semantic or graph rebuild.
- **Interval without watching:** `--interval` alone does not start a watcher.
  With `open`, it only matters when `--watch` is also supplied.
- **Generated configuration:** reopening rewrites ccx-owned configuration,
  instructions, skill, and plugin files. Do not expect hand edits to those
  generated files to survive another `open`.

### Working inside OpenCode

After `ccx open` enters the terminal UI, ask the assistant to use semantic search
for implementation discovery or Graphify for relationships and impact analysis.
For example, ask “Use semantic search to find token validation” or “Use the graph
to identify callers of the authentication function.”

Semantic search/status/indexing and the explicit read-oriented Graphify allowlist
are auto-approved by the generated configuration. `clear_index`, unknown tools,
and Graphify mutation tools require approval; importantly, the auto-approved
`index_codebase` tool also accepts a `force` parameter. For a stricter policy,
change its generated permission to `ask`, remembering that reopening regenerates
the file.

## Searching and inspecting context

### `ccx search TARGET QUERY`

Searches the existing semantic index using the configured embedding endpoint.
It requires a running project container and does not implicitly refresh stale code.

```bash
ccx search . "where are API requests authenticated?"
ccx search /path/to/repository "retry logic after a network timeout"
```

This CLI requests up to 20 results from its semantic adapter. There is no public
`--limit` option in this version, and results are printed as returned text rather
than a promised stable JSON schema.

### `ccx graph-query TARGET QUERY`

Passes the query to Graphify using the configured graph file. The project must
have Graphify enabled, a running container, and an existing graph.

```bash
ccx graph-query . "authentication"
ccx graph-query . "payment"
```

The query is one positional argument, so quote multiword text. This is Graphify's
query/traversal interface, not a guarantee of an LLM-written answer; ccx does not
forward arbitrary Graphify CLI flags.

### `ccx status TARGET`

Prints JSON with the project slug/path, container-running state, collection name,
watcher-running state, graph-enabled setting, and graph information. If the project
container is running, it also attempts to retrieve semantic indexing status.

```bash
ccx status .
ccx status /path/to/repository > project-status.json
```

Semantic failures can appear as an `error` field inside otherwise successful
status output. Inspect the content rather than treating exit status zero as proof
that every backend is healthy or up to date.

### `ccx graph-status TARGET`

Reads graph metadata directly from the registered repository's output directory.
It reports whether Graphify is enabled and whether the graph exists, plus node
count, edge count, and the graph file's last-modified time when available.

```bash
ccx graph-status .
```

Unlike `graph-query`, this command does not need a running project container or
an inference endpoint. The timestamp is file metadata, not proof that every
current source edit has been indexed.

## Refreshing context

### `ccx reindex TARGET [--full] [--yes]`

Refreshes semantic context and, if enabled, the graph. It requires a running
project container; there is no public `--semantic-only` option.

| Option | Default | Behavior |
| --- | --- | --- |
| `--full` | Off | Rebuild semantic context and force graph extraction instead of normal incremental behavior |
| `--yes` | Off | Skip the confirmation required by `--full`; has no additional effect on an ordinary refresh |

```bash
ccx reindex .                 # Normal refresh
ccx reindex . --full          # Ask before a full rebuild
ccx reindex . --full --yes    # Deliberately confirmed, noninteractive rebuild
```

An existing semantic index normally uses file-change-based indexing. A first
index is built from scratch, and an imported index deliberately performs a full
semantic rebuild on its first refresh even without `--full`.

If one backend fails, ccx still attempts the other and records the results in
`projects/<slug>/last-refresh.json` under the application home. A failed semantic
index or changed embedding identity requires an explicit full rebuild; see the
recovery workflow below.

### `ccx build-graph TARGET [--full]`

Refreshes only the graph and leaves the semantic index untouched. Graphify must
be enabled and the project container must be running.

| Option | Default | Behavior |
| --- | --- | --- |
| `--full` | Off | Force graph extraction rather than normal cached/update behavior |

```bash
ccx build-graph .
ccx build-graph . --full
```

In code-only mode, an existing graph uses `graphify update`. With semantic graph
extraction enabled, refresh uses cache-aware extraction against the inference
endpoint. Unlike `reindex --full`, `build-graph --full` does not prompt for
confirmation and has no `--yes` option.

## Watching file changes

### `ccx watch TARGET [--interval SECONDS] [--stop]`

Starts a detached host process that watches repository changes and refreshes both
enabled context backends. There is no watcher or periodic semantic sync timer by
default; start one explicitly when you want automatic refreshes.

| Option | Default | Behavior |
| --- | --- | --- |
| `--interval SECONDS` | `WATCH_DEBOUNCE_SECONDS`, initially `5` | Quiet time after the latest event before refreshing; CLI minimum `0.1` |
| `--stop` | Off | Request graceful shutdown instead of starting a watcher |

```bash
ccx watch .
ccx status .
ccx watch . --stop

# Start again with a different quiet period:
ccx watch . --interval 2
```

Only one watcher may run per project. To change its interval, stop it and start
it again; a second start reports “Watcher is already running” rather than updating
the existing process.

```bash
ccx watch . --stop
ccx watch . --interval 10
```

- **Debounce:** an interval of five means “wait for five quiet seconds,” not
  “reindex every five seconds.” Watching itself does not perform an immediate
  initial refresh; use `open` or `reindex` first when needed.
- **Events during work:** changes arriving while a refresh runs remain queued.
  One observer feeds one refresh loop, rather than running a separate graph watcher.
- **Ignored paths:** the configured graph output, `.git`, `.opencode`, virtual
  environments, `node_modules`, common caches, `dist`, and `build` are excluded.
  Names beginning with `.env` and suffixes `.pem`, `.key`, `.swp`, `.tmp`, and
  `.pyc` are also excluded by the watcher.
- **Failure handling:** failed refreshes are logged and retried after another
  quiet interval. Stop a repeatedly failing watcher while fixing the underlying
  problem; watching does not automatically override a required full rebuild.
- **Graceful stop:** active indexing finishes before shutdown. The stop command
  can report that a stop was requested while the operation is still finishing;
  check `ccx status` before reopening or clearing anything.
- **Persistence:** the watcher survives exiting OpenCode but does not automatically
  restart after a host reboot. Stop it explicitly when you are done.

The exclusions above describe watcher triggers, not a comprehensive secret scanner
or a replacement for each backend's indexing rules. Inspect the repository and
endpoint policy before allowing code to leave your machine.

## Exporting, importing, and clearing data

### `ccx export TARGET DESTINATION`

Writes a versioned ZIP with collection schema, vector rows, graph artifacts when
present, metadata, checksums, and an informational semantic snapshot. It requires
a running project container and an existing semantic collection; graph-only export
is not exposed.

```bash
ccx export . "$HOME/backups/my-project-context.zip"
```

The destination must not already exist, and parent directories are created as
needed. There is no overwrite flag. For a quieter backup window, stop the watcher
and avoid source edits or direct Graphify mutations while exporting.

The archive excludes the active `.env`, API keys, and the repository as a complete
source tree, but its vector rows contain code chunks and its graph can contain
source-derived text. Treat exports as confidential code data; checksums detect
corruption but are not signatures or proof of authenticity.

### `ccx import TARGET SOURCE [--yes]`

Restores a bundle into an already registered, running project container. The
target semantic collection and configured graph output directory must not exist,
and its watcher must be stopped.

| Option | Default | Behavior |
| --- | --- | --- |
| `--yes` | Off | Skip the import confirmation; does not authorize overwriting existing data |

```bash
# Prepare a new target without creating indexes or opening the assistant.
ccx open /path/to/target-repository --prepare-only --no-interactive
ccx import /path/to/target-repository "$HOME/backups/my-project-context.zip"
ccx search /path/to/target-repository "authentication"
```

Import validates the archive, Claude Context version, embedding model name, and
live embedding dimension before promotion. Use the same embedding model weights
and compatible source checkout; equal model names and vector dimensions alone do
not prove that two embedding services are equivalent.

The imported index is intended to be searchable before a refresh. Its first
subsequent semantic refresh is a full rebuild because path-dependent Merkle
snapshots are not restored blindly; ordinary `ccx open` also refreshes, so use
`--prepare-only` if you need to reopen before that rebuild.

### `ccx clear-index TARGET [--yes]`

Deletes only the project's semantic index and associated semantic state, leaving
graph artifacts and source files intact. The project container must be running
and the watcher must be stopped.

```bash
ccx watch . --stop
ccx clear-index .             # Confirmation prompt
ccx clear-index . --yes       # Skip that prompt
```

After clearing, semantic search has no usable index until you rebuild or import
one. An ordinary `ccx reindex .` also refreshes the graph if it is enabled.

### `ccx clear-graph TARGET [--yes]`

Deletes the configured graph output directory while leaving semantic vectors and
source files outside that directory intact. The project container must be running,
the watcher must be stopped, and the directory must carry ccx's ownership marker.

```bash
ccx watch . --stop
ccx clear-graph .             # Confirmation prompt
ccx clear-graph . --yes       # Skip that prompt
ccx build-graph .             # Rebuild, if Graphify is enabled
```

Do not put hand-maintained files in a ccx-owned graph directory: clearing it removes
the whole directory. ccx refuses unmanaged directories and symlink output paths;
never bypass the protection by manually adding a marker to a source directory.

## Configuration reference

Settings come from the active application home's `.env`, not from the shell's
current repository. For recognized keys, process environment variables override
the file, and file values override shipped defaults.

Boolean values must be `true` or `false` (case-insensitive); timeouts/debounce
must be positive finite numbers, and ports must be integers in `1..65535`.
The `.env` parser does not expand `${OTHER_VARIABLE}` references, and runtime
environment values must not contain line breaks.

### Inference and embedding endpoints

| Variable | Shipped default | Purpose |
| --- | --- | --- |
| `INFERENCE_API_HOST` | `host.docker.internal` | Host for OpenCode and optional semantic graph extraction |
| `INFERENCE_API_PORT` | `8080` | Port used when no inference base URL override is set |
| `INFERENCE_API_BASE_URL` | Empty | Complete HTTP(S) base URL; overrides inference host/port URL construction |
| `INFERENCE_API_KEY` | `local-inference` | Inference credential or placeholder accepted by your local server |
| `INFERENCE_MODEL` | `local-coder` | Exact inference model identifier |
| `EMBEDDING_API_HOST` | `host.docker.internal` | Host for semantic code embeddings |
| `EMBEDDING_API_PORT` | `8081` | Port used when no embedding base URL override is set |
| `EMBEDDING_API_BASE_URL` | Empty | Complete HTTP(S) embedding base URL override |
| `EMBEDDING_API_KEY` | `local-embedding` | Embedding credential or accepted local placeholder |
| `EMBEDDING_MODEL` | `local-embedding` | Exact embedding model identifier |

Without an override, ccx constructs `http://HOST:PORT/v1`. An override is used as
the base URL with trailing slashes removed; include the required API prefix such
as `/v1` yourself, and do not put credentials in the URL.

Model URLs are consumed inside containers. On Linux, a model server bound only to
host `127.0.0.1` may not be reachable through the host-gateway mapping; configure
an appropriate reachable interface and firewall rather than assuming container
`localhost` refers to your host.

### Graph and timing behavior

| Variable | Shipped default | Purpose |
| --- | --- | --- |
| `GRAPHIFY_ENABLED` | `true` | Graph default for `open` when neither graph flag is supplied |
| `GRAPHIFY_OUT_DIR` | `graphify-out` | Repository-relative generated output directory |
| `GRAPHIFY_SEMANTIC_EXTRACTION` | `false` | Enable inference-backed graph extraction instead of code-only extraction |
| `GRAPHIFY_COMMIT_OUTPUT` | `false` | Control whether ccx adds ignore entries for generated graph/skill/plugin files |
| `WATCH_DEBOUNCE_SECONDS` | `5` | Default watcher quiet period |
| `INDEX_TIMEOUT_SECONDS` | `3600` | Semantic MCP/indexing and in-container graph-operation time budget |
| `COMMAND_TIMEOUT_SECONDS` | `3600` | Host-side noninteractive Docker-exec time budget |

`GRAPHIFY_OUT_DIR` must stay inside the repository and cannot be the repository
root, a traversal path, `.git`, `.opencode`, or a symlink path. Existing nonempty
unmanaged directories are refused; use a fresh dedicated directory.

`GRAPHIFY_COMMIT_OUTPUT=true` does not run Git or commit files. It skips adding
the three ignore patterns; it does not remove ignore entries from an earlier
opening, so review `.gitignore` yourself if you change the setting.

The timeout variables do not override every operation. Image builds have a
30-minute host timeout, Compose calls a 10-minute host timeout with a 180-second
health wait, and interactive OpenCode sessions do not use the noninteractive
Docker-exec timeout.

### Shared services

| Variable | Shipped default | Purpose |
| --- | --- | --- |
| `MILVUS_PORT` | `19530` | Loopback host port for Milvus; project containers still use `milvus:19530` internally |
| `MINIO_CONSOLE_PORT` | `9001` | Loopback host port for the MinIO console |
| `ATTU_PORT` | `8000` | Loopback host port for Attu when enabled |
| `MINIO_ROOT_USER` | `ccx` | MinIO administrator user |
| `MINIO_ROOT_PASSWORD` | Generated by `ccx init` | MinIO administrator password and platform storage credential |

The example template contains a password placeholder, which a fresh `ccx init`
replaces. Avoid changing storage credentials casually after data exists; treat
credential rotation and service-image upgrades as coordinated platform changes.

### Project Python environments and large dependency downloads

Version 0.1.2 forwards the settings below to the project container. The dedicated
environment and cache persist in its HOME volume rather than using the host
repository's `.venv` or ccx's own `/opt/venv`; see the
[uv environment and timeout guide](docs/releases/0.1.2.md) for setup and recovery.

| Variable | Shipped default | Purpose |
| --- | --- | --- |
| `UV_CACHE_DIR` | `/home/ccx/.cache/uv` | Persistent uv package cache |
| `UV_PROJECT_ENVIRONMENT` | `/home/ccx/.venvs/project` | Container-side Python environment |
| `UV_HTTP_TIMEOUT` | `300` | HTTP-read timeout in seconds |
| `UV_CONCURRENT_DOWNLOADS` | `2` | Limit competing downloads |
| `UV_LINK_MODE` | `copy` | Cross-filesystem-compatible package installation |
| `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` | `1800000` | Default 30-minute OpenCode shell-tool deadline |

`COMMAND_TIMEOUT_SECONDS` does not change OpenCode's shell-tool deadline. An
explicit timeout supplied by the assistant can override the default; inspect
the tool call if setup is still interrupted around two minutes.

After a successful explicit `uv sync`, ask the assistant to use `uv run --no-sync`
for repeated runs while dependencies remain unchanged. Never use that flag as
a substitute for finishing an incomplete install, and do not routinely clean
the cache or replace CUDA requirements merely to make a failing install shorter.

### Pinned package and image versions

| Variable | Shipped default |
| --- | --- |
| `OPENCODE_IMAGE` | `ghcr.io/anomalyco/opencode:1.2.27` |
| `CLAUDE_CONTEXT_VERSION` | `0.1.15` |
| `GRAPHIFY_VERSION` | `0.9.83` |
| `MILVUS_IMAGE` | `milvusdb/milvus:v2.5.6` |
| `ETCD_IMAGE` | `quay.io/coreos/etcd:v3.5.18` |
| `MINIO_IMAGE` | `minio/minio:RELEASE.2024-12-18T13-15-44Z` |
| `ATTU_IMAGE` | `zilliz/attu:v2.5.0` |

These are maintenance controls, not a promise that arbitrary versions work.
The Dockerfile explicitly requires the pinned Claude Context and Graphify
versions; changing those values alone fails the build. Update the adapter,
dependency locks, image guards, and tests together.

### When changes take effect

New CLI processes load current host configuration, but an existing container keeps
the environment from its creation and a watcher keeps its startup settings.
Changing `.env` alone does not update either running process.

| Changed setting | Recommended action |
| --- | --- |
| Inference endpoint, API key, or model | Stop watcher, exit OpenCode, reopen project |
| Embedding endpoint or model identity | Stop watcher, prepare/reopen container, explicitly full-reindex |
| Graph enablement, output directory, or extraction mode | Stop watcher and reopen; pass the intended graph flag |
| Watcher interval | Stop/start watcher, or pass `--interval` at startup |
| uv directories/download limits or OpenCode shell deadline | Exit OpenCode, stop watcher and reopen the container; finish initial project sync if using a new environment |
| Packaged image/runtime contents | Refresh templates as appropriate and use `open --rebuild` |
| Shared service ports/images/credentials | Plan a shared-platform restart and check every affected project |

If you need a one-command environment override to reach the container, apply it
to `open`, which regenerates the runtime configuration. Applying a new model
variable only to `search` or `reindex` does not replace the existing container
environment.

## Common workflows

### Normal development with automatic refresh

Open the repository with watching enabled, then use either OpenCode or separate
terminal commands against the same registered project. Stop the watcher when the
session ends if you no longer want background updates.

```bash
ccx open /path/to/repository --watch --interval 3

# In another terminal:
ccx status /path/to/repository
ccx search /path/to/repository "request validation"
ccx watch /path/to/repository --stop
```

### Headless indexing and queries

Use `--no-interactive` for shell-driven workflows that do not need the OpenCode
terminal UI. This still starts the project container and performs the normal
context refresh.

```bash
ccx open /path/to/repository --no-interactive
ccx search /path/to/repository "error handling"
ccx graph-query /path/to/repository "errors"
ccx reindex /path/to/repository
```

### Change embedding service or recover a failed semantic index

Stop the watcher and edit the active `.env` before recreating the container.
Preparation-only reopening avoids attempting an incremental refresh with the new
embedding identity before you can request the required full rebuild.

```bash
ccx watch /path/to/repository --stop
# Exit any active OpenCode session and edit the active home .env.
ccx open /path/to/repository --prepare-only --no-interactive
ccx reindex /path/to/repository --full
ccx status /path/to/repository
ccx watch /path/to/repository
```

If you want Graphify disabled, include `--no-graph` on the reopen command rather
than relying on an earlier opening's setting. Changing embedding model identity
is not an incremental migration of existing vectors.

### Restore over a previously indexed project

There is intentionally no overwrite-import option. Back up first, explicitly
clear both targets, then import into the now-empty project.

```bash
ccx watch /path/to/repository --stop
ccx export /path/to/repository /safe/location/before-restore.zip
ccx clear-index /path/to/repository
ccx clear-graph /path/to/repository
ccx import /path/to/repository /safe/location/desired-context.zip
ccx search /path/to/repository "authentication"
```

The export filename must be new. Keep the project container running throughout
this sequence, and remember that a subsequent refresh rebuilds imported semantic
snapshots.

### Stop work and resume later

Exit OpenCode and stop the watcher first. You can leave the project container
running, or deliberately stop it with Docker because this ccx version has no
`close` subcommand.

```bash
ccx watch /path/to/repository --stop
ccx platform down

# Optional: use the actual slug from ccx status.
# docker stop ccx-<slug>

# Later, recreate/reopen the project and start shared services:
ccx open /path/to/repository
```

Named volumes persist across these operations. Stopping the shared platform does
not erase indexes, but it interrupts semantic operations for other projects.

## State, generated files, and permissions

The following layout shows the default application home and the files you will
most often inspect. Replace the home path if using `CCX_HOME` or `--home`.

```text
~/.claude-context-cli/
  .env                         Active configuration and secrets
  .env.example                 Reference template
  compose.yaml                 Shared platform definition
  Dockerfile                   Project image definition
  src/ccx/                     Installed runtime copied into the build context
  projects/<slug>/
    project.json               Registered source path and graph preferences
    opencode.json              Generated provider, MCP, and permission configuration
    runtime.env                Generated container environment; contains secrets
    CONTEXT.md                 Generated assistant guidance
    last-refresh.json          Latest refresh results/errors, not an event history
    watch.log                  Appended watcher errors/output
    watch.json                 Watcher metadata while active
    operation.lock             Host-operation lock file
    watch.lock                 Watcher exclusivity lock file
```

Inside the repository, ccx manages the files below and, by default, adds relevant
patterns to `.gitignore`. Review those changes just as you would any generated
project files.

```text
<repository>/
  .opencode/skills/ccx-context/SKILL.md
  .opencode/plugins/ccx-context.js
  graphify-out/                Or your GRAPHIFY_OUT_DIR
    .ccx-generated.json        Ownership guard; do not forge it
    graph.json                Queryable graph
    GRAPH_REPORT.md            Generated graph report
    ...                       Other Graphify output/cache/visualization files
```

The repository is mounted at `/workspace/<slug>` in container `ccx-<slug>`, and the
named volume `ccx-<slug>-home` persists `/home/ccx`. It holds semantic snapshots and
runtime state such as `.context` and `.ccx`; platform volumes separately persist
Milvus, MinIO, and etcd data.

Do not share `.env`, `runtime.env`, full container inspection output, or unreviewed
logs publicly. The local shared platform is not a hardened multi-tenant service,
and anyone with Docker access can inspect container environments and volumes.

## Troubleshooting

Start with the relevant status commands, then inspect the most specific log.
The table distinguishes configuration, lifecycle, and data problems so you do not
reach for a destructive rebuild unnecessarily.

| Symptom | What to check or do |
| --- | --- |
| `ccx` not found | Check your `uv` executable installation path and refresh your shell |
| Project not registered | Run `ccx open PATH`; use the same application home and repository root |
| Project container is not running | Reopen with `--no-interactive`, or add `--prepare-only` when preserving an import target |
| Docker executable/daemon unavailable | Run `docker info` and `docker compose version`; start Docker and check user access |
| Platform services unhealthy | Run `ccx platform status` and inspect Compose logs |
| Endpoint refused/timed out | Check container-reachable URL, listening interface, port, firewall, API key, and model identifier |
| Embedding configuration changed / previous index failed | Stop watcher, recreate configuration if needed, then `ccx reindex TARGET --full` |
| Watcher is already running | `ccx watch TARGET --stop`, wait for shutdown, then restart with the desired interval |
| Stop requested but watcher still running | Let the active indexing call finish; inspect status and watcher logs before reopening |
| Graphify disabled | Reopen with `--graph`, unless you intentionally want semantic-only context |
| Unmanaged graph directory refused | Choose a new dedicated output directory or move old generated artifacts aside; do not forge a marker |
| Graph missing or stale | Run `ccx build-graph TARGET`; use `--full` when deliberately forcing extraction |
| Import target already exists | Export a backup, stop watcher, then explicitly clear the index and graph |
| Import model/dimension/version mismatch | Use a compatible environment or rebuild locally instead of forcing import |
| Missing/unknown environment keys | Compare the active `.env` with `.env.example`; `init --force` does not merge values |
| Settings seem unchanged after editing `.env` | Reopen the project and restart the watcher; container environments are not hot-reloaded |
| Image rebuild did not rebuild indexes | Use `ccx reindex TARGET --full`; `open --rebuild` is a different operation |

To inspect logs, substitute the real slug printed by `ccx open` or `ccx status`.
If you selected the home only through `--home`, set the shell variable below to
that same path before using these ordinary shell commands.

```bash
CCX_STATE="${CCX_HOME:-$HOME/.claude-context-cli}"
SLUG="replace-with-your-actual-project-slug"

tail -n 100 "$CCX_STATE/projects/$SLUG/watch.log"
cat "$CCX_STATE/projects/$SLUG/last-refresh.json"

docker compose --project-name ccx-platform \
  --env-file "$CCX_STATE/.env" \
  -f "$CCX_STATE/compose.yaml" \
  logs --tail 100 milvus minio etcd
```

Most modifying commands require a running project container and a healthy shared
platform. Graph status is local-only, and stopping an existing watcher does not
require the container to be running.

For scripting, inspect JSON content as well as the process exit status.
`status` can embed a semantic error, `env check` can report drift without failing,
and declining some confirmation prompts returns without making changes; `--yes`
only suppresses the prompt on commands that explicitly provide it.

## Development, testing, and release files

The host application and orchestration are Python, with a small pinned JavaScript
adapter for Claude Context internals. Keep integration-specific code at those
boundaries so upstream upgrades do not spread changes across the CLI.

```text
src/ccx/
  cli.py                    Command parsing and presentation
  service.py                Project and multi-backend workflows
  config.py, project.py     Configuration and project identity
  process.py, docker.py     Process and Docker adapters
  semantic.py               Claude Context host adapter
  graph/                    Graphify adapter and output ownership
  runtime/                  Container MCP, indexing, graph, and transfer entry points
  watch.py                  Native observer, queue, debounce, graceful stop
  transfer.py               Archive creation and safe validation/extraction
  assets/                   Docker/Compose templates and runtime dependency locks
tests/                      Unit, contract, native watcher, and optional integration tests
scripts/                    Installation, maintenance, and validation commands
docs/                       Architecture, operations, requirements, and verification
```

| Script | Purpose |
| --- | --- |
| `scripts/install.sh` | Install the current project as a Python 3.12 `uv` tool |
| `scripts/test.sh` | Sync dev dependencies; run lint, formatting, mypy, tests, coverage, and Bash syntax checks |
| `scripts/test-integrations.sh` | Test real Graphify and Node/Milvus Lite using a local embedding stub |
| `scripts/build.sh` | Build the wheel and source distribution in `dist/` |
| `scripts/lock.sh` | Regenerate host/runtime/npm dependency locks and synchronize templates |
| `scripts/sync-templates.sh` | Copy packaged Docker/Compose/environment templates to the source-tree root |
| `scripts/smoke.sh PATH` | Docker/model-endpoint workflow against disposable copies of a repository; requires explicit opt-in |
| `scripts/check-upstream.mjs` | Verify expected exports against the installed pinned npm adapter dependencies |

```bash
uv sync --locked --group dev
uv run ccx --help
./scripts/test.sh
./scripts/test-integrations.sh
./scripts/build.sh

# Requires Docker and reviewed model-endpoint configuration:
CCX_RUN_DOCKER_TESTS=1 ./scripts/smoke.sh /path/to/disposable/repository
```

The normal test suite does not require Docker or paid model services. The optional
integration script needs Node/npm and a compatible Milvus Lite binary; its live
import test verifies rollback because Lite lacks collection rename, while successful
promotion is covered by a fake and still needs standalone-Milvus acceptance testing.

To build the container image directly from the source tree, use the command below.
For normal operation, prefer `ccx open`, which supplies the environment, network,
bind mounts, persistent HOME, and generated configuration.

```bash
docker build \
  --build-arg CCX_UID="$(id -u)" \
  --build-arg CCX_GID="$(id -g)" \
  -t ccx-opencode:local .
```

The hidden command `_watch-run TARGET --interval SECONDS --token TOKEN` is an
internal launcher used by `ccx watch`, not a supported manual workflow. It also
accepts `--help`, but users should let ccx generate its token and manage its lock.

## Limitations and further documentation

This version does not provide `close`, `list`, `doctor`, `logs`, overwrite-import,
query-limit, or semantic-only-refresh subcommands/options. Use the documented
status commands and explicit Docker/shell inspection where needed instead of
assuming those features exist.

- **Docker runtime:** the official OpenCode image supplies the release version;
  the final runtime uses Debian and the matching official npm release for Python
  binary-dependency compatibility.
- **Vector format:** the implementation uses dense embeddings with hybrid/BM25
  disabled. Export/import is designed around that schema.
- **Backup consistency:** export is not a distributed transaction spanning every
  possible semantic and graph writer. Quiesce activity for important backups.
- **Deployment validation:** passing local tests is not evidence that your Docker
  deployment, real endpoints, credentials, or interactive tool approvals have
  passed acceptance testing.
- **Licensing:** no license was inferred for the new project. Select one before
  public redistribution; third-party packages retain their own licenses.

Continue with the documents below for implementation details and recorded
verification boundaries. They complement this command reference rather than
changing the CLI behavior.

- [Architecture and integration contracts](docs/architecture.md)
- [Operations and release runbook](docs/runbook.md)
- [Transfer-document requirements mapping](docs/requirements.md)
- [Verification results and remaining acceptance checks](docs/verification.md)
- [0.1.1 MCP runtime fix and upgrade steps](docs/releases/0.1.1.md)
- [0.1.2 persistent Python environments and download troubleshooting](docs/releases/0.1.2.md)
- [Original technology transfer document](docs/technology-transfer.md)

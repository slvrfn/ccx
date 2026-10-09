# Operations and support

## Configuration and first startup

Run `ccx init`, edit `.env`, and use `ccx env check` to identify missing/stale keys.
Environment variables override `.env`. Base-URL overrides allow HTTPS and IPv6;
otherwise URLs are composed as `http://HOST:PORT/v1`. Docker's
`host.docker.internal:host-gateway` mapping handles host endpoints on Linux.
Endpoint services must listen on an interface reachable from Docker; a service
bound exclusively to host `127.0.0.1` may not be reachable on Linux.

Inference settings only configure OpenCode and optional semantic graph extraction.
Embedding settings only configure Claude Context. Code-only graph extraction is
the default. The shipped `.env.example` values name placeholder models, not
working public services. Replace them with models your servers actually serve.

## Common failures

- **Docker executable or daemon unavailable:** install/start Docker, run
  `docker info`, and confirm the current user has access. Do not run ccx as root.
- **Services unhealthy:** run `ccx platform status`, then
  `docker compose --project-name ccx-platform -f ~/.claude-context-cli/compose.yaml
  --env-file ~/.claude-context-cli/.env logs --tail 200`.
- **Endpoint refused or timed out:** check the base URL from inside the project
  container and confirm server binding, firewall and model names. Never paste
  API keys or full `docker inspect` output into public bug reports.
- **Embedding identity changed:** restore the old endpoint/model or run
  `ccx reindex <project> --full`. This is intentionally not an incremental update.
- **Graph extraction failed:** semantic indexing still runs independently.
  Inspect `projects/<slug>/last-refresh.json`, fix parsing/configuration and rerun
  `ccx build-graph`. Code-only operation needs no LLM.
- **Watcher appears stalled:** check `watch.log`, `watch.json`, and `ccx status`.
  A long active index operation delays graceful shutdown. File locks are released
  automatically when processes exit; stale PID values are never used to kill.
- **Import refuses existing data:** use a new registered target or explicitly
  clear the old semantic index and graph after exporting a backup.
- **Interrupted import:** inspect Attu for `<collection>_import_<id>` and compare
  against the import manifest before manually dropping it. Never delete a
  collection merely because its name looks old.
- **Dependency version changed:** do not simply override package versions in
  `.env`. Update the adapter, locks, image guards, contracts, and acceptance tests.

## Lifecycle and data retention

`ccx platform down` stops shared services but retains volumes. Reopening a project
replaces only its container, retaining its HOME volume. Stop watchers before
reopening so they do not race container replacement. `--prepare-only` creates the
container without making inference/embedding calls.

`clear-index` clears only vectors and semantic snapshots. `clear-graph` deletes
only the configured repository-local graph directory. Both require confirmation
unless `--yes` is supplied. Repository code is never removed by a ccx command.
Do not set `GRAPHIFY_OUT_DIR` to a directory containing hand-maintained assets.

Graph output directories carry a `.ccx-generated.json` ownership marker. An
existing nonempty directory without that marker is never adopted, rebuilt or
deleted automatically. Move old generated artifacts aside or choose a new
output directory; do not add markers to directories containing source files.

All persisted ccx JSON writes are atomic replace operations. Graphify and
Claude Context manage their own artifacts and recovery behavior. Export bundles
should be backed up separately and retained according to your source-code policy.

## Release procedure

1. Update dependency pins in `pyproject.toml`, runtime input files and Docker stages.
2. Run `scripts/lock.sh`, synchronize top-level templates, and review lock diffs.
3. Run `scripts/test.sh`, optional real Graphify tests, and upstream contracts.
4. Build the wheel and source archive with `scripts/build.sh`.
5. On Linux and macOS Docker hosts, run the Docker smoke test with disposable code.
6. Test the TUI manually, including tool approvals and both inference endpoints.
7. Export/import a representative project; compare counts, search and graph results.
8. Scan images and packages. Pin image digests if required by your deployment policy.

Expected telemetry is local status JSON, watcher logs and Docker logs. There is
no ccx analytics endpoint. Dependency tools may have their own telemetry behavior;
review their configurations independently. Do not assume a code-only invocation
makes every third-party component network-isolated.

# Code Context CLI Verification Report

Release candidate: `0.1.1`. Verification performed on October 9, 2026 in a Linux
sandbox with Python 3.12.13 and Node 20.20.2. The Docker runtime specifies Node 22;
Docker was not installed in this sandbox.

## Completed checks

| Check | Result |
| --- | --- |
| Default pytest suite | 100 passed; 2 opt-in integration tests skipped in this invocation |
| Default-suite Python statement coverage | 77%; integration coverage not combined |
| Python MCP regression tests | 7 passed with both host MCP 1.30 and pinned runtime MCP 1.26; all 7 failed before the fix |
| Stdio MCP facade | All four tools invoked over the protocol; server startup and calls run with warnings treated as errors |
| Real Graphify integration | Passed: extraction, custom output, report generation, incremental update, query |
| Real semantic integration | Passed through the Python stdio MCP facade and Node MCP: local Milvus Lite, initial index, status, search, modify/add/delete refresh, export, failed-import rollback, clear |
| Native watcher | Passed: debounce and preservation of events arriving during an active refresh |
| Import success path | Passed with a mocked Milvus boundary: row checks, promotion call, path remapping, ownership marker |
| Archive safety | Passed: checksum corruption, path traversal, symlink, unknown-version and manifest checks |
| Graph cleanup safety | Passed: unmanaged directories are refused |
| Ruff lint and formatting | Passed |
| Strict mypy | Passed across 27 source files |
| Bash syntax | Passed for all supplied scripts |
| JavaScript syntax and pinned upstream export contracts | Passed |
| Python wheel and source distribution build | Passed |
| Clean-environment wheel installation | Passed; `ccx init` and `ccx env check` succeeded |
| Packaged assets | Verified Docker, Compose, hidden environment template, npm lock and runtime requirements are in the wheel |
| npm dependency audit | 0 reported vulnerabilities in the locked adapter tree at verification time |

The live semantic test uses a deterministic local HTTP embedding stub and a real
Milvus Lite process. This validates API/data-flow integration, not retrieval
quality, model behavior, credentials, or the user's endpoint deployment.

## Not verified here

- **Docker image build and Compose startup:** the daemon/CLI was unavailable.
  Service readiness, image tags on the target architecture, volume ownership and
  container-to-host routing require the supplied Docker smoke run.
- **Successful import promotion against standalone Milvus:** Milvus Lite does not
  implement `RenameCollection`. The live test asserts cleanup after that RPC
  fails, rather than pretending a mocked rename is a live round trip.
- **OpenCode TUI and inference:** no real model endpoints or user credentials were
  supplied. Provider loading, interactive approvals and final model responses
  require an operator acceptance run.
- **Platform matrix:** tests ran on Linux/Python 3.12. CI definitions for Python
  3.13 and other jobs are supplied but were not executed by GitHub Actions here.
- **Security certification:** the npm audit is not a full security review. Python
  dependencies, container layers, base-image digests and unused provider paths
  need the operator's normal vulnerability and supply-chain checks.

## Reproduce

```bash
./scripts/test.sh
./scripts/test-integrations.sh
./scripts/build.sh

# After reviewing ~/.claude-context-cli/.env and starting Docker:
CCX_RUN_DOCKER_TESTS=1 ./scripts/smoke.sh /path/to/disposable/repository
```

The normal test command deliberately omits Docker and live model calls.
`test-integrations.sh` installs the optional integration group and locked npm
packages, then uses a local embedding stub. The smoke script can transmit the
test repository to the embedding endpoint configured by the operator.

## Release notes

The implementation separates host orchestration, infrastructure adapters,
semantic context, graph context and container entry points. Dependencies are
locked, graph deletion is ownership-guarded, and index success is verified against
stored vectors rather than trusting an upstream progress message alone.

The official OpenCode image provides the version for the Debian-based final
runtime. This explicit architecture adjustment, dense-only vector export, the
first-refresh rebuild after import, and local single-user trust assumptions are
documented in `architecture.md` and `requirements.md`.

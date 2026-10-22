---
name: ccx-testing
description: ccx testing patterns, verification commands, and integration requirements
---
# ccx-testing skill

Guidance for testing `ccx` (`code-context-cli`).

## Verification commands

- Full check (lint + format + mypy strict + pytest + coverage + bash syntax): `./scripts/test.sh`
- Build wheel + sdist: `./scripts/build.sh`
- Upstream npm adapter contract check: `scripts/check-upstream.mjs`
- Integration tests (Graphify + Node + Milvus Lite, local embedding stub): `./scripts/test-integrations.sh` (requires `uv sync --locked --group integration`)
- Docker/model-endpoint smoke test (disposable repo, opt-in): `CCX_RUN_DOCKER_TESTS=1 ./scripts/smoke.sh /path/to/disposable/repository`

## Python environment

- Dependencies belong to `UV_PROJECT_ENVIRONMENT`, not `/opt/venv` and not the host repository's `.venv`.
- Do **not** use `uv pip --system` or install packages into `/opt/venv` or `tests/`-adjacent `.venv` directories.
- Initial setup: `uv sync --locked --group dev` (and `--group integration` only when integration tests are explicitly needed).
- Repeated commands while dependencies unchanged: `uv run --no-sync <cmd>`.
- Never clean the uv cache as a routine response to an interrupted sync.
- Do not repeat a failing large sync without inspecting whether the HTTP read timeout or shell-tool deadline ended it; set an explicit suitable bash timeout for initial setup.

## Test conventions (`tests/`)

- `conftest.py`: `FakeRunner` (captures argv + env), `settings` fixture, `project` fixture, `runner` fixture.
- Unit tests mock `Application` adapters (`semantic.build`, `graph.build`, `docker.inspect_running`) to avoid Docker/endpoints.
- `test_service_cli.py` — CLI command registration/help, refresh orchestration, failure isolation (semantic failure doesn't skip graph), full-reindex approval.
- `test_graphify_integration.py` — real Graphify extract/update/query (`CCX_TEST_GRAPHIFY=1`).
- `test_semantic_integration.py`, `test_mcp_dispatch.py`, `test_transfer_runtime.py`, `test_runtime.py`, `test_watch_transfer.py`, `test_config_project.py`, `test_generated_docker.py`, `test_uv_environment.py` — various unit/integration coverage.
- Integration marker: `pytest.mark.integration` (requires Graphify or Docker, explicit opt-in).
- Run default suite (no Docker/model services): `uv run pytest`.

## Lint / type / format

- Ruff: `line-length = 100`, `target-version = "py312"`, select `["E", "F", "I", "UP", "B", "ANN"]`, ignore `["ANN401", "E501"]`.
- MyPy: `strict = true`, `python_version = "3.12"`, excludes `tests`; `pymilvus.*` and `graphify.*` ignore missing imports.
- Coverage: default pytest suite reports statement coverage (integration coverage not combined).

## Bash syntax

- `scripts/*.sh` and `scripts/check-upstream.mjs` are syntax-checked as part of `./scripts/test.sh`.

## Integration test requirements

- Graphify integration: install `graphifyy[mcp]==0.9.83` and set `CCX_TEST_GRAPHIFY=1`.
- Semantic integration: local Milvus Lite + embedding stub (Node/npm required).
- Integration group: `uv sync --locked --group integration`.

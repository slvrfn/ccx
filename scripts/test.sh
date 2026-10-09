#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
uv sync --locked --group dev
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/ccx
uv run pytest --cov=ccx --cov-report=term-missing "$@"
for script in scripts/*.sh; do bash -n "$script"; done


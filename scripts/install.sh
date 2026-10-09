#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
command -v uv >/dev/null || { printf '%s\n' 'Install uv first: https://docs.astral.sh/uv/'; exit 1; }
uv tool install --python 3.12 "$ROOT"
printf '%s\n' 'Installed. Run: ccx init'


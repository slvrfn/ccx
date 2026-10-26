#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
uv lock
uv pip compile --python-version 3.12 --generate-hashes \
  src/ccx/assets/requirements-container.in \
  -o src/ccx/assets/requirements-container.txt
(cd src/ccx/assets && npm install --package-lock-only --ignore-scripts)
./scripts/sync-templates.sh


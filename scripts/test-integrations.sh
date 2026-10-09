#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
uv sync --locked --group dev --group integration --python 3.12
NODE_PROJECT="$(mktemp -d)"
trap 'rm -rf -- "$NODE_PROJECT"' EXIT
cp src/ccx/assets/package{,-lock}.json "$NODE_PROJECT/"
(cd "$NODE_PROJECT" && npm ci --ignore-scripts)
export CCX_TEST_GRAPHIFY=1 CCX_TEST_SEMANTIC=1
export CCX_UPSTREAM_NODE_MODULES="$NODE_PROJECT/node_modules"
uv run --no-sync pytest tests/test_graphify_integration.py tests/test_semantic_integration.py -v
echo 'Milvus Lite lacks RenameCollection: import rollback is tested, full import requires Docker smoke.'

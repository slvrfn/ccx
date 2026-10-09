#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
for file in Dockerfile compose.yaml .env.example .dockerignore; do
  cp -- "src/ccx/assets/$file" "$file"
done


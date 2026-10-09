#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
uv build
printf '%s\n' 'Python wheel and source distribution are in dist/.'


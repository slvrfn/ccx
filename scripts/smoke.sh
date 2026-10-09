#!/usr/bin/env bash
set -euo pipefail
[[ "${CCX_RUN_DOCKER_TESTS:-0}" == 1 ]] || {
  echo 'Opt in with CCX_RUN_DOCKER_TESTS=1. This may send code to configured endpoints.'; exit 2;
}
[[ $# == 1 && -d "$1" ]] || { echo "Usage: $0 /path/to/disposable/repository"; exit 2; }
command -v docker >/dev/null
docker info >/dev/null
WORK="$(mktemp -d)"
# Retain the fixture on failure for diagnostics. Never delete the caller's source.
cp -R -- "$1" "$WORK/source"
cp -R -- "$1" "$WORK/restore"
echo "Smoke-test fixtures: $WORK"
ccx open "$WORK/source" --no-interactive --rebuild
ccx status "$WORK/source"
ccx search "$WORK/source" "main entry point"
ccx graph-status "$WORK/source"
printf '\n# ccx smoke edit\n' >> "$WORK/source/ccx_smoke.py"
ccx reindex "$WORK/source"
ccx export "$WORK/source" "$WORK/context.zip"
ccx open "$WORK/restore" --prepare-only --no-interactive
ccx import "$WORK/restore" "$WORK/context.zip" --yes
ccx search "$WORK/restore" "main entry point"
ccx reindex "$WORK/restore"
ccx watch "$WORK/source" --interval 1
printf '\ndef ccx_smoke():\n    return 42\n' >> "$WORK/source/ccx_smoke.py"
sleep 5
ccx watch "$WORK/source" --stop
ccx status "$WORK/source"
echo "Smoke workflow completed. Inspect results, then remove fixtures/containers deliberately: $WORK"


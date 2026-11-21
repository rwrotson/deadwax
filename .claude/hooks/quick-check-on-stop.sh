#!/usr/bin/env bash
# Stop: run `poe quick` (lint, import contracts, mypy) when Python files changed; block the stop on failure.
set -uo pipefail

[ "$(jq -r '.stop_hook_active // false')" = "true" ] && exit 0

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0
git status --porcelain --untracked-files=all | grep -qE '\.pyi?"?$' || exit 0

if ! out="$(uv run --quiet poe quick 2>&1)"; then
  printf 'poe quick failed; fix it before finishing:\n%s\n' "$out" | tail -n 60 >&2
  exit 2
fi
exit 0

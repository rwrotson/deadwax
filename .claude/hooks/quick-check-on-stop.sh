#!/usr/bin/env bash
# Stop: run lint, import contracts, and mypy when Python files changed; block the stop on failure.
set -uo pipefail

[ "$(jq -r '.stop_hook_active // false')" = "true" ] && exit 0

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0
git status --porcelain --untracked-files=all | grep -qE '\.pyi?"?$' || exit 0

failed=0
out=""
for task in lint lint-imports typecheck; do
  if ! result="$(uv run --quiet poe "$task" 2>&1)"; then
    failed=1
    out+=$'\n'"== poe $task failed =="$'\n'"$result"
  fi
done

if [ "$failed" -ne 0 ]; then
  printf 'Quick checks failed; fix them before finishing:%s\n' "$out" | tail -n 60 >&2
  exit 2
fi
exit 0

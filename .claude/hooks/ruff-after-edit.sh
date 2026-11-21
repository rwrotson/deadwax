#!/usr/bin/env bash
# PostToolUse: format and autofix an edited Python file; report remaining errors to Claude.
set -uo pipefail

project="${CLAUDE_PROJECT_DIR:-$(pwd)}"
file="$(jq -r '.tool_input.file_path // empty')"

case "$file" in
  *.py | *.pyi) ;;
  *) exit 0 ;;
esac
case "$file" in
  "$project"/*) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0

cd "$project" || exit 0
uv run --quiet ruff format --quiet "$file" >/dev/null 2>&1
if ! out="$(uv run --quiet ruff check --fix --quiet "$file" 2>&1)"; then
  printf 'ruff check reports errors in %s:\n%s\n' "$file" "$out" >&2
  exit 2
fi
exit 0

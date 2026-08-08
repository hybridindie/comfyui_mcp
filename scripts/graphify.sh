#!/usr/bin/env bash
# graphify wrapper — sources the repo .env (LLM backend/model) and picks the
# pinned interpreter before invoking the graphify CLI. See
# .opencode/rules/graphify.md for why .env must be observed.
#
# Usage:
#   scripts/graphify.sh label . --update
#   scripts/graphify.sh query "How does the rate limiter work?"
#   scripts/graphify.sh update .
#   scripts/graphify.sh path "RateLimiter" "AuditLogger"
#   scripts/graphify.sh explain "WorkflowInspector"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Source .env if present (graphify reads os.environ; it does not load .env
# itself). `set -a` exports every assignment.
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

# Pick the graphify interpreter. Prefer the pinned path written by the skill /
# CLI (graphify-out/.graphify_python), then pyenv 3.13.14, then whatever
# `graphify` resolves to on PATH.
GFY_PY=""
if [ -f "$ROOT/graphify-out/.graphify_python" ]; then
  _CANDIDATE="$(tr -d '[:space:]' < "$ROOT/graphify-out/.graphify_python")"
  case "$_CANDIDATE" in
    *[!a-zA-Z0-9/_.@:\\-]*) ;;  # skip invalid chars
    *) if [ -x "$_CANDIDATE" ] && "$_CANDIDATE" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('graphify') else 1)" 2>/dev/null; then
         GFY_PY="$_CANDIDATE"
       fi ;;
  esac
fi
if [ -z "$GFY_PY" ]; then
  _PYENV="/home/johnd/.pyenv/versions/3.13.14/bin/python3"
  if [ -x "$_PYENV" ] && "$_PYENV" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('graphify') else 1)" 2>/dev/null; then
    GFY_PY="$_PYENV"
  fi
fi
if [ -z "$GFY_PY" ]; then
  if command -v graphify >/dev/null 2>&1; then
    exec graphify "$@"
  fi
  echo "could not locate a Python with graphify installed" >&2
  exit 1
fi

exec "$GFY_PY" -m graphify "$@"

#!/usr/bin/env bash
# Claude Code PostToolUse hook: run the architecture guardrail tests after an
# Edit/Write that touches app code, requirements, or the API snapshot.
# Exit 2 feeds the failure back to the model so it fixes the violation
# immediately; everything else stays silent.
set -u

input=$(cat)
file_path=$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
print(data.get("tool_input", {}).get("file_path", ""))
' 2>/dev/null)

case "$file_path" in
  */app/*|*/requirements.txt|*/tests/openapi_snapshot.json) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/..}" || exit 0

PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

if ! out=$("$PY" -m pytest -q tests/test_architecture.py 2>&1); then
  printf 'Architecture guardrail tests failed:\n%s\n' "$out" >&2
  exit 2
fi
exit 0

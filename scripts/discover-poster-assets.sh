#!/usr/bin/env bash
# Daily source discovery only: it never downloads or approves external media.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$REPO/.venv/bin/python"
if ! "$PYTHON_BIN" -c 'import sys' >/dev/null 2>&1; then
  PYTHON_BIN=/usr/bin/python3
fi
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 RUN_DIR YYYY-MM-DD [--dry-run]" >&2
  exit 64
fi

"$PYTHON_BIN" -m jaguartv_prematch.cli assets-discover --run-dir "$1" --date "$2" "${@:3}"

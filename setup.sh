#!/usr/bin/env bash
# Run from any directory; no shell sourcing of installation configuration.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.11+ is required. Install python3, then rerun bash setup.sh.' >&2
  exit 1
fi
exec python3 "$ROOT/scripts/install.py" "$@"

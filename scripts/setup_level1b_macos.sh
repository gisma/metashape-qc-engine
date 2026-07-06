#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'ERROR: setup_level1b_macos.sh must run on macOS.\n' >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
printf 'macOS Level-1B setup: using the shared Level-1B dependency contract.\n'
exec bash "$REPO_ROOT/scripts/setup_level1b.sh"

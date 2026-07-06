#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'ERROR: setup_level1a_macos.sh must run on macOS.\n' >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
printf 'macOS Level-1A setup: using the shared Level-1A dependency contract.\n'
exec bash "$REPO_ROOT/scripts/setup_level1a.sh"

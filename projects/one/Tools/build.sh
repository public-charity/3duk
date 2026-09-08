#!/usr/bin/env bash
# Git Bash wrapper for Tools/build.ps1 (UE_PLAN.md 5.1). Usage: ./build.sh [-Config Development|DebugGame] [-ProjectFiles]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$here/build.ps1")" "$@"

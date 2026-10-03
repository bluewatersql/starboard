#!/usr/bin/env bash
# Tier-1 entry point for the starboard-warehouse skill (Phase-2 D4).
#
# Keeps the invocation stable so the SKILL.md `allowed-tools` prefix
# (`Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)`) matches the exact command the
# body tells Claude to run — the script therefore runs with no permission
# prompt. The pure warehouse fingerprint + health analyzers run out-of-context
# in Python (no databricks-sdk); only the compact JSON envelope returns.
set -euo pipefail
exec python -m starboard_x.warehouse "$@"

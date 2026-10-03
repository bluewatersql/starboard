#!/usr/bin/env bash
# Tier-1 entry point for the starboard-diagnostic skill (Phase-1 B2).
#
# Keeps the invocation stable so the SKILL.md `allowed-tools` prefix
# (`Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)`) matches the exact command the
# body tells Claude to run — the script therefore runs with no permission
# prompt. The dep-light analyzers execute out-of-context in Python; only the
# compact JSON envelope returns to the model.
set -euo pipefail
exec python -m starboard_x.diagnostic "$@"

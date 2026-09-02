#!/usr/bin/env bash
# Tier-1 entry point for the workload-review skill (Phase-3 D1b).
#
# Keeps the invocation stable so the SKILL.md `allowed-tools` prefix
# (`Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)`) matches the exact command the
# body tells Claude to run — the script therefore runs with no permission
# prompt. Runs the deterministic Workload Review end-to-end against the resolved
# workspace (public system.* data, no LLM) and emits the stable JSON envelope
# (`{ok, domain, command, data|error, meta}`) to stdout; only that compact
# envelope returns to the model.
set -euo pipefail
exec starboard review --json "$@"

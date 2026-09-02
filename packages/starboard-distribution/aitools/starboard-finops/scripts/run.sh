#!/usr/bin/env bash
# Tier-1 entry point for the starboard-finops skill.
#
# FinOps cost data on the workspace-read-only path lives in the deterministic
# discovery `billing` pack (system.billing.usage — list-price DBU quantities, no
# account-admin credentials required). This wrapper keeps the invocation stable
# so the SKILL.md `allowed-tools` prefix
# (`Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)`) matches the command the body
# tells the host to run — it therefore runs with no permission prompt. The
# pipeline runs out-of-context in Python (no LLM); only the compact JSON
# envelope returns to the model.
set -euo pipefail
exec python -m starboard_x.discovery "$@"

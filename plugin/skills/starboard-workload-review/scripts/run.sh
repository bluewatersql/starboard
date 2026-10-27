#!/usr/bin/env bash
# Tier-1 entry point for the workload-review skill.
#
# The SKILL.md `allowed-tools` prefix (`Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)`)
# runs this with NO permission prompt — so it must NEVER install anything itself.
# If the `starboard` CLI is not present it prints the exact install command and exits 3; the
# SKILL then runs that `pip install` as a SEPARATE, non-allowlisted command, which
# Claude Code prompts you to approve before fetching code from the internal Git
# source (supply-chain safety). After you approve and it installs, re-run this.
set -euo pipefail

_spec='starboard @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard'
if ! command -v starboard >/dev/null 2>&1; then
    echo "[starboard] workload-review: required dependency is not installed." >&2
    echo "[starboard] Install it (Claude Code will ask you to approve this), then re-run:" >&2
    echo "    pip install \"${_spec}\"" >&2
    exit 3
fi
exec starboard review --json "$@"

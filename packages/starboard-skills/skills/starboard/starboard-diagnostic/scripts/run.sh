#!/usr/bin/env bash
# Tier-1 entry point for the starboard-diagnostic skill.
#
# The SKILL.md `allowed-tools` prefix (`Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)`)
# runs this with NO permission prompt — so it must NEVER install anything itself.
# If the starboard_x.diagnostic analyzer tier is not present it prints the exact install command and exits 3; the
# SKILL then runs that `pip install` as a SEPARATE, non-allowlisted command, which
# Claude Code prompts you to approve before fetching code from the internal Git
# source (supply-chain safety). After you approve and it installs, re-run this.
set -euo pipefail

_spec='starboard-kernel[diagnostics] @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard-core'
if ! python -c 'import starboard_x.diagnostic' 2>/dev/null; then
    echo "[starboard] starboard-diagnostic: required dependency is not installed." >&2
    echo "[starboard] Install it (Claude Code will ask you to approve this), then re-run:" >&2
    echo "    pip install \"${_spec}\"" >&2
    exit 3
fi
exec python -m starboard_x.diagnostic "$@"

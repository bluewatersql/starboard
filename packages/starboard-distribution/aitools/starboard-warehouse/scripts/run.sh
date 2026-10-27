#!/usr/bin/env bash
# Tier-1 entry point for the starboard-warehouse skill.
#
# The SKILL.md `allowed-tools` prefix (`Bash(python -m starboard_x.warehouse *)`)
# runs this with NO permission prompt — so it must NEVER install anything itself.
# If the starboard_x.warehouse analyzer tier is not present it prints the exact install command and exits 3; the
# SKILL then runs that `pip install` as a SEPARATE, non-allowlisted command, which
# Claude Code prompts you to approve before fetching code from the internal Git
# source (supply-chain safety). After you approve and it installs, re-run this.
set -euo pipefail

_spec='starboard-kernel[warehouse] @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard-core'
if ! python -c 'import starboard_x.warehouse' 2>/dev/null; then
    echo "[starboard] starboard-warehouse: required dependency is not installed." >&2
    echo "[starboard] Install it (Claude Code will ask you to approve this), then re-run:" >&2
    echo "    pip install \"${_spec}\"" >&2
    exit 3
fi
exec python -m starboard_x.warehouse "$@"

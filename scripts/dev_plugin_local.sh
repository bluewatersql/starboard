#!/usr/bin/env bash
# Register + test the Starboard Claude Code plugin locally under Isaac (Phase-3 G3).
#
# Plugins are NOT MCP servers: this registers the skills-only plugin at ./plugin
# so Isaac injects its skills into a session. No MCP server is started.
#
# Usage:
#   scripts/dev_plugin_local.sh add       # register + enable the local plugin
#   scripts/dev_plugin_local.sh on|off    # toggle injection (entry kept)
#   scripts/dev_plugin_local.sh list      # show dev entries + on/off state
#   scripts/dev_plugin_local.sh remove    # delete the dev entry
#   scripts/dev_plugin_local.sh check     # verify vendored skills are in sync
set -euo pipefail

ALIAS="starboard-dev"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="${REPO_ROOT}/plugin"

require_isaac() {
  command -v isaac >/dev/null 2>&1 || {
    echo "error: 'isaac' CLI not found on PATH." >&2
    exit 127
  }
}

cmd="${1:-add}"
case "$cmd" in
  add)
    require_isaac
    # Keep the vendored plugin skills in sync with the canonical source first.
    python3 "${REPO_ROOT}/scripts/vendor_plugin_skills.py" --check \
      || { echo "Vendored skills drifted — running the vendor step..."; \
           python3 "${REPO_ROOT}/scripts/vendor_plugin_skills.py"; }
    echo "Registering local plugin '${ALIAS}' -> ${PLUGIN_DIR}"
    isaac plugin dev add "${ALIAS}" "${PLUGIN_DIR}"
    isaac plugin dev on "${ALIAS}"
    echo
    echo "Registered + enabled. Now start Isaac and confirm the skills are injected:"
    echo "  isaac --claude"
    echo "Then in-session, ask something that triggers a Starboard skill, e.g."
    echo "  \"review this workspace's jobs and warehouses\"  (workload-review)"
    echo "  \"map this workspace\"                            (starboard-discovery)"
    echo "Skills shell out via: python -m starboard_x.<capability> (no MCP, no prompt)."
    echo "Clean up when done:  scripts/dev_plugin_local.sh remove"
    ;;
  on|off)
    require_isaac
    isaac plugin dev "$cmd" "${ALIAS}"
    ;;
  list)
    require_isaac
    isaac plugin dev list
    ;;
  remove)
    require_isaac
    isaac plugin dev remove "${ALIAS}"
    echo "Removed dev entry '${ALIAS}'."
    ;;
  check)
    python3 "${REPO_ROOT}/scripts/vendor_plugin_skills.py" --check
    ;;
  *)
    echo "usage: $0 {add|on|off|list|remove|check}" >&2
    exit 2
    ;;
esac

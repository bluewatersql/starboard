#!/usr/bin/env bash
# Republish the Starboard plugins to every local agent client.
#
# Steps:
#   1. Check the vendored bundles against the canonical skills tree
#      (plugin/skills, plugin-internal/skills when present, plugin/rules, the
#      aitools mirror and the OpenCode bundle); regenerate only what drifted.
#   2. Reload the Isaac dev-mode plugins (Claude Code serves them live from the
#      repo; the off/on toggle makes new sessions pick up the current tree).
#   3. Refresh the Codex snapshot. Isaac copies dev-mode plugins into
#      ~/.codex/isaac-plugin-sync only when it launches Codex, so this runs one
#      minimal non-interactive Codex turn (a few thousand tokens). Every model
#      launched through Isaac's Codex runtime reads that snapshot.
#   4. Print what each client is serving.
#
# Local only: nothing is pushed or published to a shared marketplace (use
# scripts/mirror-to-vibe.sh for that).
#
# Usage:
#   ./scripts/republish-plugins.sh             # all steps
#   ./scripts/republish-plugins.sh --no-codex  # skip the Codex snapshot refresh
#   make republish                             # same as the first form
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PATH="$REPO_ROOT/.venv/bin:$PATH"

REFRESH_CODEX=1
for arg in "$@"; do
  case "$arg" in
    --no-codex) REFRESH_CODEX=0 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# `isaac` is usually a shell alias for `dbexec repo run isaac`; aliases don't
# exist in scripts, so resolve it explicitly.
isaac() {
  local bin
  bin="$(type -P isaac || true)"   # a real binary on PATH (this function shadows the name)
  if [ -n "$bin" ]; then
    "$bin" "$@"
  elif command -v dbexec >/dev/null 2>&1; then
    dbexec repo run isaac "$@"
  else
    echo "isaac not found (need isaac or dbexec on PATH)" >&2
    return 127
  fi
}

# Kill a process and all its descendants (the Codex launch is a
# dbexec -> node -> codex chain).
kill_tree() {
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$child"; done
  kill "$1" 2>/dev/null || true
}

HAS_INTERNAL=0
[ -d plugin-internal ] && [ -d packages/starboard-internal ] && HAS_INTERNAL=1

echo "==> 1/4 Checking bundles (regenerating only what drifted)"
# Regenerate a bundle only when its --check fails, so an in-sync tree stays
# clean (regeneration rewrites timestamps even when content is unchanged).
sync_bundle() {  # <label> <check-cmd> <regen-cmd>
  if eval "$2" >/dev/null 2>&1; then
    echo "    $1: in sync"
  else
    eval "$3" >/dev/null
    eval "$2" >/dev/null
    echo "    $1: regenerated"
    CHANGED=1
  fi
}
CHANGED=0
python scripts/gen_rulesets.py >/dev/null   # deterministic; feeds the OpenCode bundle
sync_bundle "plugin skills" "python scripts/vendor_plugin_skills.py --check" "python scripts/vendor_plugin_skills.py"
if [ "$HAS_INTERNAL" = 1 ]; then
  sync_bundle "internal plugin skills" "python scripts/vendor_plugin_skills.py --internal --check" "python scripts/vendor_plugin_skills.py --internal"
fi
sync_bundle "aitools bundle" "python scripts/skills.py --check" "python scripts/skills.py"
sync_bundle "OpenCode bundle" "python scripts/port_to_opencode.py --check" "python scripts/port_to_opencode.py"
if [ "$CHANGED" = 1 ] || ! git diff --quiet -- plugin plugin-internal packages/starboard-distribution; then
  echo "    note: vendored files changed — commit them so other checkouts and CI match"
fi

echo "==> 2/4 Reloading Isaac dev-mode plugins"
ALIASES=(starboard)
[ "$HAS_INTERNAL" = 1 ] && ALIASES+=(starboard-internal)
DEV_LIST="$(isaac plugin dev list 2>&1 || true)"
for alias in "${ALIASES[@]}"; do
  if grep -q "• ${alias} " <<<"$DEV_LIST"; then
    isaac plugin dev off "$alias" >/dev/null 2>&1
    isaac plugin dev on "$alias" >/dev/null 2>&1
    echo "    reloaded $alias"
  else
    echo "    $alias is not registered — run: isaac plugin dev add $alias <repo>/$( [ "$alias" = starboard ] && echo plugin || echo plugin-internal )"
  fi
done

CODEX_MP="$HOME/.codex/isaac-plugin-sync/marketplaces/isaac-sync-dev-mode/.agents/plugins/marketplace.json"
if [ "$REFRESH_CODEX" = 1 ]; then
  echo "==> 3/4 Refreshing the Codex snapshot (one minimal Codex turn)"
  if [ -d "$HOME/.codex" ]; then
    before="$(grep -o '"path": *"[^"]*"' "$CODEX_MP" 2>/dev/null || true)"
    # stdin from /dev/null: `codex exec` otherwise waits on an inherited,
    # never-closing stdin (e.g. under make or an agent shell). Run in the
    # background with a 180s watchdog so a hung launch can't block the script.
    (cd "${TMPDIR:-/tmp}" && isaac codex --no-omni -- exec --skip-git-repo-check \
      "Reply with the single word: ok" </dev/null >/dev/null 2>&1) &
    codex_pid=$!
    for _ in $(seq 1 90); do kill -0 "$codex_pid" 2>/dev/null || break; sleep 2; done
    if kill -0 "$codex_pid" 2>/dev/null; then
      kill_tree "$codex_pid"
      echo "    warning: Codex launch timed out after 180s; snapshot may be stale" >&2
    elif ! wait "$codex_pid"; then
      echo "    warning: Codex launch failed; snapshot may be stale" >&2
    fi
    after="$(grep -o '"path": *"[^"]*"' "$CODEX_MP" 2>/dev/null || true)"
    if [ "$before" != "$after" ]; then echo "    snapshot updated"; else echo "    snapshot unchanged (already current, or the sync did not run)"; fi
  else
    echo "    ~/.codex not found — Codex is not set up; skipping"
  fi
else
  echo "==> 3/4 Skipping the Codex snapshot refresh (--no-codex)"
fi

echo "==> 4/4 What each client serves"
echo "    repo HEAD: $(git rev-parse --short HEAD)$(git diff --quiet || echo ' (+ uncommitted changes)')"
isaac plugin dev list 2>&1 | grep -A1 "•" | sed 's/^/    /' || true
if [ -f "$CODEX_MP" ]; then
  echo "    Codex snapshot ($(stat -f '%Sm' "$CODEX_MP" 2>/dev/null || stat -c '%y' "$CODEX_MP")):"
  grep -o '"path": *"[^"]*"' "$CODEX_MP" | sed 's/.*plugins\//      /; s/"$//'
fi
echo "    OpenCode / aitools bundles: packages/starboard-distribution/ (in sync)"
echo "Done. Start fresh agent sessions to pick up the new plugins."

#!/usr/bin/env bash
# Mirror main to the public bluewatersql/starboard repo via SSH.
#
# INTERNAL PATHS ARE STRIPPED before pushing — the public mirror never sees them.
#
# Excluded paths (never reach the public mirror):
#   packages/starboard-internal/   — gated internal port adapters
#   plugin-internal/               — internal enrichment overlay plugin
#   .superpowers/                  — dev-only scratch (SDD ledgers, audit/review
#                                    prose that names internal red-line tokens)
#
# .claude-plugin/marketplace.json is also filtered to remove any
# "starboard-internal" plugin entry before the push.
#
# Mechanism: a temporary git index file is populated from HEAD's tree; internal
# paths are removed via `git rm --cached`; marketplace.json is rewritten as a
# new blob in the object store; the filtered tree is materialised with
# `git write-tree`; an ORPHAN commit (no parent) is created with
# `git commit-tree` (no -p flag).  Everything happens in the git object store —
# the working tree, the real index, and the main branch history are never
# modified.  No branch switch occurs.
#
# Orphan-snapshot semantics: the public mirror carries NO internal history.
# Each run produces a parentless filtered snapshot that replaces the public tip.
# Internal files are never recoverable via `git log` on the public remote.
#
# Usage:
#   ./scripts/mirror-public.sh             # full mirror (SSH + push access required)
#   ./scripts/mirror-public.sh --dry-run   # build filtered tree + verify; NO push
#
# Prerequisites (full mirror):
#   - SSH key with access to git@github.com:bluewatersql/starboard.git
#   - Run from repo root on 'main' with a clean working tree
#   - python3 (stdlib only; for marketplace.json filtering)

set -euo pipefail

PUBLIC_REMOTE_URL="git@github.com:bluewatersql/starboard.git"
REMOTE_NAME="public"
BRANCH="main"

# Paths to EXCLUDE from the public mirror (relative to repo root).
# Extend this list if new internal subtrees are added; the script handles
# absent paths gracefully (no-op with a logged notice).
readonly INTERNAL_PATHS=(
    "packages/starboard-internal"
    "plugin-internal"
    ".superpowers"
)

# Plugin names to strip from .claude-plugin/marketplace.json
readonly INTERNAL_PLUGIN_NAMES=("starboard-internal")
readonly MARKETPLACE_JSON=".claude-plugin/marketplace.json"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

# ── helpers ───────────────────────────────────────────────────────────────────

die()  { echo "Error: $*" >&2; exit 1; }
warn() { echo "Warning: $*" >&2; }

# Temp index used to build the filtered tree without touching the real index,
# the working tree, or any branch.
TMP_INDEX=$(mktemp)
cleanup_tmp() { rm -f "$TMP_INDEX"; }
trap cleanup_tmp EXIT

# ── SSH key (production only) ─────────────────────────────────────────────────

if [[ "$DRY_RUN" -eq 0 ]]; then
    MIRROR_SSH_KEY="${MIRROR_SSH_KEY:-$HOME/.ssh/id_ed25519_personal}"
    if [[ -f "$MIRROR_SSH_KEY" ]]; then
        pub="${MIRROR_SSH_KEY}.pub"
        key_fp="$(ssh-keygen -lf "${pub:-$MIRROR_SSH_KEY}" 2>/dev/null | awk '{print $2}')"
        if [[ -z "$key_fp" ]] || ! ssh-add -l 2>/dev/null | grep -qF "$key_fp"; then
            echo "Loading SSH key into agent: $MIRROR_SSH_KEY"
            if [[ "$(uname)" == "Darwin" ]]; then
                ssh-add --apple-use-keychain "$MIRROR_SSH_KEY"
            else
                ssh-add "$MIRROR_SSH_KEY"
            fi
        fi
    else
        warn "SSH key '$MIRROR_SSH_KEY' not found; relying on existing agent/config."
    fi
fi

# ── remote setup (production only) ───────────────────────────────────────────

if [[ "$DRY_RUN" -eq 0 ]]; then
    if ! git remote get-url "$REMOTE_NAME" &>/dev/null; then
        echo "Adding remote '$REMOTE_NAME' -> $PUBLIC_REMOTE_URL"
        git remote add "$REMOTE_NAME" "$PUBLIC_REMOTE_URL"
    fi
fi

# ── pre-flight checks ─────────────────────────────────────────────────────────

current_branch=$(git rev-parse --abbrev-ref HEAD)
if [[ "$current_branch" != "$BRANCH" ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
        warn "Not on '$BRANCH' (on '$current_branch') — dry-run proceeds from current HEAD."
    else
        die "Must be on '$BRANCH' to mirror (currently on '$current_branch')"
    fi
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    die "Working tree has uncommitted changes — commit or stash first"
fi

HEAD_SHA=$(git rev-parse HEAD)
echo "Source: ${current_branch} @ ${HEAD_SHA}"

# ── build filtered tree via temp index ───────────────────────────────────────
#
# All plumbing commands use GIT_INDEX_FILE=$TMP_INDEX so the real index,
# working tree, and branch history are never touched.

echo ""
echo "Building filtered mirror tree..."

# Populate the temp index from HEAD's committed tree
GIT_INDEX_FILE="$TMP_INDEX" git read-tree "$HEAD_SHA"

REMOVED_PATHS=()
for path in "${INTERNAL_PATHS[@]}"; do
    # Capture-then-test, NOT `git ls-files | grep -q`: under pipefail, grep -q
    # short-circuits on a multi-file subtree, git dies with SIGPIPE (141), and
    # the pipeline reads false — which would SKIP removing a tracked internal
    # path. (The verification gate below is fail-closed and would abort, but we
    # must not rely on it as the only backstop.)
    tracked_files="$(GIT_INDEX_FILE="$TMP_INDEX" git ls-files -- "$path")"
    if [[ -n "$tracked_files" ]]; then
        echo "  Removing from mirror: ${path}/"
        GIT_INDEX_FILE="$TMP_INDEX" git rm -r --cached --quiet -- "$path"
        REMOVED_PATHS+=("$path")
    else
        echo "  Not tracked (no-op): ${path}"
    fi
done

# Filter marketplace.json: rewrite the blob in the object store (no disk write).
MARKETPLACE_CHANGED=0
if [[ -n "$(GIT_INDEX_FILE="$TMP_INDEX" git ls-files -- "$MARKETPLACE_JSON")" ]]; then
    current_mp_info=$(GIT_INDEX_FILE="$TMP_INDEX" git ls-files -s -- "$MARKETPLACE_JSON")
    current_mp_mode=$(echo "$current_mp_info" | awk '{print $1}')
    current_mp_sha=$(echo  "$current_mp_info" | awk '{print $2}')

    filtered_mp=$(git cat-file blob "$current_mp_sha" | python3 -c "
import json, sys
data = json.load(sys.stdin)
internal_names = {'starboard-internal'}
before = data.get('plugins', [])
after  = [p for p in before if p.get('name') not in internal_names]
data['plugins'] = after
json.dump(data, sys.stdout, indent=2)
sys.stdout.write('\n')
removed = len(before) - len(after)
if removed:
    print(f'  Filtered {removed} internal plugin entry(s) from marketplace.json', file=sys.stderr)
else:
    print('  marketplace.json: no internal entries found (no change)', file=sys.stderr)
")
    new_mp_sha=$(printf '%s' "$filtered_mp" | git hash-object -w --stdin)

    if [[ "$new_mp_sha" != "$current_mp_sha" ]]; then
        GIT_INDEX_FILE="$TMP_INDEX" git update-index \
            --cacheinfo "${current_mp_mode},${new_mp_sha},${MARKETPLACE_JSON}"
        MARKETPLACE_CHANGED=1
    fi
fi

# Rewrite the canonical internal source URL -> public mirror URL.
# Internal (databricks-field-eng/starboard) is the source of truth in-repo so
# internal/EMU testers install the real HEAD; the public mirror must reference
# the public repo (bluewatersql/starboard) so external users can install.
# Same object-store blob-rewrite technique as marketplace.json above — the
# working tree, the real index, and branch history are never touched.
readonly INTERNAL_URL="github.com/bluewatersql/starboard"
readonly PUBLIC_URL="github.com/bluewatersql/starboard"
URL_REWRITTEN=0
while IFS= read -r url_file; do
    [[ -z "$url_file" ]] && continue
    url_info=$(GIT_INDEX_FILE="$TMP_INDEX" git ls-files -s -- "$url_file")
    url_mode=$(echo "$url_info" | awk '{print $1}')
    url_sha=$(echo  "$url_info" | awk '{print $2}')
    new_url_sha=$(git cat-file blob "$url_sha" \
        | perl -pe "s{\Q${INTERNAL_URL}\E}{${PUBLIC_URL}}g" \
        | git hash-object -w --stdin)
    if [[ "$new_url_sha" != "$url_sha" ]]; then
        GIT_INDEX_FILE="$TMP_INDEX" git update-index \
            --cacheinfo "${url_mode},${new_url_sha},${url_file}"
        URL_REWRITTEN=$((URL_REWRITTEN + 1))
    fi
done < <(GIT_INDEX_FILE="$TMP_INDEX" git grep --cached -l -F "$INTERNAL_URL" 2>/dev/null || true)
echo "  Rewrote internal source URL -> public mirror in ${URL_REWRITTEN} file(s)"

# Write the filtered tree and create an ORPHAN commit entirely in the object store.
# No -p (parent) flag is passed to commit-tree — the public mirror carries no
# internal history.  Both branches (paths removed, nothing removed) always produce
# a parentless snapshot so internal commits are never reachable on the public remote.
FILTERED_TREE=$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)

if [[ ${#REMOVED_PATHS[@]} -gt 0 ]] || [[ "$MARKETPLACE_CHANGED" -eq 1 ]] || [[ "$URL_REWRITTEN" -gt 0 ]]; then
    commit_msg="$(printf \
        'chore(mirror): orphan snapshot for public mirror\n\nExcluded: %s\nmarketplace.json filtered: %s\nSource: %s @ %s\n\nOrphan snapshot — the public mirror carries no internal history.\nEach mirror run replaces the public tip with a parentless filtered snapshot.\nNever merged to main.' \
        "${REMOVED_PATHS[*]:-none}" "$MARKETPLACE_CHANGED" "$current_branch" "$HEAD_SHA")"
else
    echo "  No tracked internal paths found — mirror tree matches source content."
    commit_msg="$(printf \
        'chore(mirror): orphan snapshot for public mirror\n\nNo internal paths removed.\nSource: %s @ %s\n\nOrphan snapshot — the public mirror carries no internal history.\nEach mirror run replaces the public tip with a parentless filtered snapshot.\nNever merged to main.' \
        "$current_branch" "$HEAD_SHA")"
fi

SCRATCH_SHA=$(git commit-tree "$FILTERED_TREE" -m "$commit_msg")
echo "  Orphan snapshot commit: ${SCRATCH_SHA}"

# ── verify exclusions ─────────────────────────────────────────────────────────

echo ""
echo "Verifying filtered tree (${SCRATCH_SHA})..."
FAILURES=0

# Snapshot the tree's file list ONCE into a variable, then grep the variable.
# Do NOT pipe `git ls-tree` straight into `grep -q`: under `set -o pipefail`,
# `grep -q` short-circuits on the first match and closes the pipe, `git ls-tree`
# then dies with SIGPIPE (exit 141), and pipefail turns the whole pipeline
# non-zero — so a path that IS present reads as absent. That would make the
# survival checks false-warn AND the exclusion checks false-pass on a real leak.
TREE_FILES="$(git ls-tree -r --name-only "$SCRATCH_SHA")"

for path in "${INTERNAL_PATHS[@]}"; do
    if grep -qE "^${path}(/|$)" <<<"$TREE_FILES"; then
        echo "  FAIL: '${path}' is still present in the filtered tree" >&2
        FAILURES=$((FAILURES + 1))
    else
        echo "  OK: '${path}' is absent from filtered tree"
    fi
done

# Verify no internal plugin names survive in the filtered marketplace.json.
if [[ -f "$MARKETPLACE_JSON" ]]; then
    for plugin_name in "${INTERNAL_PLUGIN_NAMES[@]}"; do
        in_tree=$(git show "${SCRATCH_SHA}:${MARKETPLACE_JSON}" 2>/dev/null \
            | python3 -c "
import json, sys
data = json.load(sys.stdin)
names = {p.get('name') for p in data.get('plugins', [])}
print('yes' if '${plugin_name}' in names else 'no')
" 2>/dev/null || echo "no")
        if [[ "$in_tree" == "yes" ]]; then
            echo "  FAIL: plugin '${plugin_name}' still present in filtered marketplace.json" >&2
            FAILURES=$((FAILURES + 1))
        else
            echo "  OK: '${plugin_name}' absent from filtered marketplace.json"
        fi
    done
fi

# Verify the internal source URL was fully rewritten to the public mirror.
# Fail-closed: an internal URL surviving into the public snapshot would give
# external users an install ref they cannot resolve.
if git grep -q -F "$INTERNAL_URL" "$SCRATCH_SHA" -- 2>/dev/null; then
    echo "  FAIL: internal source URL '${INTERNAL_URL}' still present in filtered tree" >&2
    git grep -l -F "$INTERNAL_URL" "$SCRATCH_SHA" -- 2>/dev/null | sed 's/^/    /' >&2
    FAILURES=$((FAILURES + 1))
else
    echo "  OK: internal source URL absent from filtered tree (rewritten to public mirror)"
fi
if git grep -q -F "$PUBLIC_URL" "$SCRATCH_SHA" -- 2>/dev/null; then
    echo "  OK: public mirror URL present in filtered tree"
else
    warn "Public mirror URL '${PUBLIC_URL}' not found in filtered tree"
fi

# Spot-check: public paths must still be present in the filtered tree.
for path in "plugin" ".claude-plugin/marketplace.json"; do
    if grep -qE "^${path}(/|$)" <<<"$TREE_FILES"; then
        echo "  OK: public path '${path}' present in filtered tree"
    else
        warn "Public path '${path}' not found in filtered tree"
    fi
done

[[ "$FAILURES" -gt 0 ]] && die "Verification failed ($FAILURES check(s)) — aborting."
echo "Verification passed."
echo ""

# ── push or dry-run exit ──────────────────────────────────────────────────────

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY RUN complete — no push performed."
    echo "  Filtered commit SHA: ${SCRATCH_SHA}"
    echo "  To run the real mirror: ./scripts/mirror-public.sh"
    exit 0
fi

echo "Mirroring filtered tree (${SCRATCH_SHA}) -> ${REMOTE_NAME} ${BRANCH}..."
git push "$REMOTE_NAME" "${SCRATCH_SHA}:refs/heads/${BRANCH}" --force
echo "Done. Public mirror updated: ${SCRATCH_SHA}"

#!/usr/bin/env bash
# Mirror main branch to the public bluewatersql/starboard repo via SSH.
# Usage: ./scripts/mirror-public.sh
#
# Prerequisites:
#   - SSH key with access to git@github.com:bluewatersql/starboard.git must be
#     configured (same key used for other bluewatersql projects).
#   - Run `git remote -v` to verify the 'public' remote exists; if not, this
#     script will add it automatically.

set -euo pipefail

PUBLIC_REMOTE_URL="git@github.com:bluewatersql/starboard.git"
REMOTE_NAME="public"
BRANCH="main"

# Add the remote if it doesn't exist
if ! git remote get-url "$REMOTE_NAME" &>/dev/null; then
    echo "Adding remote '$REMOTE_NAME' -> $PUBLIC_REMOTE_URL"
    git remote add "$REMOTE_NAME" "$PUBLIC_REMOTE_URL"
fi

# Verify we're on the right branch
current_branch=$(git rev-parse --abbrev-ref HEAD)
if [[ "$current_branch" != "$BRANCH" ]]; then
    echo "Error: must be on '$BRANCH' to mirror (currently on '$current_branch')" >&2
    exit 1
fi

# Verify working tree is clean
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Error: working tree has uncommitted changes — commit or stash first" >&2
    exit 1
fi

echo "Mirroring $BRANCH -> $REMOTE_NAME ($PUBLIC_REMOTE_URL)..."
git push "$REMOTE_NAME" "$BRANCH" --force
echo "Done."

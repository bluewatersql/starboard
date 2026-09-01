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

# Ensure the bluewatersql SSH key is loaded in the ssh-agent. After a reboot the
# agent starts empty, which makes git@github.com fail with
# "Permission denied (publickey)". Load it from the macOS keychain if missing.
# Override the key path with MIRROR_SSH_KEY if yours differs.
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
    echo "Warning: SSH key '$MIRROR_SSH_KEY' not found; relying on existing agent/config." >&2
fi

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

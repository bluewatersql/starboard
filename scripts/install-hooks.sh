#!/usr/bin/env bash
# Install git hooks for this repo.
# Currently installs: post-push (auto-mirrors main to bluewatersql/starboard).
#
# Usage: ./scripts/install-hooks.sh
# Run once after cloning. Hooks are not committed to the repo (.git/hooks/ is
# excluded by git), so each developer must run this script.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

install_hook() {
    local name="$1"
    local target="$HOOKS_DIR/$name"

    cat > "$target" << 'HOOK'
#!/usr/bin/env bash
# Auto-mirror main to public repo on push.
# Installed by scripts/install-hooks.sh

BRANCH="main"
REMOTE_NAME="public"
PUBLIC_REMOTE_URL="git@github.com:bluewatersql/starboard.git"

# Only mirror when pushing main
while read local_ref local_sha remote_ref remote_sha; do
    if [[ "$remote_ref" == "refs/heads/$BRANCH" ]]; then
        if ! git remote get-url "$REMOTE_NAME" &>/dev/null; then
            git remote add "$REMOTE_NAME" "$PUBLIC_REMOTE_URL"
        fi
        echo "[post-push] Mirroring $BRANCH to $REMOTE_NAME..."
        git push "$REMOTE_NAME" "$BRANCH" --force
        echo "[post-push] Mirror complete."
    fi
done
HOOK

    chmod +x "$target"
    echo "Installed: $target"
}

install_hook "post-push"
echo "All hooks installed. Run 'git push origin main' to trigger auto-mirror."

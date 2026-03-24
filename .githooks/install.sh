#!/bin/bash
#
# Install git hooks for the repository
#
# This script configures git to use the hooks in .githooks/ directory
# instead of the default .git/hooks/
#
# Usage:
#   .githooks/install.sh

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Installing git hooks...${NC}"

# Check if we're in a git repository
if [ ! -d .git ]; then
  echo -e "${RED}Error: Not in a git repository${NC}"
  exit 1
fi

# Make hooks executable
chmod +x .githooks/pre-commit

# Configure git to use .githooks directory
git config core.hooksPath .githooks

echo -e "${GREEN}✅ Git hooks installed successfully!${NC}"
echo ""
echo "Installed hooks:"
echo "  - pre-commit: Auto-regenerates TypeScript types when Pydantic models change"
echo ""
echo "To disable hooks temporarily, use:"
echo "  git commit --no-verify"


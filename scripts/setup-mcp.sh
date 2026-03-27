#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }

echo ""
echo "==============================="
echo "  Starboard MCP Server Setup"
echo "==============================="
echo ""

# ---------------------------------------------------------------------------
# 1. Check if starboard-mcp is available, offer to install
# ---------------------------------------------------------------------------
if command -v starboard-mcp &>/dev/null; then
    ok "starboard-mcp found at $(command -v starboard-mcp)"
else
    warn "starboard-mcp command not found."
    read -rp "Install starboard-server[mcp] now? [Y/n]: " do_install
    do_install=${do_install:-Y}
    if [[ "$do_install" =~ ^[Yy]$ ]]; then
        info "Installing starboard-server with MCP extras..."
        if command -v uv &>/dev/null; then
            uv pip install -e "${REPO_ROOT}/packages/starboard-server[mcp]"
        elif command -v pip &>/dev/null; then
            pip install -e "${REPO_ROOT}/packages/starboard-server[mcp]"
        else
            error "Neither uv nor pip found. Please install Python packaging tools first."
            exit 1
        fi

        if ! command -v starboard-mcp &>/dev/null; then
            error "Installation completed but starboard-mcp is still not on PATH."
            error "You may need to activate your virtualenv or add it to PATH."
            exit 1
        fi
        ok "starboard-mcp installed successfully."
    else
        warn "Skipping installation. You can install later with:"
        echo "  pip install -e \"packages/starboard-server[mcp]\""
        echo ""
    fi
fi

# ---------------------------------------------------------------------------
# 2. Choose target (Cursor IDE, Claude Desktop, or Both)
# ---------------------------------------------------------------------------
echo ""
echo "Where do you want to configure Starboard?"
echo "  1) Cursor IDE  (.cursor/mcp.json)"
echo "  2) Claude Desktop"
echo "  3) Both"
read -rp "Choice [1]: " target
target=${target:-1}

if [[ ! "$target" =~ ^[123]$ ]]; then
    error "Invalid choice: $target. Please enter 1, 2, or 3."
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. Collect credentials
# ---------------------------------------------------------------------------
echo ""
info "Enter your Databricks and LLM credentials."
echo ""

read -rp "Databricks workspace URL (e.g. https://myworkspace.cloud.databricks.com): " db_host
if [[ -z "$db_host" ]]; then
    error "Databricks workspace URL is required."
    exit 1
fi

read -rsp "Databricks token (input hidden): " db_token
echo ""
if [[ -z "$db_token" ]]; then
    error "Databricks token is required."
    exit 1
fi

read -rp "LLM provider (openai/anthropic) [openai]: " llm_provider
llm_provider=${llm_provider:-openai}

read -rsp "LLM API key (input hidden): " llm_key
echo ""
if [[ -z "$llm_key" ]]; then
    error "LLM API key is required."
    exit 1
fi

default_model="gpt-4o"
if [[ "$llm_provider" == "anthropic" ]]; then
    default_model="claude-sonnet-4-20250514"
fi
read -rp "LLM model [$default_model]: " llm_model
llm_model=${llm_model:-$default_model}

# ---------------------------------------------------------------------------
# Helper: generate MCP config JSON
# ---------------------------------------------------------------------------
generate_config() {
    cat <<ENDJSON
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "DATABRICKS_HOST": "${db_host}",
        "DATABRICKS_TOKEN": "${db_token}",
        "LLM_PROVIDER": "${llm_provider}",
        "LLM_API_KEY": "${llm_key}",
        "LLM_MODEL": "${llm_model}"
      }
    }
  }
}
ENDJSON
}

# ---------------------------------------------------------------------------
# 4. Write config to appropriate location
# ---------------------------------------------------------------------------
write_cursor_config() {
    local cursor_dir="${REPO_ROOT}/.cursor"
    local cursor_config="${cursor_dir}/mcp.json"

    mkdir -p "$cursor_dir"

    if [[ -f "$cursor_config" ]]; then
        warn "Cursor config already exists at $cursor_config"
        read -rp "Overwrite? [y/N]: " overwrite
        if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
            info "Skipping Cursor config."
            return
        fi
    fi

    generate_config > "$cursor_config"
    ok "Cursor config written to $cursor_config"
}

write_claude_desktop_config() {
    local claude_config
    if [[ "$(uname)" == "Darwin" ]]; then
        claude_config="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
    else
        # Linux / WSL fallback
        claude_config="${APPDATA:-$HOME/.config}/Claude/claude_desktop_config.json"
    fi

    local claude_dir
    claude_dir="$(dirname "$claude_config")"
    mkdir -p "$claude_dir"

    if [[ -f "$claude_config" ]]; then
        warn "Claude Desktop config already exists at $claude_config"
        warn "You may want to manually merge the starboard server entry."
        read -rp "Overwrite entire file? [y/N]: " overwrite
        if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
            info "Skipping Claude Desktop config."
            echo ""
            info "To add manually, merge this into your existing config:"
            generate_config
            return
        fi
    fi

    generate_config > "$claude_config"
    ok "Claude Desktop config written to $claude_config"
}

case "$target" in
    1) write_cursor_config ;;
    2) write_claude_desktop_config ;;
    3) write_cursor_config; write_claude_desktop_config ;;
esac

# ---------------------------------------------------------------------------
# 5. Optional: install skills
# ---------------------------------------------------------------------------
echo ""
read -rp "Install Claude Code skills to ~/.claude/skills/? [y/N]: " install_skills
if [[ "$install_skills" =~ ^[Yy]$ ]]; then
    skills_src="${REPO_ROOT}/skills/starboard"
    if [[ -d "$skills_src" ]]; then
        skills_dest="$HOME/.claude/skills/starboard"
        mkdir -p "$skills_dest"
        cp -r "$skills_src"/* "$skills_dest/"
        ok "Skills installed to $skills_dest"
    else
        warn "Skills directory not found at $skills_src. Skipping."
    fi
fi

# Also offer Cursor skills
if [[ "$target" == "1" || "$target" == "3" ]]; then
    read -rp "Install Cursor skills to ~/.cursor/skills/? [y/N]: " install_cursor_skills
    if [[ "$install_cursor_skills" =~ ^[Yy]$ ]]; then
        skills_src="${REPO_ROOT}/skills/starboard"
        if [[ -d "$skills_src" ]]; then
            skills_dest="$HOME/.cursor/skills/starboard"
            mkdir -p "$skills_dest"
            cp -r "$skills_src"/* "$skills_dest/"
            ok "Skills installed to $skills_dest"
        else
            warn "Skills directory not found at $skills_src. Skipping."
        fi
    fi
fi

# ---------------------------------------------------------------------------
# 6. Verify connectivity by running a ping
# ---------------------------------------------------------------------------
echo ""
if command -v starboard-mcp &>/dev/null; then
    info "Testing MCP server connectivity..."
    ping_result=$(echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | \
        DATABRICKS_HOST="$db_host" DATABRICKS_TOKEN="$db_token" \
        LLM_PROVIDER="$llm_provider" LLM_API_KEY="$llm_key" LLM_MODEL="$llm_model" \
        starboard-mcp --transport stdio 2>/dev/null | head -1) || true

    if [[ -n "$ping_result" ]]; then
        ok "MCP server responded: $ping_result"
    else
        warn "No response from MCP server. This may be expected if the server requires additional setup."
        warn "Try running 'starboard-mcp --transport stdio' manually to debug."
    fi
else
    warn "Skipping connectivity test (starboard-mcp not installed)."
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "==============================="
ok "Setup complete!"
echo "==============================="
echo ""
info "Next steps:"
if [[ "$target" == "1" || "$target" == "3" ]]; then
    echo "  - Restart Cursor IDE to pick up the new MCP config"
fi
if [[ "$target" == "2" || "$target" == "3" ]]; then
    echo "  - Restart Claude Desktop to pick up the new MCP config"
fi
echo "  - See docs/CLAUDE_CODE_INTEGRATION.md for usage examples"
echo ""

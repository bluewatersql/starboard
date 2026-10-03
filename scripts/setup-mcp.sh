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
    read -rp "Install starboard now? [Y/n]: " do_install
    do_install=${do_install:-Y}
    if [[ "$do_install" =~ ^[Yy]$ ]]; then
        info "Installing starboard..."
        if command -v uv &>/dev/null; then
            uv pip install -e "${REPO_ROOT}/packages/starboard"
        elif command -v pip &>/dev/null; then
            pip install -e "${REPO_ROOT}/packages/starboard"
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
        echo "  pip install -e \"packages/starboard\""
        echo ""
    fi
fi

# ---------------------------------------------------------------------------
# 2. Choose target (Cursor IDE, Claude Desktop, Claude Code, or All)
# ---------------------------------------------------------------------------
echo ""
echo "Where do you want to configure Starboard?"
echo "  1) Cursor IDE  (.cursor/mcp.json)"
echo "  2) Claude Desktop"
echo "  3) Claude Code  (.mcp.json in project root)"
echo "  4) All"
read -rp "Choice [1]: " target
target=${target:-1}

if [[ ! "$target" =~ ^[1234]$ ]]; then
    error "Invalid choice: $target. Please enter 1, 2, 3, or 4."
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. Collect credentials (falls back to environment variables)
# ---------------------------------------------------------------------------
echo ""
info "Enter your Databricks and LLM credentials."
info "Press Enter to use the value from your environment (shown in brackets)."
echo ""

env_db_host="${DATABRICKS_HOST:-}"
env_db_token="${DATABRICKS_TOKEN:-}"
env_llm_provider="${LLM_PROVIDER:-openai}"
env_llm_key="${LLM_API_KEY:-${OPENAI_API_KEY:-}}"
env_llm_model="${LLM_MODEL:-}"

# -- Databricks host
if [[ -n "$env_db_host" ]]; then
    read -rp "Databricks workspace URL [$env_db_host]: " db_host
    db_host=${db_host:-$env_db_host}
else
    read -rp "Databricks workspace URL (e.g. https://myworkspace.cloud.databricks.com): " db_host
fi
if [[ -z "$db_host" ]]; then
    error "Databricks workspace URL is required. Set DATABRICKS_HOST or enter a value."
    exit 1
fi

# -- Databricks token
if [[ -n "$env_db_token" ]]; then
    read -rsp "Databricks token [****${env_db_token: -4}] (Enter to keep): " db_token
    echo ""
    db_token=${db_token:-$env_db_token}
else
    read -rsp "Databricks token (input hidden): " db_token
    echo ""
fi
if [[ -z "$db_token" ]]; then
    error "Databricks token is required. Set DATABRICKS_TOKEN or enter a value."
    exit 1
fi

# -- LLM provider
read -rp "LLM provider (openai/anthropic) [$env_llm_provider]: " llm_provider
llm_provider=${llm_provider:-$env_llm_provider}

# -- LLM API key
if [[ -n "$env_llm_key" ]]; then
    read -rsp "LLM API key [****${env_llm_key: -4}] (Enter to keep): " llm_key
    echo ""
    llm_key=${llm_key:-$env_llm_key}
else
    read -rsp "LLM API key (input hidden): " llm_key
    echo ""
fi
if [[ -z "$llm_key" ]]; then
    error "LLM API key is required. Set LLM_API_KEY or enter a value."
    exit 1
fi

# -- LLM model
default_model="${env_llm_model:-gpt-4o}"
if [[ -z "$env_llm_model" && "$llm_provider" == "anthropic" ]]; then
    default_model="claude-sonnet-4-20250514"
fi
read -rp "LLM model [$default_model]: " llm_model
llm_model=${llm_model:-$default_model}

# -- Ask whether to embed credentials or rely on env fallback
echo ""
echo "How should credentials be stored in the config?"
echo "  1) Embed in config  (credentials written to the JSON file)"
echo "  2) Rely on environment  (minimal config, credentials read from env at runtime)"
read -rp "Choice [1]: " cred_mode
cred_mode=${cred_mode:-1}

# ---------------------------------------------------------------------------
# Helper: generate MCP config JSON
# ---------------------------------------------------------------------------
generate_config() {
    if [[ "$cred_mode" == "2" ]]; then
        cat <<ENDJSON
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio"],
      "timeout": 900
    }
  }
}
ENDJSON
    else
        cat <<ENDJSON
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio"],
      "timeout": 900,
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
    fi
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
        warn "You may want to manually merge the starboard MCP entry."
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

write_claude_code_config() {
    local mcp_config="${REPO_ROOT}/.mcp.json"

    if [[ -f "$mcp_config" ]]; then
        warn "Claude Code config already exists at $mcp_config"
        read -rp "Overwrite? [y/N]: " overwrite
        if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
            info "Skipping Claude Code config."
            return
        fi
    fi

    generate_config > "$mcp_config"
    ok "Claude Code config written to $mcp_config"
}

case "$target" in
    1) write_cursor_config ;;
    2) write_claude_desktop_config ;;
    3) write_claude_code_config ;;
    4) write_cursor_config; write_claude_desktop_config; write_claude_code_config ;;
esac

# ---------------------------------------------------------------------------
# 5. Optional: install skills
# ---------------------------------------------------------------------------
echo ""
skills_src="${REPO_ROOT}/skills/starboard"

# Offer Claude Code skills for Claude Code or All targets
if [[ "$target" == "3" || "$target" == "4" ]]; then
    read -rp "Install Claude Code skills to ~/.claude/skills/? [Y/n]: " install_skills
    install_skills=${install_skills:-Y}
else
    read -rp "Install Claude Code skills to ~/.claude/skills/? [y/N]: " install_skills
fi
if [[ "$install_skills" =~ ^[Yy]$ ]]; then
    if [[ -d "$skills_src" ]]; then
        skills_dest="$HOME/.claude/skills/starboard"
        mkdir -p "$skills_dest"
        cp -r "$skills_src"/* "$skills_dest/"
        ok "Skills installed to $skills_dest"
    else
        warn "Skills directory not found at $skills_src. Skipping."
    fi
fi

# Offer Cursor skills for Cursor or All targets
if [[ "$target" == "1" || "$target" == "4" ]]; then
    read -rp "Install Cursor skills to ~/.cursor/skills/? [Y/n]: " install_cursor_skills
    install_cursor_skills=${install_cursor_skills:-Y}
    if [[ "$install_cursor_skills" =~ ^[Yy]$ ]]; then
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
# 7. Auto-approve Starboard MCP tools in Claude Code
# ---------------------------------------------------------------------------
if [[ "$target" == "3" || "$target" == "4" ]]; then
    echo ""
    info "Claude Code prompts for permission on every MCP tool call."
    info "Auto-approving Starboard tools avoids repeated prompts."
    read -rp "Auto-approve all Starboard MCP tools in Claude Code? [Y/n]: " approve_tools
    approve_tools=${approve_tools:-Y}

    if [[ "$approve_tools" =~ ^[Yy]$ ]]; then
        claude_settings="$HOME/.claude/settings.json"
        if [[ -f "$claude_settings" ]]; then
            # Generate the allowlist from the installed MCP server
            starboard_tools=()
            if command -v starboard-mcp &>/dev/null && source "$REPO_ROOT/.venv/bin/activate" 2>/dev/null; then
                while IFS= read -r tool; do
                    starboard_tools+=("$tool")
                done < <(python3 -c "
from starboard.mcp.tool_bridge import PHASE_B_TOOLS
from starboard.mcp.composite_tools import COMPOSITE_TOOL_METADATA
from starboard.mcp.agent_bridge import AGENT_TOOL_METADATA
tools = {'starboard_ping'}
tools.update(PHASE_B_TOOLS)
tools.update(t['name'] for t in COMPOSITE_TOOL_METADATA)
tools.update(t['name'] for t in AGENT_TOOL_METADATA)
for t in sorted(tools):
    print(f'mcp__starboard__{t}')
" 2>/dev/null)
            fi

            if [[ ${#starboard_tools[@]} -eq 0 ]]; then
                warn "Could not generate tool list from installed package."
                warn "Falling back to known tool list."
                starboard_tools=(
                    "mcp__starboard__analytics_agent"
                    "mcp__starboard__analyze_access_patterns"
                    "mcp__starboard__analyze_code_quality"
                    "mcp__starboard__analyze_discovery_domain"
                    "mcp__starboard__analyze_explain_plan"
                    "mcp__starboard__analyze_job_history"
                    "mcp__starboard__analyze_policy_coverage"
                    "mcp__starboard__analyze_query_impact"
                    "mcp__starboard__analyze_query_plan"
                    "mcp__starboard__analyze_schema_drift"
                    "mcp__starboard__analyze_storage_optimization"
                    "mcp__starboard__analyze_table_costs"
                    "mcp__starboard__analyze_table_schema"
                    "mcp__starboard__analyze_warehouse_topology"
                    "mcp__starboard__build_analytics_context"
                    "mcp__starboard__build_sql_query"
                    "mcp__starboard__cluster_agent"
                    "mcp__starboard__configure_warehouse_slo"
                    "mcp__starboard__diagnostic_agent"
                    "mcp__starboard__discover_active_products"
                    "mcp__starboard__discover_tables"
                    "mcp__starboard__execute_sql_query"
                    "mcp__starboard__explore_artifact"
                    "mcp__starboard__generate_portfolio_chargeback"
                    "mcp__starboard__generate_schema_diff"
                    "mcp__starboard__generate_warehouse_chargeback"
                    "mcp__starboard__get_cluster_config"
                    "mcp__starboard__get_cluster_events"
                    "mcp__starboard__get_cluster_health"
                    "mcp__starboard__get_cluster_metrics"
                    "mcp__starboard__get_enriched_table_metadata"
                    "mcp__starboard__get_job_config"
                    "mcp__starboard__get_job_summary"
                    "mcp__starboard__get_query_analysis"
                    "mcp__starboard__get_query_runtime_metrics"
                    "mcp__starboard__get_run_output"
                    "mcp__starboard__get_source_code"
                    "mcp__starboard__get_spark_logs"
                    "mcp__starboard__get_table_fingerprint"
                    "mcp__starboard__get_table_grants"
                    "mcp__starboard__get_table_history"
                    "mcp__starboard__get_table_lineage"
                    "mcp__starboard__get_table_metadata"
                    "mcp__starboard__get_table_profile"
                    "mcp__starboard__get_task_logs"
                    "mcp__starboard__get_warehouse_fingerprint"
                    "mcp__starboard__get_warehouse_health"
                    "mcp__starboard__get_warehouse_portfolio"
                    "mcp__starboard__get_warehouse_user_activity"
                    "mcp__starboard__get_workspace_overview"
                    "mcp__starboard__job_agent"
                    "mcp__starboard__list_clusters"
                    "mcp__starboard__list_uc_assets"
                    "mcp__starboard__query_agent"
                    "mcp__starboard__resolve_job"
                    "mcp__starboard__resolve_query"
                    "mcp__starboard__run_discovery_queries"
                    "mcp__starboard__starboard_ping"
                    "mcp__starboard__synthesize_discovery_report"
                    "mcp__starboard__uc_agent"
                    "mcp__starboard__validate_sql_query"
                    "mcp__starboard__warehouse_agent"
                )
            fi

            # Merge permissions into settings.json using Python for safe JSON manipulation
            python3 -c "
import json, sys

settings_path = '$claude_settings'
with open(settings_path) as f:
    settings = json.load(f)

new_tools = sys.argv[1:]
allow = settings.get('permissions', {}).get('allow', [])
top_allow = settings.get('allow', [])

added = 0
for tool in new_tools:
    if tool not in allow:
        allow.append(tool)
        added += 1
    if tool not in top_allow:
        top_allow.append(tool)

settings.setdefault('permissions', {})['allow'] = allow
settings['allow'] = top_allow

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')

print(f'{added} tools auto-approved')
" "${starboard_tools[@]}"

            ok "Starboard MCP tools added to Claude Code permissions."
            ok "No more per-tool approval prompts for Starboard tools."
        else
            warn "Claude Code settings not found at $claude_settings"
            warn "Run 'claude' once first to initialize settings, then re-run this script."
        fi
    fi
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
if [[ "$target" == "1" || "$target" == "4" ]]; then
    echo "  - Restart Cursor IDE to pick up the new MCP config"
fi
if [[ "$target" == "2" || "$target" == "4" ]]; then
    echo "  - Restart Claude Desktop to pick up the new MCP config"
fi
if [[ "$cred_mode" == "2" ]]; then
    echo "  - Ensure DATABRICKS_HOST, DATABRICKS_TOKEN, and LLM_API_KEY are"
    echo "    exported in your shell (or defined in .env) before starting the IDE"
fi
echo "  - See docs/SKILLS.md for skill documentation and usage examples"
echo ""

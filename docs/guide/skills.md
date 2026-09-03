# Skills & MCP Integration

Starboard ships **10 AI coding assistant skills** that teach Claude Code, Cursor, Codex, and OpenCode how to run Databricks workspace analyses. Each skill is a `SKILL.md` playbook — trigger keywords, tool-call workflows, and interpretation guidance — covering a specific analysis domain.

The skills drive the optional `starboard-mcp` server when it is available, and fall back to the `starboard` / `python -m starboard_x.<cap>` CLI otherwise. **The MCP server is optional** — skills work fine without it.

---

## Skill catalog

| Skill | Domain | What it does |
|-------|--------|-------------|
| `starboard-analyze` | Meta-router | Reads the request, matches it to the right domain skill, dispatches |
| `starboard-query` | SQL Queries | Execution plans, runtime metrics, optimization recommendations |
| `starboard-job` | Jobs | Run history, failure patterns, code anti-patterns, config review |
| `starboard-uc` | Unity Catalog | Lineage, governance, grants, schema drift, storage optimization |
| `starboard-cluster` | Compute | Cluster sizing, health, autoscaling, Spark config |
| `starboard-finops` | FinOps / cost | Cost allocation, billing queries, budget trends (list-price DBU estimates) |
| `starboard-warehouse` | SQL Warehouses | Portfolio health, SLO compliance, right-sizing, chargeback |
| `starboard-diagnostic` | Troubleshooting | Cross-domain root-cause analysis, log triage |
| `starboard-discovery` | Workspace health | 4-phase workspace assessment and product-usage inventory |
| `starboard-workload-review` | Workload Review | Ranked, evidence-cited findings over public `system.*` data |

The canonical skills tree lives at `packages/starboard-skills/skills/starboard/`.

---

## Install

```bash
pip install starboard-skills
```

This installs the skills tree and the `starboard-helper` script.

### Claude Code

Copy the skills into Claude Code's skills directory:

```bash
# Manual
cp -r packages/starboard-skills/skills/starboard ~/.claude/skills/starboard

# Or via the setup script (from the repo root)
./scripts/setup-mcp.sh   # choose "y" when prompted to install Claude Code skills
```

Verify:

```bash
ls ~/.claude/skills/starboard/*/SKILL.md
# Should list 10 SKILL.md files
```

!!! note "Tool permissions"
    Claude Code prompts for approval on every MCP tool call by default. The setup script (`./scripts/setup-mcp.sh`) can auto-approve all Starboard tools. Claude Code does not support wildcard permissions (`mcp__starboard__*`); each tool must be listed explicitly.

### Cursor

Skills in `packages/starboard-skills/skills/starboard/` are discovered automatically when the workspace is open — no additional installation needed.

### Codex / OpenCode

Codex and OpenCode have no plugin loader. They call the `starboard_x` helpers directly:

```bash
pip install starboard-core           # or: pip install "starboard-kernel[diagnostics,discovery,warehouse,uc,review]"

python -m starboard_x.discovery run [--profile NAME]
python -m starboard_x.warehouse analyze --history '[]'
python -m starboard_x.diagnostic <exit_code>
python -m starboard_x --help        # list all capabilities
```

Auth uses the Databricks SDK credential chain (`DATABRICKS_HOST` + `DATABRICKS_TOKEN`, or `--profile`).

---

## Optional: MCP server

The `starboard-mcp` server exposes Starboard's tools to any MCP-capable host (Claude Code, Cursor, Claude Desktop) as structured MCP tools. It is included in `pip install starboard`.

```bash
pip install starboard
starboard-mcp --help
```

### Configure for Claude Code

Place in `.mcp.json` (project root) or `~/.claude/settings.json` (global):

```json
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "DATABRICKS_HOST": "https://YOUR_WORKSPACE.cloud.databricks.com",
        "DATABRICKS_TOKEN": "dapi_YOUR_TOKEN_HERE",
        "LLM_PROVIDER": "openai",
        "LLM_API_KEY": "sk-YOUR_KEY_HERE"
      }
    }
  }
}
```

If `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and `LLM_API_KEY` are already exported in your shell, the `env` block is optional — just `command` and `args` are enough.

### Configure for Cursor

Place in `.cursor/mcp.json` in your project root (same content as above). Restart Cursor after saving.

### Tool scope

| Scope | Tools | Default? |
|-------|-------|----------|
| `phase_a` | 11 quick-lookup tools | No |
| `phase_b` | 40+ tools (quick + deep analysis, discovery, analytics) | **Yes** |
| `full` | All tools | No |

Override via env var: `STARBOARD_MCP_TOOL_SCOPE=phase_b`

### Multi-workspace setup

```bash
starboard-mcp workspace add --id production --host https://prod.cloud.databricks.com
starboard-mcp workspace add --id staging    --host https://staging.cloud.databricks.com
starboard-mcp workspace list
```

Credentials are stored in `~/.starboard/.env` (mode 0600) and never exposed to AI assistants. Switch workspaces by telling the assistant: *"switch to production"* — it calls the `list_workspaces` / `switch_workspace` MCP tools.

---

## Host coverage summary

| Host | Skills path | MCP server |
|------|-------------|-----------|
| **Claude Code** | `~/.claude/skills/starboard/` | `.mcp.json` or `~/.claude/settings.json` |
| **Cursor** | Project tree (`packages/starboard-skills/skills/starboard/`) | `.cursor/mcp.json` |
| **Codex** | `python -m starboard_x.<cap>` directly | Not needed |
| **OpenCode** | `python -m starboard_x.<cap>` directly; agent configs in `plugin/agents/` | Not needed |

---

## Related

- [Quickstart](./quickstart.md) — get a workspace running in minutes
- [CLI reference](./cli.md) — `starboard`, `starboard review`, `starboard auth`
- [Agent catalog](../overview/agents.md) — what each domain agent does
- [Troubleshooting](./troubleshooting.md) — MCP and auth fixes

name: starboard-workspace
description: Switch between Databricks workspaces or check which workspace is active. Use when user mentions workspace switching, different environment, production vs staging, or changing workspace. Do NOT use for "workspace discovery" or "workspace health" — those belong to starboard-discovery.
  Triggers on: switch workspace, change workspace, which workspace, production, staging, workspace list, environments, list workspaces.

## Prerequisites

- Starboard MCP server configured in `.cursor/mcp.json` or Claude Desktop config
- At least one workspace configured via `starboard-mcp workspace add`

## Quick Path

When this skill is triggered, IMMEDIATELY call the MCP tool below. Do NOT describe the skill, list capabilities, or ask the user for confirmation. Execute now.

1. Call MCP tool `list_workspaces` (no parameters needed).
2. Present the workspaces as a list showing: workspace ID, host, default status, and warehouse ID.
3. If the user asked to switch to a specific workspace, call `switch_workspace` with `{ "workspace_id": "<id>" }`.
4. Tell the user to pass `workspace_id: "<id>"` in subsequent tool calls to target that workspace.

If the user wants to add, remove, or configure workspaces, tell them to run the CLI:
```bash
starboard-mcp workspace add       # interactive — prompts for host, token
starboard-mcp workspace remove <id>
starboard-mcp workspace set-default <id>
starboard-mcp workspace list
```

Credentials are managed outside of Claude for security — tokens are stored in `~/.starboard/.env` (mode 0600).

## Available MCP Tools

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `list_workspaces` | List configured workspaces with IDs and hosts (no secrets) | (none) |
| `switch_workspace` | Validate workspace ID and get instructions for switching | `workspace_id` |

## Example Prompts

- "Which workspace am I connected to?"
- "Switch to the staging workspace"
- "List all configured Databricks workspaces"
- "Run this analysis on the production workspace instead"
- "I want to analyze jobs on workspace xyz-123"

## Interpreting Results

- **Default workspace**: All tools use this workspace when no `workspace_id` is specified. Shown with `is_default: true`.
- **Switching workspaces**: Does not change the server default — it returns the workspace ID to pass to subsequent tool calls. The user can also change the default via the CLI.
- **Adding workspaces**: Must be done via the `starboard-mcp workspace add` CLI to keep credentials outside AI context. Tokens never appear in MCP tool responses.

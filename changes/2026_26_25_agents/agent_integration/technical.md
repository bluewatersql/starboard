# Technical Design — Starboard Agent-Host Integration

> Companion to `opportunities.md` / `recommendation.md`. All manifests below use **current (2026) verified formats**; sources cited inline. Confidence: **[C]** confirmed, **[I]** inferred, **[U]** unverified.
> Repo anchors: `packages/starboard-skills/` (skills + `starboard-helper`), `packages/starboard/starboard/mcp/` (MCP server), `packages/starboard/starboard/mcp/agent_bridge.py` (agent tool names).

## 0. The substrate: `starboard-helper` CLI contract

Every no-MCP integration funnels through one CLI. Current shape (repo: `starboard_skills/helpers/__main__.py`):

```
starboard-helper <domain> <command> [options]     # JSON to stdout
domains: job | query | warehouse | uc | cluster | finops | diagnostic
exit codes: 0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error
auth: bare databricks.sdk.WorkspaceClient()  (unified auth chain)
```

Proposed additions for cross-host parity: a `--format json` flag (already implicit), a `genie ask` subcommand (O8), and `analyze`/`discovery` as first-class composite subcommands so the 9 skills map 1:1 to CLI verbs. This CLI is the **single dependency** each host wraps.

Real MCP agent-tool names (for the MCP path, `agent_bridge.py`): `query_agent`, `job_agent`, `uc_agent`, `cluster_agent`, `analytics_agent`, `warehouse_agent`, `diagnostic_agent`, `discovery_agent`.

---

## 1. Claude Code plugin (flagship, O1–O3)

### 1.1 Directory layout

```
starboard-plugin/
├── .claude-plugin/
│   ├── plugin.json                 # manifest
│   └── marketplace.json            # (if this repo is also the marketplace)
├── skills/                         # bundled skills (dual-mode, from starboard-skills)
│   ├── starboard-query/SKILL.md
│   ├── starboard-finops/SKILL.md
│   ├── starboard-diagnostic/SKILL.md
│   ├── starboard-cluster/SKILL.md
│   ├── starboard-job/SKILL.md
│   ├── starboard-uc/SKILL.md
│   ├── starboard-warehouse/SKILL.md
│   ├── starboard-discovery/SKILL.md
│   └── starboard-analyze/SKILL.md
├── commands/
│   └── starboard-triage.md         # optional one-shot (O11)
├── .mcp.json                       # OPTIONAL (O3 dual-mode only)
└── README.md                       # documents `pip install starboard-skills`
```

> Note: file is `SKILL.md` (uppercase) in Claude Code plugins; directory name becomes the `/command`. **[C]** (code.claude.com/docs/en/skills). The repo currently uses lowercase `skill.md` — rename on packaging.

### 1.2 `plugin.json` — skills-only (NO MCP), O1

```json
{
  "name": "starboard",
  "displayName": "Starboard — Databricks Analysis",
  "version": "0.1.1",
  "description": "AI-powered Databricks workload analysis: queries, jobs, Unity Catalog, clusters, FinOps, warehouses, diagnostics. CLI-helper mode, no server required.",
  "author": { "name": "Starboard", "url": "https://github.com/<org>/starboard" },
  "homepage": "https://github.com/<org>/starboard",
  "repository": "https://github.com/<org>/starboard",
  "license": "Apache-2.0",
  "keywords": ["databricks", "finops", "unity-catalog", "spark", "optimization"],
  "skills": "./skills/",
  "commands": ["./commands/starboard-triage.md"]
}
```

Verified fields (`skills` path, `commands` array, `author` object, `keywords`) per plugins-reference. **[C]** No `mcpServers` key ⇒ pure CLI-helper mode; each skill's dual-mode branch takes the `starboard-helper` path automatically.

### 1.3 `plugin.json` — dual-mode with optional MCP, O3

Add a toggle + conditional MCP declaration:

```json
{
  "name": "starboard",
  "version": "0.1.1",
  "skills": "./skills/",
  "commands": ["./commands/starboard-triage.md"],
  "mcpServers": "./.mcp.json",
  "userConfig": {
    "enable_mcp": {
      "type": "boolean",
      "title": "Enable Starboard MCP server (full agent stack)",
      "description": "Runs starboard-mcp for server-side 7-agent orchestration. Requires LLM credentials.",
      "required": false
    }
  }
}
```

`.mcp.json` (bundled; `${CLAUDE_PLUGIN_ROOT}` resolves to the plugin dir) **[C]**:

```json
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio"],
      "timeout": 900,
      "env": {
        "DATABRICKS_HOST": "${DATABRICKS_HOST}",
        "LLM_PROVIDER": "${LLM_PROVIDER}",
        "LLM_API_KEY": "${LLM_API_KEY}",
        "LLM_MODEL": "${LLM_MODEL}"
      }
    }
  }
}
```

When present and enabled, the skills see `mcp__starboard__*_agent` tools and route to the full stack; when disabled/absent, they fall back to `starboard-helper`. Same skill files, two fidelity levels. **[C repo dual-mode logic]**

### 1.4 SKILL.md frontmatter (hardened dual-mode)

Current skills carry only a title; add standard frontmatter so Claude auto-discovers them and pre-authorizes the CLI (avoids per-call permission prompts):

```yaml
---
name: starboard-query
description: >
  Analyze Databricks SQL query performance — fetch history, find slow/failed
  queries, diagnose, and recommend optimizations. Use when the user asks about
  query performance, slow queries, warehouse query load, or SQL failures.
allowed-tools: Bash(starboard-helper:*), Read
---
```

`description` is the required field and drives auto-invocation; `name` defaults to the directory name; `allowed-tools` gates and pre-approves tools. Skills follow the Agent Skills open standard (agentskills.io) with Claude Code extensions (invocation control, subagent execution, dynamic-context injection via `` !`cmd` ``). **[C]** (code.claude.com/docs/en/skills). Body keeps the existing "MCP path vs Non-MCP path" branch.

### 1.5 `marketplace.json` (O2)

```json
{
  "name": "starboard-marketplace",
  "owner": "<org-or-team>",
  "plugins": [
    {
      "name": "starboard",
      "source": "https://github.com/<org>/starboard",
      "description": "Databricks workload analysis & optimization (skills + optional MCP)"
    }
  ]
}
```

`source` may be a git URL, a GitHub release download, or `{ "type": "npm", "package": "..." }`. **[C]** Install UX: `/plugin marketplace add <org>/starboard` → `/plugin install starboard`.

### 1.6 Install flows

| Host | Command |
|------|---------|
| Claude Code (public) | `/plugin marketplace add <org>/starboard` then `/plugin install starboard@starboard-marketplace` **[C]** |
| Isaac (internal) | `isaac plugin add starboard@<marketplace>`; verify `isaac -- plugin list \| grep starboard` **[C]** |
| Databricks customers | `databricks aitools install` (skills only) **[C]** |

---

## 2. Isaac (internal) — mostly free-riding on §1

**Model [C]:** Isaac CLI is the supported entry point that wraps Claude Code (`isaac --claude`), Codex (`isaac codex`), OpenCode (`isaac opencode`), Cursor, Omnigent. It provides Databricks auth + managed config, a **plugin marketplace**, and MCP passthrough.

- **Plugins**: `isaac plugin add|remove|update PLUGIN@MARKETPLACE`; `isaac plugin list installed`. Plugins deliver "skills, commands, MCP integrations, and apps." **[C]** ⇒ the §1 Claude Code plugin *is* the Isaac artifact. A plugin-delivered MCP shows as `plugin:starboard:starboard`. **[C]**
- **MCP passthrough**: `isaac -- mcp add|remove|list -s user|project` forwards to the underlying Claude CLI (`--` = "forward to Claude CLI", space required). **[C]**
- **Rules/guidance**: Universe `.isaac/rules/` compiles into Claude rules, Cursor rules, and **Codex `AGENTS.md`**. **[C]** ⇒ a Starboard rules snippet propagates guidance to all harnesses (O10).
- **Distribution**: internal marketplaces are git-repo snapshots (e.g. FE `vibe` at `~/.vibe/marketplace/`, plugins named `plugin@marketplace` like `fe-ai-tools@fe-vibe`; `vibe plugins --update --latest` refreshes). **[C]** Starboard would onboard analogously.

**Confidence:** wrapper model, plugin/MCP commands, rules compilation = **[C]** (Confluence, updated 2026-08). Byte-identical plugin format to Anthropic's, and whether Isaac's injected Databricks OAuth reaches `starboard-helper`'s SDK chain = **[I]/[U]** (open questions I2, I5).

---

## 3. Codex (O5, O7)

### 3.1 `AGENTS.md` (repo root or `~/.codex/AGENTS.md`) — no MCP

```markdown
## Starboard — Databricks analysis

`starboard-helper` is on PATH. Use it to fetch Databricks telemetry as JSON,
then analyze and recommend. Never guess metrics — call the CLI.

- Query perf:   starboard-helper query slow --min-duration-ms 10000 --limit 25
- Job failures: starboard-helper diagnostic run-state --run-id <RUN_ID>
- FinOps:       starboard-helper finops <cmd>
- Discovery:    starboard-helper job list | cluster list | warehouse list | uc catalogs

Auth via the Databricks unified chain (DATABRICKS_HOST/TOKEN or ~/.databrickscfg).
Exit codes: 1=auth, 2=not-found, 3=api-error.
```

`/init` generates `AGENTS.md`; precedence spans `~/.codex/AGENTS.md` + repo root. **[C]** (learn.chatgpt.com/docs/codex/cli). Under Isaac this content can be emitted by `.isaac/rules/`. **[C]**

### 3.2 Custom prompt → slash command (`~/.codex/prompts/starboard-triage.md`)

```markdown
Analyze the Databricks workspace for the user's request: $ARGUMENTS

Steps:
1. Run `starboard-helper job list --limit 100` and `warehouse list`.
2. For any failing job, `starboard-helper diagnostic run-state --run-id <id>`.
3. Summarize health, root causes, and prioritized recommendations.
```

Invoked as `/starboard-triage <args>`, `$ARGUMENTS` substitution. **[C]**

### 3.3 `~/.codex/config.toml` — optional MCP (O7)

```toml
[mcp_servers.starboard]
command = "starboard-mcp"
args = ["--transport", "stdio"]

[profiles.databricks]
model = "gpt-5.4"
# starboard MCP enabled by default in this profile
```

`[mcp_servers.NAME]` (stdio + HTTP) and `[profiles.NAME]` verified. **[C]** Codex also supports **skills** ("package repeatable instructions as skills") — format less documented; **verify before building** (open question X1, **[U]**). Non-interactive: `codex exec "..."` for CI. **[C]**

---

## 4. OpenCode (O6, O7)

### 4.1 Custom tool `.opencode/tool/starboard.ts` — no MCP

```typescript
import { tool } from "@opencode-ai/plugin"
import { z } from "zod"
import { $ } from "bun"

export default tool({
  description: "Fetch Databricks telemetry via the Starboard CLI (returns JSON).",
  args: {
    domain: z.enum(["query","job","warehouse","uc","cluster","finops","diagnostic"]),
    command: z.string().describe("subcommand, e.g. 'slow' or 'run-state'"),
    flags: z.array(z.string()).optional().describe("e.g. ['--limit','25']"),
  },
  async execute(args) {
    const res = await $`starboard-helper ${args.domain} ${args.command} ${args.flags ?? []}`
    return res.stdout.toString()
  },
})
```

`import { tool } from "@opencode-ai/plugin"`, zod args, Bun `$` shell-out verified against repo examples. **[C]** (opencode.ai/docs/custom-tools).

### 4.2 Subagent `.opencode/agent/databricks-expert.md`

```markdown
---
mode: subagent
description: Databricks workspace analysis specialist (Starboard)
permission:
  starboard: allow
---
You are a Databricks analysis expert. Use the `starboard` tool to gather
telemetry as JSON, then diagnose and recommend. Cite metrics from tool output.
```

Frontmatter (`mode: subagent|primary|all`, `permission`, `model`, `description`) verified. **[C]** (opencode.ai/docs/agents).

### 4.3 `opencode.jsonc` wiring + optional MCP (O7)

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "permission": { "starboard": "allow" },
  "instructions": ["AGENTS.md"],
  // Optional MCP superset path:
  "mcp": {
    "starboard": { "type": "local", "command": ["starboard-mcp","--transport","stdio"], "enabled": false }
  }
}
```

`mcp` local/remote, `permission`, `instructions` verified. **[C]** (opencode.ai/docs/mcp-servers, /permissions, /rules). OpenCode also supports `SKILL.md` skills under `.opencode/skills/` **[C]** — the skill bodies can be shared with Claude Code (same Agent Skills standard), but files must be placed in OpenCode's layout (no automatic plugin carryover). Isaac launches it via `isaac opencode` with AI-Gateway model config. **[C]**

---

## 5. Genie integration

### 5.1 Consume Genie (O8) — call flow

**REST** (verified paths, docs.databricks.com Genie Conversation API, updated 2026-08-20) **[C]**:

```
POST /api/2.0/genie/spaces/{space_id}/start-conversation          {content}
     → {conversation_id, message_id, status}
GET  /api/2.0/genie/spaces/{space_id}/conversations/{cid}/messages/{mid}
     → poll until status == COMPLETED  (IN_PROGRESS|PENDING_WAREHOUSE|EXECUTING_QUERY|COMPLETED|FAILED|CANCELLED)
     → attachments[].query (generated SQL) + text description
GET  .../messages/{mid}/query-result/{attachment_id}
     → statement_response (result rows)
```

**Python SDK** (verified, databricks-sdk-py GenieAPI) **[C]** — the shape a `starboard-helper genie ask` subcommand would use:

```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
msg = w.genie.start_conversation_and_wait(space_id=SPACE, content=question)
for att in msg.attachments or []:
    if att.query:                      # generated SQL + description
        sql = att.query.query
        result = w.genie.get_message_attachment_query_result(
            space_id=SPACE, conversation_id=msg.conversation_id,
            message_id=msg.id, attachment_id=att.attachment_id)
# Starboard then validates/optimizes `sql` and reasons over `result`.
```

Auth: OAuth U2M/M2M; requires `CAN USE` on a pro/serverless SQL warehouse + `CAN RUN` on the space. **[C]** Follow-ups reuse `create_message_and_wait(space_id, conversation_id, content)`.

### 5.2 Expose Starboard in Genie (O9)

`w.genie.create_space(warehouse_id, serialized_space, title, description)` / `update_space(...)` provision a curated "Starboard" space seeded from the discovery query-packs (`discovery/query_packs/*.py`: billing, jobs, query_performance, compute, governance, …) as sample queries/instructions. **[C]** method exists; `serialized_space` schema is under-documented **[U]** (open question G3).

---

## 6. Dual-mode mapping across hosts

| Host | No-MCP surface | Skill support | Optional MCP | Isaac-reachable |
|------|----------------|---------------|--------------|-----------------|
| Claude Code | plugin `skills` + `commands` → `starboard-helper` | native SKILL.md **[C]** | plugin `.mcp.json` + `userConfig` **[C]** | `isaac --claude` **[C]** |
| Codex | `AGENTS.md` + `~/.codex/prompts/*` → CLI | Codex skills (format **[U]**) | `[mcp_servers.starboard]` **[C]** | `isaac codex` **[C]** |
| OpenCode | custom `tool()` + agent → CLI | `.opencode/skills/SKILL.md` **[C]** | `mcp.starboard` local **[C]** | `isaac opencode` **[C]** |
| Genie | n/a (is a data source) | n/a | n/a (native REST) | via SDK |

**Design invariant:** all four host surfaces converge on `starboard-helper` (no-MCP) or `starboard-mcp` (opt-in). Build the CLI contract once; adapt thin per-host wrappers.

---

## 7. Build sequence (technical)

1. Consolidate canonical skills (resolve `starboard-skills/skills` vs `starboard/skills` duplication), rename `skill.md`→`SKILL.md`, add standard frontmatter (§1.4).
2. Add `--format json`, `analyze`/`discovery`/`genie` subcommands to `starboard-helper`.
3. Author `.claude-plugin/plugin.json` (skills-only) + `marketplace.json`; test `/plugin install`.
4. Add O3 `userConfig` + `.mcp.json` for the optional MCP toggle.
5. Codex: ship `AGENTS.md` snippet + 1–2 `~/.codex/prompts/*.md`.
6. OpenCode: ship `.opencode/tool/starboard.ts` + agent + `opencode.jsonc` snippet.
7. Genie: add `genie ask` subcommand (O8); prototype `create_space` (O9).
8. Isaac: onboard the plugin into the internal marketplace; add `.isaac/rules/` guidance.

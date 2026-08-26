# Starboard Decomposition — Technical Architecture

> Proposed target layout, per-unit packaging, dependency graph, and the composition/meta-bundle
> design. Manifest field names for Claude Code plugin/marketplace/skill formats are cross-checked
> with the `agent_integration` topic; `§6` flags anything to re-verify against current docs.

---

## 1. Target repository layout

Keep the single uv workspace (`pyproject.toml:[tool.uv.workspace]`) — decomposition is about
**re-cutting distributables**, not splitting repos. Proposed tree:

```
job-agent/                                  # one repo, one uv.lock
├── packages/
│   ├── starboard-kernel/                   # Tier 0 — pure, pydantic+polars only
│   │   └── starboard_kernel/
│   │       ├── models/        transformers/        # from starboard-core/domain/models
│   │       ├── analyzers/     # warehouse, uc, exit_code, sql_validate, dataframe_profile
│   │       └── prompts/       # versioned templates
│   ├── starboard-sparklog/                 # Tier 1 — standalone product
│   │   └── starboard_sparklog/
│   │       ├── parsing/       # event_log_parser, job/stage/task/dag models (pure)
│   │       └── loaders/       # dbfs, s3, https, local  → optional extras
│   ├── starboard-charts/                   # Tier 1 — Vega-Lite → PNG/SVG
│   ├── starboard-diagnostics/              # Tier 1 — triager, profile-extractor, pattern-matcher
│   ├── starboard-discovery/                # Tier 1 — query_packs (data) + heuristics + engine
│   ├── starboard-databricks/               # Tier 1 — I/O fetchers (SDK boundary)
│   ├── starboard-agents/                   # Tier 2 — runtime + 8 domain agents
│   ├── starboard-mcp/                       # Tier 2 — FastMCP surface (composes Tier-1 MCP tools)
│   ├── starboard-cli/                       # Tier 2 — umbrella CLI
│   └── starboard/                           # Tier 2 — meta wheel (deps only, back-compat)
├── skills/                                  # CANONICAL skill source (one copy!)
│   └── starboard/<domain>/SKILL.md
├── plugin/                                  # Claude Code plugin that vendors skills/ + agents/
│   └── .claude-plugin/plugin.json
└── .claude-plugin/marketplace.json          # marketplace listing (repo root)
```

**Skill de-duplication mechanism:** `skills/` is the *only* hand-edited copy. Both the
`starboard-mcp`/meta wheel (via a hatch build hook that copies `skills/` into the wheel) and the
plugin (via a symlink or build-time copy of `skills/` into `plugin/skills/`) consume it. The
current `packages/starboard-skills/skills/starboard/*/skill.md` tree is deleted; the
`starboard-helper` CLI folds into `starboard-cli`. This removes the divergence proven by
`diff -rq skills/starboard packages/starboard-skills/skills/starboard`.

## 2. Dependency graph (strictly downward)

```
                         ┌───────────────────────────────────────┐
Tier 2 (experiences)     │ starboard (meta) │ starboard-mcp │ CLI │
                         │        starboard-agents (+runtime)      │
                         └───┬───────────┬───────────┬────────────┘
                             │           │           │
Tier 1 (capabilities)  ┌─────▼───┐ ┌─────▼────┐ ┌────▼─────────┐ ┌──────────────┐
                       │ sparklog│ │ charts   │ │ diagnostics  │ │ discovery    │
                       └─────┬───┘ └─────┬────┘ └────┬─────────┘ └────┬─────────┘
                             │           │           │                │
                       ┌─────▼───────────▼───────────▼────────────────▼───┐
                       │ starboard-databricks (I/O)   (only where needed)  │
                       └───────────────────────┬──────────────────────────┘
                                                │
Tier 0                                   ┌──────▼───────┐
                                         │ starboard-kernel │  (pydantic, polars)
                                         └──────────────┘
```

Rules enforced in CI (import-linter or a simple AST check):
- `starboard-kernel` **must not** import `databricks-sdk`, `openai`, `fastapi`, `mcp`.
- Tier-1 pure packages (`charts`, `diagnostics`, `discovery[data_only]`) **must not** import `databricks-sdk`.
- All SDK/auth/network I/O lives in `starboard-databricks` or sparklog's `[loaders]` extras.

## 3. Per-unit packaging

### 3a. Tier-0 kernel — `pyproject.toml`
```toml
[project]
name = "starboard-kernel"
version = "0.2.0"
requires-python = ">=3.12"
dependencies = ["pydantic>=2.0,<3.0"]

[project.optional-dependencies]
frames = ["polars>=1.17,<2.0"]   # analyzers that need dataframes

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 3b. Tier-1 capability with CLI + MCP tool — `starboard-diagnostics`
```toml
[project]
name = "starboard-diagnostics"
version = "0.1.0"
dependencies = ["starboard-kernel>=0.2,<0.3"]

[project.optional-dependencies]
mcp = ["mcp>=1.19,<2.0"]          # only when exposing the MCP-tool surface

[project.scripts]
starboard-triage = "starboard_diagnostics.cli:main"      # exit-code-triager CLI
starboard-qprofile = "starboard_diagnostics.cli:qprofile" # query-profile-extractor CLI

[project.entry-points."starboard.mcp_tools"]             # discovered by the meta MCP server
exit_code_triager   = "starboard_diagnostics.mcp:exit_code_triager"
query_profile       = "starboard_diagnostics.mcp:query_profile_extractor"
```
The `starboard.mcp_tools` **entry-point group** is the composition seam: the meta `starboard-mcp`
server enumerates this group at startup and registers every advertised tool — replacing today's
hard-coded `ALL_TOOL_METADATA` (`agents/tools/registry.py:84`) with plugin-style discovery.

### 3c. Standalone product with I/O extras — `starboard-sparklog`
```toml
[project]
name = "starboard-sparklog"
version = "0.1.0"
dependencies = ["starboard-kernel>=0.2,<0.3"]

[project.optional-dependencies]
s3    = ["boto3>=1.34"]
dbfs  = ["databricks-sdk>=0.73,<1.0"]
https = ["httpx>=0.28,<1.0"]
all   = ["starboard-sparklog[s3,dbfs,https]"]

[project.scripts]
starboard-sparklog = "starboard_sparklog.cli:main"   # parse a log file/URI → JSON
```
`pip install starboard-sparklog` gives a **pure parser**; cloud fetch is opt-in. This resolves the
open question about loader placement (open_questions §7) in favor of keeping parse-vs-fetch separable.

### 3d. Subagent file — `plugin/agents/starboard-diagnostic.md`
```markdown
---
name: starboard-diagnostic
description: Root-cause a failed Databricks job/run. Use for run failures, cluster errors, OOM, exit codes, stack traces.
tools: Bash, Read, Grep      # or MCP tools when the server is present
model: sonnet
---
You are Starboard's diagnostic specialist. Given a run_id or cluster_id, fetch evidence
via `starboard-triage`/`starboard-qprofile` (or `mcp__starboard__*` when available),
then produce a root-cause report: health assessment → error events → hypotheses → remediation.
```

### 3e. Canonical skill — `skills/starboard/starboard-diagnostic/SKILL.md`
Fixes the current unfenced-frontmatter bug (every `skills/starboard/*/SKILL.md` today starts with a
bare `name:` line — no `---`):
```markdown
---
name: starboard-diagnostic
description: Run diagnostics on Databricks components — run states, cluster logs, node types, exit codes. Triggers on failed run, cluster error, OOM, exit code, RCA.
allowed-tools: Bash, Read, mcp__starboard__diagnostic_agent
---

# Starboard: Diagnostic Analysis
## Dual-Mode Behavior
If `mcp__starboard__*` tools are present → use the agent path.
Else → `starboard-triage --exit-code <N>` / `starboard-qprofile --statement-id <ID>` (Tier-1 CLIs).
... (body unchanged from today's dual-mode content)
```

## 4. Composition / meta-bundle design

### 4a. Plugin manifest — `plugin/.claude-plugin/plugin.json`
```json
{
  "name": "starboard",
  "version": "0.2.0",
  "description": "AI-powered Databricks workload analysis — agents, skills, and an MCP server",
  "author": { "name": "Databricks" },
  "license": "Databricks Open Model License",
  "keywords": ["databricks", "spark", "finops", "unity-catalog", "diagnostics"],
  "commands": "./commands",
  "agents": "./agents",
  "skills": "./skills",
  "mcpServers": "./.mcp.json"
}
```

### 4b. Bundled MCP server — `plugin/.mcp.json` (mirrors today's `.mcp.json`)
```json
{
  "mcpServers": {
    "starboard": {
      "command": "starboard-mcp",
      "args": ["--transport", "stdio", "--bundle", "all"],
      "timeout": 900
    }
  }
}
```
`--bundle` is new: it selects a named subset of the `starboard.mcp_tools` entry-point group, so the
same server binary can expose *just diagnostics* or *the full 45-tool surface* — formalizing the
existing `tool_scope` mechanism (`mcp/server.py:352`, `tool_bridge.py:114`).

### 4c. Marketplace — `.claude-plugin/marketplace.json`
```json
{
  "name": "starboard-marketplace",
  "owner": { "name": "Databricks" },
  "plugins": [
    { "name": "starboard",             "source": "./plugin",
      "description": "Full Starboard: 8 domain agents + 10 skills + MCP server" },
    { "name": "starboard-diagnostics", "source": "./plugin-diagnostics",
      "description": "Just RCA: diagnostic agent + skill + triager/profile MCP tools" },
    { "name": "starboard-finops",      "source": "./plugin-finops",
      "description": "Just cost analytics: analytics agent + finops skill" }
  ]
}
```
Installed with `/plugin marketplace add <git-url-or-path>` then `/plugin install starboard@starboard-marketplace`. Single-domain plugins let a user consume one capability (recommendation §5, success criterion 4).

### 4d. Runtime composition (the "meta" wiring)
```
User → Claude Code / Isaac
        ├─ picks up skills/  (thin orchestration, dual-mode)
        ├─ picks up agents/  (subagents)
        └─ starts starboard-mcp (stdio)
                 └─ StarboardMCPServer.configure(tool_registry, agent_factory)  # mcp/server.py:234
                       ├─ enumerates entry-point group starboard.mcp_tools  → Tier-1 tools
                       ├─ registers *_agent tools from starboard-agents      # agent_bridge.py:149
                       └─ loads service_catalog.yaml (P14) for cross-domain handoff
```
The `MultiAgentConversationManager` (R2) + `IntentRouter` (L9) become an **optional coordinator**:
present in the meta bundle, absent in single-domain plugins where the one agent is entered directly.

## 5. Migration path (non-breaking)

1. Introduce `starboard-kernel`; make `starboard-core` re-export from it (`from starboard_kernel.models import *`) — zero downstream churn.
2. Add entry-point groups to existing packages *before* splitting — the meta MCP server switches from `ALL_TOOL_METADATA` to entry-point discovery while behavior is identical (golden tool-list test).
3. Split Tier-1 packages one at a time; each old import path kept alive via re-export shims.
4. Collapse skills to `skills/`; `packages/starboard-skills` becomes a thin re-export + deprecation notice.
5. Publish plugin + marketplace last, once wheels are stable.

## 6. Format specifics (confirmed conventions)

The manifests above follow the standard Claude Code plugin/skill/marketplace conventions. Key
points that make the design realistic (the `agent_integration` topic owns the authoritative
format spec; re-confirm against current docs at implementation time):

- **`plugin.json`** lives at `.claude-plugin/plugin.json`. Only `name` is required; `version`,
  `description`, `author` (string or `{name,email,url}`), `homepage`, `repository`, `license`,
  `keywords` are optional. Crucially, **components are auto-discovered from convention
  directories** — `commands/`, `agents/`, `skills/` (each `<name>/SKILL.md`), `hooks/hooks.json`,
  and `.mcp.json` are picked up **without** being listed. The `commands`/`agents`/`hooks`/
  `mcpServers` keys are *optional overrides* to point at additional/non-standard locations, and
  accept a path string or an array of paths. **Implication for us:** the `plugin.json` in §4a can
  be reduced to `{name, version, description, author, license, keywords}` — the `skills/`,
  `agents/`, `commands/`, and `.mcp.json` are found by convention. This makes the plugin the
  cleanest surface for the de-duplicated `skills/` tree.
- **`marketplace.json`** lives at `.claude-plugin/marketplace.json`: `name`, `owner`
  (`{name, email?, url?}`), and a `plugins[]` array. Each entry has `name`, `source`, and
  `description`; `source` accepts a **relative path** (`"./plugin"`), a `{source:"github",
  repo:"owner/repo"}` object, or a `{source:"git", url:"…"}` object. A marketplace **is** a git
  repo; users add it with `/plugin marketplace add <owner/repo | git-url | local-path>` then
  `/plugin install <name>@<marketplace>`. Our §4c form is valid.
- **`SKILL.md`** must be named `SKILL.md` (uppercase) with a **`---`-fenced YAML frontmatter**;
  `name` and `description` are required, `allowed-tools` (hyphenated) is optional. This confirms
  the two current bugs (bare `name:` with no fence in `skills/`; lowercase `skill.md` with no
  frontmatter in the package copy) — both must be fixed to §3e's form. Discovery precedence:
  plugin `skills/` and project `.claude/skills/` and personal `~/.claude/skills/` are all scanned.
- **Subagent `.md`** frontmatter: `name`, `description` (required-ish), optional `tools`
  (comma-separated string) and `model` (accepts aliases `sonnet`/`opus`/`haiku` or `inherit`).
  §3d is valid.
- **MCP** (`.mcp.json` or a `mcpServers` object): stdio form `{command, args, env}` (our §4b),
  or remote form `{type:"http"|"sse", url}`. Both supported.

The net effect of the auto-discovery rule is that **the plugin needs almost no manifest wiring** —
dropping the de-duplicated `skills/`, the `agents/*.md`, and `.mcp.json` into the plugin dir is
sufficient, which is exactly what makes "one canonical skill source, consumed by both wheel and
plugin" (recommendation §2) low-effort.

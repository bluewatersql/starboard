---
schema: starboard-ruleset/1
domain: discovery
title: "Starboard: Discovery Agent Rules"
skill: starboard-discovery
mcp_agent: mcp__starboard__run_discovery_queries
triggers: ["discovery", "inventory", "workspace", "explore", "audit"]
generated: true
source: packages/starboard-skills/skills/starboard/starboard-discovery/SKILL.md
---

# Starboard: Discovery Agent Rules

> **Scope:** Discover and map a Databricks workspace — enumerate jobs, clusters, warehouses, and Unity Catalog assets to build a comprehensive inventory. Use when the user wants a workspace inventory, a health assessment, or to explore what exists in a workspace.
>
> Dollar figures are **list-price DBU estimates** — always label them as such.

## When to use

Discover and map a Databricks workspace — enumerate jobs, clusters, warehouses, and Unity Catalog assets to build a comprehensive inventory. Use when the user wants a workspace inventory, a health assessment, or to explore what exists in a workspace.

## Tool guidance

Prefer the highest available tier. Check in order: Tier-2 → Tier-1 → Tier-0.

### Tier-2 — MCP agent (preferred)

If `mcp__starboard__*` tools are available in your context:

Use `mcp__starboard__run_discovery_queries` for deterministic query data only.
**Do NOT** call `start_discovery_analysis`, `get_discovery_analysis_progress`, or
`synthesize_discovery_report` — those invoke a second server-side LLM.
Take the returned data and synthesize the inventory yourself.

### Tier-1 — bundled helper

If `${CLAUDE_SKILL_DIR}/scripts/run.sh` exists, use the bundled pure analyzer (no network, pre-approved — no permission prompt):

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh run --data-only
${CLAUDE_SKILL_DIR}/scripts/run.sh run --data-only --packs finops_billing jobs
```

### Tier-0 — raw fetch via `starboard-helper`

See the skill body for raw fetch commands.

## Domain heuristics

- **Jobs**: Count, names, schedule patterns, cluster attachment types
- **Clusters**: Running vs. terminated, job-attached vs. interactive
- **Warehouses**: Types (classic/serverless), sizes, states
- **Data**: Catalog hierarchy, number of schemas and tables

## Success criteria

A complete analysis for this domain must include:

1. **Workspace summary**: Counts of each resource type
2. **Jobs inventory**: Scheduled vs. manual, production vs. development indicators
3. **Compute inventory**: Cluster and warehouse utilization snapshot
4. **Data inventory**: Unity Catalog hierarchy overview
5. **Observations**: Notable patterns, potential issues, quick wins
6. **Recommended next steps**: Which domains to analyze in depth

## Ground rules

- **Dollar figures are list-price DBU estimates** — always label them as such.
- **Single workspace by default** — targets the resolved workspace; do not assume fleet/cross-account scope.
- **Auth by subtraction** — rely on the resolved credential chain (`--profile` / `STARBOARD_WORKSPACE` / ambient); never hard-code hosts or tokens.
- **Read-only advisory** — Starboard analyzes and recommends; it does not modify the workspace.
- **Exit codes** — `0` ok · `1` auth error · `2` not found · `3` API error · `4` arg error.
- Present findings **highest-priority first** with their evidence (`query_id` + row).

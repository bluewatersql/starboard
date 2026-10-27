---
schema: starboard-ruleset/1
domain: warehouse
title: "Starboard: Warehouse Agent Rules"
skill: starboard-warehouse
mcp_agent: mcp__starboard__warehouse_agent
triggers: ["warehouse", "sql warehouse", "autostop", "cluster_size", "serverless"]
generated: true
source: packages/starboard-skills/skills/starboard/starboard-warehouse/SKILL.md
---

# Starboard: Warehouse Agent Rules

> **Scope:** Analyze Databricks SQL warehouses — inspect configuration, monitor state, and identify sizing and cost issues. Use when the user asks about SQL warehouse configuration, warehouse sizing, autostop, or warehouse cost and performance.
>
> Dollar figures are **list-price DBU estimates** — always label them as such.

## When to use

Analyze Databricks SQL warehouses — inspect configuration, monitor state, and identify sizing and cost issues. Use when the user asks about SQL warehouse configuration, warehouse sizing, autostop, or warehouse cost and performance.

## Tool guidance

Prefer the highest available tier. Check in order: Tier-2 → Tier-1 → Tier-0.

### Tier-2 — MCP agent (preferred)

If `mcp__starboard__*` tools are available in your context:

Dispatch directly to `mcp__starboard__warehouse_agent`.
The full agent stack handles orchestration, analysis, and recommendations.
Return the agent response directly.

### Tier-1 — bundled helper

Not available for this domain — proceed to Tier-0.

### Tier-0 — raw fetch via `starboard-helper`

See the skill body for raw fetch commands.

## Domain heuristics

Apply domain expertise when reviewing the structured JSON output.

## Success criteria

A complete analysis for this domain must include:

Produce a structured, prioritized analysis with actionable recommendations.

## Ground rules

- **Dollar figures are list-price DBU estimates** — always label them as such.
- **Single workspace by default** — targets the resolved workspace; do not assume fleet/cross-account scope.
- **Auth by subtraction** — rely on the resolved credential chain (`--profile` / `STARBOARD_WORKSPACE` / ambient); never hard-code hosts or tokens.
- **Read-only advisory** — Starboard analyzes and recommends; it does not modify the workspace.
- **Exit codes** — `0` ok · `1` auth error · `2` not found · `3` API error · `4` arg error.
- Present findings **highest-priority first** with their evidence (`query_id` + row).

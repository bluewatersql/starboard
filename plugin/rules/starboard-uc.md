---
schema: starboard-ruleset/1
domain: uc
title: "Starboard: UC Agent Rules"
skill: starboard-uc
mcp_agent: mcp__starboard__uc_agent
triggers: ["unity catalog", "catalog", "schema", "lineage", "governance", "table"]
generated: true
source: packages/starboard-skills/skills/starboard/starboard-uc/SKILL.md
---

# Starboard: UC Agent Rules

> **Scope:** Analyze Unity Catalog metadata and governance — explore catalogs, schemas, tables, lineage, and governance posture. Use when the user asks about Unity Catalog, data governance, catalog/schema/table structure, or data lineage.
>
> Dollar figures are **list-price DBU estimates** — always label them as such.

## When to use

Analyze Unity Catalog metadata and governance — explore catalogs, schemas, tables, lineage, and governance posture. Use when the user asks about Unity Catalog, data governance, catalog/schema/table structure, or data lineage.

## Tool guidance

Prefer the highest available tier. Check in order: Tier-2 → Tier-1 → Tier-0.

### Tier-2 — MCP agent (preferred)

If `mcp__starboard__*` tools are available in your context:

Dispatch directly to `mcp__starboard__uc_agent`.
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

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

If `${CLAUDE_SKILL_DIR}/scripts/run.sh` exists, use the bundled pure analyzer (no network, pre-approved — no permission prompt):

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh analyze --input <table.json>
```

### Tier-0 — raw fetch via `starboard-helper`

```bash
starboard-helper uc catalogs
starboard-helper uc schemas --catalog <CATALOG>
starboard-helper uc tables --catalog <CATALOG> --schema <SCHEMA>
starboard-helper uc table --full-name <CATALOG>.<SCHEMA>.<TABLE>
starboard-helper uc lineage --full-name <CATALOG>.<SCHEMA>.<TABLE>
```

## Domain heuristics

- **Governance**: Do tables have owners and comments? Missing metadata is a governance gap.
- **Lineage**: Are there orphaned tables (no upstream/downstream)? Potential dead data.
- **Table types**: Are MANAGED vs EXTERNAL tables used appropriately?
- **Data formats**: Are legacy formats (CSV, JSON) used where Delta would be better?
- **Access patterns**: Are schemas organized logically (bronze/silver/gold or domain-based)?

## Success criteria

A complete analysis for this domain must include:

1. Catalog/schema overview and health
2. Governance gaps (missing owners, comments, tags)
3. Data organization recommendations
4. Lineage observations
5. Priority: critical / high / medium / low

## Ground rules

- **Dollar figures are list-price DBU estimates** — always label them as such.
- **Single workspace by default** — targets the resolved workspace; do not assume fleet/cross-account scope.
- **Auth by subtraction** — rely on the resolved credential chain (`--profile` / `STARBOARD_WORKSPACE` / ambient); never hard-code hosts or tokens.
- **Read-only advisory** — Starboard analyzes and recommends; it does not modify the workspace.
- **Exit codes** — `0` ok · `1` auth error · `2` not found · `3` API error · `4` arg error.
- Present findings **highest-priority first** with their evidence (`query_id` + row).

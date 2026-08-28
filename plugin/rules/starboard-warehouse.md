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

If `${CLAUDE_SKILL_DIR}/scripts/run.sh` exists, use the bundled pure analyzer (no network, pre-approved — no permission prompt):

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh analyze --history <history.json> [--warehouse-id <ID>]
```

### Tier-0 — raw fetch via `starboard-helper`

```bash
starboard-helper warehouse list
starboard-helper warehouse fetch --warehouse-id <WH_ID>
starboard-helper warehouse metrics --warehouse-id <WH_ID>
```

## Domain heuristics

- **Sizing**: Is `cluster_size` appropriate for the active session count?
- **Scaling**: Is `max_num_clusters` unnecessarily high, driving cost?
- **Auto-stop**: Is `auto_stop_mins` configured too high (idle cost)?
- **Type**: Should classic warehouses be migrated to serverless for variable workloads?
- **Health**: Are there any health warnings or errors?

## Success criteria

A complete analysis for this domain must include:

1. Summary of warehouse fleet health
2. Rightsizing recommendations per warehouse
3. Cost optimization opportunities (auto-stop, serverless migration)
4. Priority: critical / high / medium / low

## Ground rules

- **Dollar figures are list-price DBU estimates** — always label them as such.
- **Single workspace by default** — targets the resolved workspace; do not assume fleet/cross-account scope.
- **Auth by subtraction** — rely on the resolved credential chain (`--profile` / `STARBOARD_WORKSPACE` / ambient); never hard-code hosts or tokens.
- **Read-only advisory** — Starboard analyzes and recommends; it does not modify the workspace.
- **Exit codes** — `0` ok · `1` auth error · `2` not found · `3` API error · `4` arg error.
- Present findings **highest-priority first** with their evidence (`query_id` + row).

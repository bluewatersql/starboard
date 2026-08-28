---
schema: starboard-ruleset/1
domain: cluster
title: "Starboard: Cluster Agent Rules"
skill: starboard-cluster
mcp_agent: mcp__starboard__cluster_agent
triggers: ["cluster", "autoscale", "node", "compute", "oom", "node lost"]
generated: true
source: packages/starboard-skills/skills/starboard/starboard-cluster/SKILL.md
---

# Starboard: Cluster Agent Rules

> **Scope:** Analyze Databricks clusters — inspect configuration, review events, diagnose failures, and recommend optimizations. Use when the user asks about cluster performance, autoscaling, node types, cluster failures, or compute sizing.
>
> Dollar figures are **list-price DBU estimates** — always label them as such.

## When to use

Analyze Databricks clusters — inspect configuration, review events, diagnose failures, and recommend optimizations. Use when the user asks about cluster performance, autoscaling, node types, cluster failures, or compute sizing.

## Tool guidance

Prefer the highest available tier. Check in order: Tier-2 → Tier-1 → Tier-0.

### Tier-2 — MCP agent (preferred)

If `mcp__starboard__*` tools are available in your context:

Dispatch directly to `mcp__starboard__cluster_agent`.
The full agent stack handles orchestration, analysis, and recommendations.
Return the agent response directly.

### Tier-1 — bundled helper

Not available for this domain — proceed to Tier-0.

### Tier-0 — raw fetch via `starboard-helper`

```bash
starboard-helper cluster list
starboard-helper cluster list --filter-by-state RUNNING
starboard-helper cluster fetch --cluster-id <CLUSTER_ID>
starboard-helper cluster events --cluster-id <CLUSTER_ID> --limit 50
starboard-helper cluster spark-context --cluster-id <CLUSTER_ID>
```

## Domain heuristics

- **Sizing**: Is the node type and worker count appropriate for the workload?
- **Autoscaling**: Is autoscale configured and within appropriate min/max bounds?
- **Events**: Are there recurring error events (OOM, node lost, preemption)?
- **Spark config**: Are there performance-relevant configs set (shuffle partitions, memory fractions)?
- **Lifespan**: Are long-running clusters accumulating state or should they be ephemeral?
- **Source**: Are clusters created interactively (risk) vs. job-attached (preferred for production)?

## Success criteria

A complete analysis for this domain must include:

1. Cluster fleet overview
2. Rightsizing recommendations
3. Event-based failure diagnosis
4. Spark configuration tuning suggestions
5. Priority: critical / high / medium / low

## Ground rules

- **Dollar figures are list-price DBU estimates** — always label them as such.
- **Single workspace by default** — targets the resolved workspace; do not assume fleet/cross-account scope.
- **Auth by subtraction** — rely on the resolved credential chain (`--profile` / `STARBOARD_WORKSPACE` / ambient); never hard-code hosts or tokens.
- **Read-only advisory** — Starboard analyzes and recommends; it does not modify the workspace.
- **Exit codes** — `0` ok · `1` auth error · `2` not found · `3` API error · `4` arg error.
- Present findings **highest-priority first** with their evidence (`query_id` + row).

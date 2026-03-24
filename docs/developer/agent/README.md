---
title: Agent Developer Documentation
description: Index page for agent development documentation.
last_reviewed: 2026-03-24
status: current
---

# Agent Developer Documentation

> **Docs** > **Developer** > **Agent Development**

> Complete guide for developing domain-specialized AI agents

## Documents

| Document | Purpose |
|----------|---------|
| [IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md) | **Start here** -- Complete guide for creating new domain agents |
| [REPORT_UI_GUIDELINES.md](./REPORT_UI_GUIDELINES.md) | Guidelines for agent UI report types and rendering |

## Quick Start: New Agent

Creating a new domain agent requires these steps:

1. **Define Domain Identity** -- Add to `AgentDomain` type literals
2. **Create System Prompt** -- `prompts/{domain}/v1.py` with standard sections
3. **Add Handoff Context** -- Use shared components from `prompts/shared/`
4. **Register Prompt Builder** -- Add to `prompts/factories.py`
5. **Configure Tools** -- Add to `TOOL_CATEGORIES` in `tool_categories.py`
6. **Add Routing Rules** -- Update `IntentRouter` patterns
7. **Register Tool Display Config** -- Update `tool_display.py`
8. **Write Tests** -- Golden tests, routing tests, integration tests

See [IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md) for complete details.

---

## Current Domain Agents

| Domain | Purpose | Tools | Report Type |
|--------|---------|-------|-------------|
| `router` | Intent classification | 3 | N/A |
| `query` | SQL optimization | 8 | `advisor` |
| `job` | Job/workflow optimization | 14 | `advisor` |
| `uc` | Unity Catalog governance | 18 | `advisor` |
| `cluster` | Cluster configuration and health | 8 | `compute` |
| `analytics` | FinOps cost analysis (agentic RAG) | 6 | `analytics` |
| `warehouse` | SQL warehouse portfolio optimization | 11 | `compute` |
| `discovery` | Workspace health assessment (4-phase) | 6 | `discovery` |
| `diagnostic` | Troubleshooting and root cause analysis | ALL | `advisor` |

Tool counts sourced from `packages/starboard-server/starboard_server/agents/tool_categories.py`.

---

## Report Type Matrix

| Report Type | Primary UI Components | Use When |
|-------------|----------------------|----------|
| `advisor` | FindingCard, RecommendationCard, CodeBlock | Performance optimization, code fixes |
| `analytics` | CostSummary, ChartVisualization, SavingsCard | Cost analysis, FinOps, chargeback |
| `compute` | PortfolioOverview, HealthGauge, TopologyCard | Resource health, fleet management |
| `discovery` | HealthScore, DomainSummary, PriorityList | Workspace assessment |

### Agent --> Report Type Mapping

| Agent | Default Report Type | Cost-Focused Override |
|-------|--------------------|-----------------------|
| Query | `advisor` | N/A |
| Job | `advisor` | N/A |
| UC | `advisor` | `analytics` |
| Cluster | `compute` | `analytics` |
| Analytics | `analytics` | N/A |
| Warehouse | `compute` | `analytics` |
| Discovery | `discovery` | N/A |
| Diagnostic | `advisor` | N/A |

---

## Key Files

### Backend

| Category | Location | Purpose |
|----------|----------|---------|
| Agent Prompts | `packages/starboard-server/starboard_server/prompts/` | System prompts for each domain |
| Shared Handoff | `packages/starboard-server/starboard_server/prompts/shared/` | Shared handoff context components |
| Report Schemas | `packages/starboard-core/starboard_core/domain/models/` | Pydantic models for report types |
| Report Formatters | `packages/starboard-server/starboard_server/agents/report_formatters/` | Markdown formatters |
| Tool Display Config | `packages/starboard-server/starboard_server/agents/tool_display.py` | Friendly names, thinking steps, UI metadata |
| Tool Categories | `packages/starboard-server/starboard_server/agents/tool_categories.py` | Domain --> tool mappings |

### Frontend

| Category | Location | Purpose |
|----------|----------|---------|
| TypeScript Types | `frontend/lib/types/api.ts` | Report interfaces |
| Report Router | `frontend/components/chat/ReportBubble.tsx` | Report type switching |
| Report Bubbles | `frontend/components/chat/reports/` | Report rendering components |

---

## Handoff Context (Agent-to-Agent)

When users navigate between agents, context is passed via the `[Handoff Context]` block. All agents use a standardized section from `prompts/shared/handoff_context.py`.

### Standard Resource IDs

| Field | Singular | Plural |
|-------|----------|--------|
| Query | `statement_id:` | `query_ids:` |
| Job | `job_id:` | `job_ids:` |
| Cluster | `cluster_id:` | `cluster_ids:` |
| Warehouse | `warehouse_id:` | `warehouse_ids:` |
| Table | `table_name:` | `tables:` |
| Context | `Previous analysis summary:` | `From previous agent:` |

### Behavior Rules

1. **If IDs provided --> Start immediately** (do not ask user)
2. **Use EXACTLY provided values** (do not fabricate)
3. **Multiple IDs --> Process in PARALLEL**
4. **Reference previous findings** for continuity

See [IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md#handoff-context) for full details.

---

## Related Documentation

- [Agent Documentation Index](../../agents/README.md) -- All agents overview
- [System Architecture](../../architecture/SYSTEM_ARCHITECTURE.md) -- System design
- [Tool Architecture](../../TOOL_ARCHITECTURE.md) -- Tool system design
- [Frontend Architecture](../../FRONTEND_ARCHITECTURE.md) -- Frontend patterns

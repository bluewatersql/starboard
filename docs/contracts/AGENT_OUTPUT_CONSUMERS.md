# Agent Output Consumers

This document catalogs downstream consumers of the `AgentOutput` / `FinalOutputEvent`
structures, plus the kernel **Workload Review `Finding`** contract. Any change to these
schemas must be coordinated with the listed consumers and contract tests.

**Last Updated:** 2026-08-27
**Related:** `tests/contract/test_agent_output_contract.py` (`make test-contract`)

> **Delivery note:** `FinalOutputEvent` is delivered through the **in-process** event
> stream to the CLI/SDK — it is serialized to JSON but is **not** an HTTP SSE endpoint.
> The "Frontend Consumers" listed below describe an **external / separate** web UI (this
> repository ships no web frontend); the authoritative in-repo consumers are the **CLI**
> and the **contract tests**.

---

## Overview

Agent output flows through this pipeline:

```
DomainAgent.run()
    ↓
AgentOutput (dataclass)
    ↓
FinalOutputEvent.to_sse_data()   # JSON serialization of the event
    ↓
in-process event stream (JSON)
    ↓
CLI / SDK consumers  (external web UI, if any, consumes the same JSON)
```

---

## SSE Output Structure

```json
{
  "message_id": "msg_abc123",
  "output": {
    "status": "success | error | budget_exceeded | max_steps_reached",
    "complete_report": {
      "report_type": "advisor | analytics | compute",
      "summary": { "overview": "..." },
      ...domain-specific fields...
    },
    "next_steps": [
      {
        "id": "step_1",
        "number": 1,
        "title": "Continue analysis",
        "description": "Optional description",
        "action_type": "continue | route | tool_call",
        "target_agent": null,
        "tool_name": null,
        "parameters": null
      }
    ],
    "tokens_used": 1500,
    "cost_usd": 0.025,
    "duration_seconds": 12.5,
    "steps_taken": 5
  },
  "formatted_markdown": "## Report\n..."
}
```

---

## Frontend Consumers

### 1. `components/chat/ReportBubble.tsx`

**Purpose:** Routes to specialized report components based on `report_type`.

**Fields Consumed:**
- `message.metadata.complete_report`
- `complete_report.report_type` (discriminator)
- `complete_report.report` (handles LLM double-wrapping bug)
- `complete_report.next_steps`

**Routing Logic:**
```typescript
switch (report.report_type) {
  case "analytics": return <AnalyticsReportBubble />;
  case "advisor": return <AdvisorReportBubble />;
  case "warehouse": return <WarehouseReportBubble />;
  default: return <MarkdownReportBubble />;
}
```

**Known Defensive Code:**
```typescript
// Handles LLM double-wrapping: { report_type, report: {...} }
if (rawReport.report) {
  return { ...rawReport.report, report_type: rawReport.report_type };
}
```

---

### 2. `components/chat/MessageList.tsx`

**Purpose:** Renders conversation messages with reports and next steps.

**Fields Consumed:**
- `message.metadata.complete_report`
- `message.metadata.tokens_used`
- `message.metadata.cost_usd`
- `message.metadata.duration_seconds`
- `message.metadata.steps_taken`
- `message.next_steps` (after extraction from complete_report)

**SSE Event Handling:**
- Listens for `final_output` event type
- Updates message store with `output` and `formatted_markdown`

---

### 3. `components/chat/reports/AdvisorReportBubble.tsx`

**Purpose:** Renders performance optimization reports.

**Fields Consumed:**
- `report.summary.overview`
- `report.summary.current_state`
- `report.analysis.findings[]`
- `report.analysis.findings[].category`
- `report.analysis.findings[].title`
- `report.analysis.findings[].recommendation`
- `report.analysis.findings[].impact_estimate`
- `report.analysis.findings[].effort`
- `report.data_table` (optional)

**Report Type:** `"advisor"`

---

### 4. `components/chat/reports/AnalyticsReportBubble.tsx`

**Purpose:** Renders FinOps/cost analysis reports.

**Fields Consumed:**
- `report.summary.overview`
- `report.findings[]`
- `report.findings[].category`
- `report.findings[].title`
- `report.findings[].recommendation`
- `report.findings[].cost_impact`
- `report.cost_summary.total_monthly_cost_usd`
- `report.cost_summary.potential_savings_usd`
- `report.visualization` (optional)

**Report Type:** `"analytics"`

---

### 5. `components/chat/reports/WarehouseReportBubble.tsx`

**Purpose:** Renders warehouse analysis reports.

**Fields Consumed:**
- `report.summary.overview`
- `report.portfolio_summary` (optional)
- `report.health_metrics` (optional)
- `report.topology_analysis` (optional)
- `report.warehouses[]` (optional)
- `report.data_table` (optional)

**Report Type:** `"warehouse"`

---

### 6. `components/chat/NextStepsBubble.tsx`

**Purpose:** Renders actionable next step options.

**Fields Consumed:**
- `next_steps[].id`
- `next_steps[].number`
- `next_steps[].title`
- `next_steps[].description`
- `next_steps[].action_type`
- `next_steps[].target_agent`
- `next_steps[].parameters`

**Action Handling:**
- `"continue"`: Send message to current agent
- `"route"`: Hand off to `target_agent`
- `"tool_call"`: Execute `tool_name` with `parameters`

---

### 7. `lib/types/api.ts` / `lib/types/generated-api.ts`

**Purpose:** TypeScript type definitions for API responses.

**Types Defined:**
- `AgentOutput`
- `NextStepOption`
- `AdvisorReport`
- `AnalyticsReport`
- `WarehouseReport`
- `FinalOutputEventData`

**Note:** These should be auto-generated from backend schemas via `scripts/generate_types.py`.

---

## CLI Consumers

### 1. `packages/starboard/starboard/cli/main.py`

**Purpose:** Command-line interface for agent interactions.

**Fields Consumed:**
- `final_output["complete_report"]`
- `final_output["formatted_markdown"]`
- `final_output["output"]["status"]`
- `final_output["output"]["tokens_used"]`
- `final_output["output"]["cost_usd"]`

**Report Formatting:**
```python
if "complete_report" in final_output and final_output["complete_report"]:
    formatted_markdown = format_agent_report(final_output["complete_report"])
```

---

## Backend Internal Consumers

### 1. `agents/domain/output_builder.py`

**Purpose:** Builds `AgentOutput` from agent state.

**Produces:**
- `AgentOutput.complete_report`
- `AgentOutput.next_steps`
- `AgentOutput.status`
- All metric fields

---

### 2. `agents/events/user_events.py` (`FinalOutputEvent`)

**Purpose:** Converts `AgentOutput` to SSE JSON.

**Transform Logic:**
- Extracts `complete_report` from output
- Generates `formatted_markdown` from complete_report
- Serializes `next_steps` to dicts
- Handles malformed structures (summary in wrong location)

---

### 3. `agents/report_formatters/`

**Purpose:** Generates markdown from complete_report.

**Input:** `complete_report` dict
**Output:** Formatted markdown string

---

## Contract Test Coverage

| Consumer | Contract Test File |
|----------|-------------------|
| AgentOutput shape | `tests/contract/test_agent_output_contract.py` |
| SSE output shape | `tests/contract/test_agent_output_contract.py` |
| SSE event fixtures | `tests/contract/backend/fixtures/final_output.json` |
| Frontend types | `tests/contract/test_api_schemas.py` |

---

## Breaking Change Checklist

Before modifying agent output schemas:

1. [ ] Update contract tests in `tests/contract/test_agent_output_contract.py`
2. [ ] Update SSE fixtures in `tests/contract/backend/fixtures/`
3. [ ] Update CLI consumers if structure changes
4. [ ] Run full contract test suite: `make test-contract`
5. [ ] Coordinate version bump if breaking

---

## Status Values

| Status | Meaning | When Emitted |
|--------|---------|--------------|
| `success` | Agent completed successfully | Normal completion |
| `error` | Agent encountered an error | Unrecoverable error |
| `budget_exceeded` | Token budget exhausted | Budget enforcement triggered |
| `max_steps_reached` | Step limit reached | config.max_steps exceeded |

**Note:** Phase 1 of agent-hardening will add `partial` status for validation failures.

---

## Report Types

| report_type | Domains | Frontend Component |
|-------------|---------|-------------------|
| `advisor` | query, job, uc, diagnostic | `AdvisorReportBubble` |
| `analytics` | analytics (FinOps) | `AnalyticsReportBubble` |
| `warehouse` | warehouse | `WarehouseReportBubble` |

---

## Field Optionality

| Field | Required | Notes |
|-------|----------|-------|
| `status` | Yes | Always present |
| `complete_report` | No | Can be null |
| `next_steps` | No | Can be null or empty |
| `formatted_markdown` | No | Can be null |
| `tokens_used` | Yes | Always present, >= 0 |
| `cost_usd` | Yes | Always present, >= 0 (list-price DBU estimate) |
| `duration_seconds` | Yes | Always present, >= 0 |
| `steps_taken` | Yes | Always present, >= 0 |

---

## Workload Review `Finding` contract

The Workload Review flagship (`starboard review`, `python -m starboard_x.review`) emits a
`WorkloadReview` of `ReviewFinding`s. The kernel-tier `Finding` model
(`starboard_core.domain.models.finding`) is a pure-pydantic contract:

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Stable finding identifier |
| `severity` | `Severity` | `critical` / `high` / `medium` / `low` |
| `category` | `str` | Domain category (query, cluster, uc, warehouse, …) |
| `summary` | `str` | One-line summary |
| `rationale` | `str` | Why it matters |
| `current_state` | `str` | Observed / "bad" state (validation alias `bad`) |
| `suggested_fix` | `str` | Recommended fix (validation alias `good`) |
| `impact` | `int` (1–5) | Impact multiplier |
| `effort` | `Effort` | `XS`/`S`/`M`/`L`/`XL` |
| `confidence` | `Confidence` | `low`/`medium`/`high` (default `medium`) |
| `location` | `Location \| None` | file/line/table/entity reference |
| `rule_id` | `str \| None` | Originating rule id |
| `source` | `str \| None` | **Public** reference only (no internal links) |
| `score` | `float` (computed) | `(severity_weight × impact) / effort_points` |
| `bucket` | `Bucket` (computed) | *Fix Immediately / This Sprint / Backlog / Nice-to-Have* |

**Weights:** severity `{critical:4, high:3, medium:2, low:1}`; effort
`{XS:1, S:2, M:3, L:4, XL:5}`. **Bucket thresholds** (inclusive): ≥20 Fix Immediately,
≥10 This Sprint, ≥4 Backlog, else Nice-to-Have. Findings are ranked deterministically
(`rank_findings`: score desc, severity desc, id asc) and de-duplicated by concrete
`location` (keeping the most severe).

The rule that produces a finding is a `Rule`
(`starboard_core.domain.rules.schema`): `id` / `name` / `category` /
`short_description` / `rationale` / `severity` / `default_effort` / `default_impact` /
`bad` / `good` / `suggested_fix` / `detect` / `evidence_query` / `source` / `enabled`.
`evidence_query` must resolve to a real query-pack `query_id`
(`RuleRegistry.validate_evidence_queries`, dependency-inverted to keep the kernel pure).

> **Governance:** `source` is a public reference or null — never an internal `go/` link.
> All dollar figures are **list-price DBU estimates**.


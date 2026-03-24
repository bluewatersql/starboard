# Agent Report UI Guidelines

> **Version**: 1.1.0  
> **Updated**: December 9, 2025  
> **Scope**: Technical guidelines for creating UI report experiences for agents

---

## Table of Contents

1. [Overview](#overview)
2. [Report Type Selection](#report-type-selection)
3. [Architecture Components](#architecture-components)
4. [Creating a New Report Type](#creating-a-new-report-type)
5. [Using Existing Report Types](#using-existing-report-types)
6. [Schema Design Patterns](#schema-design-patterns)
7. [Frontend Component Patterns](#frontend-component-patterns)
8. [Tool Display Names](#tool-display-names)
9. [Testing Requirements](#testing-requirements)
10. [Checklist](#checklist)

---

## Overview

### What is a Report Type?

A **report type** is a discriminated union that determines how agent output is rendered in the frontend. Each report type has:

1. **Backend Schema** (Pydantic model) - Validates LLM output structure
2. **Backend Formatter** - Converts schema to markdown fallback
3. **Frontend Types** (TypeScript) - Type-safe client-side models
4. **Frontend Component** - React component for rich rendering

### Current Report Types

| Report Type | Purpose | Primary Agents |
|-------------|---------|----------------|
| `advisor` | Performance optimization, findings, code fixes | Query, Job, UC, Diagnostic |
| `analytics` | Cost analysis, savings, charts | Analytics (FinOps) |
| `compute` | Resource health, portfolio metrics, topology | Warehouse, Compute |

### Decision: New Type vs. Existing Type

```
┌─────────────────────────────────────────────────────────────────┐
│                    REPORT TYPE DECISION TREE                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │ Does your agent output fit    │
              │ an existing schema?           │
              └───────────────────────────────┘
                      │             │
                     YES           NO
                      │             │
                      ▼             ▼
              ┌─────────────┐   ┌─────────────────────────────────┐
              │ Use existing│   │ Is the new UI significantly     │
              │ report type │   │ different from existing ones?   │
              └─────────────┘   └─────────────────────────────────┘
                                        │             │
                                       YES           NO
                                        │             │
                                        ▼             ▼
                                ┌─────────────┐   ┌─────────────────────┐
                                │ Create new  │   │ Extend existing     │
                                │ report type │   │ type with optional  │
                                └─────────────┘   │ fields              │
                                                  └─────────────────────┘
```

---

## Report Type Selection

### Use `advisor` When:

- Agent provides **performance findings** with impact/effort estimates
- Agent suggests **code fixes** (SQL rewrites, DDL changes, config changes)
- Agent analyzes **optimization opportunities**
- Output has structured **findings → recommendations** flow

**Example Agents:** Query, Job, UC (default), Diagnostic

**Schema Shape:**
```json
{
  "report_type": "advisor",
  "summary": {
    "overview": "...",
    "current_state": {"cloud_provider": "AWS", "key_symptoms": [...]}
  },
  "analysis": {
    "findings": [
      {
        "id": "finding_001",
        "category": "QUERY|TABLE|CLUSTER|...",
        "title": "...",
        "recommendation": "...",
        "impact_estimate": {"query_time_pct": -40.0, "cost_pct": -20.0, "confidence": "high"},
        "effort": {"level": "low", "estimate_hours": 0.5},
        "fixes": [{"type": "SQL_REWRITE", "snippet": "...", "notes": "..."}],
        "rank": 1
      }
    ],
    "query_rewrite": {"applicable": true, "sql": "...", "notes": "..."}
  },
  "next_steps": [...]
}
```

### Use `analytics` When:

- Agent provides **cost summaries** with totals, means, trends
- Agent identifies **cost savings opportunities**
- Agent performs **cost attribution** (by user, team, resource)
- Output benefits from **chart visualization**

**Example Agents:** Analytics (FinOps), UC (cost-focused), Warehouse (chargeback)

**Schema Shape:**
```json
{
  "report_type": "analytics",
  "summary": {
    "overview": "...",
    "current_state": {"cloud_provider": "AWS", "key_symptoms": [...]}
  },
  "cost_summary": {
    "primary_metric": "total_cost",
    "primary_metric_unit": "USD",
    "total": 45000.00,
    "mean": 1500.00,
    "max": 5000.00,
    "period": "30 days",
    "cost_trend": "increasing",
    "top_contributors": [{"id": "...", "name": "...", "value": 5000, "unit": "USD"}]
  },
  "findings": [
    {
      "id": "finops_001",
      "category": "COST_OPTIMIZATION|WASTE_DETECTION|UTILIZATION|ATTRIBUTION",
      "title": "...",
      "recommendation": "...",
      "cost_impact": {
        "current_monthly_cost": 5000.0,
        "projected_savings_monthly": 1500.0,
        "cost_unit": "dollar",
        "savings_pct": 30.0,
        "confidence": "medium"
      },
      "effort": {"level": "low"},
      "rank": 1
    }
  ],
  "visualization": {
    "recommended_chart": "bar",
    "primary_metric": "total_cost",
    "primary_dimension": "resource_name",
    "data_reference": "cache_key_123",
    "has_visualization": true
  },
  "next_steps": [...]
}
```

### Use `compute` When:

- Agent provides **resource health metrics** (health scores, SLO compliance)
- Agent analyzes **portfolio of resources** (multiple warehouses/clusters)
- Agent performs **topology analysis** (consolidation, similarity)
- Agent tracks **user activity** across compute resources

**Example Agents:** Warehouse, Compute (Cluster)

**Schema Shape:**
```json
{
  "report_type": "compute",
  "summary": {
    "overview": "...",
    "current_state": {"resource_type": "warehouse", "key_symptoms": [...]}
  },
  "portfolio_summary": {
    "total_count": 5,
    "health_distribution": {"healthy": 3, "warning": 1, "critical": 1, "inactive": 0},
    "top_resources": [...]
  },
  "health_metrics": {
    "overall_score": 78,
    "metric_scores": {"latency": 85, "availability": 95, "queue_time": 60, "error_rate": 90},
    "slo_compliance": {"targets_met": 3, "targets_total": 4},
    "risk_factors": [...]
  },
  "topology_analysis": {
    "clusters": [...],
    "consolidation_opportunities": [...]
  },
  "user_activity": {
    "period": "30 days",
    "top_users": [...],
    "allocation_method": "runtime"
  },
  "analysis": {...},  // Optional: advisor-style findings
  "next_steps": [...]
}
```

---

## Architecture Components

### End-to-End Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. AGENT PROMPT                                                          │
│    packages/starboard-server/starboard_server/prompts/{domain}/v1.py     │
│                                                                          │
│    Define output schema in system prompt:                                │
│    - report_type discriminator                                           │
│    - Required sections                                                   │
│    - Next steps format                                                   │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 2. PYDANTIC SCHEMA                                                       │
│    packages/starboard-core/starboard_core/domain/models/                 │
│                                                                          │
│    - llm_schemas.py (existing: advisor models)                           │
│    - compute_schemas.py (compute models)                                 │
│    - {domain}_schemas.py (for new types)                                 │
│                                                                          │
│    Validate LLM output structure, provide defaults, enforce types        │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 3. REPORT FORMATTER                                                      │
│    packages/starboard-server/starboard_server/agents/report_formatters/  │
│                                                                          │
│    - {type}_formatter.py: Implements ReportFormatter protocol            │
│    - registry.py: Register new formatter                                 │
│                                                                          │
│    Generates markdown fallback for non-JS clients / export               │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 4. SSE STREAMING                                                         │
│    packages/starboard-server/starboard_server/agents/                    │
│                                                                          │
│    - domain/domain_agent.py: complete tool unwrapping                    │
│    - conversation/multi_agent_manager.py: attach complete_report         │
│    - events/user_events.py: FinalOutputEvent.to_sse_data()               │
│                                                                          │
│    Streams complete_report + formatted_markdown to frontend              │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 5. TYPESCRIPT TYPES                                                      │
│    frontend/lib/types/api.ts (or generated-api.ts)                       │
│                                                                          │
│    Define interfaces matching Pydantic schemas                           │
│    Can auto-generate via scripts/generate_types.py                       │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 6. REPORT BUBBLE COMPONENT                                               │
│    frontend/components/chat/reports/                                     │
│                                                                          │
│    - ReportBubble.tsx: Router (switch on report_type)                    │
│    - {Type}ReportBubble.tsx: Specialized rendering                       │
│    - Sub-components in {type}/ directory                                 │
└──────────────────────────────────────────────────────────────────────────┘
```

### File Naming Conventions

| Component | Location | Naming Pattern |
|-----------|----------|----------------|
| Agent Prompt | `prompts/{domain}/v{N}.py` | `{DOMAIN}_SYSTEM_PROMPT` |
| Pydantic Models | `domain/models/{type}_schemas.py` | `{Type}Report`, `{Sub}Model` |
| Formatter | `report_formatters/{type}_formatter.py` | `{Type}ReportFormatter` |
| TS Types | `lib/types/api.ts` | `{Type}Report`, `{Sub}Summary` |
| React Component | `reports/{Type}ReportBubble.tsx` | `{Type}ReportBubble` |
| Sub-components | `reports/{type}/` | `{Feature}Card.tsx`, `{Feature}Table.tsx` |

---

## Creating a New Report Type

### Step 1: Define Pydantic Schema

Create `packages/starboard-core/starboard_core/domain/models/{type}_schemas.py`:

```python
"""Pydantic models for {type} report type."""

from typing import Literal
from pydantic import BaseModel, Field

from starboard_core.domain.models.llm_schemas import (
    Summary,
    NextStepAction,
)


class {Type}SpecificSection(BaseModel):
    """Domain-specific section for {type} reports."""
    field1: str = Field(..., description="Description")
    field2: int | None = None


class {Type}Report(BaseModel):
    """Complete {type} report schema."""
    
    report_type: Literal["{type}"] = "{type}"
    summary: Summary
    next_steps: list[NextStepAction] = Field(
        ..., min_length=1, max_length=5,
        description="Suggested next actions"
    )
    
    # Type-specific sections
    {type}_section: {Type}SpecificSection | None = None
```

### Step 2: Create Report Formatter

Create `packages/starboard-server/starboard_server/agents/report_formatters/{type}_formatter.py`:

```python
"""Report formatter for {type} reports."""

from typing import Any

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class {Type}ReportFormatter:
    """Formats {Type}Report to markdown."""

    def get_report_type(self) -> str:
        """Return supported report type."""
        return "{type}"

    def format_to_markdown(self, report: dict[str, Any]) -> str:
        """Format {Type}Report to markdown."""
        if not isinstance(report, dict):
            return "Analysis complete."

        parts = []

        # Format each section
        summary = report.get("summary", {})
        if summary:
            parts.append(self._format_summary(summary))

        # Add type-specific sections
        specific = report.get("{type}_section")
        if specific:
            parts.append(self._format_specific(specific))

        return "\n\n".join(filter(None, parts)) or "Analysis complete."

    def _format_summary(self, summary: dict[str, Any]) -> str:
        """Format summary section."""
        lines = ["## Summary\n"]
        overview = summary.get("overview", "")
        if overview:
            lines.append(overview)
        return "\n".join(lines)

    def _format_specific(self, section: dict[str, Any]) -> str:
        """Format type-specific section."""
        # Implement type-specific formatting
        return ""
```

### Step 3: Register Formatter

Update `packages/starboard-server/starboard_server/agents/report_formatters/registry.py`:

```python
from starboard_server.agents.report_formatters.{type}_formatter import (
    {Type}ReportFormatter,
)

# In global registry initialization
_global_registry.register({Type}ReportFormatter())
```

### Step 4: Define TypeScript Types

Update `frontend/lib/types/api.ts`:

```typescript
export interface {Type}Report extends AgentReport {
  report_type: "{type}";
  summary: Summary;
  next_steps: Array<NextStepAction>;
  
  // Type-specific sections
  {type}_section?: {Type}SpecificSection;
}

export interface {Type}SpecificSection {
  field1: string;
  field2?: number;
}
```

### Step 5: Create React Component

Create `frontend/components/chat/reports/{Type}ReportBubble.tsx`:

```tsx
"use client";

import React from "react";
import { Box, Paper, Typography } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import type { Message, {Type}Report, FeedbackRating } from "@/lib/types/api";
import { ReportHeader, ReportFooter } from "../shared";

interface {Type}ReportBubbleProps {
  message: Message;
  report: {Type}Report;
  onSubmitFeedback?: (messageId: string, rating: FeedbackRating) => Promise<void>;
}

export function {Type}ReportBubble({
  message,
  report,
  onSubmitFeedback,
}: {Type}ReportBubbleProps) {
  const theme = useTheme();

  return (
    <Box sx={{ display: "flex", justifyContent: "flex-start", mb: 2, px: 2 }}>
      <Box sx={{ display: "flex", gap: 1, maxWidth: "85%", flexDirection: "row" }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Paper
            elevation={2}
            sx={{
              p: 2,
              bgcolor: theme.palette.mode === "dark"
                ? "rgba(X, X, X, 0.08)"
                : "rgba(X, X, X, 0.04)",
              borderRadius: 2,
              borderLeft: `4px solid ${theme.palette.primary.main}`,
            }}
          >
            <ReportHeader
              title="{Type} Analysis"
              icon="🔍"
              hasCompleteReport={!!message.metadata?.complete_report}
              conversationId={message.conversation_id}
            />

            {/* Summary */}
            {report.summary && (
              <Box sx={{ mb: 2 }}>
                <Typography variant="body1">
                  {report.summary.overview}
                </Typography>
              </Box>
            )}

            {/* Type-specific sections */}
            {report.{type}_section && (
              <{Type}Section data={report.{type}_section} />
            )}

            <ReportFooter metadata={message.metadata} />
          </Paper>
        </Box>
      </Box>
    </Box>
  );
}
```

### Step 6: Update Report Router

Update `frontend/components/chat/ReportBubble.tsx`:

```tsx
import { {Type}ReportBubble } from "./reports";
import type { {Type}Report } from "@/lib/types/api";

// In the switch statement
case "{type}":
  return (
    <{Type}ReportBubble
      message={message}
      report={report as {Type}Report}
      onSubmitFeedback={onSubmitFeedback}
    />
  );
```

### Step 7: Update Agent Prompt

Add output schema to agent's system prompt in `prompts/{domain}/v1.py`:

```python
## Output Format (complete tool)

When calling 'complete', provide a {Type}Report with:

**1. Report Type**: Always set `report_type: "{type}"`

**2. Summary**:
   - overview: 2-3 sentence summary
   - current_state: {...}

**3. {Type}-Specific Sections**:
   Include `{type}_section`:
   {
     "field1": "...",
     "field2": 123
   }

**4. Next Steps** (2-5 actionable options - REQUIRED)
```

---

## Using Existing Report Types

### Advisor Report

To use the `advisor` report type for your agent:

1. **Ensure prompt outputs correct schema** - See `prompts/query/v1.py` for example
2. **Set `report_type: "advisor"`** in complete tool output
3. **Use standard categories** - QUERY, TABLE, WAREHOUSE, JOB_CONFIG, CODE, CLUSTER, DATA, RUNTIME, SCHEMA, RESOURCE

**No additional code needed** - existing `AdvisorReportBubble` will render.

### Analytics Report

To use the `analytics` report type for cost-focused outputs:

1. **Include `cost_summary`** with primary_metric, total, period, top_contributors
2. **Use AnalyticsFinding format** with cost_impact (not impact_estimate)
3. **Set `report_type: "analytics"`**

**Trigger heuristic** - Add cost override logic to prompt:

```python
## Cost-Focused Output Override

If the user's request is COST-FOCUSED (contains cost, spending, chargeback, 
billing, expensive, "how much"), use report_type: "analytics" instead.
```

---

## Schema Design Patterns

### 1. Discriminated Union Pattern

Always use `report_type` as discriminator:

```python
class MyReport(BaseModel):
    report_type: Literal["my_type"] = "my_type"  # Fixed literal
```

### 2. Optional Sections Pattern

Make domain-specific sections optional for flexibility:

```python
class MyReport(BaseModel):
    report_type: Literal["my_type"] = "my_type"
    summary: Summary  # Required
    next_steps: list[NextStepAction]  # Required
    
    # Optional based on analysis type
    section_a: SectionA | None = None
    section_b: SectionB | None = None
```

### 3. Reuse Common Models

Import from `llm_schemas.py` for consistency:

```python
from starboard_core.domain.models.llm_schemas import (
    Summary,
    Analysis,
    NextStepAction,
    Finding,
    ImpactEstimate,
    EffortEstimate,
)
```

### 4. Strict Validation

Use Pydantic constraints:

```python
health_score: int = Field(..., ge=0, le=100, description="Health score (0-100)")
confidence: Literal["low", "medium", "high"] = Field(...)
next_steps: list[NextStepAction] = Field(..., min_length=1, max_length=5)
```

---

## Frontend Component Patterns

### 1. Theme-Aware Styling

Use theme palette for consistent dark/light mode:

```tsx
sx={{
  bgcolor: theme.palette.mode === "dark"
    ? "rgba(X, X, X, 0.08)"
    : "rgba(X, X, X, 0.04)",
}}
```

### 2. Shared Components

Reuse existing shared components:

```tsx
import { ReportHeader, ReportFooter } from "../shared";
import { FeedbackWidget } from "../FeedbackWidget";
```

### 3. Memoization

Memoize computed values and callbacks:

```tsx
const formattedData = useMemo(() => {
  return processData(report.data);
}, [report.data]);

const handleAction = useCallback(() => {
  // ...
}, [dependencies]);
```

### 4. Sub-Component Organization

For complex report types, create sub-component directory:

```
reports/
├── MyTypeReportBubble.tsx       # Main component
├── mytype/                       # Sub-components
│   ├── SectionCard.tsx
│   ├── MetricsTable.tsx
│   └── index.ts                 # Barrel export
└── index.ts                     # Export main component
```

---

## Tool Display Names

### Overview

Tool display names provide user-friendly labels for tool calls in the UI. All configuration is in a single file:

**Location:** `packages/starboard-server/starboard_server/agents/tool_display.py`

### Tool Display Configuration

```python
from starboard_server.agents.tool_display import ToolDisplayConfig

TOOL_DISPLAY: dict[str, ToolDisplayConfig] = {
    "resolve_query": ToolDisplayConfig(
        friendly_name="Resolving Query",
        thinking_title="Resolving Query",
        thinking_description="Fetching query details and SQL",
    ),
    "get_table_metadata": ToolDisplayConfig(
        friendly_name="Getting Table Metadata",
        friendly_template="Fetching Table Metadata for {table_name}",
        thinking_title="Fetching Table Metadata",
        thinking_description="Loading schema and statistics",
    ),
    "resolve_job": ToolDisplayConfig(
        friendly_name="Resolving Job",
        friendly_template="Resolving Job: {job_id}",
        thinking_title="Resolving Job",
        thinking_description="Finding job details",
    ),
    # ... more tools
}
```

### ToolDisplayConfig Fields

| Field | Purpose | Example |
|-------|---------|---------|
| `friendly_name` | Static display name | `"Resolving Query"` |
| `friendly_template` | Name with parameter substitution | `"Resolving Job: {job_id}"` |
| `thinking_title` | Title in thinking step UI | `"Resolving Query"` |
| `thinking_description` | Description in thinking step | `"Fetching query details"` |
| `hidden_in_ui` | Hide from UI (default: False) | `True` for internal tools |

### Adding a New Tool Display Name

Add a single entry to `TOOL_DISPLAY`:

```python
TOOL_DISPLAY: dict[str, ToolDisplayConfig] = {
    # ... existing tools
    "my_new_tool": ToolDisplayConfig(
        friendly_name="Performing My Action",
        friendly_template="Performing My Action for {target_id}",
        thinking_title="My Action",
        thinking_description="Executing the action",
    ),
}
```

### Tool Visibility

To hide a tool from the UI, set `hidden_in_ui=True`:

```python
"complete": ToolDisplayConfig(
    friendly_name="Complete",
    thinking_title="Generating Report",
    thinking_description="Formatting final output",
    hidden_in_ui=True,  # Hidden from UI
),
```

---

## Testing Requirements

### Required Tests for New Report Type

| Test Type | Location | Coverage |
|-----------|----------|----------|
| **Pydantic Schema** | `tests/unit/domain/models/test_{type}_schemas.py` | Model validation, defaults |
| **Formatter** | `tests/unit/agents/report_formatters/test_{type}_formatter.py` | Markdown output |
| **Golden/Snapshot** | `tests/golden/test_{type}_report_schema.py` | Schema stability |
| **Component** | `frontend/.../reports/__tests__/{Type}ReportBubble.test.tsx` | Rendering |
| **Contract** | `tests/contract/{type}_report_schema.json` | API contract |

### Schema Golden Test Example

```python
# tests/golden/test_{type}_report_schema.py

def test_{type}_report_structure(snapshot):
    """Test {type} report schema structure."""
    valid_report = {
        "report_type": "{type}",
        "summary": {"overview": "Test", "current_state": {...}},
        "next_steps": [...],
        "{type}_section": {...}
    }
    
    report = {Type}Report.model_validate(valid_report)
    snapshot.assert_match(report.model_dump_json(indent=2), "{type}_report.json")
```

---

## Checklist

### New Report Type Checklist

- [ ] **Schema Design**
  - [ ] Define Pydantic models in `domain/models/{type}_schemas.py`
  - [ ] Use `Literal["{type}"]` for report_type discriminator
  - [ ] Reuse common models (Summary, NextStepAction, etc.)
  - [ ] Add field validation constraints

- [ ] **Backend Formatter**
  - [ ] Create `report_formatters/{type}_formatter.py`
  - [ ] Implement `ReportFormatter` protocol
  - [ ] Register in `registry.py`
  - [ ] Export from `__init__.py`

- [ ] **Tool Display Config**
  - [ ] Add entry to `TOOL_DISPLAY` in `tool_display.py`
  - [ ] Include `friendly_name`, `thinking_title`, `thinking_description`
  - [ ] Add `friendly_template` if tool uses parameter substitution

- [ ] **Frontend Types**
  - [ ] Add TypeScript interfaces to `lib/types/api.ts`
  - [ ] Ensure type alignment with Pydantic models

- [ ] **Frontend Component**
  - [ ] Create `{Type}ReportBubble.tsx`
  - [ ] Add case to `ReportBubble.tsx` switch
  - [ ] Create sub-components if needed
  - [ ] Export from `reports/index.ts`

- [ ] **Agent Prompt**
  - [ ] Add output schema section to prompt
  - [ ] Include report_type instruction
  - [ ] Document required/optional sections
  - [ ] Add cost-focused override if applicable

- [ ] **Testing**
  - [ ] Unit tests for Pydantic models
  - [ ] Unit tests for formatter
  - [ ] Golden tests for schema stability
  - [ ] Component tests for React rendering
  - [ ] Contract tests for API

### Using Existing Report Type Checklist

- [ ] **Advisor Type**
  - [ ] Set `report_type: "advisor"` in prompt
  - [ ] Use standard Finding categories
  - [ ] Include impact_estimate and effort
  - [ ] Add fixes array with code snippets

- [ ] **Analytics Type**
  - [ ] Set `report_type: "analytics"` in prompt
  - [ ] Include cost_summary with totals
  - [ ] Use AnalyticsFinding with cost_impact
  - [ ] Add visualization recommendation

- [ ] **Cost Override**
  - [ ] Add cost-focused detection to prompt
  - [ ] Switch to analytics schema for cost queries

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-08 | Initial guidelines |
| 1.1.0 | 2025-12-09 | Added Tool Display Names section, updated file locations |



---
title: Agent Implementation Guide
description: Step-by-step guide for implementing new domain agents in Starboard.
last_reviewed: 2026-03-24
prompt_version: "1.2.0"
status: current
---

# Domain Agent Implementation Guide

> **Docs** > **Agents** > **Framework** > **Implementation Guide**
> Reading time: 15 minutes

> **Version**: 1.2.0

**What you'll learn:**

- How the agent creation flow works
- Step-by-step process for building a new domain agent
- Tool configuration and sharing patterns
- Prompt engineering guidelines
- Testing requirements

---

## Overview

### What is a Domain Agent?

A **domain agent** is a specialized AI assistant that handles a specific category of Databricks optimization tasks. Each agent has:

1. **Domain Identity** -- Unique identifier (e.g., `query`, `job`, `warehouse`)
2. **System Prompt** -- Instructions defining behavior, tools, and output format
3. **Tool Set** -- Filtered subset of tools relevant to the domain
4. **Report Type** -- Output schema for structured responses

### Current Domain Agents

| Domain | Purpose | Tools | Report Type |
|--------|---------|-------|-------------|
| `router` | Intent classification and routing | 3 | N/A |
| `query` | SQL query optimization | 8 | `advisor` |
| `job` | Job/workflow optimization | 14 | `advisor` |
| `uc` | Unity Catalog governance | 18 | `advisor` |
| `cluster` | Cluster configuration and health | 8 | `compute` |
| `analytics` | FinOps cost analysis (agentic RAG) | 6 | `analytics` |
| `warehouse` | SQL warehouse portfolio optimization | 11 | `compute` |
| `discovery` | Workspace health assessment (4-phase) | 6 | `discovery` |
| `diagnostic` | Troubleshooting (unrestricted tools) | ALL | `advisor` |

Tool counts sourced from `packages/starboard/starboard/agents/tool_categories.py`.

### Tool Sharing Strategy (80/20 Rule)

```
+-----------------------------------------------------------------------+
|                        TOOL SHARING PHILOSOPHY                        |
|                                                                       |
|   80% of operations: Agents complete independently (strategic overlap)|
|   20% of operations: Delegate to domain specialist (no tool needed)  |
|                                                                       |
|   Example:                                                            |
|   - Query agent has get_table_metadata (needs schemas for EXPLAIN)   |
|   - Query agent does NOT have get_table_lineage (delegates to UC)    |
+-----------------------------------------------------------------------+
```

---

## Architecture

### Agent Creation Flow

```
+-----------------------------------------------------------------------+
|                          AgentFactory                                  |
|                                                                       |
|   1. get_agent(domain)                                                |
|                                                                       |
|   2. Filter tools for domain                                          |
|      -> tool_categories.py: TOOL_CATEGORIES[domain]                   |
|      -> ToolRegistry.filter_by_domain(domain)                         |
|                                                                       |
|   3. Get domain prompt builder                                        |
|      -> prompts/factories.py: get_prompt_builder_for_domain(domain)   |
|                                                                       |
|   4. Apply model/temperature overrides                                |
|      -> AgentConfig.get_model_for_domain(domain)                      |
|      -> AgentConfig.get_temperature_for_domain(domain)                |
|                                                                       |
|   5. Create DomainAgent instance                                      |
|      -> DomainAgent(llm_client, tools, config, events)                |
|                                                                       |
|                                    v                                  |
|                          +------------------+                         |
|                          |  DomainAgent     |                         |
|                          |  (ready to run)  |                         |
|                          +------------------+                         |
+-----------------------------------------------------------------------+
```

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| AgentFactory | `agents/agent_factory.py` | Creates and caches domain agents |
| DomainAgent | `agents/domain/domain_agent.py` | Base reasoning agent implementation |
| ToolRegistry | `agents/tools/registry.py` | Tool management and filtering |
| TOOL_CATEGORIES | `agents/tool_categories.py` | Domain --> tool mappings |
| Prompt Factories | `prompts/factories.py` | Prompt builders per domain |
| IntentRouter | `agents/routing/intent_router.py` | Routes requests to domains |

All paths relative to `packages/starboard/starboard/`.

---

## Step-by-Step: Creating a New Agent

### Step 1: Define Domain Identity

Add the domain to the `AgentDomain` type literal in **two files**:

**File 1:** `packages/starboard/starboard/prompts/base.py`

```python
AgentDomain = Literal[
    "router", "query", "job", "uc", "cluster",
    "diagnostic", "analytics", "warehouse", "discovery",
    "my_new_domain",  # ADD HERE
]
```

**File 2:** `packages/starboard/starboard/agents/routing/routing_models.py`

```python
AgentDomain = Literal[
    "query", "job", "uc", "cluster", "diagnostic",
    "analytics", "warehouse", "discovery",
    "my_new_domain",  # ADD HERE (excluding "router")
]
```

### Step 2: Create System Prompt

Create prompt directory and files:

```
packages/starboard/starboard/prompts/my_new_domain/
    __init__.py
    v1.py
```

**File:** `prompts/my_new_domain/v1.py`

```python
"""
My New Domain prompts - Version 1.

PROMPT_VERSION tracks prompt evolution for golden tests.
"""

PROMPT_VERSION = "1.0.0"


def build_system_prompt(
    tools: list[dict],
    mode: str = "online",
    handoff_context: str | None = None,
) -> str:
    """Build system prompt for the my_new_domain agent."""
    tool_catalog = _format_tool_catalog(tools)

    return f"""You are the My New Domain Agent...

## Available Tools
{tool_catalog}

## Output Format
You MUST call the `complete` tool with an OptimizerAdvisorReport...

## Handoff Context
{handoff_context or "No prior context."}
"""
```

> !!! warning
>     Always include `PROMPT_VERSION` as a module-level constant. Golden tests rely on this to detect unintended prompt changes.

### Step 3: Register Prompt Builder

**File:** `packages/starboard/starboard/prompts/factories.py`

```python
from starboard.prompts.my_new_domain.v1 import build_system_prompt as my_new_domain_prompt

PROMPT_BUILDERS: dict[str, Callable] = {
    # ... existing domains
    "my_new_domain": my_new_domain_prompt,
}
```

### Step 4: Configure Tools

**File:** `packages/starboard/starboard/agents/tool_categories.py`

```python
TOOL_CATEGORIES: dict[str, list[str] | str] = {
    # ... existing domains
    "my_new_domain": [
        "my_tool_1",           # Primary domain tool
        "my_tool_2",           # Primary domain tool
        "get_table_metadata",  # SHARED - if needed for analysis
        "request_user_input",  # Core - ask for clarification
        "complete",            # Core - deliver report
    ],
}
```

### Step 5: Add Routing Rules

**File:** `packages/starboard/starboard/agents/routing/intent_router.py`

Add keyword patterns and domain description for the Intent Router to recognize your domain.

### Step 6: Register Tool Display Config

**File:** `packages/starboard/starboard/agents/tool_display.py`

```python
TOOL_DISPLAY: dict[str, ToolDisplayConfig] = {
    # ... existing tools
    "my_tool_1": ToolDisplayConfig(
        friendly_name="Analyzing My Resource",
        friendly_template="Analyzing {resource_id}",
        thinking_title="Resource Analysis",
        thinking_description="Examining the resource configuration",
    ),
}
```

### Step 7: Write Tests

Required tests for every new agent:

1. **Golden tests** -- Snapshot the system prompt to detect unintended changes
2. **Routing tests** -- Verify the Intent Router correctly classifies requests for your domain
3. **Tool category tests** -- Verify tool filtering returns correct tools
4. **Integration tests** -- End-to-end agent execution with mocked tools

```bash
# Run golden tests
make test-golden

# Run specific test file
cd packages/starboard
pytest tests/unit/agents/test_my_new_domain.py -v
```

---

## Prompt Engineering Guidelines

### Standard Sections

Every system prompt should include:

1. **Identity** -- "You are the X Agent, specializing in..."
2. **Core Principles** -- Immutable behavioral rules
3. **Tool Catalog** -- Available tools with cost estimates
4. **Workflow Patterns** -- Mode-specific workflows (ONLINE vs OFFLINE)
5. **Output Format** -- Report schema and structure
6. **Handoff Context** -- Integration with multi-agent system

### Use Shared Handoff Components

```python
from starboard.prompts.shared.handoff_context import (
    SHARED_HANDOFF_SECTION,
    build_handoff_section,
)
```

### Temperature Guidelines

- **Structural/tool calls**: temperature <= 0.4
- **Creative responses**: temperature <= 0.9
- **Routing**: temperature <= 0.2

---

## Handoff Context

### Standard Resource IDs

All agents recognize these fields in handoff context:

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

---

## Checklist

Before submitting a PR for a new agent:

- [ ] Domain added to `AgentDomain` in both `prompts/base.py` and `routing_models.py`
- [ ] System prompt created in `prompts/{domain}/v1.py` with `PROMPT_VERSION`
- [ ] Prompt builder registered in `prompts/factories.py`
- [ ] Tools configured in `TOOL_CATEGORIES` in `tool_categories.py`
- [ ] Routing rules added to `IntentRouter`
- [ ] Tool display config added to `tool_display.py`
- [ ] Golden tests written and passing
- [ ] Routing tests written and passing
- [ ] Integration tests written with mocked tools
- [ ] Agent documentation created in `docs/agents/domain/{domain}.md`
- [ ] Agent added to `docs/agents/README.md` domain table

---

## Related Documentation

- [Agent Documentation Index](../../agents/README.md) -- All agents overview
- [Tool Architecture](../../TOOL_ARCHITECTURE.md) -- Three-layer tool design
- [Tool Development Guide](../../tools/TOOL_DEVELOPMENT_GUIDE.md) -- Building new tools
- [Report UI Guidelines](REPORT_UI_GUIDELINES.md) -- Output format design
- [Tool Categories Source](../../../packages/starboard/starboard/agents/tool_categories.py) -- Canonical tool mappings

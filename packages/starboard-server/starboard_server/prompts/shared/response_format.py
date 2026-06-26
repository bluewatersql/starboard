# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Shared response formatting guidelines for domain agent prompts.

This module provides reusable instructions for consistent output formatting
across all domain agents, particularly for:
- Using the 'complete' tool for structured reports (NOT free text)
- Handling data listing requests with markdown tables

When users ask for lists, tables, or enumerated data, agents should prioritize
displaying the data in a structured format (markdown table) rather than
burying it within prose analysis.
"""

# =============================================================================
# COMPLETE TOOL OUTPUT GUIDELINES (CRITICAL)
# =============================================================================

COMPLETE_TOOL_GUIDELINES = """
===============================================================================
COMPLETE TOOL OUTPUT GUIDELINES (CRITICAL)
===============================================================================

**CRITICAL: Use the 'complete' tool—do NOT output report content as text.**

**When to call 'complete':**
- Analysis results
- Reports (advisor/analytics/compute/etc.)
- Findings and recommendations

**Rules:**
1. Call 'complete' tool with structured JSON—NOT conversational text
2. Tool handles ALL formatting for UI
3. Thinking text = reasoning only, NOT final report
4. Call 'complete' ONCE with full report

**Examples:**

❌ **WRONG:**
```
I've analyzed the data. Here are my findings:
{{{{
  "report": {{{{
    "summary": {{{{"overview": "Your costs are..."}}}},
    ...
  }}}}
}}}}
```

✅ **CORRECT:**
```
I've analyzed the data and identified key cost drivers.
[Calls complete tool with structured JSON]
```

**Never duplicate report content in thinking text.**
"""

# =============================================================================
# DATA LISTING RESPONSE GUIDELINES
# =============================================================================

DATA_LISTING_GUIDELINES = """
===============================================================================
DATA LISTING RESPONSE GUIDELINES
===============================================================================

**CRITICAL:** When users request lists, tables, or rankings—show the data FIRST.

**Trigger Patterns:**
- "top/bottom N..." → ranked list expected
- "list/show/what are..." → enumerated results expected
- "which/how many..." → specific items expected
- Explicit requests for tables/lists/rankings

**Response Structure:**

1. **Lead with the data** as a markdown table
2. Add brief context/recommendations AFTER (optional)

**Table Format:**
```
| Rank | Name | Key Metric | Notes |
|------|------|------------|-------|
| 1    | Item | 1,234.56   | ...   |
```

**DON'T:**
- Bury lists in prose
- Summarize when specifics are requested
- Truncate unless >25 rows

**Example:**

✅ **GOOD:**
"Here are your top 5 most expensive jobs:

| Rank | Job Name | Cost | Runs |
|------|----------|------|------|
| 1 | ETL Pipeline | $1,245 | 156 |
[...table continues...]

The ETL Pipeline shows optimization potential. Need details?"

❌ **BAD:**
"Your most expensive job was ETL Pipeline at $1,245 across 156 runs, followed by..."
"""

# =============================================================================
# NEXT STEPS GUIDELINES (REQUIRED FOR ALL AGENTS)
# =============================================================================

NEXT_STEPS_GUIDELINES = """
===============================================================================
INTERACTIVE NEXT STEPS (REQUIRED)
===============================================================================

**CRITICAL:** `next_steps` is REQUIRED at TOP LEVEL of tool output (sibling to `report`, NOT nested).

**JSON Structure:**
```json
{{{{
  "summary": {{{{ ... }}}},
  "findings": [ ... ],
  "next_steps": [
    {{{{
      "id": "unique_action_id_1",
      "number": 1,
      "title": "Short action title (3-7 words)",
      "description": "One sentence explaining value",
      "action_type": "continue | route | tool_call",
      "target_agent": "agent_name or null",
      "tool_name": "tool_name or null",
      "parameters": {{{{ "key": "value" }}}} or null
    }}}}
  ]
}}}}
```

**Action Types:**
- `continue`: Stay with current agent
- `route`: Hand off to specialist (compute/query/job/uc/analytics/warehouse)
- `tool_call`: Pre-fill tool parameters

**Requirements:**
- ALWAYS 2-5 options (never 0 or >9)
- Number sequentially from 1
- First option = action-oriented (implement/fix/analyze)
- Include routing option when cross-domain relevant
- Titles: 3-7 words, action-focused
- Descriptions: 1 sentence value proposition
- Parameters: Include entity IDs or "context" field

**Common Patterns:**
1. Implement recommendation (continue)
2. Drill into top finding (continue/tool_call)
3. Analyze related resource (route)
4. Compare to baseline (continue)
5. Explain details (continue)

**NEVER omit—UI requires this field.**
"""

# =============================================================================
# BUILDER FUNCTIONS
# =============================================================================


def build_complete_tool_section() -> str:
    """
    Build the complete tool guidelines section for inclusion in prompts.

    Returns:
        Complete tool usage guidelines string ready to embed in a prompt.

    Example:
        >>> from starboard_server.prompts.shared.response_format import (
        ...     build_complete_tool_section
        ... )
        >>> guidelines = build_complete_tool_section()
        >>> "complete" in guidelines.lower()
        True
    """
    return COMPLETE_TOOL_GUIDELINES


def build_data_listing_section() -> str:
    """
    Build the data listing guidelines section for inclusion in prompts.

    Returns:
        Complete data listing guidelines string ready to embed in a prompt.

    Example:
        >>> from starboard_server.prompts.shared.response_format import (
        ...     build_data_listing_section
        ... )
        >>> guidelines = build_data_listing_section()
        >>> "markdown table" in guidelines.lower()
        True
    """
    return DATA_LISTING_GUIDELINES


def build_next_steps_section() -> str:
    """
    Build the next steps guidelines section for inclusion in prompts.

    Returns:
        Next steps guidelines string ready to embed in a prompt.

    Example:
        >>> from starboard_server.prompts.shared.response_format import (
        ...     build_next_steps_section
        ... )
        >>> guidelines = build_next_steps_section()
        >>> "next_steps" in guidelines.lower()
        True
    """
    return NEXT_STEPS_GUIDELINES

"""
Visualization prompts - Version 1.

This module contains prompts for LLM-driven chart recommendation.
It includes system prompts, few-shot examples, and a builder function
for constructing complete prompts with query metadata.

Design Principles:
    - Clear role definition (data visualization expert)
    - Explicit constraints (chart types, encoding types)
    - Query catalog integration (recommended chart types)
    - Few-shot learning (2-4 examples per chart type)
    - Structured JSON output with validation schema
    - Confidence scoring for recommendation quality
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


PROMPT_VERSION = "1.0.0"
"""Semantic version for visualization prompts. Increment on any prompt change:
- PATCH: Wording tweaks, typo fixes
- MINOR: New examples, improved guidance
- MAJOR: Structural changes, new sections

Changelog:
- 1.0.0: Fresh start for prompts v2 standardization
"""

# System prompt with role, constraints, and output format
VISUALIZATION_SYSTEM_PROMPT = """You are a data visualization expert specializing in financial and operational analytics. Your task is to recommend the most appropriate chart type and generate a complete chart configuration for analytical data.

**Your Role:**
- Analyze data profiles (statistical summaries, column types, row counts)
- Recommend chart types that best convey insights
- Generate complete chart configurations with proper encodings
- Provide reasoning and confidence scores for recommendations

**Available Chart Types:**
1. **bar** - Compare values across categories (e.g., cost by service, top 10 items)
2. **line** - Show trends over time (e.g., daily costs, performance metrics)
3. **area** - Emphasize cumulative trends (e.g., running totals, stacked values)
4. **scatter** - Explore relationships between two variables (e.g., cost vs usage)
5. **histogram** - Show distribution of values (e.g., job duration distribution)
6. **table** - Display raw data when visualization is not appropriate

**Encoding Types:**
- **quantitative** - Continuous numeric values (integers, floats, decimals)
- **nominal** - Unordered categories (strings, IDs without inherent order)
- **ordinal** - Ordered categories (small/medium/large, rankings)
- **temporal** - Date/time values (dates, timestamps, time periods)

**Decision Guidelines:**
1. **Query Catalog Constraints**: If recommended chart types are provided, strongly prefer those types
2. **Data Characteristics**: Match chart type to data structure (timeseries → line/area, categorical → bar)
3. **Row Count**: Large datasets (>100 rows) may need aggregation; very small (<5 rows) may prefer table
4. **Column Types**: Temporal columns suggest line/area charts; categorical suggest bar charts
5. **Confidence Scoring**:
   - High (≥0.8): Clear match between data and chart type
   - Medium (0.5-0.8): Reasonable choice but alternatives exist
   - Low (<0.5): Uncertain or no good visualization (recommend table)

**Output Requirements:**
Return a JSON object with three fields:
1. **summary** (string): 1-2 sentence description of the data and why this chart type was chosen
2. **chart_recommendation** (object): Chart type, reasoning, and confidence score (0.0-1.0)
3. **chart_config** (object): Configuration with chart_type and title (encodings only for charts, not tables)

**Important Constraints:**
- chart_config is ALWAYS required
- For table: set chart_type to "table" and omit encodings
- For charts (bar/line/area/etc): include encodings with x and y
- Only use columns present in the data profile
- Match encoding types to column data types
- Provide clear, actionable reasoning for your choice
"""

# Few-shot examples demonstrating various chart types
FEW_SHOT_EXAMPLES: list[dict[str, Any]] = [
    # Example 1: Line chart for time-series cost data
    {
        "input": {
            "query_name": "Daily Cost Trend",
            "query_description": "Daily cost breakdown over time",
            "recommended_chart_types": ["line", "area"],
            "goals": ["Show cost trends over time"],
            "data_profile": {
                "row_count": 30,
                "column_count": 2,
                "columns": {
                    "date": {
                        "type": "Date",
                        "null_count": 0,
                        "min": "2024-11-01",
                        "max": "2024-11-30",
                    },
                    "total_cost": {
                        "type": "Float64",
                        "null_count": 0,
                        "min": 1234.56,
                        "max": 9876.54,
                        "mean": 5000.0,
                    },
                },
            },
        },
        "output": {
            "summary": "This data shows daily cost trends over a 30-day period. A line chart is ideal for visualizing temporal patterns and identifying trends.",
            "chart_recommendation": {
                "chart_type": "line",
                "reasoning": "Line chart effectively displays time-series data, making it easy to spot trends, seasonality, and anomalies in daily costs.",
                "confidence": 0.95,
            },
            "chart_config": {
                "chart_type": "line",
                "title": "Daily Cost Trend",
                "description": "Total costs over 30-day period",
                "encodings": {
                    "x": {
                        "field": "date",
                        "type": "temporal",
                        "title": "Date",
                    },
                    "y": {
                        "field": "total_cost",
                        "type": "quantitative",
                        "title": "Total Cost (USD)",
                    },
                },
                "options": {"interpolation": "monotone"},
            },
        },
    },
    # Example 2: Bar chart for categorical comparison
    {
        "input": {
            "query_name": "Cost by Service",
            "query_description": "Total cost grouped by service type",
            "recommended_chart_types": ["bar"],
            "goals": ["Compare costs across different services"],
            "data_profile": {
                "row_count": 10,
                "column_count": 2,
                "columns": {
                    "service_name": {
                        "type": "Utf8",
                        "null_count": 0,
                        "unique_count": 10,
                        "top_values": [
                            ("Compute Engine", 1),
                            ("Cloud Storage", 1),
                            ("BigQuery", 1),
                        ],
                    },
                    "total_cost": {
                        "type": "Float64",
                        "null_count": 0,
                        "min": 100.0,
                        "max": 5000.0,
                        "mean": 1500.0,
                    },
                },
            },
        },
        "output": {
            "summary": "This data compares costs across 10 different services. A bar chart clearly shows which services incur the highest costs.",
            "chart_recommendation": {
                "chart_type": "bar",
                "reasoning": "Bar charts excel at comparing values across discrete categories, making it easy to rank services by cost.",
                "confidence": 0.9,
            },
            "chart_config": {
                "chart_type": "bar",
                "title": "Cost by Service",
                "description": "Total cost per service type",
                "encodings": {
                    "x": {
                        "field": "service_name",
                        "type": "nominal",
                        "title": "Service",
                    },
                    "y": {
                        "field": "total_cost",
                        "type": "quantitative",
                        "title": "Total Cost (USD)",
                    },
                },
                "options": {"sort": {"field": "total_cost", "order": "descending"}},
            },
        },
    },
    # Example 3: Area chart for cumulative data
    {
        "input": {
            "query_name": "Cumulative Usage Over Time",
            "query_description": "Running total of resource usage",
            "recommended_chart_types": ["area", "line"],
            "goals": ["Show accumulation over time"],
            "data_profile": {
                "row_count": 24,
                "column_count": 2,
                "columns": {
                    "hour": {
                        "type": "Int64",
                        "null_count": 0,
                        "min": 0,
                        "max": 23,
                    },
                    "cumulative_usage": {
                        "type": "Float64",
                        "null_count": 0,
                        "min": 0.0,
                        "max": 1000.0,
                        "mean": 500.0,
                    },
                },
            },
        },
        "output": {
            "summary": "This data shows cumulative resource usage over 24 hours. An area chart emphasizes the accumulation and fills the space to highlight total magnitude.",
            "chart_recommendation": {
                "chart_type": "area",
                "reasoning": "Area charts effectively visualize cumulative data, with the filled area emphasizing the growing total over time.",
                "confidence": 0.85,
            },
            "chart_config": {
                "chart_type": "area",
                "title": "Cumulative Usage Over Time",
                "description": "Running total of resource usage per hour",
                "encodings": {
                    "x": {
                        "field": "hour",
                        "type": "quantitative",
                        "title": "Hour of Day",
                    },
                    "y": {
                        "field": "cumulative_usage",
                        "type": "quantitative",
                        "title": "Cumulative Usage",
                    },
                },
                "options": {"interpolation": "monotone"},
            },
        },
    },
    # Example 4: Scatter plot for correlation analysis
    {
        "input": {
            "query_name": "Cost vs Usage Correlation",
            "query_description": "Analyze relationship between usage and cost",
            "recommended_chart_types": ["scatter"],
            "goals": ["Explore correlation between two metrics"],
            "data_profile": {
                "row_count": 50,
                "column_count": 2,
                "columns": {
                    "usage_hours": {
                        "type": "Float64",
                        "null_count": 0,
                        "min": 10.0,
                        "max": 1000.0,
                        "mean": 300.0,
                    },
                    "total_cost": {
                        "type": "Float64",
                        "null_count": 0,
                        "min": 50.0,
                        "max": 5000.0,
                        "mean": 1500.0,
                    },
                },
            },
        },
        "output": {
            "summary": "This data explores the relationship between usage hours and cost across 50 instances. A scatter plot reveals correlation patterns and outliers.",
            "chart_recommendation": {
                "chart_type": "scatter",
                "reasoning": "Scatter plots are ideal for exploring relationships between two continuous variables, revealing correlation strength and identifying outliers.",
                "confidence": 0.8,
            },
            "chart_config": {
                "chart_type": "scatter",
                "title": "Cost vs Usage Correlation",
                "description": "Relationship between usage hours and total cost",
                "encodings": {
                    "x": {
                        "field": "usage_hours",
                        "type": "quantitative",
                        "title": "Usage Hours",
                    },
                    "y": {
                        "field": "total_cost",
                        "type": "quantitative",
                        "title": "Total Cost (USD)",
                    },
                },
                "options": {},
            },
        },
    },
    # Example 5: Table fallback for complex/unsuitable data
    {
        "input": {
            "query_name": "Job Configuration Details",
            "query_description": "Detailed job settings and parameters",
            "recommended_chart_types": [],
            "goals": ["View detailed configuration"],
            "data_profile": {
                "row_count": 3,
                "column_count": 8,
                "columns": {
                    "job_id": {"type": "Utf8", "null_count": 0},
                    "cluster_size": {"type": "Utf8", "null_count": 0},
                    "driver_type": {"type": "Utf8", "null_count": 0},
                    "worker_type": {"type": "Utf8", "null_count": 0},
                    "num_workers": {"type": "Int64", "null_count": 0},
                    "libraries": {"type": "Utf8", "null_count": 2},
                    "timeout": {"type": "Int64", "null_count": 1},
                    "retry_policy": {"type": "Utf8", "null_count": 0},
                },
            },
        },
        "output": {
            "summary": "This data contains detailed job configuration with 8 diverse columns and only 3 rows. A table is most appropriate for viewing detailed settings.",
            "chart_recommendation": {
                "chart_type": "table",
                "reasoning": "With many heterogeneous columns and few rows, a table format preserves detail and allows comparison of individual configurations.",
                "confidence": 0.9,
            },
            "chart_config": None,
        },
    },
]


_USER_CONTENT_TEMPLATE = """Analyze this data and recommend a visualization:

**Query Context:**
- Name: {query_name}
- Description: {query_description}
- Goals: {goals_str}
- Recommended Chart Types: {recommended_str}

**Data Profile:**
```json
{data_profile_json}
```

**Required Output Format:**
Return a JSON object with exactly these three fields:
```json
{{
  "summary": "Brief description of the data and visualization choice",
  "chart_recommendation": {{
    "chart_type": "bar|line|area|scatter|histogram|table",
    "reasoning": "Explain why this chart type is appropriate",
    "confidence": 0.0-1.0
  }},
  "chart_config": {{
    "chart_type": "same as above",
    "title": "Chart title",
    "description": "Chart description (optional)",
    "encodings": {{
      "x": {{"field": "column_name", "type": "quantitative|nominal|ordinal|temporal", "title": "Axis title"}},
      "y": {{"field": "column_name", "type": "quantitative|nominal|ordinal|temporal", "title": "Axis title"}}
    }},
    "options": {{}}
  }}
}}
```

**For table views (chart_type="table"):**
```json
{{
  "chart_config": {{
    "chart_type": "table",
    "title": "Data Table"
  }}
}}
```
Note: Omit encodings for tables!

**Important:**
- chart_config is ALWAYS required (never null)
- For tables: ONLY include chart_type and title (no encodings)
- For charts: MUST include encodings with x and y
- Only use columns present in the data profile
- Match encoding types to column data types (temporal for dates, quantitative for numbers, nominal/ordinal for strings)
- Prefer recommended chart types when provided
- DO NOT include fields like x_axis_label, y_axis_label, stacked, show_legend, group_by - use encodings.x, encodings.y, encodings.color instead
"""


def build_visualization_prompt(
    query_metadata: dict[str, Any], data_profile: dict[str, Any]
) -> list[dict[str, str]]:
    """
    Build a complete LLM prompt for chart recommendation.

    Constructs a two-message prompt (system + user) that includes the system
    prompt defining the task, along with query metadata and data profile to
    guide the LLM's chart selection.

    Args:
        query_metadata: Query catalog metadata including:
            - id (str): Query identifier
            - name (str): Human-readable query name
            - description (str): Query purpose
            - recommended_chart_types (list[str], optional): Preferred chart types
            - goals (list[str], optional): Analysis goals
        data_profile: Statistical summary of the data including:
            - row_count (int): Number of rows
            - column_count (int): Number of columns
            - columns (dict): Per-column statistics (type, min, max, mean, etc.)
            - sample_rows (list[dict], optional): Example rows

    Returns:
        List of message dictionaries with 'role' and 'content' keys:
        [
            {"role": "system", "content": "<system prompt>"},
            {"role": "user", "content": "<query metadata + data profile>"}
        ]

    Example:
        >>> query_meta = {
        ...     "id": "daily_costs",
        ...     "name": "Daily Cost Trend",
        ...     "recommended_chart_types": ["line"],
        ...     "goals": ["Show cost trends"]
        ... }
        >>> profile = {
        ...     "row_count": 30,
        ...     "columns": {"date": {"type": "Date"}, "cost": {"type": "Float64"}}
        ... }
        >>> messages = build_visualization_prompt(query_meta, profile)
        >>> len(messages)
        2
        >>> messages[0]["role"]
        'system'
    """
    # Extract metadata fields
    query_name = query_metadata.get("name", "Unknown Query")
    query_description = query_metadata.get("description", "")
    recommended_types = query_metadata.get("recommended_chart_types", [])
    goals = query_metadata.get("goals", [])

    # Build system message
    system_message = {"role": "system", "content": VISUALIZATION_SYSTEM_PROMPT}

    # Build user message with query context and data
    recommended_str = ", ".join(recommended_types) if recommended_types else "any"
    goals_str = ", ".join(goals) if goals else "general analysis"

    user_content = _USER_CONTENT_TEMPLATE.format(
        query_name=query_name,
        query_description=query_description,
        goals_str=goals_str,
        recommended_str=recommended_str,
        data_profile_json=json.dumps(data_profile, indent=2, cls=DateTimeEncoder),
    )

    user_message = {"role": "user", "content": user_content}

    return [system_message, user_message]

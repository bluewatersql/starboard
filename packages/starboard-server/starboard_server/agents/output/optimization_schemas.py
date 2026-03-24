"""
Unified optimization report schemas for all domains.

This module defines comprehensive output schemas for optimization agents,
ensuring consistent, detailed reports across query, job, table, compute, and
diagnostic domains.

The schemas are designed to:
- Force LLMs to provide structured, evidence-based recommendations
- Quantify impact wherever possible (% improvements)
- Track effort estimates and risks
- Provide testing/validation plans
- Prioritize actions by total impact

Architecture:
- Base schema structure is domain-agnostic
- Domain-specific variations handled via enum extensions
- All schemas validated by Pydantic models in starboard_core
"""

from typing import Any, Literal

# Domain-specific category enums
QUERY_CATEGORIES = ["QUERY", "TABLE", "WAREHOUSE"]
JOB_CATEGORIES = ["JOB_CONFIG", "CODE", "CLUSTER", "DATA", "RUNTIME"]
TABLE_CATEGORIES = ["DATA", "TABLE", "SCHEMA"]
COMPUTE_CATEGORIES = ["CLUSTER", "WAREHOUSE", "RESOURCE"]
DIAGNOSTIC_CATEGORIES = [
    "QUERY",
    "TABLE",
    "WAREHOUSE",
    "JOB_CONFIG",
    "CODE",
    "CLUSTER",
    "DATA",
    "RUNTIME",
]

# Fix type enums
QUERY_FIX_TYPES = ["SQL_REWRITE", "DDL_DML", "CONFIG_CHANGE", "PROCESS_CHANGE"]
JOB_FIX_TYPES = [
    "CODE_REWRITE",
    "CONFIG_CHANGE",
    "CLUSTER_TUNING",
    "DATA_OPTIMIZATION",
    "PROCESS_CHANGE",
]
TABLE_FIX_TYPES = ["DDL_DML", "DATA_OPTIMIZATION", "PROCESS_CHANGE"]
COMPUTE_FIX_TYPES = ["CLUSTER_TUNING", "CONFIG_CHANGE"]
ALL_FIX_TYPES = [
    "SQL_REWRITE",
    "DDL_DML",
    "CONFIG_CHANGE",
    "PROCESS_CHANGE",
    "CODE_REWRITE",
    "CLUSTER_TUNING",
    "DATA_OPTIMIZATION",
]


def get_optimization_schema(
    domain: Literal[
        "query", "job", "uc", "compute", "analytics", "diagnostic", "warehouse"
    ],
    include_query_rewrite: bool = False,
) -> dict[str, Any]:
    """
    Get optimization report schema for a specific domain (auto-generated from Pydantic).

    This function auto-generates a comprehensive JSON schema from the appropriate
    Pydantic model (AdvisorReport or AnalyticsReport), ensuring the schema and
    validation models never drift out of sync.

    Benefits of auto-generation:
    - Single source of truth (Pydantic model)
    - No schema drift between tool schema and validation
    - Automatically compatible with strict mode
    - Less maintenance (update Pydantic model once, schema updates automatically)

    Args:
        domain: Domain name (query, job, uc, compute, analytics, diagnostic, warehouse) - used for schema selection
        include_query_rewrite: Include query_rewrite in analysis (query domain only)

    Returns:
        JSON schema dict for LLM function calling (OpenAI format)

    Example:
        >>> schema = get_optimization_schema("analytics")
        >>> # Use in ToolMetadata for 'complete' tool
        >>> complete_tool = ToolMetadata(
        ...     name="complete",
        ...     description="...",
        ...     parameters=schema
        ... )
    """
    # Select appropriate report model based on domain
    # Import models based on domain type
    from starboard_core.domain.models.compute_schemas import WarehouseReport
    from starboard_core.domain.models.report_types import AdvisorReport, AnalyticsReport

    report_model: type[AnalyticsReport] | type[AdvisorReport] | type[WarehouseReport]
    if domain == "analytics":
        report_model = AnalyticsReport
    elif domain == "warehouse":
        report_model = WarehouseReport
    else:
        # Other optimizer/advisor domains use AdvisorReport
        report_model = AdvisorReport

    # Auto-generate schema from Pydantic model (Pydantic V2 method)
    base_schema = report_model.model_json_schema(
        mode="serialization",  # Use serialization mode for LLM output
        by_alias=False,  # Use Python field names, not aliases
    )

    # Pydantic generates schema with $defs at the top level
    # OpenAI/Claude/Databricks expect parameters.properties structure for tools
    # Extract the main definition and include $defs
    if "$defs" in base_schema:
        # This is the proper format for function calling
        schema = {
            "type": "object",
            "properties": base_schema.get("properties", {}),
            "required": base_schema.get("required", []),
            "$defs": base_schema["$defs"],  # Include nested definitions
        }
    else:
        # No nested definitions, use as-is
        schema = base_schema

    # Note: Domain-specific filtering of categories/fix types could be implemented
    # by modifying the Pydantic model to be domain-aware, but for now we use
    # the full schema for all domains (simpler and works well in practice)

    # Parameters 'domain' and 'include_query_rewrite' are kept for backward
    # compatibility with existing call sites, but are currently unused.
    # The Pydantic model includes all fields for all domains.
    _ = (domain, include_query_rewrite)  # Acknowledge unused parameters

    return schema


def get_optimization_schema_manual(
    domain: Literal["query", "job", "uc", "compute", "analytics", "diagnostic"],
    include_query_rewrite: bool = False,
) -> dict[str, Any]:
    """
    DEPRECATED: Get optimization report schema (manually maintained version).

    This function is kept for reference but is no longer used. The manually-written
    schema can drift from the Pydantic validation model, causing bugs.

    Use get_optimization_schema() instead, which auto-generates from Pydantic.

    WARNING: This schema uses LEGACY next_steps format with rank/action/expected_impact.
    The canonical format uses: id, number, title, description, action_type, target_agent,
    tool_name, parameters.

    Args:
        domain: Domain name (query, job, uc, compute, diagnostic)
        include_query_rewrite: Include query_rewrite in analysis (query domain only)

    Returns:
        JSON schema dict for LLM function calling (OpenAI format)

    .. deprecated::
        Use get_optimization_schema() instead for auto-generated schemas.
    """
    import warnings

    warnings.warn(
        "get_optimization_schema_manual is deprecated. Use get_optimization_schema() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Select domain-specific enums
    if domain == "query":
        categories = QUERY_CATEGORIES
        fix_types = QUERY_FIX_TYPES
        current_state_fields = {
            "cloud_provider": {"type": "string"},
            "runtime_version": {"type": "string"},
            "warehouse_tier": {"type": "string"},
            "warehouse_size": {"type": "string"},
            "key_symptoms": {"type": "array", "items": {"type": "string"}},
        }
        current_state_required = [
            "cloud_provider",
            "runtime_version",
            "warehouse_tier",
            "warehouse_size",
            "key_symptoms",
        ]
    elif domain == "job":
        categories = JOB_CATEGORIES
        fix_types = JOB_FIX_TYPES
        current_state_fields = {
            "cloud_provider": {"type": "string"},
            "runtime_version": {"type": "string"},
            "cluster_type": {"type": "string"},
            "cluster_size": {"type": "string"},
            "key_symptoms": {"type": "array", "items": {"type": "string"}},
        }
        current_state_required = [
            "cloud_provider",
            "runtime_version",
            "cluster_type",
            "cluster_size",
            "key_symptoms",
        ]
    elif domain == "uc":
        categories = TABLE_CATEGORIES
        fix_types = TABLE_FIX_TYPES
        current_state_fields = {
            "cloud_provider": {"type": "string"},
            "runtime_version": {"type": "string"},
            "table_format": {"type": "string"},
            "key_symptoms": {"type": "array", "items": {"type": "string"}},
        }
        current_state_required = ["cloud_provider", "key_symptoms"]
    elif domain == "compute":
        categories = COMPUTE_CATEGORIES
        fix_types = COMPUTE_FIX_TYPES
        current_state_fields = {
            "cloud_provider": {"type": "string"},
            "runtime_version": {"type": "string"},
            "resource_type": {"type": "string"},
            "resource_size": {"type": "string"},
            "key_symptoms": {"type": "array", "items": {"type": "string"}},
        }
        current_state_required = [
            "cloud_provider",
            "resource_type",
            "resource_size",
            "key_symptoms",
        ]
    else:  # diagnostic
        categories = DIAGNOSTIC_CATEGORIES
        fix_types = ALL_FIX_TYPES
        current_state_fields = {
            "cloud_provider": {"type": "string"},
            "runtime_version": {"type": "string"},
            "key_symptoms": {"type": "array", "items": {"type": "string"}},
        }
        current_state_required = ["cloud_provider", "key_symptoms"]

    # Base schema structure
    schema = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "object",
                "properties": {
                    "overview": {
                        "type": "string",
                        "description": "2-3 sentence summary of analysis and key findings",
                    },
                    "current_state": {
                        "type": "object",
                        "properties": current_state_fields,
                        "required": current_state_required,
                        "description": "Current system state and configuration",
                    },
                },
                "required": ["overview", "current_state"],
                "description": "High-level summary of analysis",
            },
            "analysis": {
                "type": "object",
                "properties": {
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Unique identifier (e.g., 'query_finding_001')",
                                },
                                "category": {
                                    "type": "string",
                                    "enum": categories,
                                    "description": "Finding category",
                                },
                                "title": {
                                    "type": "string",
                                    "description": "Short, descriptive title (e.g., 'Missing partition predicate')",
                                },
                                "recommendation": {
                                    "type": "string",
                                    "description": "Clear, actionable recommendation",
                                },
                                "fixes": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "type": {
                                                "type": "string",
                                                "enum": fix_types,
                                                "description": "Type of fix",
                                            },
                                            "snippet": {
                                                "type": "string",
                                                "description": "Code/SQL/config snippet (before/after if applicable)",
                                            },
                                            "notes": {
                                                "type": "string",
                                                "description": "Implementation notes and guidance",
                                            },
                                        },
                                        "required": ["type", "snippet", "notes"],
                                    },
                                    "description": "Concrete fix suggestions with code examples",
                                },
                                "proofs": {
                                    "type": "object",
                                    "properties": {
                                        "evidence": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": "Evidence from tool outputs (e.g., 'Query plan shows full table scan')",
                                        },
                                        "code_line_refs": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "object": {
                                                        "type": "string",
                                                        "description": "Object name (file, query, plan)",
                                                    },
                                                    "line": {
                                                        "type": "integer",
                                                        "description": "Line number",
                                                    },
                                                },
                                                "required": ["object", "line"],
                                            },
                                            "description": "References to specific lines in code/plans",
                                        },
                                        "references": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "title": {
                                                        "type": "string",
                                                        "description": "Reference title",
                                                    },
                                                    "url": {
                                                        "type": "string",
                                                        "description": "Documentation URL",
                                                    },
                                                    "cloud": {
                                                        "type": "string",
                                                        "description": "Cloud provider (aws, azure, gcp)",
                                                    },
                                                },
                                                "required": ["title", "url", "cloud"],
                                            },
                                            "description": "Links to Databricks documentation",
                                        },
                                    },
                                    "required": [
                                        "evidence",
                                        "code_line_refs",
                                        "references",
                                    ],
                                    "description": "Evidence supporting this finding",
                                },
                                "impact_estimate": {
                                    "type": "object",
                                    "properties": {
                                        "query_time_pct": {
                                            "type": "number",
                                            "description": "Query/job time impact % (negative = improvement, e.g., -40 = 40% faster)",
                                        },
                                        "data_read_pct": {
                                            "type": "number",
                                            "description": "Data read impact % (negative = reduction)",
                                        },
                                        "shuffle_pct": {
                                            "type": "number",
                                            "description": "Shuffle impact % (negative = reduction)",
                                        },
                                        "cost_pct": {
                                            "type": "number",
                                            "description": "Cost impact % (negative = savings)",
                                        },
                                        "confidence": {
                                            "type": "string",
                                            "enum": ["low", "medium", "high"],
                                            "description": "Confidence in impact estimate",
                                        },
                                    },
                                    "required": [
                                        "query_time_pct",
                                        "data_read_pct",
                                        "shuffle_pct",
                                        "cost_pct",
                                        "confidence",
                                    ],
                                    "description": "Quantified impact estimates",
                                },
                                "effort": {
                                    "type": "object",
                                    "properties": {
                                        "level": {
                                            "type": "string",
                                            "enum": ["low", "medium", "high"],
                                            "description": "Implementation effort level",
                                        },
                                        "estimate_hours": {
                                            "type": "number",
                                            "description": "Estimated implementation hours",
                                        },
                                    },
                                    "required": ["level", "estimate_hours"],
                                    "description": "Implementation effort estimate",
                                },
                                "risks": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Potential risks and caveats",
                                },
                                "rank": {
                                    "type": "integer",
                                    "description": "Priority ranking (1 = highest impact)",
                                },
                            },
                            "required": [
                                "id",
                                "category",
                                "title",
                                "recommendation",
                                "fixes",
                                "proofs",
                                "impact_estimate",
                                "effort",
                                "risks",
                                "rank",
                            ],
                        },
                        "description": "Detailed findings with evidence and impact",
                    },
                },
                "required": ["findings"],
                "description": "Analysis results with findings",
            },
            "testing_validation": {
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Step-by-step testing plan",
                    },
                    "metrics_to_track": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Metrics to measure (e.g., 'Query duration', 'Cost per run')",
                    },
                    "success_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Acceptance criteria (e.g., 'Query completes in <5s')",
                    },
                },
                "required": ["plan", "metrics_to_track", "success_criteria"],
                "description": "Testing and validation approach",
            },
            "next_steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rank": {
                            "type": "integer",
                            "description": "Priority ranking (1 = highest impact, 4 = lowest)",
                        },
                        "action": {
                            "type": "string",
                            "description": "Specific, actionable step to take (used as title)",
                        },
                        "expected_impact": {
                            "type": "string",
                            "description": "Expected benefit (e.g., '30% faster queries', '$500/mo cost savings')",
                        },
                        "effort": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "Implementation effort required",
                        },
                        "category": {
                            "type": "string",
                            "enum": categories,
                            "description": "Category of the next step",
                        },
                        "action_type": {
                            "type": "string",
                            "enum": ["continue", "route"],
                            "description": "continue = stay with current agent, route = hand off to another agent domain",
                        },
                        "target_agent": {
                            "type": "string",
                            "enum": [
                                "query",
                                "job",
                                "uc",
                                "compute",
                                "diagnostic",
                                "analytics",
                            ],
                            "description": "Target agent domain (only when action_type=route). Use 'uc' for table/Unity Catalog analysis.",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "Context to pass to the next action. Include relevant IDs and data discovered during analysis (e.g., tables, query_id, job_id, cluster_id).",
                            "additionalProperties": True,
                        },
                    },
                    "required": [
                        "rank",
                        "action",
                        "expected_impact",
                        "effort",
                        "category",
                    ],
                },
                "minItems": 1,
                "maxItems": 4,
                "description": "1-4 prioritized next steps ranked by total impact. For cross-domain handoffs (e.g., table optimization after query analysis), set action_type='route' and target_agent to the appropriate domain, and include discovered context in parameters.",
            },
        },
        "required": ["summary", "analysis", "testing_validation", "next_steps"],
        "additionalProperties": False,
    }

    # Add query_rewrite for query domain
    if domain == "query" and include_query_rewrite:
        schema["properties"]["analysis"]["properties"]["query_rewrite"] = {  # type: ignore[index]
            "type": "object",
            "properties": {
                "applicable": {
                    "type": "boolean",
                    "description": "Is a query rewrite applicable?",
                },
                "sql": {
                    "type": "string",
                    "description": "Complete rewritten SQL (if applicable)",
                },
                "notes": {
                    "type": "string",
                    "description": "Explanation of changes and improvements",
                },
            },
            "required": ["applicable", "sql", "notes"],
            "description": "Query rewrite suggestion",
        }
        schema["properties"]["analysis"]["required"].append("query_rewrite")  # type: ignore[index]

    return schema


# Pre-generated schemas for each domain (for convenience)
QUERY_OPTIMIZATION_SCHEMA = get_optimization_schema("query", include_query_rewrite=True)
JOB_OPTIMIZATION_SCHEMA = get_optimization_schema("job")
UC_OPTIMIZATION_SCHEMA = get_optimization_schema("uc")
COMPUTE_OPTIMIZATION_SCHEMA = get_optimization_schema("compute")
DIAGNOSTIC_OPTIMIZATION_SCHEMA = get_optimization_schema("diagnostic")
# Backward compatibility alias
TABLE_OPTIMIZATION_SCHEMA = UC_OPTIMIZATION_SCHEMA


def get_domain_categories(
    domain: Literal["query", "job", "uc", "compute", "diagnostic"],
) -> list[str]:
    """
    Get valid categories for a domain.

    Args:
        domain: Domain name

    Returns:
        List of valid category strings
    """
    mapping = {
        "query": QUERY_CATEGORIES,
        "job": JOB_CATEGORIES,
        "uc": TABLE_CATEGORIES,
        "compute": COMPUTE_CATEGORIES,
        "diagnostic": DIAGNOSTIC_CATEGORIES,
    }
    return mapping[domain]


def get_domain_fix_types(
    domain: Literal["query", "job", "uc", "compute", "diagnostic"],
) -> list[str]:
    """
    Get valid fix types for a domain.

    Args:
        domain: Domain name

    Returns:
        List of valid fix type strings
    """
    mapping = {
        "query": QUERY_FIX_TYPES,
        "job": JOB_FIX_TYPES,
        "uc": TABLE_FIX_TYPES,
        "compute": COMPUTE_FIX_TYPES,
        "diagnostic": ALL_FIX_TYPES,
    }
    return mapping[domain]

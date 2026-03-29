"""
Tool categorization for domain filtering (Phase 2).

This module implements the Pragmatic Hybrid (80/20) approach for tool sharing
across domain agents:

- 80% of operations: Agents complete independently (strategic tool overlap)
- 20% of complex operations: Delegate to domain specialist (no tool)

Design Principles:
1. Core tools shared by all agents (complete, request_user_input)
2. Frequent operations get shared tools (80% rule)
3. Complex/rare operations delegate to specialists (20% rule)
4. Domain experts get ALL tools in their domain
5. Diagnostic agent gets ALL tools (special case)

Tool Sharing Strategy:
- Query + Job agents share basic table tools (both need table metadata)
- Job + Cluster agents share basic cluster tools (jobs run on clusters)
- Table agent has exclusive access to advanced table operations
- Cluster agent has exclusive access to detailed cluster metrics
- Diagnostic agent can use any tool based on investigation needs
"""

from typing import Literal

# Type for domain specialists
AgentDomain = Literal[
    "router",
    "query",
    "job",
    "uc",
    "cluster",
    "analytics",
    "diagnostic",
    "warehouse",
    "discovery",
]


# =============================================================================
# Tool Category Mappings (Pragmatic Hybrid Approach)
# =============================================================================

TOOL_CATEGORIES: dict[str, list[str] | str] = {
    # =========================================================================
    # ROUTER AGENT - Minimal Tools (Intent Classification Only)
    # =========================================================================
    "router": [
        "resolve_user_intent",  # Classify user request
        "request_user_input",  # Request clarification (pauses and waits)
        "complete",  # Return routing decision
    ],
    # =========================================================================
    # QUERY AGENT - SQL Optimization (Primary + Strategic Table Overlap)
    # =========================================================================
    "query": [
        # Primary query tools (EXCLUSIVE)
        "resolve_query",  # Get SQL text from statement_id
        "analyze_query_plan",  # Run EXPLAIN and analyze execution plan
        "get_query_runtime_metrics",  # SHARED - Get actual execution metrics
        # Table tools (STRATEGIC OVERLAP - query optimization needs these)
        "get_table_metadata",  # SHARED - Need schemas, partitions, stats
        "discover_tables",  # SHARED - Extract table references from SQL
        "get_table_history",  # SHARED - Check recent table operations
        # Table tools (NO - Too specialized, delegate to table agent)
        # "get_table_lineage",  # Complex lineage tracing -> table agent
        # "get_enriched_table_metadata", # Enrichment operations -> table agent
        # Core tools
        "request_user_input",  # Request clarification (pauses and waits)
        "complete",  # Provide recommendations
    ],
    # =========================================================================
    # JOB AGENT - Job Optimization (Primary + Strategic Cluster/Table Overlap)
    # =========================================================================
    "job": [
        # Primary job tools (EXCLUSIVE)
        "resolve_job",  # Get job metadata from job_id or name
        "get_job_config",  # Retrieve job settings and task definitions
        "analyze_job_history",  # Review past runs, failures, durations
        "get_run_output",  # Get run output and logs for diagnostics
        "get_task_logs",  # Get logs for a specific task in a run
        "get_source_code",  # Fetch notebook/script source code
        "analyze_code_quality",  # Static analysis for anti-patterns
        # Cluster tools (STRATEGIC OVERLAP - jobs run on clusters)
        "get_cluster_config",  # SHARED - Jobs need cluster info
        "get_spark_logs",  # SHARED - Job analysis needs Spark logs (STANDARD jobs only)
        "get_cluster_metrics",  # SHARED - For SERVERLESS jobs (via system tables)
        # Cluster tools (NO - Too specialized, delegate to compute agent)
        # "get_cluster_events",  # Scaling events -> compute agent
        # "get_warehouse_metrics",      # Warehouse metrics -> compute agent
        # Table tools (STRATEGIC OVERLAP - jobs often work with tables)
        "get_table_metadata",  # SHARED - Jobs query tables
        "discover_tables",  # SHARED - Find tables in job code
        # Table tools (NO - Too specialized, delegate to table agent)
        # "get_table_history",   # Historical operations -> table agent if needed
        # "get_table_lineage",   # Complex lineage -> table agent
        # Core tools
        "request_user_input",  # Request clarification (pauses and waits)
        "complete",  # Provide recommendations
    ],
    # =========================================================================
    # UC AGENT - Unity Catalog Expert (ALL UC/Table Tools)
    # Replaces the deprecated "table" domain with extended governance capabilities
    # =========================================================================
    "uc": [
        # Phase 1 - Core UC Tools
        "list_uc_assets",  # List catalogs, schemas, tables, volumes, functions
        "get_table_metadata",  # Extended table metadata (schema + storage + stats)
        "get_table_lineage",  # Trace upstream/downstream deps
        "get_table_grants",  # Access policies and grants
        "analyze_table_schema",  # Schema analysis with anomaly detection
        "get_table_history",  # Delta version history
        "analyze_access_patterns",  # Query frequency, reader/writer tracking
        "analyze_schema_drift",  # Track schema changes over time
        # Phase 2 - Advanced UC Tools
        "analyze_storage_optimization",  # Storage optimization recommendations
        "analyze_query_impact",  # Query performance prediction
        "get_table_fingerprint",  # Comprehensive workload profile
        "analyze_table_costs",  # Per-table cost breakdown
        "generate_schema_diff",  # Version-aware schema comparison
        "analyze_policy_coverage",  # Security policy completeness
        # Legacy table tools (backward compatibility during transition)
        "get_enriched_table_metadata",  # Get enriched metadata for multiple tables
        "discover_tables",  # Find related tables in SQL/notebooks
        # Core tools
        "request_user_input",  # Request clarification (pauses and waits)
        "complete",  # Provide recommendations
    ],
    # =========================================================================
    # CLUSTER AGENT - Cluster Configuration Expert (Databricks Clusters)
    # =========================================================================
    "cluster": [
        # Cluster discovery (fleet overview)
        "list_clusters",  # EXCLUSIVE - List all clusters with recent activity
        # Cluster tools (DOMAIN EXPERT)
        "get_cluster_config",  # SHARED - Get cluster settings
        "get_cluster_health",  # EXCLUSIVE - Health scoring and risk analysis
        "get_cluster_metrics",  # EXCLUSIVE - CPU, memory, I/O metrics
        "get_cluster_events",  # EXCLUSIVE - Review scaling events
        # Spark logs (SHARED - multiple agents need this)
        "get_spark_logs",  # SHARED - Analyze resource utilization
        # Core tools
        "request_user_input",  # Request clarification (pauses and waits)
        "complete",  # Provide recommendations
    ],
    # =========================================================================
    # ANALYTICS AGENT - FinOps Cost Analysis (Agentic RAG)
    # =========================================================================
    "analytics": [
        # RAG context builder (agentic RAG)
        "build_analytics_context",
        # SQL Generation & Execution Tools (After RAG context gathered)
        "build_sql_query",  # Generate SQL from user query + RAG context
        "validate_sql_query",  # Validate SQL (syntax + EXPLAIN)
        "execute_sql_query",  # Execute validated SQL and return results
        # Core tools
        "request_user_input",  # Request clarification (pauses and waits)
        "complete",  # Provide cost analysis recommendations
    ],
    # =========================================================================
    # DIAGNOSTIC AGENT - Troubleshooting (ALL TOOLS AVAILABLE)
    # =========================================================================
    "diagnostic": "all",  # Special marker - gets unrestricted access
    # =========================================================================
    # WAREHOUSE AGENT - SQL Warehouse Portfolio Optimization
    # =========================================================================
    "warehouse": [
        # Portfolio analysis tools
        "get_warehouse_portfolio",  # List all warehouses with metrics
        "get_warehouse_fingerprint",  # Detailed warehouse analysis
        "get_warehouse_health",  # Health scoring and SLO compliance
        "get_query_runtime_metrics",  # SHARED - Query metrics for warehouse analysis
        # SLO management tools
        "configure_warehouse_slo",  # Configure SLO targets
        # Topology tools
        "analyze_warehouse_topology",  # Cross-warehouse analysis
        # User activity & chargeback
        "get_warehouse_user_activity",  # User activity breakdown
        "generate_warehouse_chargeback",  # Single warehouse chargeback
        "generate_portfolio_chargeback",  # Portfolio-wide chargeback
        # Core tools
        "request_user_input",  # Request clarification (pauses and waits)
        "complete",  # Provide recommendations
    ],
    # =========================================================================
    # DISCOVERY AGENT - Workspace Health Assessment (4-Phase Workflow)
    # =========================================================================
    "discovery": [
        # Phase 1: Audit active products
        "discover_active_products",
        # Phase 2: Execute query packs
        "run_discovery_queries",
        # Phase 3: Analyze domains (sync or async)
        "analyze_discovery_domain",
        "start_discovery_analysis",
        "get_discovery_analysis_progress",
        # Phase 4: Assemble final report
        "synthesize_discovery_report",
        # Core tools
        "request_user_input",
        "complete",
    ],
}


# =============================================================================
# Online Tools (Require Databricks API Calls)
# These tools are filtered out when offline_mode is enabled
# =============================================================================

ONLINE_TOOLS: set[str] = {
    # Job tools - require jobs API
    "resolve_job",
    "get_job_config",
    "analyze_job_history",
    "get_run_output",
    "get_task_logs",
    "get_source_code",
    # Cluster tools - require clusters API
    "list_clusters",
    "get_cluster_config",
    "get_cluster_health",
    "get_cluster_metrics",
    "get_cluster_events",
    "get_spark_logs",
    # Query tools - require SQL/warehouse API
    "resolve_query",
    "analyze_query_plan",
    "get_query_runtime_metrics",
    # Table/UC tools - require UC API
    "list_uc_assets",
    "get_table_metadata",
    "get_table_lineage",
    "get_table_grants",
    "analyze_table_schema",
    "get_table_history",
    "analyze_access_patterns",
    "analyze_schema_drift",
    "discover_tables",
    "get_enriched_table_metadata",
    "analyze_storage_optimization",
    "analyze_query_impact",
    "get_table_fingerprint",
    "analyze_table_costs",
    "generate_schema_diff",
    "analyze_policy_coverage",
    # Discovery tools - require Databricks SQL
    "discover_active_products",
    "run_discovery_queries",
    "analyze_discovery_domain",
    "start_discovery_analysis",
    "get_discovery_analysis_progress",
    "synthesize_discovery_report",
    "run_workspace_discovery",
    # Warehouse tools - require warehouse API
    "get_warehouse_portfolio",
    "get_warehouse_fingerprint",
    "get_warehouse_health",
    "configure_warehouse_slo",
    "analyze_warehouse_topology",
    "get_warehouse_user_activity",
    "generate_warehouse_chargeback",
    "generate_portfolio_chargeback",
    # Analytics v3 context builder
    "build_analytics_context",
    "build_sql_query",
    "validate_sql_query",
    "execute_sql_query",
}

# Offline-safe tools (work without Databricks API)
OFFLINE_TOOLS: set[str] = {
    # Core tools - always available
    "complete",
    "request_user_input",
    # Diagnostic tools - work on cached artifacts
    "explore_artifact",
    # Code analysis tools - work on provided code
    "analyze_code_quality",
    # User intent tools - work locally
    "resolve_user_intent",
}


# =============================================================================
# Tool Overlap Documentation
# =============================================================================

TOOL_OVERLAP_MATRIX = {
    # UC/Table tools - "uc" replaces "table"
    "get_table_metadata": ["query", "job", "uc", "diagnostic"],
    "discover_tables": ["query", "job", "uc", "diagnostic"],
    "get_table_history": ["query", "uc", "diagnostic"],
    "get_table_lineage": ["uc", "diagnostic"],  # UC expert only
    # New UC-specific tools (Phase 1)
    "list_uc_assets": ["uc", "diagnostic"],  # UC expert only
    "get_table_grants": ["uc", "diagnostic"],  # UC expert only
    "analyze_table_schema": ["uc", "diagnostic"],  # UC expert only
    "analyze_access_patterns": ["uc", "diagnostic"],  # UC expert only
    "analyze_schema_drift": ["uc", "diagnostic"],  # UC expert only
    # Cluster tools
    "list_clusters": ["cluster", "diagnostic"],  # Cluster discovery
    "get_cluster_config": ["job", "cluster", "diagnostic"],
    "get_cluster_health": [
        "cluster",
        "diagnostic",
    ],  # Health scoring - cluster expert only
    "get_spark_logs": ["job", "cluster", "diagnostic"],
    "get_cluster_metrics": ["cluster", "diagnostic"],  # Cluster expert only
    "get_cluster_events": ["cluster", "diagnostic"],  # Cluster expert only
    # Analytics/FinOps tools (Agentic RAG)
    "build_analytics_context": ["analytics", "diagnostic"],
    # SQL Generation tools (Analytics - agentic workflow)
    "build_sql_query": ["analytics", "diagnostic"],
    "validate_sql_query": ["analytics", "diagnostic"],
    "execute_sql_query": ["analytics", "diagnostic"],
    # Query runtime metrics (shared between query and warehouse)
    "get_query_runtime_metrics": ["query", "warehouse", "diagnostic"],
    # Core tools available to ALL domains
    "request_user_input": [
        "router",
        "query",
        "job",
        "uc",
        "cluster",
        "analytics",
        "diagnostic",
        "warehouse",
        "discovery",
    ],
    "complete": [
        "router",
        "query",
        "job",
        "uc",
        "cluster",
        "analytics",
        "diagnostic",
        "warehouse",
        "discovery",
    ],
    # Warehouse-specific tools (implemented tools only)
    "get_warehouse_portfolio": ["warehouse", "diagnostic"],
    "get_warehouse_fingerprint": ["warehouse", "diagnostic"],
    "get_warehouse_health": ["warehouse", "diagnostic"],
    "configure_warehouse_slo": ["warehouse", "diagnostic"],
    "analyze_warehouse_topology": ["warehouse", "diagnostic"],
    "get_warehouse_user_activity": ["warehouse", "diagnostic"],
    "generate_warehouse_chargeback": ["warehouse", "diagnostic"],
    "generate_portfolio_chargeback": ["warehouse", "diagnostic"],
}


# =============================================================================
# Tool Filtering Functions
# =============================================================================


def get_tools_for_domain(
    domain: AgentDomain,
    all_tools: list[str],
    offline_mode: bool = False,
) -> list[str]:
    """
    Get filtered tool list for a domain agent.

    Implements the Pragmatic Hybrid (80/20) approach:
    - Most agents get strategic subset of tools
    - Diagnostic agent gets all tools (special case)
    - Domain experts get all tools in their domain
    - If offline_mode=True, tools requiring Databricks API are filtered out

    Args:
        domain: Agent domain (router, query, job, table, compute, analytics, diagnostic)
        all_tools: Complete list of available tools
        offline_mode: If True, filter out tools that require Databricks API calls

    Returns:
        Filtered list of tool names for the domain

    Raises:
        ValueError: If domain is not recognized

    Example:
        >>> all_tools = ["resolve_query", "get_table_metadata", ...]
        >>> query_tools = get_tools_for_domain("query", all_tools)
        >>> "resolve_query" in query_tools
        True
        >>> "get_table_lineage" in query_tools  # Too specialized for query
        False
        >>>
        >>> # Diagnostic gets everything
        >>> diag_tools = get_tools_for_domain("diagnostic", all_tools)
        >>> len(diag_tools) == len(all_tools)
        True
        >>>
        >>> # Offline mode filters online tools
        >>> diag_offline = get_tools_for_domain("diagnostic", all_tools, offline_mode=True)
        >>> "get_job_config" in diag_offline
        False
        >>> "complete" in diag_offline
        True
    """
    if domain not in TOOL_CATEGORIES:
        raise ValueError(
            f"Unknown domain: {domain}. Must be one of: {list(TOOL_CATEGORIES.keys())}"
        )

    # Special case: Diagnostic agent gets all tools
    if domain == "diagnostic":
        base_tools = all_tools
    else:
        # Get domain's tool list
        domain_tools = TOOL_CATEGORIES[domain]

        # Ensure it's a list (not "all" marker)
        if not isinstance(domain_tools, list):
            raise ValueError(
                f"Invalid tool configuration for domain '{domain}': "
                f"expected list, got {type(domain_tools)}"
            )

        # Filter to only include tools that actually exist
        # (graceful handling of missing tools)
        base_tools = [tool for tool in domain_tools if tool in all_tools]

        # Warn if some configured tools are missing (excluding known runtime tools)
        # Runtime tools (complete, request_user_input) are registered dynamically during agent execution
        RUNTIME_TOOLS = {"complete", "request_user_input"}
        missing_tools = set(domain_tools) - set(all_tools)
        missing_non_runtime = missing_tools - RUNTIME_TOOLS

        if missing_non_runtime:
            from starboard_server.infra.observability.logging import get_logger

            logger = get_logger(__name__)
            logger.warning(
                f"Domain '{domain}' configured for missing tools",
                missing_tools=list(missing_non_runtime),
                configured=len(domain_tools),
                available=len(base_tools),
                note="Runtime tools (complete, request_user_input) are registered during execution",
            )

    # Apply offline mode filter
    if offline_mode:
        from starboard_server.infra.observability.logging import get_logger

        logger = get_logger(__name__)

        # Filter out online tools
        filtered_tools = [t for t in base_tools if t not in ONLINE_TOOLS]

        removed_count = len(base_tools) - len(filtered_tools)
        if removed_count > 0:
            logger.info(
                f"Offline mode: filtered {removed_count} online tools for {domain}",
                domain=domain,
                offline_mode=True,
                removed_count=removed_count,
                remaining_count=len(filtered_tools),
            )

        return filtered_tools

    return base_tools


def get_domains_for_tool(tool_name: str) -> list[str]:
    """
    Get list of domains that have access to a tool.

    Useful for understanding tool sharing patterns and
    debugging tool availability issues.

    Args:
        tool_name: Name of the tool

    Returns:
        List of domain names that can access this tool

    Example:
        >>> get_domains_for_tool("get_table_metadata")
        ['query', 'job', 'uc', 'diagnostic']
        >>>
        >>> get_domains_for_tool("get_table_lineage")
        ['uc', 'diagnostic']  # Only uc expert + diagnostic
    """
    if tool_name in TOOL_OVERLAP_MATRIX:
        return TOOL_OVERLAP_MATRIX[tool_name]

    # Check all domain tool lists
    domains = []
    for domain, tools in TOOL_CATEGORIES.items():
        if tools == "all" or (isinstance(tools, list) and tool_name in tools):
            domains.append(domain)

    return domains


def count_tools_by_domain(all_tools: list[str]) -> dict[str, int]:
    """
    Count how many tools each domain has access to.

    Useful for understanding tool distribution and
    verifying the 80/20 strategy.

    Args:
        all_tools: Complete list of available tools

    Returns:
        Dictionary mapping domain to tool count

    Example:
        >>> all_tools = get_all_available_tools()
        >>> counts = count_tools_by_domain(all_tools)
        >>> counts["query"] < counts["diagnostic"]  # Diagnostic has most
        True
        >>> counts["uc"] < counts["query"]  # UC is more focused
        True
    """
    counts = {}
    for domain in TOOL_CATEGORIES:
        tools = get_tools_for_domain(domain, all_tools)  # type: ignore
        counts[domain] = len(tools)
    return counts


def validate_tool_categories(all_tools: list[str]) -> dict[str, list[str]]:
    """
    Validate tool category configuration.

    Checks for:
    - Unknown tools in TOOL_CATEGORIES
    - Domains with no tools
    - Core tools missing from domains

    Args:
        all_tools: Complete list of available tools

    Returns:
        Dictionary of validation errors by domain (empty if valid)

    Example:
        >>> all_tools = get_all_available_tools()
        >>> errors = validate_tool_categories(all_tools)
        >>> len(errors) == 0  # Should have no errors
        True
    """
    errors = {}

    for domain, tools in TOOL_CATEGORIES.items():
        domain_errors = []

        # Skip "all" marker (diagnostic)
        if tools == "all":
            continue

        if not isinstance(tools, list):
            domain_errors.append(f"Invalid tools type: {type(tools)}")
            errors[domain] = domain_errors
            continue

        # Check for unknown tools
        unknown = set(tools) - set(all_tools)
        if unknown:
            domain_errors.append(f"Unknown tools: {unknown}")

        # Check for empty tool lists
        if not tools:
            domain_errors.append("No tools configured")

        # Check that core tools are present (except router)
        if domain != "router" and "complete" not in tools:
            domain_errors.append("Missing 'complete' tool")

        if domain_errors:
            errors[domain] = domain_errors

    return errors

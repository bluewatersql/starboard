"""Tool factory for multi-agent reasoning framework.

This module provides a factory function to create and register native
tools with the ToolRegistry, making them available for dynamic tool selection.

Architecture:
    - Native Tools: Dict-based tools using NativeToolAdapter
      * QueryTools, JobTools, UCTools, ClusterTools, SourceTools, IntentTools
      * AnalyticsTools, WarehouseTools
      * RequestUserInputTool
      * Clean signature: async def tool(**kwargs) -> dict[str, Any]
      * Fast, type-safe, no JSON serialization overhead
      * ALL tools use unified architecture with SharedContextProvider + transforms

Context Management:
    Tools use SharedContextProvider directly with transforms module:
    - QueryTools.from_provider() - uses transforms for EXPLAIN plans
    - JobTools.from_provider() - uses transforms for job metadata
    - ClusterTools.from_provider() - uses transforms for cluster/warehouse/query

    No facade layer needed - direct provider + transforms pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard_server.adapters.databricks.async_sql_executor import AsyncSQLExecutor
from starboard_server.adapters.llm import create_llm_client
from starboard_server.adapters.state.inmemory.cache_store import InMemoryCacheStore
from starboard_server.agents.tools.registry import ALL_TOOL_METADATA
from starboard_server.agents.tools.tool_registry import (
    NativeToolAdapter,
    ToolMetadata,
    ToolRegistry,
)
from starboard_server.infra.core.config import EnvConfig, get_config
from starboard_server.infra.observability.events import EventEmitter
from starboard_server.infra.observability.logging import get_logger
from starboard_server.services.context.provider import SharedContextProvider

# Import tool adapters (native dict-based tools)
from starboard_server.tools.adapters.analytics_sql_tools import AnalyticsSQLTools
from starboard_server.tools.adapters.cluster_tools import ClusterTools
from starboard_server.tools.adapters.diagnostic_tools import DiagnosticTools
from starboard_server.tools.adapters.discovery_tools import DiscoveryTools
from starboard_server.tools.adapters.intent_tools import IntentTools
from starboard_server.tools.adapters.job_tools import JobTools
from starboard_server.tools.adapters.query_tools import QueryTools
from starboard_server.tools.adapters.rag_tools import AnalyticsContextTools
from starboard_server.tools.adapters.source_tools import SourceTools
from starboard_server.tools.adapters.uc_tools import UCTools
from starboard_server.tools.adapters.warehouse_data_provider import (
    WarehouseDataAdapter,
)
from starboard_server.tools.adapters.warehouse_tools import WarehouseTools
from starboard_server.tools.domain.analytics_sql.sql_validator import SQLValidator
from starboard_server.tools.request_user_input_tool import RequestUserInputTool
from starboard_server.tools.services.query_result_cache import QueryResultCache
from starboard_server.tools.services.warehouse_portfolio_service import (
    WarehousePortfolioService,
)

if TYPE_CHECKING:
    from starboard_server.adapters.databricks import AsyncDatabricksClient

logger = get_logger(__name__)


def _ensure_llm_client(llm_client: Any | None, env_config: EnvConfig) -> Any:
    """Ensure LLM client is available, creating default if needed.

    Args:
        llm_client: Optional existing LLM client
        env_config: Environment configuration

    Returns:
        LLM client instance
    """
    if llm_client is None:
        logger.warning(
            "llm_client_missing_for_templates",
            action="creating_default_client",
        )
        return create_llm_client(cfg=env_config)
    return llm_client


def create_tool_registry(
    api: AsyncDatabricksClient,
    provider: SharedContextProvider,
    events: EventEmitter | None = None,
    input_callback: Any | None = None,  # noqa: ARG001
    llm_client: Any | None = None,
    cache_store: Any | None = None,
    cache_factory: Any | None = None,
    semantic_cache: Any | None = None,  # noqa: ARG001
    reflexion_store: Any | None = None,  # noqa: ARG001
    vector_store: Any | None = None,
    embedding_service: Any | None = None,
) -> tuple[ToolRegistry, RequestUserInputTool]:
    """Create and populate a ToolRegistry with all agent tools.

    Creates tool instances using SharedContextProvider + transforms pattern,
    instantiates all tool classes with dependencies, and registers them with metadata.

    Args:
        api: Async Databricks client
        provider: Shared context provider (wraps caching and data fetching)
        events: Optional event emitter for status updates
        input_callback: Unused (kept for backwards compatibility)
        llm_client: Optional LLM client for code analysis and analytics
        cache_store: Optional shared cache store for query result caching
        cache_factory: Optional CacheFactory for artifact exploration tools
        semantic_cache: Unused (kept for backwards compatibility)
        reflexion_store: Unused (kept for backwards compatibility)
        vector_store: Optional vector store for RAG discovery
        embedding_service: Optional embedding service for RAG

    Returns:
        Tuple of (ToolRegistry, RequestUserInputTool instance)
    """
    logger.debug("Creating tool registry with native dict-based tools")
    registry = ToolRegistry()

    # Instantiate core tool classes
    logger.debug("Creating core tools with direct provider architecture")
    job_tools = JobTools.from_provider(provider, events=events)
    query_tools = QueryTools.from_provider(api, provider, events=events)
    uc_tools = UCTools(api, llm_client, events)
    source_tools = SourceTools(api, llm_client, events)
    intent_tools = IntentTools(events=events)
    cluster_tools = ClusterTools.from_provider(provider, events=events)

    # Create or use provided cache store
    if cache_store is None:
        logger.debug("Creating new cache store for result caching")
        cache_store = InMemoryCacheStore()
    else:
        logger.debug(
            "Using provided cache store from container (shared with visualization endpoint)"
        )

    # Create analytics tools (FinOps, system queries)
    logger.debug("Instantiating analytics SQL tools")
    env_config = get_config()
    llm_client = _ensure_llm_client(llm_client, env_config)

    # Create SQL executor and result cache
    sql_executor = AsyncSQLExecutor(api, default_cache_ttl=300)
    result_cache = QueryResultCache(
        cache_store=cache_store,
        default_ttl=3600,  # 60 minutes (with reset-on-hit)
    )

    # Create analytics SQL tools (direct initialization)
    analytics_sql_tools = AnalyticsSQLTools(
        llm_client=llm_client,
        sql_executor=sql_executor,
        sql_validator=SQLValidator(sql_executor=sql_executor),
        result_cache=result_cache,
    )

    logger.info(
        "analytics_sql_tools_initialized",
        workflow="agentic_rag",
        tools=["build", "validate", "execute"],
    )

    # Import types for proper type checking
    from starboard_server.infra.rag.domain.protocols import (
        EmbeddingProvider,
        MultiCollectionStore,
    )

    # Create analytics context tools only if vector store and embedding service are available
    analytics_context_tools = None
    if vector_store is not None and embedding_service is not None:
        # Type guard for vector_store and embedding_service
        if not isinstance(vector_store, MultiCollectionStore):
            raise TypeError(
                f"vector_store must be MultiCollectionStore, got {type(vector_store)}"
            )
        if not isinstance(embedding_service, EmbeddingProvider):
            raise TypeError(
                f"embedding_service must be EmbeddingProvider, got {type(embedding_service)}"
            )

        analytics_context_tools = AnalyticsContextTools(
            vector_store=vector_store,
            embedding_provider=embedding_service,
            analytics_sql_tools=analytics_sql_tools,  # Inject for context handle storage
        )
        logger.info(
            "analytics_context_tools_initialized",
            workflow="agentic_rag",
            tools=["build_analytics_context"],
        )
    else:
        logger.warning(
            "analytics_context_tools_disabled",
            reason="vector_store or embedding_service not provided",
            vector_store_provided=vector_store is not None,
            embedding_service_provided=embedding_service is not None,
        )

    # Create warehouse tools
    logger.debug("Creating warehouse portfolio tools")
    warehouse_data_adapter = WarehouseDataAdapter(api)
    # WarehousePortfolioService refactored to use AsyncSQLExecutor directly
    warehouse_service = WarehousePortfolioService(
        sql_executor=sql_executor,
        warehouse_data=warehouse_data_adapter,
    )
    warehouse_tools = WarehouseTools(
        warehouse_service=warehouse_service,
        events=events,
        provider=provider,
    )

    # Create diagnostic tools if cache_factory provided
    diagnostic_tools: DiagnosticTools | None = None
    if cache_factory:
        logger.debug("Creating diagnostic tools with artifact exploration")
        diagnostic_tools = DiagnosticTools(
            attachments_cache=cache_factory.get_or_create("attachments"),
            events=events,
        )

    # Create discovery tools
    logger.debug("Creating discovery tools")
    discovery_tools = DiscoveryTools(
        sql_executor=sql_executor,
        llm_client=llm_client,
        env_config=env_config,
    )

    # Tool mapping: tool_name -> (instance, method_name)
    tool_mapping = {
        # Intent resolution tools
        "resolve_user_intent": (intent_tools, "resolve_user_intent"),
        # Query tools
        "resolve_query": (query_tools, "resolve_query"),
        "analyze_query_plan": (query_tools, "analyze_query_plan"),
        "analyze_explain_plan": (query_tools, "analyze_explain_plan"),
        # Table/UC tools - Phase 1 (Core)
        "list_uc_assets": (uc_tools, "enumerate_uc_assets"),
        "get_table_metadata": (uc_tools, "fetch_uc_table_metadata"),
        "get_table_history": (uc_tools, "fetch_delta_history"),
        "discover_tables": (uc_tools, "discover_tables_from_source"),
        "get_table_lineage": (uc_tools, "fetch_table_lineage"),
        "get_enriched_table_metadata": (uc_tools, "enrich_table_references"),
        "get_table_grants": (uc_tools, "fetch_table_grants"),
        "analyze_table_schema": (uc_tools, "analyze_table_schema"),
        "analyze_access_patterns": (uc_tools, "analyze_access_patterns"),
        "analyze_schema_drift": (uc_tools, "detect_schema_drift"),
        # Table/UC tools - Phase 2 (Advanced)
        "analyze_storage_optimization": (uc_tools, "recommend_storage_optimization"),
        "analyze_query_impact": (uc_tools, "analyze_query_impact"),
        "get_table_fingerprint": (uc_tools, "fetch_table_fingerprint"),
        "analyze_table_costs": (uc_tools, "attribute_table_costs"),
        "generate_schema_diff": (uc_tools, "generate_schema_diff"),
        "analyze_policy_coverage": (uc_tools, "analyze_policy_coverage"),
        # Job tools
        "resolve_job": (job_tools, "resolve_job"),
        "get_job_config": (job_tools, "get_job_config"),
        "analyze_job_history": (job_tools, "analyze_job_history"),
        "get_run_output": (job_tools, "get_run_output"),
        "get_task_logs": (job_tools, "get_task_logs"),
        # Source code tools
        "analyze_code_quality": (source_tools, "analyze_code_quality"),
        "get_source_code": (source_tools, "get_source_code"),
        # Cluster tools (domain-aligned architecture)
        "list_clusters": (cluster_tools, "list_clusters"),
        "get_cluster_config": (cluster_tools, "get_cluster_config"),
        "get_cluster_health": (cluster_tools, "get_cluster_health"),
        "get_cluster_events": (cluster_tools, "get_cluster_events"),
        "get_cluster_metrics": (cluster_tools, "get_cluster_metrics"),
        "get_spark_logs": (cluster_tools, "get_spark_logs"),
        # Basic warehouse config/metrics tools (migrated from ClusterTools to WarehouseTools)
        "get_warehouse_config": (warehouse_tools, "get_warehouse_config"),
        "get_warehouse_metrics": (warehouse_tools, "get_warehouse_metrics"),
        "get_query_runtime_metrics": (warehouse_tools, "get_query_runtime_metrics"),
        # Analytics tools (Agentic RAG Workflow)
        "build_sql_query": (analytics_sql_tools, "build_sql_query"),
        "validate_sql_query": (analytics_sql_tools, "validate_sql_query"),
        "execute_sql_query": (analytics_sql_tools, "execute_sql_query"),
        # Warehouse portfolio tools
        "get_warehouse_portfolio": (warehouse_tools, "get_warehouse_portfolio"),
        "get_warehouse_fingerprint": (warehouse_tools, "get_warehouse_fingerprint"),
        "get_warehouse_health": (warehouse_tools, "get_warehouse_health"),
        "configure_warehouse_slo": (warehouse_tools, "configure_warehouse_slo"),
        "analyze_warehouse_topology": (warehouse_tools, "analyze_warehouse_topology"),
        "get_warehouse_user_activity": (warehouse_tools, "get_warehouse_user_activity"),
        "generate_warehouse_chargeback": (
            warehouse_tools,
            "generate_warehouse_chargeback",
        ),
        "generate_portfolio_chargeback": (
            warehouse_tools,
            "generate_portfolio_chargeback",
        ),
        # Discovery tools (granular 4-phase workflow)
        "discover_active_products": (discovery_tools, "discover_active_products"),
        "run_discovery_queries": (discovery_tools, "run_discovery_queries"),
        "analyze_discovery_domain": (discovery_tools, "analyze_discovery_domain"),
        "synthesize_discovery_report": (discovery_tools, "synthesize_discovery_report"),
        # Discovery tools (legacy monolithic)
        "run_workspace_discovery": (discovery_tools, "run_workspace_discovery"),
    }

    # Register diagnostic tools if available
    if diagnostic_tools:
        tool_mapping["explore_artifact"] = (diagnostic_tools, "explore_artifact")

    # Register analytics context tools if available (requires vector store + embeddings)
    if analytics_context_tools:
        tool_mapping["build_analytics_context"] = (
            analytics_context_tools,
            "build_analytics_context",
        )

    # Always register request_user_input tool (works in all contexts)
    request_input_tool = RequestUserInputTool(events=events, timeout_seconds=300.0)
    tool_mapping["request_user_input"] = (
        request_input_tool,
        "request_user_input",
    )

    # Register each tool with its metadata and adapter
    logger.debug("Registering {len(tool_mapping)} tools")
    registered_count = 0

    for tool_name, (tool_instance, method_name) in tool_mapping.items():
        try:
            if tool_name not in ALL_TOOL_METADATA:
                logger.warning("No metadata found for tool: {tool_name}, skipping")
                continue

            metadata_dict = ALL_TOOL_METADATA[tool_name]
            metadata = ToolMetadata(
                name=metadata_dict["name"],
                description=metadata_dict["description"],
                parameters=metadata_dict["parameters"],
            )

            adapter = NativeToolAdapter(
                tool_instance=tool_instance,
                method_name=method_name,
                metadata=metadata,
            )

            registry.register(tool_name, adapter)
            registered_count += 1

        except (ImportError, AttributeError, TypeError) as e:
            logger.error("Failed to register tool", tool_name=tool_name, error=str(e))
            continue

    logger.debug(
        f"Successfully registered {registered_count}/{len(tool_mapping)} tools",
        available_tools=registry.list_tools(),
    )

    return registry, request_input_tool


def get_tool_count() -> int:
    """
    Get the total number of tools that will be registered.

    Returns:
        Number of tools
    """
    return len(ALL_TOOL_METADATA)


def validate_tool_metadata() -> dict[str, list[str]]:
    """
    Validate all tool metadata for correctness.

    Returns:
        Dictionary with validation results:
        - "valid": List of valid tool names
        - "invalid": List of tool names with issues
        - "errors": List of error messages
    """
    valid = []
    invalid = []
    errors = []

    for tool_name, metadata_dict in ALL_TOOL_METADATA.items():
        try:
            # Check required fields
            if "name" not in metadata_dict:
                errors.append(f"{tool_name}: missing 'name' field")
                invalid.append(tool_name)
                continue

            if "description" not in metadata_dict:
                errors.append(f"{tool_name}: missing 'description' field")
                invalid.append(tool_name)
                continue

            if "parameters" not in metadata_dict:
                errors.append(f"{tool_name}: missing 'parameters' field")
                invalid.append(tool_name)
                continue

            # Validate parameters structure
            params = metadata_dict["parameters"]
            if not isinstance(params, dict):
                errors.append(f"{tool_name}: 'parameters' must be a dict")
                invalid.append(tool_name)
                continue

            if "type" not in params:
                errors.append(f"{tool_name}: parameters missing 'type' field")
                invalid.append(tool_name)
                continue

            if params["type"] == "object" and "properties" not in params:
                errors.append(f"{tool_name}: object parameters missing 'properties'")
                invalid.append(tool_name)
                continue

            # All checks passed
            valid.append(tool_name)

        except (TypeError, ValueError, KeyError) as e:
            errors.append(f"{tool_name}: validation error: {str(e)}")
            invalid.append(tool_name)

    return {"valid": valid, "invalid": invalid, "errors": errors}

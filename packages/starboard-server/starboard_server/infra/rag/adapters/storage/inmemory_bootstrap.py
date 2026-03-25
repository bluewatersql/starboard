# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Bootstrap data loader for in-memory vector store.

Provides essential Databricks system table metadata and best practices
to seed the in-memory vector store for CLI and development usage.

This enables the Analytics Agent to generate SQL queries even without
a fully populated vector store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from starboard_core.rag.models import (
    RAGNuanceContext,
    RAGTableContext,
)

from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_server.infra.rag.adapters.storage.inmemory_vector_store import (
        InMemoryMultiCollectionStore,
    )

logger = get_logger(__name__)


class InMemoryVectorStoreBootstrap:
    """Bootstrap in-memory vector store with essential RAG data.

    Provides minimal but sufficient context for common analytics queries:
    - System billing tables (usage, list_prices)
    - Compute warehouse tables
    - Job/cluster tables
    - Common SQL patterns and best practices
    """

    # Essential Databricks system tables for analytics
    ESSENTIAL_TABLES: ClassVar[list[dict[str, Any]]] = [
        # Billing domain
        {
            "table_name": "system.billing.usage",
            "domain": "finops_billing",
            "catalog": "system",
            "schema": "billing",
            "description": "Databricks billing usage records with DBU consumption and list costs by SKU",
            "columns": [
                {
                    "name": "workspace_id",
                    "type": "string",
                    "description": "Unique identifier for the workspace",
                },
                {
                    "name": "sku_name",
                    "type": "string",
                    "description": "SKU name for the service (e.g., JOBS_COMPUTE, SQL_WAREHOUSE)",
                },
                {
                    "name": "usage_date",
                    "type": "date",
                    "description": "Date of usage (YYYY-MM-DD)",
                },
                {
                    "name": "usage_start_time",
                    "type": "timestamp",
                    "description": "Start timestamp of usage period",
                },
                {
                    "name": "usage_end_time",
                    "type": "timestamp",
                    "description": "End timestamp of usage period",
                },
                {
                    "name": "usage_quantity",
                    "type": "decimal",
                    "description": "Quantity of usage in DBUs",
                },
                {
                    "name": "usage_unit",
                    "type": "string",
                    "description": "Unit of measurement (DBU)",
                },
                {
                    "name": "custom_tags",
                    "type": "map<string,string>",
                    "description": "Custom tags for cost attribution",
                },
            ],
        },
        {
            "table_name": "system.billing.list_prices",
            "domain": "finops_billing",
            "catalog": "system",
            "schema": "billing",
            "description": "List prices for Databricks SKUs by cloud region and date range",
            "columns": [
                {
                    "name": "sku_name",
                    "type": "string",
                    "description": "SKU name matching system.billing.usage",
                },
                {
                    "name": "cloud",
                    "type": "string",
                    "description": "Cloud provider (AWS, Azure, GCP)",
                },
                {
                    "name": "region",
                    "type": "string",
                    "description": "Cloud region",
                },
                {
                    "name": "pricing_start_time",
                    "type": "timestamp",
                    "description": "Price effective start time",
                },
                {
                    "name": "pricing_end_time",
                    "type": "timestamp",
                    "description": "Price effective end time (null if current)",
                },
                {
                    "name": "list_price",
                    "type": "decimal",
                    "description": "List price per DBU in local currency",
                },
                {
                    "name": "currency_code",
                    "type": "string",
                    "description": "Currency code (USD, EUR, etc.)",
                },
            ],
        },
        # Warehouse domain
        {
            "table_name": "system.compute.warehouse_events",
            "domain": "compute_warehouses",
            "catalog": "system",
            "schema": "compute",
            "description": "SQL warehouse lifecycle events and state changes",
            "columns": [
                {
                    "name": "warehouse_id",
                    "type": "string",
                    "description": "Unique identifier for the warehouse",
                },
                {
                    "name": "warehouse_name",
                    "type": "string",
                    "description": "Human-readable warehouse name",
                },
                {
                    "name": "timestamp",
                    "type": "timestamp",
                    "description": "Event timestamp",
                },
                {
                    "name": "event_type",
                    "type": "string",
                    "description": "Event type (STARTING, RUNNING, STOPPING, etc.)",
                },
                {
                    "name": "cluster_size",
                    "type": "string",
                    "description": "Warehouse size (XSMALL, SMALL, MEDIUM, etc.)",
                },
            ],
        },
        {
            "table_name": "system.query.history",
            "domain": "compute_warehouses",
            "catalog": "system",
            "schema": "query",
            "description": "SQL query execution history with performance metrics",
            "columns": [
                {
                    "name": "statement_id",
                    "type": "string",
                    "description": "Unique identifier for the query",
                },
                {
                    "name": "warehouse_id",
                    "type": "string",
                    "description": "Warehouse that executed the query",
                },
                {
                    "name": "start_time",
                    "type": "timestamp",
                    "description": "Query start time",
                },
                {
                    "name": "end_time",
                    "type": "timestamp",
                    "description": "Query end time",
                },
                {
                    "name": "execution_duration",
                    "type": "bigint",
                    "description": "Execution duration in milliseconds",
                },
                {
                    "name": "query_text",
                    "type": "string",
                    "description": "SQL query text",
                },
                {
                    "name": "rows_produced",
                    "type": "bigint",
                    "description": "Number of rows returned",
                },
            ],
        },
        # Jobs domain
        {
            "table_name": "system.compute.clusters",
            "domain": "compute_jobs",
            "catalog": "system",
            "schema": "compute",
            "description": "Cluster metadata and configuration",
            "columns": [
                {
                    "name": "cluster_id",
                    "type": "string",
                    "description": "Unique identifier for the cluster",
                },
                {
                    "name": "cluster_name",
                    "type": "string",
                    "description": "Human-readable cluster name",
                },
                {
                    "name": "cluster_source",
                    "type": "string",
                    "description": "Cluster source (JOB, UI, API)",
                },
                {
                    "name": "node_type_id",
                    "type": "string",
                    "description": "EC2/VM instance type",
                },
                {
                    "name": "driver_node_type_id",
                    "type": "string",
                    "description": "Driver node instance type",
                },
            ],
        },
    ]

    # Essential SQL patterns and best practices
    ESSENTIAL_NUANCE = [
        # Billing patterns
        {
            "content": "Always filter system.billing.usage by usage_date with explicit date range (WHERE usage_date BETWEEN '...' AND '...') for optimal query performance. Avoid scanning entire table.",
            "domain": "finops_billing",
            "category": "performance",
            "source": "bootstrap",
        },
        {
            "content": "Join system.billing.usage with system.billing.list_prices on sku_name and usage_date (WHERE usage_date BETWEEN pricing_start_time AND COALESCE(pricing_end_time, CURRENT_DATE())) to calculate accurate list costs.",
            "domain": "finops_billing",
            "category": "join_pattern",
            "source": "bootstrap",
        },
        {
            "content": "Calculate total cost using: SUM(usage_quantity * list_price) AS total_cost. Group by appropriate dimensions (workspace_id, sku_name, usage_date, etc.).",
            "domain": "finops_billing",
            "category": "aggregation",
            "source": "bootstrap",
        },
        {
            "content": "For month-over-month cost analysis, use DATE_TRUNC('month', usage_date) to group by month. For daily trends, group by usage_date directly.",
            "domain": "finops_billing",
            "category": "time_series",
            "source": "bootstrap",
        },
        {
            "content": "Use custom_tags from system.billing.usage for cost attribution by team, project, or environment. Filter with: WHERE custom_tags['team'] = 'data-engineering'",
            "domain": "finops_billing",
            "category": "cost_attribution",
            "source": "bootstrap",
        },
        # Warehouse patterns
        {
            "content": "Query system.compute.warehouse_events to analyze warehouse uptime and idle time. Calculate uptime as: SUM(TIMESTAMPDIFF(SECOND, lag(timestamp), timestamp)) WHERE event_type = 'RUNNING'",
            "domain": "compute_warehouses",
            "category": "analysis",
            "source": "bootstrap",
        },
        {
            "content": "Join system.query.history with system.billing.usage on warehouse_id to correlate query performance with costs. Use statement_id for detailed query analysis.",
            "domain": "compute_warehouses",
            "category": "join_pattern",
            "source": "bootstrap",
        },
        {
            "content": "For warehouse utilization analysis, calculate concurrent queries: COUNT(DISTINCT statement_id) OVER (PARTITION BY warehouse_id ORDER BY start_time) per time window.",
            "domain": "compute_warehouses",
            "category": "analysis",
            "source": "bootstrap",
        },
        # General best practices
        {
            "content": "Always include date range filters in WHERE clause for system tables to avoid full table scans. Use CURRENT_DATE() - INTERVAL 30 DAYS for last 30 days.",
            "domain": "general",
            "category": "performance",
            "source": "bootstrap",
        },
        {
            "content": "Use LIMIT clause when exploring data or testing queries to avoid processing large result sets. Remove LIMIT for production queries.",
            "domain": "general",
            "category": "performance",
            "source": "bootstrap",
        },
        {
            "content": "For top-N queries (most expensive, slowest, etc.), use ORDER BY metric DESC LIMIT N. Add WHERE clause to filter before sorting.",
            "domain": "general",
            "category": "pattern",
            "source": "bootstrap",
        },
        {
            "content": "When aggregating by time, use DATE_TRUNC() for consistent grouping: DATE_TRUNC('hour'|'day'|'week'|'month', timestamp_column)",
            "domain": "general",
            "category": "time_series",
            "source": "bootstrap",
        },
    ]

    @staticmethod
    async def bootstrap(
        store: InMemoryMultiCollectionStore,
        include_tables: bool = True,
        include_nuance: bool = True,
    ) -> dict[str, int]:
        """Seed in-memory store with essential RAG data.

        Args:
            store: In-memory vector store to populate
            include_tables: Whether to add essential tables
            include_nuance: Whether to add essential nuance/best practices

        Returns:
            Dictionary with counts of added items

        Raises:
            ValueError: If store is not initialized
        """
        if not store._initialized:
            raise ValueError("Store must be initialized before bootstrapping")

        logger.info("bootstrap_inmemory_vector_store_start")

        counts = {"tables": 0, "nuance": 0}

        # Add essential tables
        if include_tables:
            tables = [
                RAGTableContext(
                    table_name=t["table_name"],
                    domain=t["domain"],
                    description=t["description"],
                    table_columns=", ".join(c["name"] for c in t["columns"]),
                    relationships="",  # Will be enriched later
                    use_cases="",  # Will be enriched later
                    relevance_score=1.0,
                )
                for t in InMemoryVectorStoreBootstrap.ESSENTIAL_TABLES
            ]

            await store.add_tables(tables)
            counts["tables"] = len(tables)

        # Add essential nuance
        if include_nuance:
            nuance = [
                RAGNuanceContext(
                    topic=n["category"],
                    type=n["category"],
                    content=n["content"],
                    domain=n["domain"],
                    relevance_score=1.0,
                )
                for n in InMemoryVectorStoreBootstrap.ESSENTIAL_NUANCE
            ]

            await store.add_nuance(nuance)
            counts["nuance"] = len(nuance)

        logger.info(
            "bootstrap_inmemory_vector_store_complete",
            tables_count=counts["tables"],
            nuance_count=counts["nuance"],
            store_stats=store.get_stats(),
        )

        return counts

    async def close(self) -> None:
        """Release resources (no-op for this store)."""

    async def connect(self) -> None:
        """Initialize connection (no-op for this store)."""

    async def delete(self, _key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, _key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, _key: str, _value: object) -> None:
        """Generic key-value set (Protocol compliance)."""

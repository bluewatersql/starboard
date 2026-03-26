"""RAG resource-model domains for Analytics context building.

These domains represent Databricks' resource-model alignment for RAG retrieval,
and are intentionally distinct from Starboard's *agent routing domains*
(analytics/job/query/warehouse/cluster/etc.).

This module is the single source of truth for:
- The canonical domain labels used in the RAG vector store metadata field
  `rag_resource_domain`
- Mapping Databricks system tables (e.g. ``system.query.history``) to one or more
  RAG resource domains
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum


class RagResourceDomain(StrEnum):
    """Databricks resource-model domains used for RAG filtering."""

    WORKSPACE_ADMIN = "workspace_admin"
    SECURITY_ACCESS = "security_access"
    GOVERNANCE_UNITY_CATALOG = "governance_unity_catalog"
    GOVERNANCE_SHARING = "governance_sharing"
    GOVERNANCE_CLEAN_ROOMS = "governance_clean_rooms"
    LINEAGE = "lineage"
    NETWORK = "network"
    FINOPS_BILLING = "finops_billing"
    COMPUTE_CLUSTERS = "compute_clusters"
    COMPUTE_WAREHOUSES = "compute_warehouses"
    WORKLOAD_JOBS = "workload_jobs"
    WORKLOAD_PIPELINES = "workload_pipelines"
    QUERY = "query"
    MLFLOW = "mlflow"
    SERVING = "serving"
    STORAGE_OPTIMIZATION = "storage_optimization"


@dataclass(frozen=True)
class TableDomainMapping:
    table: str
    domains: tuple[RagResourceDomain, ...]


_EXACT: Mapping[str, tuple[RagResourceDomain, ...]] = {
    # system.access.*
    "system.access.assistant_events": (RagResourceDomain.SECURITY_ACCESS,),
    "system.access.audit": (
        RagResourceDomain.SECURITY_ACCESS,
        RagResourceDomain.WORKSPACE_ADMIN,
    ),
    "system.access.clean_room_events": (
        RagResourceDomain.GOVERNANCE_CLEAN_ROOMS,
        RagResourceDomain.SECURITY_ACCESS,
    ),
    "system.access.column_lineage": (
        RagResourceDomain.LINEAGE,
        RagResourceDomain.GOVERNANCE_UNITY_CATALOG,
    ),
    "system.access.inbound_network": (
        RagResourceDomain.NETWORK,
        RagResourceDomain.SECURITY_ACCESS,
    ),
    "system.access.outbound_network": (
        RagResourceDomain.NETWORK,
        RagResourceDomain.SECURITY_ACCESS,
    ),
    "system.access.table_lineage": (
        RagResourceDomain.LINEAGE,
        RagResourceDomain.GOVERNANCE_UNITY_CATALOG,
    ),
    "system.access.workspaces_latest": (RagResourceDomain.WORKSPACE_ADMIN,),
    # system.billing.*
    "system.billing.account_prices": (RagResourceDomain.FINOPS_BILLING,),
    "system.billing.cloud_infra_cost": (RagResourceDomain.FINOPS_BILLING,),
    "system.billing.list_prices": (RagResourceDomain.FINOPS_BILLING,),
    "system.billing.usage": (RagResourceDomain.FINOPS_BILLING,),
    # system.compute.*
    "system.compute.clusters": (RagResourceDomain.COMPUTE_CLUSTERS,),
    "system.compute.node_timeline": (RagResourceDomain.COMPUTE_CLUSTERS,),
    "system.compute.node_types": (RagResourceDomain.COMPUTE_CLUSTERS,),
    "system.compute.warehouse_events": (
        RagResourceDomain.COMPUTE_WAREHOUSES,
        RagResourceDomain.QUERY,
    ),
    "system.compute.warehouses": (RagResourceDomain.COMPUTE_WAREHOUSES,),
    # system.information_schema.* (default governance)
    "system.information_schema.tables": (RagResourceDomain.GOVERNANCE_UNITY_CATALOG,),
    "system.information_schema.columns": (RagResourceDomain.GOVERNANCE_UNITY_CATALOG,),
    "system.information_schema.schemata": (RagResourceDomain.GOVERNANCE_UNITY_CATALOG,),
    "system.information_schema.catalogs": (RagResourceDomain.GOVERNANCE_UNITY_CATALOG,),
    # system.lakeflow.*
    "system.lakeflow.jobs": (RagResourceDomain.WORKLOAD_JOBS,),
    "system.lakeflow.job_tasks": (RagResourceDomain.WORKLOAD_JOBS,),
    "system.lakeflow.job_run_timeline": (RagResourceDomain.WORKLOAD_JOBS,),
    "system.lakeflow.job_task_run_timeline": (RagResourceDomain.WORKLOAD_JOBS,),
    "system.lakeflow.pipelines": (RagResourceDomain.WORKLOAD_PIPELINES,),
    "system.lakeflow.pipeline_update_timeline": (RagResourceDomain.WORKLOAD_PIPELINES,),
    # system.mlflow.*
    "system.mlflow.experiments_latest": (RagResourceDomain.MLFLOW,),
    "system.mlflow.runs_latest": (RagResourceDomain.MLFLOW,),
    "system.mlflow.run_metrics_history": (RagResourceDomain.MLFLOW,),
    # system.query.*
    "system.query.history": (
        RagResourceDomain.QUERY,
        RagResourceDomain.COMPUTE_WAREHOUSES,
        RagResourceDomain.WORKLOAD_JOBS,
    ),
    # system.serving.*
    "system.serving.endpoint_usage": (
        RagResourceDomain.SERVING,
        RagResourceDomain.FINOPS_BILLING,
    ),
    "system.serving.served_entities": (RagResourceDomain.SERVING,),
    # system.storage.*
    "system.storage.predictive_optimization_operations_history": (
        RagResourceDomain.STORAGE_OPTIMIZATION,
        RagResourceDomain.GOVERNANCE_UNITY_CATALOG,
    ),
}


def map_system_table_to_rag_resource_domains(
    table_full_name: str,
) -> tuple[RagResourceDomain, ...]:
    """Map a Databricks system table to one or more RAG resource domains."""
    t = table_full_name.strip().lower()

    if t in _EXACT:
        return _EXACT[t]

    # Prefix fallbacks (resilient to new tables)
    if t.startswith("system.billing."):
        return (RagResourceDomain.FINOPS_BILLING,)

    if t.startswith("system.compute.warehouse"):
        return (RagResourceDomain.COMPUTE_WAREHOUSES, RagResourceDomain.QUERY)

    if t.startswith("system.compute."):
        return (RagResourceDomain.COMPUTE_CLUSTERS,)

    if t.startswith("system.query."):
        return (RagResourceDomain.QUERY,)

    if t.startswith("system.lakeflow."):
        if "pipeline" in t:
            return (RagResourceDomain.WORKLOAD_PIPELINES,)
        return (RagResourceDomain.WORKLOAD_JOBS,)

    if t.startswith("system.mlflow."):
        return (RagResourceDomain.MLFLOW,)

    if t.startswith("system.serving."):
        return (RagResourceDomain.SERVING,)

    if t.startswith("system.storage."):
        return (RagResourceDomain.STORAGE_OPTIMIZATION,)

    if t.startswith("system.access."):
        if "lineage" in t:
            return (
                RagResourceDomain.LINEAGE,
                RagResourceDomain.GOVERNANCE_UNITY_CATALOG,
            )
        if "network" in t:
            return (RagResourceDomain.NETWORK, RagResourceDomain.SECURITY_ACCESS)
        return (RagResourceDomain.SECURITY_ACCESS,)

    if t.startswith("system.information_schema."):
        if (
            "share" in t
            or "recipient" in t
            or t.endswith(".providers")
            or t.endswith(".shares")
            or t.endswith(".recipients")
        ):
            return (RagResourceDomain.GOVERNANCE_SHARING,)
        if "clean_room" in t or t.endswith(".clean_rooms"):
            return (RagResourceDomain.GOVERNANCE_CLEAN_ROOMS,)
        return (RagResourceDomain.GOVERNANCE_UNITY_CATALOG,)

    return (RagResourceDomain.WORKSPACE_ADMIN,)


def map_many_system_tables(
    tables: Iterable[str],
) -> list[TableDomainMapping]:
    """Map many tables into their RAG resource domains."""
    return [
        TableDomainMapping(table=t, domains=map_system_table_to_rag_resource_domains(t))
        for t in tables
    ]

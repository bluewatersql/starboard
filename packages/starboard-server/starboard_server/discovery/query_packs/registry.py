"""Query pack registry and conditional execution logic.

Central registry for all query packs. Provides filtering based on active
Databricks products (from audit query) and config-level overrides.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import QueryPack

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

PRODUCT_TO_DOMAIN_PACKS: dict[str, list[str]] = {
    # Core workloads
    "JOBS": ["jobs", "workflow"],
    "SQL": ["query_perf", "serverless_sql", "aibi"],
    "ALL_PURPOSE": ["compute"],
    "INTERACTIVE": ["compute"],
    "BASE_ENVIRONMENTS": ["compute"],
    # DLT / Pipelines
    "DLT": ["dlt_pipelines"],
    "LAKEFLOW_CONNECT": ["lakeflow_connect"],
    # AI / ML
    "MODEL_SERVING": ["ml", "ai_gateway"],
    "AI_GATEWAY": ["ai_gateway"],
    "AI_RUNTIME": ["mlflow"],
    "AI_FUNCTIONS": ["aibi"],
    "FOUNDATION_MODEL_TRAINING": ["ml"],
    "AGENT_EVALUATION": ["mlflow"],
    "AGENT_BRICKS": ["ai_gateway"],
    "SUPERVISOR_AGENT": ["ai_gateway"],
    "ONLINE_TABLES": ["vector_search"],
    "FEATURE_ENGINEERING": ["ml", "mlflow"],
    # Platform features
    "APPS": ["apps"],
    "LAKEBASE": ["lakebase"],
    "DATABASE": ["lakebase"],
    "VECTOR_SEARCH": ["vector_search"],
    "DATA_SHARING": ["delta_sharing"],
    "LAKEHOUSE_MONITORING": ["monitoring"],
    "DATA_QUALITY_MONITORING": ["monitoring"],
    # Governance / storage
    "PREDICTIVE_OPTIMIZATION": ["governance"],
    "DATA_CLASSIFICATION": ["governance"],
    "FINE_GRAINED_ACCESS_CONTROL": ["governance"],
    "DEFAULT_STORAGE": ["governance"],
    "NETWORKING": ["governance"],
}

ALWAYS_RUN_PACKS: frozenset[str] = frozenset(
    {
        "audit",
        "billing",
        "governance",
        "migration",
    }
)


class QueryPackRegistry:
    """Registry of all available query packs.

    Provides filtering based on active products (from audit query)
    and config-level include/exclude overrides.

    Args:
        packs: All packs to register.
    """

    def __init__(self, packs: tuple[QueryPack, ...]) -> None:
        self._packs: dict[str, QueryPack] = {p.pack_id: p for p in packs}

    def get_packs_for_products(
        self,
        active_products: set[str],
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        target_domains: list[str] | None = None,
    ) -> list[QueryPack]:
        """Return packs that should run given active products.

        Selection logic:
            1. Start with all packs
            2. Keep packs where ``gating_products`` is empty (always-run)
               OR ``gating_products`` intersects ``active_products``
            3. Apply include override (force-add specific packs)
            4. Apply exclude override (force-remove specific packs)
            5. If target_domains is set, filter to only packs whose domain
               is in the target list. Always-run packs are still included.

        Args:
            active_products: ``billing_origin_product`` values from audit.
            include: Pack IDs to force-include.
            exclude: Pack IDs to force-exclude.
            target_domains: If provided, only return packs for these domains.

        Returns:
            Ordered list of packs to execute.
        """
        eligible_pack_ids: set[str] = set()

        for product in active_products:
            for pack_id in PRODUCT_TO_DOMAIN_PACKS.get(product, []):
                eligible_pack_ids.add(pack_id)

        eligible_pack_ids |= ALWAYS_RUN_PACKS

        if include:
            eligible_pack_ids |= set(include)

        if exclude:
            eligible_pack_ids -= set(exclude)

        result = [
            pack
            for pack_id, pack in self._packs.items()
            if pack_id in eligible_pack_ids
        ]

        # Domain targeting: filter to specific domains (always-run packs preserved)
        if target_domains is not None:
            target_set = set(target_domains)
            result = [
                pack for pack in result
                if pack.domain in target_set
                or pack.pack_id in ALWAYS_RUN_PACKS
            ]

        logger.info(
            "query_pack_selection",
            active_products=sorted(active_products),
            eligible_packs=sorted(eligible_pack_ids),
            selected_packs=[p.pack_id for p in result],
            include_override=include,
            exclude_override=exclude,
            target_domains=target_domains,
        )

        return result

    def get_pack(self, pack_id: str) -> QueryPack | None:
        """Get a specific pack by ID.

        Args:
            pack_id: The pack identifier.

        Returns:
            The pack, or None if not found.
        """
        return self._packs.get(pack_id)

    @property
    def all_packs(self) -> list[QueryPack]:
        """All registered packs."""
        return list(self._packs.values())

    @property
    def pack_count(self) -> int:
        """Total number of registered packs."""
        return len(self._packs)


def create_default_registry() -> QueryPackRegistry:
    """Create registry with all standard query packs.

    Returns:
        QueryPackRegistry with all domain and product-surface packs.
    """
    from starboard_server.discovery.query_packs.ai_gateway import AI_GATEWAY_PACK
    from starboard_server.discovery.query_packs.aibi import AIBI_PACK
    from starboard_server.discovery.query_packs.apps import APPS_PACK
    from starboard_server.discovery.query_packs.audit import AUDIT_PACK
    from starboard_server.discovery.query_packs.billing import BILLING_PACK
    from starboard_server.discovery.query_packs.compute import COMPUTE_PACK
    from starboard_server.discovery.query_packs.dlt_pipelines import DLT_PIPELINES_PACK
    from starboard_server.discovery.query_packs.governance import GOVERNANCE_PACK
    from starboard_server.discovery.query_packs.jobs import JOBS_PACK
    from starboard_server.discovery.query_packs.lakebase import LAKEBASE_PACK
    from starboard_server.discovery.query_packs.lakeflow_connect import (
        LAKEFLOW_CONNECT_PACK,
    )
    from starboard_server.discovery.query_packs.migration import MIGRATION_PACK
    from starboard_server.discovery.query_packs.ml import ML_PACK
    from starboard_server.discovery.query_packs.mlflow import MLFLOW_PACK
    from starboard_server.discovery.query_packs.product_surfaces import (
        DELTA_SHARING_PACK,
        MONITORING_PACK,
        SERVERLESS_SQL_PACK,
        WORKFLOW_PACK,
    )
    from starboard_server.discovery.query_packs.query_performance import (
        QUERY_PERF_PACK,
    )
    from starboard_server.discovery.query_packs.vector_search import (
        VECTOR_SEARCH_PACK,
    )

    return QueryPackRegistry(
        packs=(
            AUDIT_PACK,
            BILLING_PACK,
            JOBS_PACK,
            COMPUTE_PACK,
            QUERY_PERF_PACK,
            ML_PACK,
            MIGRATION_PACK,
            GOVERNANCE_PACK,
            # Expanded packs (replacing product_surfaces originals)
            APPS_PACK,
            LAKEBASE_PACK,
            VECTOR_SEARCH_PACK,
            AIBI_PACK,
            # Retained from product_surfaces
            DELTA_SHARING_PACK,
            MONITORING_PACK,
            SERVERLESS_SQL_PACK,
            WORKFLOW_PACK,
            # Net-new packs
            DLT_PIPELINES_PACK,
            MLFLOW_PACK,
            AI_GATEWAY_PACK,
            LAKEFLOW_CONNECT_PACK,
        )
    )

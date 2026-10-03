# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Query pack registry and conditional execution logic.

Central registry for all query packs. Provides filtering based on active
Databricks products (from audit query) and config-level overrides.
"""

from __future__ import annotations

from dataclasses import dataclass

from starboard_core.domain.models.discovery.query import QueryPack

from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)

PRODUCT_TO_DOMAIN_PACKS: dict[str, list[str]] = {
    # Core workloads
    # JOBS / DLT also route to serverless_attribution so SVA-03 (serverless performance-mode
    # mix) runs on estates whose serverless spend is Jobs / Pipelines, not just AI infra.
    "JOBS": ["jobs", "workflow", "cluster_right_sizing", "serverless_attribution"],
    # ``genie`` is also routed from SQL: on estates where Genie spaces bill under a
    # shared SQL warehouse, GENIE never appears in the audit, so routing the genie
    # pack from SQL keeps the Genie-space inventory reachable there.
    "SQL": [
        "query_perf",
        "serverless_sql",
        "aibi",
        "warehouse",
        "compute_reliability",
        "genie",
    ],
    "ALL_PURPOSE": ["compute", "compute_reliability", "cluster_right_sizing"],
    "INTERACTIVE": ["compute", "compute_reliability", "cluster_right_sizing"],
    "BASE_ENVIRONMENTS": ["compute", "compute_reliability", "cluster_right_sizing"],
    # DLT / Pipelines
    "DLT": ["dlt_pipelines", "cluster_right_sizing", "serverless_attribution"],
    "LAKEFLOW_CONNECT": ["lakeflow_connect"],
    # AI / ML
    "MODEL_SERVING": ["ml", "ai_gateway", "serverless_attribution"],
    "AI_GATEWAY": ["ai_gateway"],
    "AI_RUNTIME": ["mlflow"],
    "AI_FUNCTIONS": ["aibi"],
    "FOUNDATION_MODEL_TRAINING": ["ml"],
    "AGENT_EVALUATION": ["mlflow"],
    "AGENT_BRICKS": ["ai_gateway"],
    "SUPERVISOR_AGENT": ["ai_gateway"],
    "ONLINE_TABLES": ["vector_search"],
    # Strategic SKUs with first-class packs (issue #17).
    "GENIE": ["genie", "serverless_attribution"],
    "FEATURE_STORE": ["feature_store", "ml", "mlflow"],
    "LAKEHOUSE_REAL_TIME": ["realtime", "serverless_attribution"],
    # Platform features
    "APPS": ["apps"],
    "LAKEBASE": ["lakebase", "serverless_attribution"],
    "DATABASE": ["lakebase", "serverless_attribution"],
    "VECTOR_SEARCH": ["vector_search", "serverless_attribution"],
    "DATA_SHARING": ["delta_sharing"],
    "CLEAN_ROOM": ["delta_sharing"],
    "LAKEHOUSE_MONITORING": ["monitoring"],
    "DATA_QUALITY_MONITORING": ["data_quality"],
    # Governance / storage
    "PREDICTIVE_OPTIMIZATION": ["predictive_optimization"],
    "DATA_CLASSIFICATION": ["data_classification"],
    "FINE_GRAINED_ACCESS_CONTROL": ["governance", "column_lineage"],
    "DEFAULT_STORAGE": ["governance", "column_lineage"],
    "EXTERNAL_COMPATIBILITY": ["governance"],
    "NETWORKING": ["networking"],
}

# ``facts`` feeds the deterministic ``data.facts`` headline block (contract §1),
# so it is ungated: every run must carry the same full-day headline numbers.
ALWAYS_RUN_PACKS: frozenset[str] = frozenset({"audit", "billing", "governance", "facts"})

# Products whose presence makes the migration pack (classic -> serverless) relevant.
_CLASSIC_COMPUTE_PRODUCTS: frozenset[str] = frozenset(
    {"ALL_PURPOSE", "INTERACTIVE", "BASE_ENVIRONMENTS"}
)


@dataclass(frozen=True)
class DomainSelection:
    """One recommended domain and the packs that implement it."""

    domain: str
    packs: list[str]
    dbus: float | None


@dataclass(frozen=True)
class PlanSelection:
    """The plan verb's selection output (no packs executed)."""

    recommended: list[DomainSelection]
    always_recommended: list[str]
    contextual: list[str]


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
        active_products: set[str] | dict[str, float],
        min_dbu_threshold: float = 0.0,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        target_domains: list[str] | None = None,
    ) -> list[QueryPack]:
        """Return packs that should run given active products.

        Selection logic:
            1. If ``active_products`` is a ``dict[str, float]``, filter out
               products whose DBU total is below ``min_dbu_threshold``.
            2. Map remaining products to pack IDs via ``PRODUCT_TO_DOMAIN_PACKS``.
            3. Always include ``ALWAYS_RUN_PACKS``.
            4. Apply include/exclude overrides.
            5. If ``target_domains`` is set, keep only matching domains
               (always-run packs are still preserved).

        Args:
            active_products: ``billing_origin_product`` values from audit.
                Accepts ``set[str]`` (legacy) or ``dict[str, float]``
                (product -> total_dbus) for threshold-based filtering.
            min_dbu_threshold: Products below this DBU total are skipped.
                Only applied when ``active_products`` is a dict.
            include: Pack IDs to force-include.
            exclude: Pack IDs to force-exclude.
            target_domains: If provided, only return packs for these domains.

        Returns:
            Ordered list of packs to execute.
        """
        skipped_products: dict[str, float] = {}

        if isinstance(active_products, dict):
            product_names: set[str] = set()
            for product, dbus in active_products.items():
                if dbus >= min_dbu_threshold:
                    product_names.add(product)
                else:
                    skipped_products[product] = dbus
            if skipped_products:
                logger.info(
                    "products_below_dbu_threshold",
                    threshold=min_dbu_threshold,
                    skipped={k: round(v, 2) for k, v in skipped_products.items()},
                )
        else:
            product_names = active_products

        eligible_pack_ids: set[str] = set()

        for product in product_names:
            mapped = PRODUCT_TO_DOMAIN_PACKS.get(product, [])
            if not mapped:
                # AC1: an above-threshold product with no route is silently
                # analyzed as zero — warn so the coverage gap is visible. Per-
                # product DBUs are only known on the dict input path.
                logger.warning(
                    "unmapped_product_skipped",
                    product=product,
                    dbus=round(active_products[product], 2)
                    if isinstance(active_products, dict)
                    else None,
                )
                continue
            eligible_pack_ids.update(mapped)

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

        if target_domains is not None:
            target_set = set(target_domains)
            result = [
                pack for pack in result
                if pack.domain in target_set
                or pack.pack_id in target_set
                or pack.pack_id in ALWAYS_RUN_PACKS
            ]

        logger.info(
            "query_pack_selection",
            active_products=sorted(product_names),
            eligible_packs=sorted(eligible_pack_ids),
            selected_packs=[p.pack_id for p in result],
            include_override=include,
            exclude_override=exclude,
            target_domains=target_domains,
            skipped_products=sorted(skipped_products.keys()) if skipped_products else None,
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

    def known_selectors(self) -> set[str]:
        """Valid ``--packs`` selectors: every pack id and every domain.

        Used to validate user-supplied domain/pack filters before a run so an
        unknown name fails fast (arg-error) instead of silently selecting
        nothing (or, historically, everything).
        """
        selectors: set[str] = set()
        for pack in self._packs.values():
            selectors.add(pack.pack_id)
            selectors.add(pack.domain)
        return selectors

    def resolve_exact(self, selectors: list[str]) -> list[QueryPack]:
        """Return exactly the packs matching ``selectors`` (pack_id or domain).

        No always-run injection and no product expansion — the ``--only`` path.
        Order follows registry insertion order for determinism.
        """
        wanted = set(selectors)
        return [
            pack
            for pack in self._packs.values()
            if pack.pack_id in wanted or pack.domain in wanted
        ]

    def select_for_plan(
        self,
        active_products: dict[str, float],
        min_dbu_threshold: float = 0.0,
    ) -> PlanSelection:
        """Compute the recommended domains from active products WITHOUT running packs.

        Weights each pack by the max DBUs of the products that route to it, groups
        packs by domain, and orders domains by weight (highest first). Billing and
        governance are always recommended. Migration is recommended only when a
        classic-compute product is present; otherwise it is surfaced as contextual.
        """
        products = {
            p: d for p, d in active_products.items() if d >= min_dbu_threshold
        }

        pack_weight: dict[str, float] = {}
        for product, dbus in products.items():
            mapped = PRODUCT_TO_DOMAIN_PACKS.get(product, [])
            if not mapped:
                # AC1: above-threshold product with no route — surface the gap.
                logger.warning(
                    "unmapped_product_skipped", product=product, dbus=round(dbus, 2)
                )
                continue
            for pack_id in mapped:
                pack_weight[pack_id] = max(pack_weight.get(pack_id, 0.0), dbus)

        eligible = set(pack_weight) | {"billing", "governance"}

        classic = bool(_CLASSIC_COMPUTE_PRODUCTS & set(products))
        if classic:
            eligible.add("migration")

        # Group eligible packs by domain, keeping only registered packs.
        by_domain: dict[str, list[str]] = {}
        domain_weight: dict[str, float] = {}
        for pack_id in eligible:
            pack = self._packs.get(pack_id)
            if pack is None:
                continue
            by_domain.setdefault(pack.domain, []).append(pack.pack_id)
            domain_weight[pack.domain] = max(
                domain_weight.get(pack.domain, 0.0), pack_weight.get(pack_id, 0.0)
            )

        recommended = [
            DomainSelection(
                domain=domain,
                packs=sorted(packs),
                dbus=domain_weight.get(domain) or None,
            )
            for domain, packs in by_domain.items()
        ]
        recommended.sort(key=lambda d: (-(d.dbus or 0.0), d.domain))

        contextual = [] if classic else ["migration"]
        return PlanSelection(
            recommended=recommended,
            always_recommended=["billing", "governance"],
            contextual=contextual,
        )

    def products_without_coverage(
        self,
        active_products: set[str] | dict[str, float],
        min_dbu_threshold: float = 0.0,
    ) -> list[str]:
        """Products present (above threshold) that have no query-pack coverage.

        A product is **covered** iff :data:`PRODUCT_TO_DOMAIN_PACKS` maps it to a
        non-empty list AND at least one of those pack ids is a pack registered in
        this registry. This is the D10 coverage-gap signal (issue #17), and it is
        deliberately **filter-independent**: it ignores this run's
        ``--domains`` / include / exclude filters and never inspects post-execution
        results, so a domain filter or a query failure is never mistaken for "no
        coverage". It is the single source of truth —
        ``PRODUCT_TO_DOMAIN_PACKS`` — intersected with the registered packs.

        Products dropped only by ``min_dbu_threshold`` are **not** reported here
        (they are logged separately as ``products_below_dbu_threshold``); only
        genuinely-unmapped — or mapped-but-no-registered-pack — products are
        returned.

        Args:
            active_products: Products from the audit — ``set[str]`` or
                ``dict[str, float]`` (product -> total_dbus).
            min_dbu_threshold: Products below this DBU total are excluded from the
                check (dict input only), matching selection behavior.

        Returns:
            Sorted list of products with no coverage.
        """
        if isinstance(active_products, dict):
            names = {
                p for p, d in active_products.items() if d >= min_dbu_threshold
            }
        else:
            names = set(active_products)

        uncovered = [
            product
            for product in names
            if not any(
                pack_id in self._packs
                for pack_id in PRODUCT_TO_DOMAIN_PACKS.get(product, [])
            )
        ]
        return sorted(uncovered)


def create_default_registry() -> QueryPackRegistry:
    """Create registry with all standard query packs.

    Returns:
        QueryPackRegistry with all domain and product-surface packs.
    """
    from starboard.discovery.query_packs.ai_gateway import AI_GATEWAY_PACK
    from starboard.discovery.query_packs.aibi import AIBI_PACK
    from starboard.discovery.query_packs.apps import APPS_PACK
    from starboard.discovery.query_packs.audit import AUDIT_PACK
    from starboard.discovery.query_packs.billing import BILLING_PACK
    from starboard.discovery.query_packs.cluster_right_sizing import (
        CLUSTER_RIGHT_SIZING_PACK,
    )
    from starboard.discovery.query_packs.column_lineage import COLUMN_LINEAGE_PACK
    from starboard.discovery.query_packs.compute import COMPUTE_PACK
    from starboard.discovery.query_packs.compute_reliability import (
        COMPUTE_RELIABILITY_PACK,
    )

    # System-table packs that fill previously-empty product routes.
    from starboard.discovery.query_packs.data_classification import (
        DATA_CLASSIFICATION_PACK,
    )
    from starboard.discovery.query_packs.data_quality import DATA_QUALITY_PACK
    from starboard.discovery.query_packs.dlt_pipelines import DLT_PIPELINES_PACK
    from starboard.discovery.query_packs.facts import FACTS_PACK
    from starboard.discovery.query_packs.feature_store import FEATURE_STORE_PACK
    from starboard.discovery.query_packs.genie import GENIE_PACK
    from starboard.discovery.query_packs.governance import GOVERNANCE_PACK
    from starboard.discovery.query_packs.jobs import JOBS_PACK
    from starboard.discovery.query_packs.lakebase import LAKEBASE_PACK
    from starboard.discovery.query_packs.lakeflow_connect import (
        LAKEFLOW_CONNECT_PACK,
    )
    from starboard.discovery.query_packs.migration import MIGRATION_PACK
    from starboard.discovery.query_packs.ml import ML_PACK
    from starboard.discovery.query_packs.mlflow import MLFLOW_PACK
    from starboard.discovery.query_packs.networking import NETWORKING_PACK
    from starboard.discovery.query_packs.predictive_optimization import (
        PREDICTIVE_OPTIMIZATION_PACK,
    )
    from starboard.discovery.query_packs.product_surfaces import (
        DELTA_SHARING_PACK,
        MONITORING_PACK,
        SERVERLESS_SQL_PACK,
        WORKFLOW_PACK,
    )
    from starboard.discovery.query_packs.query_performance import (
        QUERY_PERF_PACK,
    )
    from starboard.discovery.query_packs.realtime import REALTIME_PACK
    from starboard.discovery.query_packs.serverless_attribution import (
        SERVERLESS_ATTRIBUTION_PACK,
    )
    from starboard.discovery.query_packs.vector_search import (
        VECTOR_SEARCH_PACK,
    )
    from starboard.discovery.query_packs.warehouse import WAREHOUSE_PACK

    return QueryPackRegistry(
        packs=(
            AUDIT_PACK,
            BILLING_PACK,
            # Deterministic headline facts (data.facts source queries; always-run)
            FACTS_PACK,
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
            SERVERLESS_ATTRIBUTION_PACK,
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
            # System-table packs filling previously-empty product routes
            PREDICTIVE_OPTIMIZATION_PACK,
            DATA_QUALITY_PACK,
            DATA_CLASSIFICATION_PACK,
            NETWORKING_PACK,
            # Warehouse operational framings (D2)
            WAREHOUSE_PACK,
            # Phase-2 D5 net-new packs
            COMPUTE_RELIABILITY_PACK,
            COLUMN_LINEAGE_PACK,
            # Phase-2 Task-09 right-sizing pack
            CLUSTER_RIGHT_SIZING_PACK,
            # Strategic SKU packs (issue #17): first-class Genie / Feature Store /
            # Lakehouse Real-Time domains.
            GENIE_PACK,
            FEATURE_STORE_PACK,
            REALTIME_PACK,
        )
    )

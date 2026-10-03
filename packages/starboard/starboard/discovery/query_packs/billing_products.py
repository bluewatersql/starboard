# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Vendored ``billing_origin_product`` (SKU) taxonomy — the single build-time
reference for the SKU-coverage gate (issue #17).

Discovery routes each ``billing_origin_product`` value emitted by the audit
(``P-AUDIT01``) to one or more query packs via
:data:`starboard.discovery.query_packs.registry.PRODUCT_TO_DOMAIN_PACKS`. A SKU
with no route is silently analyzed as zero. :data:`BILLING_ORIGIN_PRODUCTS` is
the authoritative set of SKUs the coverage gate
(``tests/architecture/test_sku_coverage.py``) checks the routing map against, so
a newly-shipped SKU surfaces as an actionable build failure instead of a silent
coverage gap.

Provenance (keep auditable; refresh via ``make audit-sku-coverage``):
    source: https://docs.databricks.com/aws/en/admin/system-tables/billing
    fetched: 2026-10-01

Any SKU that is intentionally not routed to a pack must be listed in
:data:`_INTENTIONALLY_UNROUTED` with a human-readable reason, so "unrouted" is
always a deliberate, documented decision rather than drift.
"""

from __future__ import annotations

#: Authoritative ``billing_origin_product`` taxonomy (33 values), captured from
#: the Databricks billing system-table docs (see module provenance). Every value
#: must be routed in ``PRODUCT_TO_DOMAIN_PACKS`` or listed in
#: :data:`_INTENTIONALLY_UNROUTED`.
BILLING_ORIGIN_PRODUCTS: frozenset[str] = frozenset(
    {
        "JOBS",
        "DLT",
        "SQL",
        "ALL_PURPOSE",
        "MODEL_SERVING",
        "INTERACTIVE",
        "DEFAULT_STORAGE",
        "VECTOR_SEARCH",
        "LAKEHOUSE_MONITORING",
        "PREDICTIVE_OPTIMIZATION",
        "ONLINE_TABLES",
        "FOUNDATION_MODEL_TRAINING",
        "AGENT_EVALUATION",
        "FINE_GRAINED_ACCESS_CONTROL",
        "EXTERNAL_COMPATIBILITY",
        "BASE_ENVIRONMENTS",
        "DATA_CLASSIFICATION",
        "DATA_QUALITY_MONITORING",
        "DATA_SHARING",
        "AI_GATEWAY",
        "AI_RUNTIME",
        "NETWORKING",
        "APPS",
        "DATABASE",
        "LAKEBASE",
        "AI_FUNCTIONS",
        "AGENT_BRICKS",
        "CLEAN_ROOM",
        "LAKEFLOW_CONNECT",
        "GENIE",
        "FEATURE_STORE",
        "SUPERVISOR_AGENT",
        "LAKEHOUSE_REAL_TIME",
    }
)

#: SKU -> reason: taxonomy values intentionally left unrouted (no honest
#: product-specific signal exists yet). Entries here are exempted from the
#: coverage gate; every key must still be a valid taxonomy SKU. Empty today —
#: every taxonomy SKU currently routes to at least one pack.
_INTENTIONALLY_UNROUTED: dict[str, str] = {}

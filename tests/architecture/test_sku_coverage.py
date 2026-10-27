# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Architecture fitness test — SKU → query-pack coverage gate (issue #17).

Discovery routes each ``billing_origin_product`` (SKU) value emitted by the audit
to query packs via ``PRODUCT_TO_DOMAIN_PACKS``. A SKU with no route is silently
analyzed as zero. This build-time gate fails when the routing map drifts from the
vendored taxonomy on any of these axes:

1. **Forward coverage** — every taxonomy SKU is routed in
   ``PRODUCT_TO_DOMAIN_PACKS`` or explicitly listed in ``_INTENTIONALLY_UNROUTED``
   with a reason.
2. **Valid keys / allowlist** — every routing-map key and every allowlist key is a
   real taxonomy SKU (catches stale codes like the old ``FEATURE_ENGINEERING``).
3. **Registered targets** — every mapped pack id exists in the default registry.
4. **Reverse reachability** — every registered non-always-run pack is reachable
   from some route (or ALWAYS_RUN_PACKS / an explicit exempt list), so a pack that
   is added but never routed — the pack-side mirror of issue #17 — is caught too.
"""

from __future__ import annotations

from starboard.discovery.query_packs.billing_products import (
    _INTENTIONALLY_UNROUTED,
    BILLING_ORIGIN_PRODUCTS,
)
from starboard.discovery.query_packs.registry import (
    ALWAYS_RUN_PACKS,
    PRODUCT_TO_DOMAIN_PACKS,
    create_default_registry,
)

#: Registered packs that are legitimately not product-routed: ``migration`` is a
#: contextual pack injected by the classic-compute heuristic in
#: ``select_for_plan`` rather than mapped from a SKU.
_UNROUTED_PACKS_EXEMPT: frozenset[str] = frozenset({"migration"})


def test_every_taxonomy_sku_is_routed_or_allowlisted() -> None:
    unrouted = sorted(
        sku
        for sku in BILLING_ORIGIN_PRODUCTS
        if sku not in PRODUCT_TO_DOMAIN_PACKS and sku not in _INTENTIONALLY_UNROUTED
    )
    assert not unrouted, (
        "taxonomy SKUs with no query-pack route and no _INTENTIONALLY_UNROUTED "
        f"entry (silently analyzed as zero): {unrouted}"
    )


def test_every_routing_key_is_a_valid_taxonomy_sku() -> None:
    invalid = sorted(k for k in PRODUCT_TO_DOMAIN_PACKS if k not in BILLING_ORIGIN_PRODUCTS)
    assert not invalid, (
        "PRODUCT_TO_DOMAIN_PACKS keys that are not real billing_origin_product "
        f"values (stale/invalid routes): {invalid}"
    )


def test_every_allowlist_entry_is_a_valid_taxonomy_sku() -> None:
    invalid = sorted(k for k in _INTENTIONALLY_UNROUTED if k not in BILLING_ORIGIN_PRODUCTS)
    assert not invalid, (
        f"_INTENTIONALLY_UNROUTED keys that are not real SKUs: {invalid}"
    )


def test_allowlist_entries_have_a_reason() -> None:
    missing = sorted(k for k, reason in _INTENTIONALLY_UNROUTED.items() if not reason.strip())
    assert not missing, f"_INTENTIONALLY_UNROUTED entries without a reason: {missing}"


def test_sku_is_routed_or_allowlisted_but_not_both() -> None:
    both = sorted(set(PRODUCT_TO_DOMAIN_PACKS) & set(_INTENTIONALLY_UNROUTED))
    assert not both, (
        f"SKUs both routed and allowlisted-as-unrouted (ambiguous): {both}"
    )


def test_every_mapped_pack_id_exists_in_registry() -> None:
    registered = {p.pack_id for p in create_default_registry().all_packs}
    missing = sorted(
        {
            pack_id
            for pack_ids in PRODUCT_TO_DOMAIN_PACKS.values()
            for pack_id in pack_ids
            if pack_id not in registered
        }
    )
    assert not missing, (
        f"PRODUCT_TO_DOMAIN_PACKS references packs not in the default registry: {missing}"
    )


def test_every_registered_pack_is_reachable() -> None:
    registered = {p.pack_id for p in create_default_registry().all_packs}
    routed = {pid for pack_ids in PRODUCT_TO_DOMAIN_PACKS.values() for pid in pack_ids}
    reachable = routed | set(ALWAYS_RUN_PACKS) | _UNROUTED_PACKS_EXEMPT
    unreachable = sorted(registered - reachable)
    assert not unreachable, (
        "registered packs that are never routed, always-run, or exempt "
        "(the pack-side mirror of issue #17 — a pack added but never reached): "
        f"{unreachable}"
    )

# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for discovery agent routing.

Verifies that discovery domain intents and routing correctly identify
workspace health and discovery-related user requests.
"""

import pytest
from starboard.agents.routing.domain_intents import (
    DOMAIN_INTENTS,
    route_by_scoring,
)
from starboard.discovery.query_packs.registry import (
    ALWAYS_RUN_PACKS,
    create_default_registry,
)


def test_discovery_in_domain_intents() -> None:
    """Verify 'discovery' exists in DOMAIN_INTENTS dict."""
    assert "discovery" in DOMAIN_INTENTS
    intent = DOMAIN_INTENTS["discovery"]
    assert intent.domain == "discovery"
    assert (
        "workspace health" in intent.description.lower()
        or "discovery" in intent.description.lower()
    )


def test_discovery_routing_exclusive_patterns() -> None:
    """Test that exclusive patterns route to discovery domain."""
    exclusive_phrases = [
        "workspace health check",
        "run discovery",
        "workspace discovery",
    ]
    for text in exclusive_phrases:
        domain, confidence, _ = route_by_scoring(text, {})
        assert domain == "discovery", (
            f"'{text}' should route to discovery, got {domain}"
        )


def test_discovery_routing_compound_keywords() -> None:
    """Test compound patterns like 'workspace health' and 'health assessment' route to discovery."""
    compound_phrases = [
        "workspace health",
        "health assessment",
    ]
    for text in compound_phrases:
        domain, _, _ = route_by_scoring(text, {})
        assert domain == "discovery", (
            f"'{text}' should route to discovery, got {domain}"
        )


def test_discovery_routing_simple_keywords() -> None:
    """Test that simple keywords 'discover' and 'health check' contribute to discovery scoring."""
    # Use phrases that favor discovery over other domains
    simple_phrases = [
        "I want to discover what's in my workspace",
        "run a health check on the platform",
    ]
    for text in simple_phrases:
        domain, _, _ = route_by_scoring(text, {})
        assert domain == "discovery", (
            f"'{text}' should route to discovery, got {domain}"
        )


def test_non_discovery_does_not_route() -> None:
    """Test that query-optimization phrases do NOT route to discovery."""
    domain, _, _ = route_by_scoring("optimize my query", {})
    assert domain != "discovery", "query optimization should not route to discovery"


@pytest.mark.unit
def test_migration_not_in_always_run():
    assert frozenset({"audit", "billing", "governance", "facts"}) == ALWAYS_RUN_PACKS
    assert "migration" not in ALWAYS_RUN_PACKS


@pytest.mark.unit
def test_resolve_exact_runs_only_named_packs_no_always_run():
    reg = create_default_registry()
    packs = reg.resolve_exact(["jobs"])
    ids = {p.pack_id for p in packs}
    assert ids == {"jobs"}  # no audit/billing/governance injected


@pytest.mark.unit
def test_resolve_exact_accepts_domain_selector():
    reg = create_default_registry()
    packs = reg.resolve_exact(["jobs"])
    assert {p.pack_id for p in packs} == {"jobs"}


@pytest.mark.unit
def test_select_for_plan_orders_by_dbu_and_flags_migration_contextual():
    reg = create_default_registry()
    sel = reg.select_for_plan({"JOBS": 5000.0, "SQL": 12000.0}, min_dbu_threshold=1.0)
    # SQL (higher DBUs) domains rank ahead of JOBS domains.
    weights = [d.dbus for d in sel.recommended if d.dbus is not None]
    assert weights == sorted(weights, reverse=True)
    assert sel.always_recommended == ["billing", "governance"]
    # No classic-compute product present -> migration is contextual, not recommended.
    assert "migration" in sel.contextual
    assert all(d.domain != "migration" for d in sel.recommended)


@pytest.mark.unit
def test_select_for_plan_recommends_migration_on_classic_compute():
    reg = create_default_registry()
    sel = reg.select_for_plan({"ALL_PURPOSE": 3000.0}, min_dbu_threshold=1.0)
    assert any(d.domain == "migration" for d in sel.recommended)

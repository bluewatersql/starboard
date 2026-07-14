# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for discovery agent routing.

Verifies that discovery domain intents and routing correctly identify
workspace health and discovery-related user requests.
"""

from starboard.agents.routing.domain_intents import (
    DOMAIN_INTENTS,
    route_by_scoring,
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

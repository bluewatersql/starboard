# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for domain-specific system prompts (Phase 1).

Tests the domain_prompts module, ensuring all prompts are properly
defined and the get_system_prompt() function works correctly.
"""

import pytest
from starboard.prompts import (
    CLUSTER_SYSTEM_PROMPT,
    DIAGNOSTIC_SYSTEM_PROMPT,
    JOB_SYSTEM_PROMPT,
    QUERY_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    UC_SYSTEM_PROMPT,
    get_system_prompt,
)


def test_all_prompts_defined():
    """All domain prompts should be defined as non-empty strings."""
    prompts = {
        "router": ROUTER_SYSTEM_PROMPT,
        "query": QUERY_SYSTEM_PROMPT,
        "job": JOB_SYSTEM_PROMPT,
        "uc": UC_SYSTEM_PROMPT,
        "cluster": CLUSTER_SYSTEM_PROMPT,
        "diagnostic": DIAGNOSTIC_SYSTEM_PROMPT,
    }

    for domain, prompt in prompts.items():
        assert prompt, f"{domain} prompt is empty"
        assert isinstance(prompt, str), f"{domain} prompt is not a string"
        assert len(prompt) > 100, f"{domain} prompt is too short"


def test_query_prompt_content():
    """Query prompt should contain SQL-specific keywords."""
    prompt = QUERY_SYSTEM_PROMPT
    assert "SQL" in prompt or "query" in prompt.lower()
    assert "optimization" in prompt.lower() or "optimize" in prompt.lower()
    assert "{token_budget" in prompt  # Has format placeholder
    assert "{goal}" in prompt  # Has format placeholder
    assert "{mode}" in prompt  # Has format placeholder


def test_job_prompt_content():
    """Job prompt should contain job-specific keywords."""
    prompt = JOB_SYSTEM_PROMPT
    assert "job" in prompt.lower()
    assert "task" in prompt.lower()
    assert "{token_budget" in prompt  # Has format placeholder


def test_uc_prompt_content():
    """UC prompt should contain Unity Catalog/governance keywords."""
    prompt = UC_SYSTEM_PROMPT
    assert "unity catalog" in prompt.lower() or "uc" in prompt.lower()
    assert "governance" in prompt.lower() or "lineage" in prompt.lower()
    assert "{token_budget" in prompt  # Has format placeholder


def test_cluster_prompt_content():
    """Cluster prompt should contain cluster-specific keywords."""
    prompt = CLUSTER_SYSTEM_PROMPT
    assert "cluster" in prompt.lower()
    assert "optimization" in prompt.lower() or "optimize" in prompt.lower()
    assert "{token_budget" in prompt  # Has format placeholder


def test_diagnostic_prompt_content():
    """Diagnostic prompt should contain troubleshooting keywords."""
    prompt = DIAGNOSTIC_SYSTEM_PROMPT
    assert "diagnostic" in prompt.lower() or "troubleshoot" in prompt.lower()
    # Diagnostic prompt should guide on when to request evidence
    assert "evidence" in prompt.lower() or "artifact" in prompt.lower()
    assert "{token_budget" in prompt  # Has format placeholder
    assert "{available_artifacts" in prompt  # Has artifact placeholder


def test_router_prompt_content():
    """Router prompt should contain routing-specific keywords."""
    prompt = ROUTER_SYSTEM_PROMPT
    assert "router" in prompt.lower() or "classify" in prompt.lower()
    assert "domain" in prompt.lower()
    # Router prompt should NOT have format placeholders
    assert "{token_budget" not in prompt
    assert "{goal}" not in prompt


def test_get_system_prompt_router():
    """get_system_prompt() should return router prompt without formatting."""
    prompt = get_system_prompt("router")
    assert "router" in prompt.lower() or "classify" in prompt.lower()
    # Should be identical to ROUTER_SYSTEM_PROMPT
    assert prompt == ROUTER_SYSTEM_PROMPT


def test_get_system_prompt_query():
    """get_system_prompt() should return formatted query prompt."""
    prompt = get_system_prompt(
        "query",
        goal="Optimize slow query",
        token_budget=100_000,
        mode="online",
    )
    assert "Optimize slow query" in prompt
    assert "100,000" in prompt  # Token budget formatted
    assert "online" in prompt
    # Should not have format placeholders remaining
    assert "{token_budget}" not in prompt
    assert "{goal}" not in prompt


def test_get_system_prompt_default_goal():
    """get_system_prompt() should use default goal if not provided."""
    prompt = get_system_prompt("query", token_budget=100_000)
    assert "Optimize" in prompt or "optimize" in prompt


def test_get_system_prompt_all_domains():
    """get_system_prompt() should work for all domains."""
    domains = ["router", "query", "job", "uc", "cluster", "diagnostic", "analytics"]
    for domain in domains:
        prompt = get_system_prompt(
            domain,
            goal="Test goal",
            token_budget=120_000,
            mode="online",
        )
        assert prompt, f"Empty prompt for {domain}"
        assert len(prompt) > 100, f"Prompt too short for {domain}"


def test_get_system_prompt_invalid_domain():
    """get_system_prompt() should raise ValueError for invalid domain."""
    with pytest.raises(ValueError, match="Unknown domain"):
        get_system_prompt("invalid_domain")


def test_get_system_prompt_with_empty_goal():
    """get_system_prompt() should handle empty goal string."""
    prompt = get_system_prompt("query", goal="", token_budget=100_000)
    # Should use default goal (domain-specific)
    assert "Optimize" in prompt or "optimize" in prompt


def test_prompts_have_tool_lists():
    """Domain prompts (except router) should list available tools."""
    domain_prompts = {
        "query": QUERY_SYSTEM_PROMPT,
        "job": JOB_SYSTEM_PROMPT,
        "uc": UC_SYSTEM_PROMPT,
        "cluster": CLUSTER_SYSTEM_PROMPT,
        "diagnostic": DIAGNOSTIC_SYSTEM_PROMPT,
    }

    for domain, prompt in domain_prompts.items():
        # Should mention 'Tools Available' or similar
        assert "tools" in prompt.lower() or "complete" in prompt.lower(), (
            f"{domain} prompt missing tools section"
        )


def test_prompts_have_workflow_guidance():
    """Domain prompts should provide workflow guidance."""
    domain_prompts = {
        "query": QUERY_SYSTEM_PROMPT,
        "job": JOB_SYSTEM_PROMPT,
        "uc": UC_SYSTEM_PROMPT,
        "cluster": CLUSTER_SYSTEM_PROMPT,
        "diagnostic": DIAGNOSTIC_SYSTEM_PROMPT,
    }

    for domain, prompt in domain_prompts.items():
        # Should mention workflow, typical flow, or steps
        assert (
            "workflow" in prompt.lower()
            or "flow" in prompt.lower()
            or "1." in prompt  # Numbered steps
        ), f"{domain} prompt missing workflow guidance"


def test_prompts_have_focus_areas():
    """Domain prompts should specify focus areas."""
    domain_prompts = {
        "query": QUERY_SYSTEM_PROMPT,
        "job": JOB_SYSTEM_PROMPT,
        "uc": UC_SYSTEM_PROMPT,
        "cluster": CLUSTER_SYSTEM_PROMPT,
        "diagnostic": DIAGNOSTIC_SYSTEM_PROMPT,
    }

    for domain, prompt in domain_prompts.items():
        # Should mention focus, goal, or output
        assert (
            "focus" in prompt.lower()
            or "goal" in prompt.lower()
            or "output" in prompt.lower()
        ), f"{domain} prompt missing focus areas"


def test_get_system_prompt_formatting_preserves_structure():
    """get_system_prompt() should preserve prompt structure after formatting."""
    prompt = get_system_prompt(
        "query",
        goal="Test goal with special chars: $, %, &",
        token_budget=100_000,
        mode="online",
    )
    # Should still have clear structure (case-insensitive check)
    assert "tools available" in prompt.lower()
    assert "workflow" in prompt.lower()
    # Special characters should be preserved
    assert "$, %, &" in prompt

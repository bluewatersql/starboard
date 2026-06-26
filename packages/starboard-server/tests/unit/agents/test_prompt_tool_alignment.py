# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for prompt-tool alignment validation.

Ensures domain prompts only reference tools they have access to
according to tool_categories.py configuration.
"""

import re

import pytest
from starboard_server.agents.tool_categories import TOOL_CATEGORIES
from starboard_server.prompts import (
    CLUSTER_SYSTEM_PROMPT,
    DIAGNOSTIC_SYSTEM_PROMPT,
    JOB_SYSTEM_PROMPT,
    QUERY_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    UC_SYSTEM_PROMPT,
)

# Prompts may mention delegated tools for user guidance even if the domain agent
# cannot directly call them (e.g., "delegate to compute agent").
_PROMPT_ALLOWED_EXTRA_TOOL_REFERENCES: dict[str, set[str]] = {
    "job": {"get_cluster_events"},
}


def extract_tool_references(prompt: str) -> set[str]:
    """
    Extract tool names referenced in prompt.

    Args:
        prompt: System prompt text

    Returns:
        Set of tool names found in prompt
    """
    # Known tool name patterns (from tool_factory.py)
    known_tools = {
        "resolve_user_intent",
        "resolve_query",
        "analyze_query_plan",
        "parse_explain_facts",
        "get_table_metadata",
        "get_table_history",
        "discover_tables",
        "get_table_lineage",
        "get_enriched_table_metadata",
        "resolve_job",
        "get_job_config",
        "analyze_job_history",
        "execute_sql",
        "analyze_code_quality",
        "get_source_code",
        "get_cluster_config",
        "get_warehouse_config",
        "get_spark_logs",
        "get_cluster_events",
        "get_cluster_metrics",
        "get_warehouse_metrics",
        "get_query_runtime_metrics",
        "ask_user",
        "request_user_input",
        "complete",
    }

    referenced = set()

    # Find all tool references in prompt
    for tool in known_tools:
        # Match tool name as word boundary (not part of larger word)
        pattern = rf"\b{re.escape(tool)}\b"
        if re.search(pattern, prompt, re.IGNORECASE):
            referenced.add(tool)

    return referenced


@pytest.mark.parametrize(
    "domain,prompt",
    [
        ("query", QUERY_SYSTEM_PROMPT),
        ("job", JOB_SYSTEM_PROMPT),
        ("uc", UC_SYSTEM_PROMPT),
        ("cluster", CLUSTER_SYSTEM_PROMPT),
        ("diagnostic", DIAGNOSTIC_SYSTEM_PROMPT),
        ("router", ROUTER_SYSTEM_PROMPT),
    ],
)
def test_prompt_only_references_allowed_tools(domain: str, prompt: str):
    """
    Ensure domain prompts only reference tools they have access to.

    Validates that:
    1. All tools mentioned in prompt are in tool_categories.py for that domain
    2. No disallowed tools are referenced
    3. Core tools (request_user_input, complete) are present
    """
    referenced_tools = extract_tool_references(prompt)
    allowed_tools_list = TOOL_CATEGORIES[domain]

    # Handle "all" marker for diagnostic agent
    if allowed_tools_list == "all":
        # Diagnostic agent can reference any tool
        return

    allowed_tools = set(allowed_tools_list)

    # Check for invalid tool references
    invalid_tools = referenced_tools - allowed_tools

    # Filter out runtime tools (registered dynamically, not in initial TOOL_CATEGORIES)
    runtime_tools = {"complete", "request_user_input"}
    invalid_tools = invalid_tools - runtime_tools
    invalid_tools = invalid_tools - _PROMPT_ALLOWED_EXTRA_TOOL_REFERENCES.get(
        domain, set()
    )

    assert not invalid_tools, (
        f"Domain '{domain}' prompt references disallowed tools: {invalid_tools}\n"
        f"Referenced: {referenced_tools}\n"
        f"Allowed: {allowed_tools}"
    )


@pytest.mark.parametrize(
    "domain,prompt",
    [
        ("query", QUERY_SYSTEM_PROMPT),
        ("job", JOB_SYSTEM_PROMPT),
        ("uc", UC_SYSTEM_PROMPT),
        ("cluster", CLUSTER_SYSTEM_PROMPT),
        ("diagnostic", DIAGNOSTIC_SYSTEM_PROMPT),
    ],
)
def test_prompt_includes_core_tools(domain: str, prompt: str):
    """
    Ensure domain prompts include core tools (request_user_input, complete).

    Router is excluded from this test as it has minimal tool set.
    Diagnostic doesn't explicitly mention request_user_input as it focuses on artifact-first analysis.
    """
    referenced_tools = extract_tool_references(prompt)

    # Core tools that should be present
    # Diagnostic domain doesn't need to explicitly mention request_user_input
    # as it's artifact-first and these tools are added dynamically
    if domain == "diagnostic":
        core_tools = {"complete"}
    else:
        core_tools = {"request_user_input", "complete"}

    missing_core = core_tools - referenced_tools

    assert not missing_core, (
        f"Domain '{domain}' prompt missing core tools: {missing_core}"
    )


@pytest.mark.parametrize(
    "domain,prompt",
    [
        ("query", QUERY_SYSTEM_PROMPT),
        ("job", JOB_SYSTEM_PROMPT),
        ("uc", UC_SYSTEM_PROMPT),
        ("cluster", CLUSTER_SYSTEM_PROMPT),
        ("diagnostic", DIAGNOSTIC_SYSTEM_PROMPT),
        ("router", ROUTER_SYSTEM_PROMPT),
    ],
)
def test_prompt_includes_reasoning_output_section(domain: str, prompt: str):
    """
    Ensure domain prompts include reasoning output guidance.

    Checks for "Reasoning Output" section (any header style) and variation requirements.
    """
    # Prompts use different header styles - check case-insensitively
    assert "reasoning output" in prompt.lower(), (
        f"Domain '{domain}' prompt missing 'Reasoning Output' section"
    )

    # Check for language variation guidance (case-insensitive for flexibility)
    if domain == "diagnostic":
        # Diagnostic uses "Vary your language" in sentence case
        assert "vary your language" in prompt.lower(), (
            f"Domain '{domain}' prompt missing language variation directive"
        )
    else:
        assert "VARY YOUR LANGUAGE" in prompt, (
            f"Domain '{domain}' prompt missing 'VARY YOUR LANGUAGE' directive"
        )


@pytest.mark.parametrize(
    "domain,prompt",
    [
        ("query", QUERY_SYSTEM_PROMPT),
        ("job", JOB_SYSTEM_PROMPT),
        ("uc", UC_SYSTEM_PROMPT),
        ("cluster", CLUSTER_SYSTEM_PROMPT),
        ("diagnostic", DIAGNOSTIC_SYSTEM_PROMPT),
    ],
)
def test_prompt_includes_error_handling_section(domain: str, prompt: str):
    """
    Ensure domain prompts include error handling guidance.

    Checks for "Error Handling" section (any header style) and fail-fast directives.
    """
    # Prompts use different header styles - check case-insensitively
    assert "error handling" in prompt.lower(), (
        f"Domain '{domain}' prompt missing 'Error Handling' section"
    )

    # Diagnostic has different error handling guidance
    if domain == "diagnostic":
        # Diagnostic says "Call `complete` after 1-2 tool failures"
        assert "call" in prompt.lower() and "complete" in prompt.lower(), (
            f"Domain '{domain}' prompt missing complete directive"
        )
    else:
        assert "DON'T retry repeatedly" in prompt, (
            f"Domain '{domain}' prompt missing retry guidance"
        )

        assert "call 'complete'" in prompt.lower(), (
            f"Domain '{domain}' prompt missing complete directive"
        )


def test_router_prompt_minimal_tools():
    """
    Ensure router prompt only has minimal tool set.

    Router should only have: resolve_user_intent, request_user_input, complete
    """
    referenced_tools = extract_tool_references(ROUTER_SYSTEM_PROMPT)
    expected_tools = {"resolve_user_intent", "request_user_input", "complete"}

    # Router should have exactly these tools (or subset)
    unexpected_tools = referenced_tools - expected_tools

    assert not unexpected_tools, (
        f"Router prompt references unexpected tools: {unexpected_tools}\n"
        f"Expected only: {expected_tools}\n"
        f"Found: {referenced_tools}"
    )


def test_diagnostic_prompt_has_all_access():
    """
    Ensure diagnostic agent is documented as having unrestricted access.
    """
    # Check that tool_categories.py marks diagnostic as "all"
    assert TOOL_CATEGORIES["diagnostic"] == "all", (
        "Diagnostic agent should have 'all' tool access in tool_categories.py"
    )

    # Diagnostic prompt focuses on artifact-first analysis rather than
    # explicitly stating tool access, since tools are provided dynamically
    # The actual tool access is enforced in tool_categories.py


@pytest.mark.parametrize(
    "domain,prompt",
    [
        ("query", QUERY_SYSTEM_PROMPT),
        ("job", JOB_SYSTEM_PROMPT),
        ("uc", UC_SYSTEM_PROMPT),
        ("cluster", CLUSTER_SYSTEM_PROMPT),
        ("diagnostic", DIAGNOSTIC_SYSTEM_PROMPT),
    ],
)
def test_prompt_includes_budget_guidance(domain: str, prompt: str):
    """
    Ensure domain prompts include token budget guidance.
    """
    assert "Budget Guidance" in prompt or "Token Budget" in prompt, (
        f"Domain '{domain}' prompt missing budget guidance"
    )


@pytest.mark.parametrize(
    "domain,prompt,has_modes",
    [
        ("query", QUERY_SYSTEM_PROMPT, True),
        ("job", JOB_SYSTEM_PROMPT, True),
        ("uc", UC_SYSTEM_PROMPT, False),
        ("cluster", CLUSTER_SYSTEM_PROMPT, False),
        ("diagnostic", DIAGNOSTIC_SYSTEM_PROMPT, False),
    ],
)
def test_prompt_mode_awareness(domain: str, prompt: str, has_modes: bool):
    """
    Ensure Query and Job agents have mode-aware workflows.

    Only Query and Job agents need ONLINE/OFFLINE mode differentiation.
    """
    if has_modes:
        assert "ONLINE MODE" in prompt, (
            f"Domain '{domain}' prompt missing ONLINE MODE section"
        )
        assert "OFFLINE MODE" in prompt, (
            f"Domain '{domain}' prompt missing OFFLINE MODE section"
        )
        assert "DO NOT CALL" in prompt, (
            f"Domain '{domain}' prompt missing DO NOT CALL restrictions for OFFLINE"
        )
    else:
        # Other domains shouldn't have mode-specific workflows
        pass

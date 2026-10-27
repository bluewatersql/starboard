# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for discovery agent prompt v1 and v2.

Verifies prompt version, format, and registration in the prompt factories.
"""

from starboard.prompts.discovery import DISCOVERY_SYSTEM_PROMPT
from starboard.prompts.discovery.v1 import (
    DISCOVERY_SYSTEM_PROMPT as V1_PROMPT,
)
from starboard.prompts.discovery.v1 import (
    PROMPT_VERSION as V1_VERSION,
)
from starboard.prompts.discovery.v2 import (
    DISCOVERY_SYSTEM_PROMPT as V2_PROMPT,
)
from starboard.prompts.discovery.v2 import (
    PROMPT_VERSION as V2_VERSION,
)
from starboard.prompts.factories import (
    get_prompt_builder_for_domain,
    get_system_prompt,
)

# =====================================================================
# V1 prompt (preserved, not active)
# =====================================================================


def test_v1_prompt_version() -> None:
    """Check V1 PROMPT_VERSION is '1.0.0'."""
    assert V1_VERSION == "1.0.0"


def test_v1_prompt_format() -> None:
    """Verify V1 prompt can be formatted with goal, token_budget, mode."""
    formatted = V1_PROMPT.format(
        goal="Run workspace health assessment",
        token_budget=50_000,
        mode="online",
    )
    assert "Run workspace health assessment" in formatted
    assert "50000" in formatted
    assert "run_workspace_discovery" in formatted


# =====================================================================
# V2 prompt (active)
# =====================================================================


def test_v2_prompt_version() -> None:
    """Check V2 PROMPT_VERSION is '2.0.0'."""
    assert V2_VERSION == "2.0.0"


def test_v2_prompt_format() -> None:
    """Verify V2 prompt can be formatted with goal, token_budget, mode."""
    formatted = V2_PROMPT.format(
        goal="Run workspace health assessment",
        token_budget=50_000,
        mode="online",
    )
    assert "Run workspace health assessment" in formatted
    assert "50000" in formatted
    assert "online" in formatted


def test_v2_prompt_contains_phase_tools() -> None:
    """V2 prompt references the 4 granular phase tools."""
    expected_tools = [
        "discover_active_products",
        "run_discovery_queries",
        "analyze_discovery_domain",
        "synthesize_discovery_report",
    ]
    formatted = V2_PROMPT.format(goal="test", token_budget=1000, mode="online")
    for tool in expected_tools:
        assert tool in formatted, f"{tool} not found in v2 prompt"


def test_v2_prompt_instructs_batch_analysis() -> None:
    """V2 prompt instructs a single batch call with all domains."""
    formatted = V2_PROMPT.format(goal="test", token_budget=1000, mode="online")
    assert "domains" in formatted
    assert "single call" in formatted.lower() or "ONCE" in formatted


def test_v2_prompt_does_not_reference_monolithic_tool() -> None:
    """V2 prompt should NOT reference the legacy run_workspace_discovery."""
    formatted = V2_PROMPT.format(goal="test", token_budget=1000, mode="online")
    assert "run_workspace_discovery" not in formatted


def test_v2_prompt_instructs_complete_tool() -> None:
    """V2 prompt instructs the agent to call the complete tool."""
    formatted = V2_PROMPT.format(goal="test", token_budget=1000, mode="online")
    assert "complete" in formatted.lower()
    assert "Phase 5: Complete" in formatted
    assert "NEVER end reasoning without calling" in formatted


def test_active_prompt_is_v2() -> None:
    """The default export from discovery/ is the v2 prompt."""
    assert DISCOVERY_SYSTEM_PROMPT is V2_PROMPT


# =====================================================================
# Factory integration
# =====================================================================


def test_discovery_prompt_registered_in_factories() -> None:
    """get_prompt_builder_for_domain('discovery') returns a valid builder."""
    builder = get_prompt_builder_for_domain("discovery")
    assert callable(builder)

    from starboard_core.domain.models.llm import OptimizationMode

    prompt = builder(
        mode=OptimizationMode.ONLINE,
        goal="Assess workspace health",
        budget_remaining=100_000,
        context=None,
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 0
    assert "discovery" in prompt.lower()


def test_discovery_in_get_system_prompt() -> None:
    """get_system_prompt('discovery', ...) returns a non-empty string."""
    prompt = get_system_prompt(
        domain="discovery",
        goal="test",
        token_budget=1000,
        mode="online",
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 0

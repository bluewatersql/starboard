# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Shared user input policy guidelines for domain agent prompts.

This module provides reusable instructions for handling user input,
parameter defaults, and date interpretation across all domain agents.

The policies defined here ensure consistent behavior when:
- Interpreting ambiguous date phrases (always use 30-day rolling window)
- Applying default parameter values
- Deciding when to ask users for clarification vs proceed with defaults

Usage:
    from starboard_server.prompts.shared.user_input_policy import (
        build_user_input_policy_section,
        USER_INPUT_POLICY_SECTION,
    )

    # Option 1: Use the pre-built combined section
    prompt = f"... {USER_INPUT_POLICY_SECTION} ..."

    # Option 2: Use builder for customization
    policy = build_user_input_policy_section(include_defaults=True)
"""

__all__ = [
    "DATE_POLICY",
    "PARAMETER_DEFAULTS",
    "USER_INPUT_POLICY",
    "USER_INPUT_POLICY_SECTION",
    "build_user_input_policy_section",
]

# =============================================================================
# DATE INTERPRETATION POLICY
# =============================================================================

DATE_POLICY = """
===============================================================================
DATE INTERPRETATION RULES (NEVER ASK FOR CLARIFICATION)
===============================================================================

**ALWAYS interpret date phrases as 30-day rolling window:**
- "last month" → start_date="30 days ago", end_date="today"
- "past month" → start_date="30 days ago", end_date="today"
- "this month" → start_date="30 days ago", end_date="today"
- "recently" → start_date="30 days ago", end_date="today"
- No time specified → start_date="30 days ago", end_date="today"

**NEVER ask the user to clarify:**
- "Rolling window or calendar month?"
- "What date range did you mean?"
- "Could you specify the time period?"

**Just use the 30-day default and proceed immediately.**
"""

# =============================================================================
# PARAMETER DEFAULTS
# =============================================================================

PARAMETER_DEFAULTS = """
===============================================================================
PARAMETER DEFAULTS (Apply Automatically)
===============================================================================

When parameters are not specified by the user:
- start_date: "30 days ago"
- end_date: "today"
- limit: 10
- idle_threshold: 50

Override only when user explicitly specifies (e.g., "top 5" → limit=5).
"""

# =============================================================================
# USER INPUT POLICY
# =============================================================================

USER_INPUT_POLICY = """
===============================================================================
USER INPUT POLICY
===============================================================================

**PRINCIPLE:** Ask for user input ONLY when absolutely necessary.

**Ask the user ONLY if:**
- A required ID parameter (job_id, warehouse_id, cluster_id, statement_id) is
  COMPLETELY missing AND cannot be inferred from context or handoff
- Multiple ambiguous matches exist (e.g., 5 tables named "customers")

**NEVER ask about:**
- Date ranges, time periods, or "last month" meaning
- Optional parameters that have sensible defaults
- Clarifications that can be inferred from context

**If in doubt:** Use defaults and proceed. Better to provide results with
defaults than to block on unnecessary clarification.
"""

# =============================================================================
# COMBINED SECTION
# =============================================================================

USER_INPUT_POLICY_SECTION = (
    DATE_POLICY + "\n" + PARAMETER_DEFAULTS + "\n" + USER_INPUT_POLICY
)


# =============================================================================
# BUILDER FUNCTION
# =============================================================================


def build_user_input_policy_section(include_defaults: bool = True) -> str:
    """
    Build the user input policy section for inclusion in prompts.

    This function assembles the user input policy guidelines that should be
    included in all domain agent prompts to ensure consistent behavior when
    handling user requests.

    Args:
        include_defaults: Whether to include the PARAMETER_DEFAULTS section.
            Set to False if the agent has its own parameter handling logic.
            Defaults to True.

    Returns:
        Complete user input policy string ready to embed in a prompt.

    Example:
        >>> from starboard_server.prompts.shared.user_input_policy import (
        ...     build_user_input_policy_section,
        ... )
        >>> policy = build_user_input_policy_section()
        >>> "30 days ago" in policy
        True
        >>> "never ask" in policy.lower()
        True

        >>> # Exclude parameter defaults for agents with custom defaults
        >>> policy_no_defaults = build_user_input_policy_section(include_defaults=False)
        >>> "PARAMETER DEFAULTS" in policy_no_defaults
        False
    """
    if include_defaults:
        return USER_INPUT_POLICY_SECTION
    return DATE_POLICY + "\n" + USER_INPUT_POLICY

"""
Shared serialization utilities for agent objects.

Provides a consistent strategy for converting step-like objects (NextStepOption,
Pydantic models, dataclasses, plain dicts) into dictionaries for storage and
transport. This replaces repeated nested-ternary patterns scattered across
agent_state, user_events, and multi_agent_manager.
"""

from __future__ import annotations

from typing import Any


def serialize_step(step: Any) -> dict[str, Any] | Any:
    """
    Serialize a step-like object to a dictionary.

    Attempts serialization in priority order:
    1. ``to_dict()`` -- custom serialization (e.g., NextStepOption)
    2. ``model_dump()`` -- Pydantic V2 models
    3. ``__dict__`` -- plain dataclasses / objects
    4. Returns the value unchanged if none of the above apply

    Args:
        step: Object to serialize (NextStepOption, Pydantic model, dataclass, or dict)

    Returns:
        Dictionary representation, or the original value if not serializable

    Example:
        >>> from starboard_server.agents.serialization import serialize_step
        >>> serialize_step({"number": 1, "label": "Run query"})
        {'number': 1, 'label': 'Run query'}
    """
    if hasattr(step, "to_dict"):
        return step.to_dict()
    if hasattr(step, "model_dump"):
        return step.model_dump()
    if hasattr(step, "__dict__"):
        return step.__dict__
    return step

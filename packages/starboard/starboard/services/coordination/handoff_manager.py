# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Agent handoff domain models.

Domain types describing agent-to-agent handoffs. These models are persisted and
reconstructed by ``ConversationPatternsRepository`` to track routing history.

Examples:
    >>> from starboard.services.coordination.handoff_manager import (
    ...     AgentHandoff,
    ...     HandoffStatus,
    ... )
    >>> handoff = AgentHandoff(
    ...     handoff_id=uuid4(),
    ...     conversation_id="conv_123",
    ...     source_agent_id="query_optimizer",
    ...     target_agent_id="performance_analyzer",
    ...     capability_id="identify_slow_queries",
    ...     status=HandoffStatus.INITIATED,
    ...     handoff_context={"warehouse_id": "prod_dw"},
    ...     initiated_at=datetime.now(UTC),
    ...     completed_at=None,
    ...     failure_reason=None,
    ... )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class HandoffStatus(StrEnum):
    """Status of agent handoff.

    Attributes:
        INITIATED: Handoff initiated, target agent starting work
        COMPLETED: Handoff completed successfully
        FAILED: Handoff failed (target unavailable, error, etc.)
    """

    INITIATED = "initiated"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentHandoff:
    """Represents an agent-to-agent handoff.

    Captures the complete lifecycle of a handoff, from initiation through
    completion or failure. Preserves context needed for seamless transitions.

    Attributes:
        handoff_id: Unique identifier for handoff
        conversation_id: ID of conversation being handed off
        source_agent_id: ID of agent initiating handoff
        target_agent_id: ID of agent receiving handoff
        capability_id: Specific capability being invoked (optional)
        status: Current status of handoff
        handoff_context: Context to pass to target agent
        initiated_at: When handoff was initiated
        completed_at: When handoff completed (None if in progress)
        failure_reason: Reason for failure (None if successful)
    """

    handoff_id: UUID
    conversation_id: str
    source_agent_id: str
    target_agent_id: str
    capability_id: str | None
    status: HandoffStatus
    handoff_context: dict[str, Any]
    initiated_at: datetime
    completed_at: datetime | None
    failure_reason: str | None

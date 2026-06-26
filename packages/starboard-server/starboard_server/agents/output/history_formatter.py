# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
History formatter for API responses.

Converts internal SharedAgentContext to API ConversationHistory format,
handling message transformation, metadata generation, and domain model configs.

Follows Python AI Agent Engineering Standards:
- Single responsibility (formatting only)
- Pure logic (deterministic transformations)
- Explicit dependencies
- Type hints on all functions
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

if TYPE_CHECKING:
    from starboard_server.agents.state.shared_context import SharedAgentContext
    from starboard_server.domain.conversation.api_types import ConversationConfig

from starboard_server.domain.conversation.api_types import (
    ConversationHistory,
    ConversationMetadata,
    DomainModelConfig,
    MessageStatus,
)

logger = structlog.get_logger(__name__)


class HistoryFormatter:
    """
    Formats conversation history for API responses.

    Converts internal SharedAgentContext representation to API ConversationHistory
    format, handling:
    - Message transformation (adding required API fields)
    - Metadata generation (counts, timestamps)
    - Domain model configuration

    Design:
    - Stateless (no instance state)
    - Pure functions (deterministic output)
    - Handles missing fields gracefully
    - Generates unique IDs for messages

    Example:
        ```python
        formatter = HistoryFormatter(domain_config_generator=gen_func)

        history = formatter.format(
            context=shared_agent_context,
            conversation_id="conv_123",
            conversation_config=config,
        )
        ```
    """

    def __init__(
        self,
        domain_config_generator: Callable[..., Any] | None = None,
    ) -> None:
        """
        Initialize history formatter.

        Args:
            domain_config_generator: Function to generate domain model configs
                                    Signature: (ConversationConfig) -> list[dict]
        """
        self._domain_config_generator = domain_config_generator

    def format(
        self,
        context: SharedAgentContext,
        conversation_id: str,
        conversation_config: ConversationConfig | None = None,
    ) -> ConversationHistory:
        """
        Format SharedAgentContext to API ConversationHistory.

        Args:
            context: Internal conversation context
            conversation_id: Conversation identifier
            conversation_config: Optional conversation configuration

        Returns:
            ConversationHistory formatted for API response

        Example:
            >>> formatter = HistoryFormatter()
            >>> history = formatter.format(
            ...     context=shared_context,
            ...     conversation_id="conv_123",
            ... )
            >>> print(f"Messages: {len(history.messages)}")
        """
        # Convert messages to API format
        message_dicts = self._format_messages(context, conversation_id)

        # Build metadata
        metadata = self._build_metadata(message_dicts)

        # Generate domain models config
        domain_models = self._generate_domain_models(context, conversation_config)

        logger.debug(
            "formatted_conversation_history",
            conversation_id=conversation_id,
            message_count=len(message_dicts),
            roles=[m["role"] for m in message_dicts],
        )

        return ConversationHistory(
            conversation_id=conversation_id,
            messages=message_dicts,
            metadata=metadata,
            domain_models=domain_models,
        )

    def _format_messages(
        self,
        context: SharedAgentContext,
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        """
        Convert internal Messages to API message dicts.

        Adds required API fields:
        - message_id: Unique identifier
        - conversation_id: Conversation identifier
        - timestamp: ISO format timestamp
        - trace_id: Trace identifier for debugging
        - status: Message status (completed, pending, error)
        - tool_calls: List of tool calls (ensures list, not None)

        Args:
            context: SharedAgentContext with conversation history
            conversation_id: Conversation identifier

        Returns:
            List of message dicts with all required API fields
        """
        message_dicts = []

        for msg in context.conversation_history:
            # Convert message to dict (handles various formats)
            msg_dict = self._message_to_dict(msg)

            # Add required API fields if missing
            self._ensure_api_fields(msg_dict, conversation_id)

            message_dicts.append(msg_dict)

        return message_dicts

    def _message_to_dict(self, msg: Any) -> dict[str, Any]:
        """
        Convert message to dictionary format.

        Handles multiple message formats:
        - Pydantic models (model_dump)
        - Legacy models (dict)
        - Dict objects
        - Raw objects (fallback)

        Extracts frontend-facing fields from metadata to top level:
        - complete_report (source of truth for all report rendering)
        - next_steps

        Args:
            msg: Message object in any format

        Returns:
            Dictionary representation of message with all fields at correct level
        """
        # Get base message dict
        if hasattr(msg, "model_dump"):
            msg_dict = msg.model_dump()
        elif isinstance(msg, dict):
            msg_dict = msg.copy()
        else:
            # Fallback: extract attributes manually
            metadata = getattr(msg, "metadata", {})
            # Extract tool_calls from metadata if present (agent Messages store it there)
            tool_calls = (
                metadata.get("tool_calls") if isinstance(metadata, dict) else None
            )
            msg_dict = {
                "role": msg.role,
                "content": msg.content,
                "tool_calls": tool_calls,
                "tool_call_id": getattr(msg, "tool_call_id", None),
                "metadata": metadata,
            }

        # Extract frontend-facing fields from metadata to top level
        # These fields are stored in metadata during message creation
        # but the frontend API expects them at the top level
        metadata = msg_dict.get("metadata", {})
        logger.debug(
            "history_formatter_processing_message",
            role=msg_dict.get("role"),
            has_metadata=metadata is not None,
            metadata_is_dict=isinstance(metadata, dict),
            metadata_keys=list(metadata.keys()) if isinstance(metadata, dict) else None,
        )
        if isinstance(metadata, dict):
            # Move complete_report from metadata to top level if present
            if "complete_report" in metadata:
                msg_dict["complete_report"] = metadata["complete_report"]

            # Move next_steps from metadata to top level if present
            if "next_steps" in metadata:
                msg_dict["next_steps"] = metadata["next_steps"]
                logger.debug(
                    "next_steps_extracted_from_metadata",
                    role=msg_dict.get("role"),
                    next_steps_count=len(metadata["next_steps"]),
                    has_complete_report=bool(msg_dict.get("complete_report")),
                )

        return msg_dict

    def _ensure_api_fields(
        self,
        msg_dict: dict[str, Any],
        conversation_id: str,
    ) -> None:
        """
        Ensure message dict has all required API fields.

        Adds missing fields with generated defaults:
        - message_id
        - conversation_id
        - timestamp
        - trace_id
        - status
        - tool_calls (ensures list)

        Args:
            msg_dict: Message dictionary (modified in place)
            conversation_id: Conversation identifier
        """
        # Add required API fields if missing
        if "message_id" not in msg_dict:
            msg_dict["message_id"] = f"msg_{uuid4().hex[:12]}"

        if "conversation_id" not in msg_dict:
            msg_dict["conversation_id"] = conversation_id

        if "timestamp" not in msg_dict:
            # Use metadata timestamp if available, otherwise use current time
            timestamp = msg_dict.get("metadata", {}).get("timestamp")
            if not timestamp:
                timestamp = datetime.now(UTC).isoformat()
            msg_dict["timestamp"] = timestamp

        if "trace_id" not in msg_dict:
            msg_dict["trace_id"] = f"trace_{uuid4().hex[:12]}"

        if "status" not in msg_dict:
            # Default to completed status
            msg_dict["status"] = MessageStatus.COMPLETED

        if msg_dict.get("tool_calls") is None:
            # Ensure tool_calls is a list, not None
            msg_dict["tool_calls"] = []

    def _build_metadata(self, message_dicts: list[dict]) -> ConversationMetadata:
        """
        Build conversation metadata from messages.

        Args:
            message_dicts: List of formatted message dictionaries

        Returns:
            ConversationMetadata with counts and timestamps
        """
        return ConversationMetadata(
            total_messages=len(message_dicts),
            total_tokens=0,  # Would need to track in context
            total_cost=0.0,  # Would need to track in context
            created_at=datetime.now(UTC),  # Placeholder, not stored in context
            updated_at=datetime.now(UTC),
            friendly_name="Conversation",  # Placeholder, not stored in context
        )

    def _generate_domain_models(
        self,
        context: SharedAgentContext,
        conversation_config: ConversationConfig | None,
    ) -> list[DomainModelConfig]:
        """
        Generate domain model configurations.

        Args:
            context: SharedAgentContext with metadata
            conversation_config: Optional conversation configuration

        Returns:
            List of DomainModelConfig objects
        """
        # Try to get config from context metadata if not provided
        if not conversation_config:
            from starboard_server.domain.conversation.api_types import (
                ConversationConfig as CC,
            )

            conv_config_dict = context.metadata.get("conversation_config", {})
            conversation_config = CC(**conv_config_dict) if conv_config_dict else CC()

        # Generate domain model configs using provided generator
        if self._domain_config_generator:
            domain_models_data = self._domain_config_generator(conversation_config)
            return [DomainModelConfig(**dm) for dm in domain_models_data]

        # No generator provided, return empty list
        return []

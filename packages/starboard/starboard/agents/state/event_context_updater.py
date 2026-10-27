# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Event context updater for shared agent context.

Updates shared conversation context based on streaming events
from specialist agents (tool usage tracking, working memory updates,
entity discovery tracking).

Follows Python AI Agent Engineering Standards:
- Single responsibility (context updates only)
- Pure function design (mutates input, but clear contract)
- Type hints on all functions
- Explicit side effects
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starboard.agents.state.shared_context import SharedAgentContext

from starboard.agents.events import (
    StreamingEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)

# Mapping of tool names to the entity types and argument keys they discover
# Format: (entity_type, argument_key)
ENTITY_DISCOVERY_MAP: dict[str, tuple[str, str]] = {
    "get_table_metadata": ("tables", "table_name"),
    "get_enriched_table_metadata": ("tables", "table_name"),
    "discover_tables": ("tables", "table_name"),  # May need special handling
    "get_table_history": ("tables", "table_name"),
    "get_table_lineage": ("tables", "table_name"),
    "resolve_query": ("query_ids", "statement_id"),
    "analyze_query_plan": ("query_ids", "statement_id"),
    "resolve_job": ("job_ids", "job_id"),
    "get_job_config": ("job_ids", "job_id"),
    "analyze_job_history": ("job_ids", "job_id"),
    "get_cluster_config": ("cluster_ids", "cluster_id"),
    "get_cluster_metrics": ("cluster_ids", "cluster_id"),
    "get_warehouse_config": ("warehouse_ids", "warehouse_id"),
    "get_warehouse_metrics": ("warehouse_ids", "warehouse_id"),
}

# Mapping of tool names to entities discovered in their OUTPUT (results)
# Format: tool_name -> list of (entity_type, output_key)
# These are extracted from ToolEndEvent.output when the tool completes
ENTITY_OUTPUT_MAP: dict[str, list[tuple[str, str]]] = {
    # analyze_job_history returns cluster_id in its result
    "analyze_job_history": [("cluster_ids", "cluster_id")],
    # get_job_config may also return cluster info
    "get_job_config": [("cluster_ids", "cluster_id")],
}


class EventContextUpdater:
    """
    Updates shared context based on streaming events.

    Tracks tool usage, discovered entities, and merges working memory
    from completed steps into the shared conversation context.

    Entity Tracking:
    When tools that discover entities (tables, IDs, etc.) are called,
    extracts the entity from the tool arguments and tracks it in the
    shared context. This enables robust cross-agent context passing.

    Design:
    - Side-effect function (mutates shared_context)
    - Handles specific event types (ToolStartEvent, ToolEndEvent)
    - Maintains tool usage history and discovered entities

    Example:
        ```python
        updater = EventContextUpdater()

        # Update context based on event
        updater.update(shared_context, tool_start_event)

        # Context now tracks discovered entities
        print(shared_context.get_discovered_entities())
        # {'tables': ['cprice_main.core.orders']}
        ```
    """

    def update(self, shared_context: SharedAgentContext, event: StreamingEvent) -> None:
        """
        Update shared context based on streaming events.

        Handles:
        - ToolStartEvent: Extracts and tracks discovered entities from arguments
        - ToolEndEvent: Tracks tool usage in working memory and extracts entities from output

        Args:
            shared_context: Shared conversation context to update (mutated)
            event: Streaming event from specialist agent

        Side Effects:
            Mutates shared_context.working_memory to track tool usage
            Mutates shared_context to track discovered entities

        Example:
            >>> updater = EventContextUpdater()
            >>> tool_event = ToolStartEvent(
            ...     tool_name="get_table_metadata",
            ...     arguments={"table_name": "main.sales.orders"},
            ...     ...
            ... )
            >>> updater.update(shared_context, tool_event)
            >>> shared_context.get_discovered_entities()
            {'tables': ['main.sales.orders']}
        """
        if isinstance(event, ToolStartEvent):
            # Extract and track entities from tool arguments
            self._track_entities_from_tool_call(shared_context, event)

        elif isinstance(event, ToolEndEvent):
            # Track tool usage in shared memory
            shared_context.working_memory = shared_context.working_memory.add_tool_used(
                event.tool_name
            )
            # Extract and track entities from tool output (results)
            self._track_entities_from_tool_output(shared_context, event)

    def _track_entities_from_tool_call(
        self,
        shared_context: SharedAgentContext,
        event: ToolStartEvent,
    ) -> None:
        """
        Extract and track discovered entities from tool call arguments.

        Looks up the tool in ENTITY_DISCOVERY_MAP to determine what
        entity type it discovers and which argument contains the value.

        Args:
            shared_context: Context to update with discovered entity
            event: Tool start event with arguments
        """
        tool_name = event.tool_name
        arguments = event.arguments or {}

        # Check if this tool discovers entities
        if tool_name not in ENTITY_DISCOVERY_MAP:
            return

        entity_type, arg_key = ENTITY_DISCOVERY_MAP[tool_name]

        # Extract entity value from arguments
        entity_value = arguments.get(arg_key)

        if entity_value:
            # Handle both single values and lists
            if isinstance(entity_value, list):
                for value in entity_value:
                    if value:
                        shared_context.track_entity(entity_type, str(value))
            else:
                shared_context.track_entity(entity_type, str(entity_value))

            logger.debug(
                "entity_discovered_from_tool_argument",
                tool_name=tool_name,
                entity_type=entity_type,
                entity_value=entity_value,
            )

    def _track_entities_from_tool_output(
        self,
        shared_context: SharedAgentContext,
        event: ToolEndEvent,
    ) -> None:
        """
        Extract and track discovered entities from tool output (results).

        Some tools return important entity IDs in their results that should
        be tracked for cross-agent context passing. For example:
        - analyze_job_history returns cluster_id in its output
        - get_job_config may return cluster configuration details

        Args:
            shared_context: Context to update with discovered entity
            event: Tool end event with output
        """
        tool_name = event.tool_name

        # Check if this tool has output entities to track
        if tool_name not in ENTITY_OUTPUT_MAP:
            return

        # Use the pre-parsed output dict from the event
        output = getattr(event, "output", None)
        if not output or not isinstance(output, dict):
            return

        # Extract each configured entity from output
        for entity_type, output_key in ENTITY_OUTPUT_MAP[tool_name]:
            entity_value = output.get(output_key)

            if entity_value:
                # Handle both single values and lists
                if isinstance(entity_value, list):
                    for value in entity_value:
                        if value:
                            shared_context.track_entity(entity_type, str(value))
                else:
                    shared_context.track_entity(entity_type, str(entity_value))

                logger.debug(
                    "entity_discovered_from_tool_output",
                    tool_name=tool_name,
                    entity_type=entity_type,
                    entity_value=entity_value,
                )

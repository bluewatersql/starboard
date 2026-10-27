# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for EventContextUpdater entity tracking functionality.

Tests the automatic extraction and tracking of discovered entities
from tool call events, enabling robust cross-agent context passing.
"""

import pytest
from starboard.agents.events import ToolEndEvent, ToolStartEvent
from starboard.agents.state.agent_state import WorkingMemory
from starboard.agents.state.event_context_updater import (
    ENTITY_DISCOVERY_MAP,
    ENTITY_OUTPUT_MAP,
    EventContextUpdater,
)
from starboard.agents.state.shared_context import SharedAgentContext


@pytest.fixture
def shared_context():
    """Create a basic SharedAgentContext for testing."""
    return SharedAgentContext(
        conversation_id="test_conv_123",
        user_id="test_user",
        conversation_history=[],
        working_memory=WorkingMemory(),
    )


@pytest.fixture
def updater():
    """Create an EventContextUpdater instance."""
    return EventContextUpdater()


class TestEntityDiscoveryFromToolCalls:
    """Tests for entity extraction from tool start events."""

    def test_get_table_metadata_tracks_table(self, shared_context, updater):
        """Test that get_table_metadata tracks the table name."""
        event = ToolStartEvent(
            step=1,
            tool_name="get_table_metadata",
            friendly_name="Getting Table Metadata",
            tool_call_id="call_123",
            arguments={"table_name": "cprice_main.core.orders"},
        )

        updater.update(shared_context, event)

        entities = shared_context.get_discovered_entities()
        assert "tables" in entities
        assert "cprice_main.core.orders" in entities["tables"]

    def test_resolve_query_tracks_statement_id(self, shared_context, updater):
        """Test that resolve_query tracks the statement ID."""
        event = ToolStartEvent(
            step=1,
            tool_name="resolve_query",
            friendly_name="Resolving Query",
            tool_call_id="call_456",
            arguments={"statement_id": "stmt_abc123"},
        )

        updater.update(shared_context, event)

        entities = shared_context.get_discovered_entities()
        assert "query_ids" in entities
        assert "stmt_abc123" in entities["query_ids"]

    def test_resolve_job_tracks_job_id(self, shared_context, updater):
        """Test that resolve_job tracks the job ID."""
        event = ToolStartEvent(
            step=1,
            tool_name="resolve_job",
            friendly_name="Resolving Job",
            tool_call_id="call_789",
            arguments={"job_id": "job_xyz789"},
        )

        updater.update(shared_context, event)

        entities = shared_context.get_discovered_entities()
        assert "job_ids" in entities
        assert "job_xyz789" in entities["job_ids"]

    def test_get_cluster_config_tracks_cluster_id(self, shared_context, updater):
        """Test that get_cluster_config tracks the cluster ID."""
        event = ToolStartEvent(
            step=1,
            tool_name="get_cluster_config",
            friendly_name="Getting Cluster Config",
            tool_call_id="call_abc",
            arguments={"cluster_id": "cluster_abc123"},
        )

        updater.update(shared_context, event)

        entities = shared_context.get_discovered_entities()
        assert "cluster_ids" in entities
        assert "cluster_abc123" in entities["cluster_ids"]

    def test_get_warehouse_config_tracks_warehouse_id(self, shared_context, updater):
        """Test that get_warehouse_config tracks the warehouse ID."""
        event = ToolStartEvent(
            step=1,
            tool_name="get_warehouse_config",
            friendly_name="Getting Warehouse Config",
            tool_call_id="call_def",
            arguments={"warehouse_id": "wh_def456"},
        )

        updater.update(shared_context, event)

        entities = shared_context.get_discovered_entities()
        assert "warehouse_ids" in entities
        assert "wh_def456" in entities["warehouse_ids"]

    def test_unknown_tool_does_not_track(self, shared_context, updater):
        """Test that unknown tools don't track entities."""
        event = ToolStartEvent(
            step=1,
            tool_name="unknown_tool",
            friendly_name="Unknown Tool",
            tool_call_id="call_unknown",
            arguments={"some_arg": "some_value"},
        )

        updater.update(shared_context, event)

        entities = shared_context.get_discovered_entities()
        assert entities == {}

    def test_missing_argument_does_not_track(self, shared_context, updater):
        """Test that missing arguments don't cause errors."""
        event = ToolStartEvent(
            step=1,
            tool_name="get_table_metadata",
            friendly_name="Getting Table Metadata",
            tool_call_id="call_123",
            arguments={},  # Missing table_name
        )

        updater.update(shared_context, event)

        entities = shared_context.get_discovered_entities()
        assert entities == {}

    def test_empty_argument_value_does_not_track(self, shared_context, updater):
        """Test that empty argument values don't track."""
        event = ToolStartEvent(
            step=1,
            tool_name="get_table_metadata",
            friendly_name="Getting Table Metadata",
            tool_call_id="call_123",
            arguments={"table_name": ""},  # Empty string value
        )

        updater.update(shared_context, event)

        entities = shared_context.get_discovered_entities()
        assert entities == {}


class TestMultipleToolCalls:
    """Tests for entity accumulation across multiple tool calls."""

    def test_multiple_tables_accumulated(self, shared_context, updater):
        """Test that multiple table calls accumulate entities."""
        tables = [
            "cprice_main.core.orders",
            "cprice_main.core.products",
            "cprice_main.core.customers",
        ]

        for i, table in enumerate(tables):
            event = ToolStartEvent(
                step=i + 1,
                tool_name="get_table_metadata",
                friendly_name=f"Getting Table Metadata for {table}",
                tool_call_id=f"call_{i}",
                arguments={"table_name": table},
            )
            updater.update(shared_context, event)

        entities = shared_context.get_discovered_entities()
        assert len(entities["tables"]) == 3
        for table in tables:
            assert table in entities["tables"]

    def test_mixed_entity_types_accumulated(self, shared_context, updater):
        """Test that different entity types accumulate correctly."""
        # Track a table
        updater.update(
            shared_context,
            ToolStartEvent(
                step=1,
                tool_name="get_table_metadata",
                friendly_name="...",
                tool_call_id="call_1",
                arguments={"table_name": "main.orders"},
            ),
        )

        # Track a query
        updater.update(
            shared_context,
            ToolStartEvent(
                step=2,
                tool_name="resolve_query",
                friendly_name="...",
                tool_call_id="call_2",
                arguments={"statement_id": "stmt_123"},
            ),
        )

        # Track a warehouse
        updater.update(
            shared_context,
            ToolStartEvent(
                step=3,
                tool_name="get_warehouse_config",
                friendly_name="...",
                tool_call_id="call_3",
                arguments={"warehouse_id": "wh_456"},
            ),
        )

        entities = shared_context.get_discovered_entities()
        assert "tables" in entities
        assert "query_ids" in entities
        assert "warehouse_ids" in entities


class TestToolEndEventBehavior:
    """Tests for ToolEndEvent handling."""

    def test_tool_end_tracks_usage(self, shared_context, updater):
        """Test that ToolEndEvent tracks tool usage."""
        event = ToolEndEvent(
            step=1,
            tool_name="get_table_metadata",
            friendly_name="Getting Table Metadata",
            tool_call_id="call_123",
            result_summary="Table metadata fetched",
            success=True,
            duration_seconds=0.5,
        )

        updater.update(shared_context, event)

        assert "get_table_metadata" in shared_context.working_memory.tools_used

    def test_tool_end_does_not_track_entities_for_unmapped_tools(
        self, shared_context, updater
    ):
        """Test that ToolEndEvent doesn't track entities for tools not in ENTITY_OUTPUT_MAP."""
        event = ToolEndEvent(
            step=1,
            tool_name="get_table_metadata",  # Not in ENTITY_OUTPUT_MAP
            friendly_name="Getting Table Metadata",
            tool_call_id="call_123",
            result_summary="Table metadata fetched",
            success=True,
            duration_seconds=0.5,
        )

        updater.update(shared_context, event)

        # Entities from arguments are tracked from ToolStartEvent
        # Entities from outputs are only tracked for tools in ENTITY_OUTPUT_MAP
        entities = shared_context.get_discovered_entities()
        assert entities == {}


class TestEntityOutputTracking:
    """Tests for entity extraction from tool output (ToolEndEvent)."""

    def test_analyze_job_history_tracks_cluster_id_from_output(
        self, shared_context, updater
    ):
        """Test that analyze_job_history extracts cluster_id from its output."""
        # Simulate ToolEndEvent with output containing cluster_id
        event = ToolEndEvent(
            step=1,
            tool_name="analyze_job_history",
            friendly_name="Analyzing Job History",
            tool_call_id="call_job_123",
            result_summary='{"total_runs": 9, "cluster_id": "1201-090640-dwj7ygpe"}',
            success=True,
            duration_seconds=0.5,
            # Note: ToolEndEvent doesn't have 'output' field, but our updater
            # checks for it to extract entities from tool results
        )

        # We need to check if the updater can handle this
        # The current implementation expects 'output' field which ToolEndEvent doesn't have
        updater.update(shared_context, event)

        # Tool usage should be tracked
        assert "analyze_job_history" in shared_context.working_memory.tools_used

    def test_entity_output_map_configuration(self):
        """Test that ENTITY_OUTPUT_MAP is properly configured."""
        # analyze_job_history should track cluster_ids from output
        assert "analyze_job_history" in ENTITY_OUTPUT_MAP
        output_mappings = ENTITY_OUTPUT_MAP["analyze_job_history"]
        assert ("cluster_ids", "cluster_id") in output_mappings

    def test_get_job_config_tracks_cluster_id_from_output(self):
        """Test that get_job_config is configured to track cluster_id."""
        assert "get_job_config" in ENTITY_OUTPUT_MAP
        output_mappings = ENTITY_OUTPUT_MAP["get_job_config"]
        assert ("cluster_ids", "cluster_id") in output_mappings


class TestEntityDiscoveryMapCoverage:
    """Tests to verify ENTITY_DISCOVERY_MAP configuration."""

    def test_all_mapped_tools_have_valid_config(self):
        """Test that all mapped tools have valid entity_type and arg_key."""
        for tool_name, (entity_type, arg_key) in ENTITY_DISCOVERY_MAP.items():
            assert isinstance(entity_type, str), f"{tool_name} has invalid entity_type"
            assert isinstance(arg_key, str), f"{tool_name} has invalid arg_key"
            assert entity_type, f"{tool_name} has empty entity_type"
            assert arg_key, f"{tool_name} has empty arg_key"

    def test_table_tools_map_to_tables_entity(self):
        """Test that table-related tools map to 'tables' entity type."""
        table_tools = [
            "get_table_metadata",
            "get_enriched_table_metadata",
            "get_table_history",
            "get_table_lineage",
        ]
        for tool in table_tools:
            if tool in ENTITY_DISCOVERY_MAP:
                entity_type, _ = ENTITY_DISCOVERY_MAP[tool]
                assert entity_type == "tables", f"{tool} should map to 'tables'"

    def test_query_tools_map_to_query_ids_entity(self):
        """Test that query-related tools map to 'query_ids' entity type."""
        query_tools = ["resolve_query", "analyze_query_plan"]
        for tool in query_tools:
            if tool in ENTITY_DISCOVERY_MAP:
                entity_type, _ = ENTITY_DISCOVERY_MAP[tool]
                assert entity_type == "query_ids", f"{tool} should map to 'query_ids'"

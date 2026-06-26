# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Contract tests for NextStepAction/NextStepOption schema.

These tests lock the canonical schema to prevent breaking changes.
The schema is used by:
- Frontend: To render interactive next step buttons
- CLI: To display numbered options
- Backend: For cross-agent routing and tool invocation

If you need to change the schema, update these tests and coordinate
with frontend/CLI consumers.

Phase 4: Agent Hardening - Next Step Standardization
"""

import pytest
from starboard_core.domain.models.llm_schemas import NextStepAction


class TestNextStepActionSchema:
    """Contract tests for NextStepAction Pydantic model."""

    def test_required_fields(self) -> None:
        """NextStepAction requires id, number, title, action_type."""
        # Valid minimal instance
        step = NextStepAction(
            id="test_step_1",
            number=1,
            title="Test action",
            action_type="continue",
        )
        assert step.id == "test_step_1"
        assert step.number == 1
        assert step.title == "Test action"
        assert step.action_type == "continue"

    def test_optional_fields_default_to_none(self) -> None:
        """Optional fields default to None."""
        step = NextStepAction(
            id="test_step",
            number=1,
            title="Test",
            action_type="continue",
        )
        assert step.description is None
        assert step.target_agent is None
        assert step.tool_name is None
        assert step.parameters is None

    def test_all_fields_populated(self) -> None:
        """All fields can be populated."""
        step = NextStepAction(
            id="route_to_cluster",
            number=2,
            title="Analyze cluster configuration",
            description="Deep dive into cluster sizing and autoscaling",
            action_type="route",
            target_agent="cluster",
            tool_name=None,
            parameters={"cluster_id": "cluster-123", "context": "performance"},
        )
        assert step.id == "route_to_cluster"
        assert step.number == 2
        assert step.title == "Analyze cluster configuration"
        assert step.description == "Deep dive into cluster sizing and autoscaling"
        assert step.action_type == "route"
        assert step.target_agent == "cluster"
        assert step.parameters == {
            "cluster_id": "cluster-123",
            "context": "performance",
        }

    def test_action_type_enum_values(self) -> None:
        """action_type must be one of: continue, route, tool_call."""
        # Valid action types
        for action_type in ["continue", "route", "tool_call"]:
            step = NextStepAction(
                id="test",
                number=1,
                title="Test",
                action_type=action_type,  # type: ignore
            )
            assert step.action_type == action_type

        # Invalid action type
        with pytest.raises(ValueError):
            NextStepAction(
                id="test",
                number=1,
                title="Test",
                action_type="invalid",  # type: ignore
            )

    def test_number_bounds(self) -> None:
        """number must be 1-9."""
        # Valid numbers
        for num in [1, 5, 9]:
            step = NextStepAction(
                id="test",
                number=num,
                title="Test",
                action_type="continue",
            )
            assert step.number == num

        # Invalid: 0 (too low)
        with pytest.raises(ValueError):
            NextStepAction(
                id="test",
                number=0,
                title="Test",
                action_type="continue",
            )

        # Invalid: 10 (too high)
        with pytest.raises(ValueError):
            NextStepAction(
                id="test",
                number=10,
                title="Test",
                action_type="continue",
            )

    def test_id_cannot_be_empty(self) -> None:
        """id field cannot be empty string."""
        with pytest.raises(ValueError):
            NextStepAction(
                id="",
                number=1,
                title="Test",
                action_type="continue",
            )

    def test_title_cannot_be_empty(self) -> None:
        """title field cannot be empty string."""
        with pytest.raises(ValueError):
            NextStepAction(
                id="test",
                number=1,
                title="",
                action_type="continue",
            )

    def test_title_max_length(self) -> None:
        """title has max length of 100 characters."""
        # Valid: exactly 100 chars
        step = NextStepAction(
            id="test",
            number=1,
            title="x" * 100,
            action_type="continue",
        )
        assert len(step.title) == 100

        # Invalid: 101 chars
        with pytest.raises(ValueError):
            NextStepAction(
                id="test",
                number=1,
                title="x" * 101,
                action_type="continue",
            )


class TestNextStepActionSerialization:
    """Contract tests for NextStepAction JSON serialization."""

    def test_model_dump_returns_canonical_fields(self) -> None:
        """model_dump() produces canonical field names."""
        step = NextStepAction(
            id="step_1",
            number=1,
            title="Test action",
            description="Test description",
            action_type="route",
            target_agent="query",
            tool_name=None,
            parameters={"key": "value"},
        )
        data = step.model_dump()

        # CRITICAL: These are the canonical field names that consumers depend on
        assert "id" in data
        assert "number" in data
        assert "title" in data
        assert "description" in data
        assert "action_type" in data
        assert "target_agent" in data
        assert "tool_name" in data
        assert "parameters" in data

        # CRITICAL: Legacy field names must NOT appear
        assert "rank" not in data
        assert "action" not in data
        assert "expected_impact" not in data
        assert "effort" not in data
        assert "category" not in data

    def test_json_roundtrip(self) -> None:
        """JSON serialization and deserialization preserves all fields."""
        original = NextStepAction(
            id="route_step",
            number=3,
            title="Route to specialist",
            description="Hand off to domain expert",
            action_type="route",
            target_agent="analytics",
            tool_name=None,
            parameters={"context": {"tables": ["sales"]}},
        )

        json_str = original.model_dump_json()
        restored = NextStepAction.model_validate_json(json_str)

        assert restored.id == original.id
        assert restored.number == original.number
        assert restored.title == original.title
        assert restored.description == original.description
        assert restored.action_type == original.action_type
        assert restored.target_agent == original.target_agent
        assert restored.parameters == original.parameters

    def test_json_schema_has_canonical_fields(self) -> None:
        """Generated JSON schema uses canonical field names."""
        schema = NextStepAction.model_json_schema()

        # Check required fields
        assert "id" in schema["required"]
        assert "number" in schema["required"]
        assert "title" in schema["required"]
        assert "action_type" in schema["required"]

        # Check properties exist
        props = schema["properties"]
        assert "id" in props
        assert "number" in props
        assert "title" in props
        assert "description" in props
        assert "action_type" in props
        assert "target_agent" in props
        assert "tool_name" in props
        assert "parameters" in props

        # Legacy fields must NOT be in schema
        assert "rank" not in props
        assert "action" not in props
        assert "expected_impact" not in props


class TestNextStepOptionDataclass:
    """Contract tests for NextStepOption frozen dataclass."""

    def test_nextstep_option_has_canonical_fields(self) -> None:
        """NextStepOption dataclass uses canonical fields."""
        from starboard_server.domain.models.conversation_patterns import (
            ActionType,
            NextStepOption,
        )

        option = NextStepOption(
            id="opt_1",
            number=1,
            title="Test option",
            description="Test description",
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters=None,
        )

        assert option.id == "opt_1"
        assert option.number == 1
        assert option.title == "Test option"
        assert option.description == "Test description"
        assert option.action_type == ActionType.CONTINUE

    def test_to_dict_produces_canonical_keys(self) -> None:
        """NextStepOption.to_dict() produces canonical keys."""
        from starboard_server.domain.models.conversation_patterns import (
            ActionType,
            NextStepOption,
        )

        option = NextStepOption(
            id="opt_2",
            number=2,
            title="Route to cluster",
            description="Analyze cluster",
            action_type=ActionType.ROUTE,
            target_agent="cluster",
            tool_name=None,
            parameters={"cluster_id": "abc"},
        )
        data = option.to_dict()

        # CRITICAL: Canonical field names
        assert data["id"] == "opt_2"
        assert data["number"] == 2
        assert data["title"] == "Route to cluster"
        assert data["description"] == "Analyze cluster"
        assert data["action_type"] == "route"
        assert data["target_agent"] == "cluster"
        assert data["parameters"] == {"cluster_id": "abc"}

        # Legacy fields must NOT appear
        assert "rank" not in data
        assert "action" not in data
        assert "expected_impact" not in data

    def test_from_dict_accepts_canonical_keys(self) -> None:
        """NextStepOption.from_dict() accepts canonical keys."""
        from starboard_server.domain.models.conversation_patterns import (
            ActionType,
            NextStepOption,
        )

        data = {
            "id": "from_dict_test",
            "number": 3,
            "title": "Tool call option",
            "description": "Execute a tool",
            "action_type": "tool_call",
            "target_agent": None,
            "tool_name": "resolve_query",
            "parameters": {"query_id": "123"},
        }
        option = NextStepOption.from_dict(data)

        assert option.id == "from_dict_test"
        assert option.number == 3
        assert option.title == "Tool call option"
        assert option.description == "Execute a tool"
        assert option.action_type == ActionType.TOOL_CALL
        assert option.tool_name == "resolve_query"
        assert option.parameters == {"query_id": "123"}

    def test_nextstep_option_is_frozen(self) -> None:
        """NextStepOption is immutable (frozen dataclass)."""
        from starboard_server.domain.models.conversation_patterns import (
            ActionType,
            NextStepOption,
        )

        option = NextStepOption(
            id="frozen_test",
            number=1,
            title="Test",
            description=None,
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters=None,
        )

        with pytest.raises(AttributeError):
            option.title = "Modified"  # type: ignore


class TestNextStepSchemaAlignment:
    """Ensure NextStepAction and NextStepOption are aligned."""

    def test_field_names_match(self) -> None:
        """NextStepAction (Pydantic) and NextStepOption (dataclass) have same fields."""
        import dataclasses

        from starboard_core.domain.models.llm_schemas import NextStepAction
        from starboard_server.domain.models.conversation_patterns import NextStepOption

        pydantic_fields = set(NextStepAction.model_fields.keys())
        dataclass_fields = {f.name for f in dataclasses.fields(NextStepOption)}

        assert pydantic_fields == dataclass_fields, (
            f"Field mismatch:\n"
            f"  Pydantic only: {pydantic_fields - dataclass_fields}\n"
            f"  Dataclass only: {dataclass_fields - pydantic_fields}"
        )

    def test_action_type_values_match(self) -> None:
        """ActionType enum values match NextStepAction action_type literals."""
        from typing import get_args

        from starboard_core.domain.models.llm_schemas import NextStepAction
        from starboard_server.domain.models.conversation_patterns import ActionType

        # Get literal values from Pydantic field
        action_type_field = NextStepAction.model_fields["action_type"]
        literal_values = set(get_args(action_type_field.annotation))

        # Get enum values
        enum_values = {e.value for e in ActionType}

        assert literal_values == enum_values, (
            f"ActionType mismatch:\n"
            f"  Literal only: {literal_values - enum_values}\n"
            f"  Enum only: {enum_values - literal_values}"
        )

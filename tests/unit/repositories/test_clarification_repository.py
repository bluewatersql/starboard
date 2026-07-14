# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for ClarificationRepository.

Coverage targets:
- CRUD operations (Create, Read, Update)
- Query operations (filtering, retrieval)
- Edge cases (empty results, nulls, missing data)
- Error handling (connection errors, invalid data)
- Data serialization (options, resolution)
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from starboard_core.domain.models.clarification import (
    ClarificationOption,
    ClarificationRequest,
    ClarificationType,
)
from starboard.repositories.clarification_repository import (
    ClarificationRepository,
)


@pytest.fixture
def mock_db_client():
    """Provide a mock database client."""
    client = AsyncMock()
    client.execute = AsyncMock()
    client.fetchone = AsyncMock()
    client.fetch_all = AsyncMock()
    return client


@pytest.fixture
def clarification_repository(mock_db_client):
    """Create a ClarificationRepository with mocked database."""
    return ClarificationRepository(db_client=mock_db_client)


@pytest.fixture
def sample_clarification():
    """Create a sample clarification request for testing."""
    return ClarificationRequest(
        clarification_id="clarif-123",
        conversation_id="conv-456",
        message_id="msg-789",
        clarification_type=ClarificationType.MULTIPLE_MATCHES,
        question="Which warehouse do you want to analyze?",
        options=(
            ClarificationOption(
                option_id="opt-1",
                display_text="Production Warehouse",
                value="prod_dw",
                is_recommended=True,
                metadata={"description": "Main production data warehouse"},
            ),
            ClarificationOption(
                option_id="opt-2",
                display_text="Staging Warehouse",
                value="staging_dw",
                is_recommended=False,
                metadata=None,
            ),
        ),
        allow_custom_response=False,
        is_required=True,
        default_value=None,
        created_at=datetime.now(UTC),
        resolved_at=None,
        resolution=None,
    )


class TestSaveClarification:
    """Tests for saving clarification requests."""

    @pytest.mark.asyncio
    async def test_save_valid_clarification(
        self, clarification_repository, mock_db_client, sample_clarification
    ):
        """Test saving a valid clarification request."""
        await clarification_repository.save(sample_clarification)

        # Verify database execute was called once
        mock_db_client.execute.assert_called_once()

        # Verify SQL INSERT query structure
        call_args = mock_db_client.execute.call_args
        query = call_args[0][0]
        assert "INSERT INTO clarification_requests" in query
        assert "clarification_id" in query

        # Verify all required fields are in the query
        params = call_args[0][1:]
        assert params[0] == "clarif-123"  # clarification_id
        assert params[1] == "conv-456"  # conversation_id
        assert params[2] == "msg-789"  # message_id

    @pytest.mark.asyncio
    async def test_save_clarification_with_options(
        self, clarification_repository, mock_db_client, sample_clarification
    ):
        """Test that options are properly serialized to JSON."""
        await clarification_repository.save(sample_clarification)

        call_args = mock_db_client.execute.call_args
        # The options should be in the parameters (7th parameter, index 6 after query)
        options_json = call_args[0][6]

        # Verify it's JSON string containing options
        assert options_json is not None
        assert isinstance(options_json, str)
        assert "opt-1" in options_json
        assert "prod_dw" in options_json
        assert "is_recommended" in options_json

    @pytest.mark.asyncio
    async def test_save_clarification_without_options(
        self, clarification_repository, mock_db_client
    ):
        """Test saving clarification without options."""
        clarification = ClarificationRequest(
            clarification_id="clarif-no-opts",
            conversation_id="conv-456",
            message_id="msg-789",
            clarification_type=ClarificationType.INSUFFICIENT_CONTEXT,
            question="Please describe your issue",
            options=None,
            allow_custom_response=True,
            is_required=False,
            default_value=None,
            created_at=datetime.now(UTC),
            resolved_at=None,
            resolution=None,
        )

        await clarification_repository.save(clarification)

        mock_db_client.execute.assert_called_once()
        call_args = mock_db_client.execute.call_args
        # Verify the call was made with correct clarification_id
        assert call_args[0][1] == "clarif-no-opts"
        # Options parameter should be None (7th param, index 6)
        options_param = call_args[0][6]
        assert options_param is None

    @pytest.mark.asyncio
    async def test_save_clarification_with_default_value(
        self, clarification_repository, mock_db_client
    ):
        """Test saving clarification with default value."""
        # Create a new clarification with default_value (can't modify frozen dataclass)
        clarification = ClarificationRequest(
            clarification_id="clarif-with-default",
            conversation_id="conv-456",
            message_id="msg-789",
            clarification_type=ClarificationType.MISSING_PARAMETER,
            question="What warehouse size?",
            options=None,
            allow_custom_response=True,
            is_required=True,
            default_value={"warehouse": "prod_dw"},  # Set default value
            created_at=datetime.now(UTC),
            resolved_at=None,
            resolution=None,
        )

        await clarification_repository.save(clarification)

        mock_db_client.execute.assert_called_once()
        call_args = mock_db_client.execute.call_args
        default_value_param = call_args[0][
            9
        ]  # default_value parameter (10th param, index 9)
        assert default_value_param is not None
        assert isinstance(default_value_param, str)
        assert "prod_dw" in default_value_param


class TestGetClarification:
    """Tests for retrieving clarification requests."""

    @pytest.mark.asyncio
    async def test_get_existing_clarification(
        self, clarification_repository, mock_db_client
    ):
        """Test retrieving an existing clarification request."""
        # Mock database response
        mock_db_client.fetchone.return_value = {
            "clarification_id": "clarif-123",
            "conversation_id": "conv-456",
            "message_id": "msg-789",
            "clarification_type": "multiple_matches",
            "question": "Which warehouse?",
            "options": '[{"option_id": "opt-1", "display_text": "Production", "value": "prod_dw", "is_recommended": true, "metadata": null}]',
            "allow_custom_response": False,
            "is_required": True,
            "default_value": None,
            "created_at": datetime.now(UTC),
            "resolved_at": None,
            "resolution": None,
        }

        result = await clarification_repository.get_by_id("clarif-123")

        # Verify database was called
        mock_db_client.fetchone.assert_called_once()

        # Verify query structure
        call_args = mock_db_client.fetchone.call_args
        assert "SELECT" in call_args[0][0]
        assert "FROM clarification_requests" in call_args[0][0]
        assert "WHERE clarification_id = $1" in call_args[0][0]

        # Verify result
        assert result is not None
        assert result.clarification_id == "clarif-123"
        assert result.conversation_id == "conv-456"
        assert result.clarification_type == ClarificationType.MULTIPLE_MATCHES
        assert len(result.options) == 1
        assert result.options[0].option_id == "opt-1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_clarification(
        self, clarification_repository, mock_db_client
    ):
        """Test that getting non-existent clarification returns None."""
        mock_db_client.fetchone.return_value = None

        result = await clarification_repository.get_by_id("nonexistent")

        assert result is None
        mock_db_client.fetchone.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_clarification_without_options(
        self, clarification_repository, mock_db_client
    ):
        """Test retrieving clarification that has no options."""
        mock_db_client.fetchone.return_value = {
            "clarification_id": "clarif-no-opts",
            "conversation_id": "conv-456",
            "message_id": "msg-789",
            "clarification_type": "insufficient_context",
            "question": "Describe your issue",
            "options": None,
            "allow_custom_response": True,
            "is_required": False,
            "default_value": None,
            "created_at": datetime.now(UTC),
            "resolved_at": None,
            "resolution": None,
        }

        result = await clarification_repository.get_by_id("clarif-no-opts")

        assert result is not None
        assert result.options is None
        assert result.clarification_type == ClarificationType.INSUFFICIENT_CONTEXT

    @pytest.mark.asyncio
    async def test_get_clarification_with_resolution(
        self, clarification_repository, mock_db_client
    ):
        """Test retrieving resolved clarification."""
        resolved_time = datetime.now(UTC)
        mock_db_client.fetchone.return_value = {
            "clarification_id": "clarif-resolved",
            "conversation_id": "conv-456",
            "message_id": "msg-789",
            "clarification_type": "multiple_matches",
            "question": "Which warehouse?",
            "options": "[]",
            "allow_custom_response": False,
            "is_required": True,
            "default_value": None,
            "created_at": datetime.now(UTC),
            "resolved_at": resolved_time,
            "resolution": '{"selected": "prod_dw"}',
        }

        result = await clarification_repository.get_by_id("clarif-resolved")

        assert result is not None
        assert result.resolved_at == resolved_time
        assert result.resolution == {"selected": "prod_dw"}


class TestUpdateResolution:
    """Tests for updating clarification resolution."""

    @pytest.mark.asyncio
    async def test_update_resolution(self, clarification_repository, mock_db_client):
        """Test updating clarification with resolution."""
        resolution = {"selected_value": "prod_dw", "option_id": "opt-1"}

        await clarification_repository.update_resolution("clarif-123", resolution)

        # Verify database was called
        mock_db_client.execute.assert_called_once()

        # Verify SQL UPDATE query structure
        call_args = mock_db_client.execute.call_args
        query = call_args[0][0]
        assert "UPDATE clarification_requests" in query
        assert "SET resolved_at = $1, resolution = $2" in query
        assert "WHERE clarification_id = $3" in query

        # Verify parameters
        params = call_args[0][1:]
        assert params[0] is not None  # resolved_at timestamp
        assert "prod_dw" in params[1]  # resolution JSON
        assert params[2] == "clarif-123"  # clarification_id

    @pytest.mark.asyncio
    async def test_update_resolution_with_complex_data(
        self, clarification_repository, mock_db_client
    ):
        """Test updating resolution with complex nested data."""
        resolution = {
            "answers": ["option1", "option2"],
            "metadata": {"source": "ui", "timestamp": 1234567890},
        }

        await clarification_repository.update_resolution("clarif-456", resolution)

        mock_db_client.execute.assert_called_once()
        call_args = mock_db_client.execute.call_args
        resolution_json = call_args[0][2]

        # Verify complex data is serialized
        assert "option1" in resolution_json
        assert "metadata" in resolution_json


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_save_with_empty_question(
        self, clarification_repository, mock_db_client
    ):
        """Test saving clarification with empty question string."""
        clarification = ClarificationRequest(
            clarification_id="clarif-empty",
            conversation_id="conv-456",
            message_id="msg-789",
            clarification_type=ClarificationType.UNCLEAR_INTENT,
            question="",  # Empty question
            options=None,
            allow_custom_response=True,
            is_required=False,
            default_value=None,
            created_at=datetime.now(UTC),
            resolved_at=None,
            resolution=None,
        )

        await clarification_repository.save(clarification)

        mock_db_client.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_with_malformed_options_json(
        self, clarification_repository, mock_db_client
    ):
        """Test handling of malformed options JSON."""
        mock_db_client.fetchone.return_value = {
            "clarification_id": "clarif-bad",
            "conversation_id": "conv-456",
            "message_id": "msg-789",
            "clarification_type": "multiple_matches",
            "question": "Test",
            "options": "invalid json {",
            "allow_custom_response": False,
            "is_required": True,
            "default_value": None,
            "created_at": datetime.now(UTC),
            "resolved_at": None,
            "resolution": None,
        }

        # Should raise JSON decode error
        import json

        with pytest.raises(json.JSONDecodeError):
            await clarification_repository.get_by_id("clarif-bad")

    @pytest.mark.asyncio
    async def test_connection_error_propagates(
        self, clarification_repository, mock_db_client
    ):
        """Test that database connection errors propagate."""
        mock_db_client.execute.side_effect = ConnectionError("Database unavailable")

        clarification = ClarificationRequest(
            clarification_id="clarif-error",
            conversation_id="conv-456",
            message_id="msg-789",
            clarification_type=ClarificationType.MISSING_PARAMETER,
            question="Test",
            options=None,
            allow_custom_response=True,
            is_required=False,
            default_value=None,
            created_at=datetime.now(UTC),
            resolved_at=None,
            resolution=None,
        )

        with pytest.raises(ConnectionError):
            await clarification_repository.save(clarification)

    @pytest.mark.asyncio
    async def test_save_with_special_characters(
        self, clarification_repository, mock_db_client
    ):
        """Test saving clarification with special characters in question."""
        clarification = ClarificationRequest(
            clarification_id="clarif-special",
            conversation_id="conv-456",
            message_id="msg-789",
            clarification_type=ClarificationType.AMBIGUOUS_ENTITY,
            question="What's your warehouse? (e.g., 'prod', \"staging\")",
            options=None,
            allow_custom_response=True,
            is_required=False,
            default_value=None,
            created_at=datetime.now(UTC),
            resolved_at=None,
            resolution=None,
        )

        await clarification_repository.save(clarification)

        mock_db_client.execute.assert_called_once()
        call_args = mock_db_client.execute.call_args
        # Question is the 6th parameter (index 5 after query)
        question_param = call_args[0][5]
        assert "What's" in question_param
        assert "staging" in question_param


class TestIntegration:
    """Integration-style tests for full lifecycle."""

    @pytest.mark.asyncio
    async def test_full_clarification_lifecycle(
        self, clarification_repository, mock_db_client, sample_clarification
    ):
        """Test complete lifecycle: save -> get -> update."""
        # Save
        await clarification_repository.save(sample_clarification)
        assert mock_db_client.execute.call_count == 1

        # Mock get response
        mock_db_client.fetchone.return_value = {
            "clarification_id": sample_clarification.clarification_id,
            "conversation_id": sample_clarification.conversation_id,
            "message_id": sample_clarification.message_id,
            "clarification_type": sample_clarification.clarification_type.value,
            "question": sample_clarification.question,
            "options": '[{"option_id": "opt-1", "display_text": "Production Warehouse", "value": "prod_dw", "is_recommended": true, "metadata": {"description": "Main production data warehouse"}}]',
            "allow_custom_response": sample_clarification.allow_custom_response,
            "is_required": sample_clarification.is_required,
            "default_value": None,
            "created_at": sample_clarification.created_at,
            "resolved_at": None,
            "resolution": None,
        }

        # Get
        retrieved = await clarification_repository.get_by_id(
            sample_clarification.clarification_id
        )
        assert retrieved is not None
        assert retrieved.clarification_id == sample_clarification.clarification_id

        # Update
        resolution = {"selected": "prod_dw"}
        await clarification_repository.update_resolution(
            sample_clarification.clarification_id, resolution
        )
        assert mock_db_client.execute.call_count == 2

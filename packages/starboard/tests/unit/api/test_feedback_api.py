# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for Feedback API endpoints.

Tests the HTTP API layer for feedback submission and performance metrics.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starboard_core.domain.models.feedback import (
    AgentPerformanceReport,
    FeedbackCategory,
    FeedbackContext,
    FeedbackRating,
    UserFeedback,
)
from starboard.api.feedback import router


@pytest.fixture
def app():
    """Create FastAPI app with feedback router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_feedback_service():
    """Create mock feedback service."""
    service = AsyncMock()
    return service


@pytest.fixture
def mock_container(mock_feedback_service):  # noqa: ARG001
    """Create mock dependency injection container."""
    container = MagicMock()

    # Mock state store with _conn attribute
    mock_state_store = MagicMock()
    mock_state_store._conn = MagicMock()  # SQLite connection
    container.state_store = mock_state_store

    # Mock conversation repository
    container.conversation_repo = MagicMock()

    return container


def override_get_container(mock_container):
    """Override dependency for testing."""
    return lambda: mock_container


class TestSubmitFeedbackEndpoint:
    """Test POST /conversations/{conversation_id}/feedback endpoint."""

    def test_submit_positive_feedback(
        self,
        client,
        mock_feedback_service,  # noqa: ARG002
        mock_container,
        app,  # noqa: ARG002
    ):
        """Test submitting positive feedback."""
        # Arrange
        feedback = UserFeedback(
            feedback_id="fb_123",
            conversation_id="conv_456",
            message_id="msg_789",
            user_id="user_001",
            agent_name="query_agent",
            rating=FeedbackRating.POSITIVE,
            categories=None,
            comment=None,
            timestamp=datetime.now(UTC),
            context_snapshot=FeedbackContext(
                user_query="test query",
                agent_response="test response",
                conversation_history=(),
                agent_version="v1.0",
                prompt_version="v1.0",
                model_used="gpt-4",
                temperature=0.4,
                response_length=100,
                num_tool_calls=0,
                tool_names=(),
                had_next_steps=False,
                response_time_ms=100.0,
                token_count=50,
                cost_usd=0.001,
                user_session_length=1,
                is_repeat_query=False,
            ),
        )

        # Override dependency and patch FeedbackService
        from starboard.api.dependencies import get_state_container

        app.dependency_overrides[get_state_container] = override_get_container(
            mock_container
        )

        with patch(
            "starboard.services.feedback.feedback_service.FeedbackService"
        ) as MockService:
            mock_service_instance = AsyncMock()
            mock_service_instance.submit_feedback.return_value = feedback
            MockService.return_value = mock_service_instance

            # Act
            response = client.post(
                "/api/conversations/conv_456/feedback",
                json={
                    "message_id": "msg_789",
                    "rating": "positive",
                },
            )

            # Assert
            assert response.status_code == 201
            data = response.json()
            assert data["feedback_id"] == "fb_123"
            assert data["rating"] == "positive"
            assert data["categories"] is None
            assert data["comment"] is None

            # Verify service was called correctly
            mock_service_instance.submit_feedback.assert_called_once()
            call_kwargs = mock_service_instance.submit_feedback.call_args.kwargs
            assert call_kwargs["conversation_id"] == "conv_456"
            assert call_kwargs["message_id"] == "msg_789"
            assert call_kwargs["rating"] == FeedbackRating.POSITIVE
            assert call_kwargs["categories"] is None

    def test_submit_negative_feedback_with_categories(
        self,
        client,
        mock_feedback_service,  # noqa: ARG002
        mock_container,
        app,  # noqa: ARG002
    ):
        """Test submitting negative feedback with categories and comment."""
        # Arrange
        feedback = UserFeedback(
            feedback_id="fb_456",
            conversation_id="conv_789",
            message_id="msg_001",
            user_id="user_002",
            agent_name="query_agent",
            rating=FeedbackRating.NEGATIVE,
            categories=(FeedbackCategory.INACCURATE, FeedbackCategory.TOO_VAGUE),
            comment="Not specific enough",
            timestamp=datetime.now(UTC),
            context_snapshot=FeedbackContext(
                user_query="test query",
                agent_response="test response",
                conversation_history=(),
                agent_version="v1.0",
                prompt_version="v1.0",
                model_used="gpt-4",
                temperature=0.4,
                response_length=100,
                num_tool_calls=0,
                tool_names=(),
                had_next_steps=False,
                response_time_ms=100.0,
                token_count=50,
                cost_usd=0.001,
                user_session_length=1,
                is_repeat_query=False,
            ),
        )

        # Override dependency and patch FeedbackService
        from starboard.api.dependencies import get_state_container

        app.dependency_overrides[get_state_container] = override_get_container(
            mock_container
        )

        with patch(
            "starboard.services.feedback.feedback_service.FeedbackService"
        ) as MockService:
            mock_service_instance = AsyncMock()
            mock_service_instance.submit_feedback.return_value = feedback
            MockService.return_value = mock_service_instance

            # Act
            response = client.post(
                "/api/conversations/conv_789/feedback",
                json={
                    "message_id": "msg_001",
                    "rating": "negative",
                    "categories": ["inaccurate", "too_vague"],
                    "comment": "Not specific enough",
                },
            )

            # Assert
            assert response.status_code == 201
            data = response.json()
            assert data["rating"] == "negative"
            assert set(data["categories"]) == {"inaccurate", "too_vague"}
            assert data["comment"] == "Not specific enough"

    def test_submit_feedback_conversation_not_found(
        self,
        client,
        mock_feedback_service,  # noqa: ARG002
        mock_container,
        app,  # noqa: ARG002
    ):
        """Test feedback submission when conversation doesn't exist."""
        # Override dependency and patch FeedbackService
        from starboard.api.dependencies import get_state_container

        app.dependency_overrides[get_state_container] = override_get_container(
            mock_container
        )

        with patch(
            "starboard.services.feedback.feedback_service.FeedbackService"
        ) as MockService:
            mock_service_instance = AsyncMock()
            mock_service_instance.submit_feedback.side_effect = ValueError(
                "Conversation not found"
            )
            MockService.return_value = mock_service_instance

            # Act
            response = client.post(
                "/api/conversations/nonexistent/feedback",
                json={
                    "message_id": "msg_123",
                    "rating": "positive",
                },
            )

            # Assert
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

    def test_submit_feedback_invalid_rating(self, client, app, mock_container):
        """Test feedback submission with invalid rating value."""
        # Override dependency (even though validation happens before service is called)
        from starboard.api.dependencies import get_state_container

        app.dependency_overrides[get_state_container] = override_get_container(
            mock_container
        )

        # Act
        response = client.post(
            "/api/conversations/conv_123/feedback",
            json={
                "message_id": "msg_456",
                "rating": "invalid_rating",
            },
        )

        # Assert
        assert response.status_code == 422  # Validation error


class TestGetAgentPerformanceEndpoint:
    """Test GET /feedback/agents/{agent_name}/performance endpoint."""

    def test_get_performance_default_period(
        self,
        client,
        mock_feedback_service,  # noqa: ARG002
        mock_container,
        app,  # noqa: ARG002
    ):
        """Test getting agent performance with default 7-day period."""
        # Arrange
        report = AgentPerformanceReport(
            agent_name="query_agent",
            period_days=7,
            total_feedback=100,
            positive_count=85,
            negative_count=15,
            satisfaction_rate=0.85,
            negative_categories={"inaccurate": 5, "too_vague": 10},
            generated_at=datetime.now(UTC),
        )

        # Override dependency and patch FeedbackService
        from starboard.api.dependencies import get_state_container

        app.dependency_overrides[get_state_container] = override_get_container(
            mock_container
        )

        with patch(
            "starboard.services.feedback.feedback_service.FeedbackService"
        ) as MockService:
            mock_service_instance = AsyncMock()
            mock_service_instance.get_agent_performance.return_value = report
            MockService.return_value = mock_service_instance

            # Act
            response = client.get("/api/feedback/agents/query_agent/performance")

            # Assert
            assert response.status_code == 200
            data = response.json()
            assert data["agent_name"] == "query_agent"
            assert data["period_days"] == 7
            assert data["total_feedback"] == 100
            assert data["satisfaction_rate"] == 0.85

            # Verify service was called with default days=7
            mock_service_instance.get_agent_performance.assert_called_once_with(
                agent_name="query_agent",
                days=7,
            )

    def test_get_performance_custom_period(
        self,
        client,
        mock_feedback_service,  # noqa: ARG002
        mock_container,
        app,  # noqa: ARG002
    ):
        """Test getting performance with custom time period."""
        # Arrange
        report = AgentPerformanceReport(
            agent_name="job_agent",
            period_days=30,
            total_feedback=250,
            positive_count=200,
            negative_count=50,
            satisfaction_rate=0.8,
            negative_categories={"didnt_answer": 30, "missing_info": 20},
            generated_at=datetime.now(UTC),
        )

        # Override dependency and patch FeedbackService
        from starboard.api.dependencies import get_state_container

        app.dependency_overrides[get_state_container] = override_get_container(
            mock_container
        )

        with patch(
            "starboard.services.feedback.feedback_service.FeedbackService"
        ) as MockService:
            mock_service_instance = AsyncMock()
            mock_service_instance.get_agent_performance.return_value = report
            MockService.return_value = mock_service_instance

            # Act
            response = client.get("/api/feedback/agents/job_agent/performance?days=30")

            # Assert
            assert response.status_code == 200
            data = response.json()
            assert data["period_days"] == 30

            # Verify service was called with custom days
            mock_service_instance.get_agent_performance.assert_called_once_with(
                agent_name="job_agent",
                days=30,
            )

    def test_get_performance_no_feedback(
        self,
        client,
        mock_feedback_service,  # noqa: ARG002
        mock_container,
        app,  # noqa: ARG002
    ):
        """Test performance endpoint when no feedback exists."""
        # Arrange
        report = AgentPerformanceReport(
            agent_name="new_agent",
            period_days=7,
            total_feedback=0,
            positive_count=0,
            negative_count=0,
            satisfaction_rate=0.0,
            negative_categories={},
            generated_at=datetime.now(UTC),
        )

        # Override dependency and patch FeedbackService
        from starboard.api.dependencies import get_state_container

        app.dependency_overrides[get_state_container] = override_get_container(
            mock_container
        )

        with patch(
            "starboard.services.feedback.feedback_service.FeedbackService"
        ) as MockService:
            mock_service_instance = AsyncMock()
            mock_service_instance.get_agent_performance.return_value = report
            MockService.return_value = mock_service_instance

            # Act
            response = client.get("/api/feedback/agents/new_agent/performance")

            # Assert
            assert response.status_code == 200
            data = response.json()
            assert data["total_feedback"] == 0
            assert data["satisfaction_rate"] == 0.0

    def test_get_performance_invalid_days_negative(self, client, app, mock_container):
        """Test performance endpoint with invalid days parameter (negative)."""
        # Override dependency (even though validation happens before service is called)
        from starboard.api.dependencies import get_state_container

        app.dependency_overrides[get_state_container] = override_get_container(
            mock_container
        )

        # Act
        response = client.get("/api/feedback/agents/query_agent/performance?days=-1")

        # Assert
        assert response.status_code == 422  # Validation error

    def test_get_performance_invalid_days_too_large(self, client, app, mock_container):
        """Test performance endpoint with days parameter exceeding limit."""
        # Override dependency (even though validation happens before service is called)
        from starboard.api.dependencies import get_state_container

        app.dependency_overrides[get_state_container] = override_get_container(
            mock_container
        )

        # Act
        response = client.get("/api/feedback/agents/query_agent/performance?days=500")

        # Assert
        assert response.status_code == 422  # Validation error

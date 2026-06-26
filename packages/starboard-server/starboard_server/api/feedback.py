# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Feedback API REST endpoints.

Provides HTTP endpoints for feedback collection and analytics:
- POST /conversations/{id}/feedback - Submit feedback on a message
- GET /feedback/agents/{agent_name}/performance - Get agent performance metrics
"""

from fastapi import APIRouter, HTTPException, Path, Query, status
from starboard_core.domain.models.feedback import FeedbackCategory, FeedbackRating

from starboard_server.api.dependencies import ContainerDep
from starboard_server.api.models import (
    AgentPerformanceResponse,
    ErrorResponse,
    FeedbackResponse,
    SubmitFeedbackRequest,
)
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["feedback"])


# =============================================================================
# Feedback Submission Endpoints
# =============================================================================


@router.post(
    "/conversations/{conversation_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit Feedback",
    description="Submit user feedback on an agent's response",
    responses={
        201: {"description": "Feedback submitted successfully"},
        404: {
            "description": "Conversation or message not found",
            "model": ErrorResponse,
        },
        422: {"description": "Validation error", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def submit_feedback(
    conversation_id: str = Path(..., description="Conversation ID"),
    request: SubmitFeedbackRequest = ...,  # type: ignore[assignment]
    container: ContainerDep = ...,  # type: ignore[assignment]
) -> FeedbackResponse:
    """
    Submit user feedback on an agent response.

    This endpoint allows users to rate agent responses as positive or negative,
    with optional categories and comments for negative feedback. The feedback
    is used to improve agent performance and identify areas for improvement.

    Args:
        conversation_id: Unique conversation identifier
        request: Feedback submission request with rating, categories, and comment
        container: Dependency injection container (injected)

    Returns:
        FeedbackResponse with feedback_id and submission details

    Raises:
        HTTPException: 404 if conversation/message not found, 422 for validation errors

    Example:
        ```bash
        curl -X POST http://localhost:8000/api/v2/conversations/conv_123/feedback \\
          -H "Content-Type: application/json" \\
          -d '{
            "message_id": "msg_456",
            "rating": "negative",
            "categories": ["inaccurate", "too_vague"],
            "comment": "The response was not specific enough"
          }'
        ```

        Response (201 Created):
        ```json
        {
          "feedback_id": "fb_xyz789",
          "conversation_id": "conv_123",
          "message_id": "msg_456",
          "rating": "negative",
          "categories": ["inaccurate", "too_vague"],
          "comment": "The response was not specific enough",
          "timestamp": "2025-11-22T12:00:00Z"
        }
        ```
    """
    try:
        # Create feedback service using container's feedback repository
        from starboard_server.services.feedback.feedback_service import FeedbackService

        feedback_service = FeedbackService(
            repository=container.feedback_repo,  # type: ignore[arg-type]
            conversation_repository=container.conversation_repo,
        )

        # Convert API enums to domain enums
        rating = FeedbackRating(request.rating.value)
        categories = None
        if request.categories:
            categories = [FeedbackCategory(cat.value) for cat in request.categories]

        # Submit feedback
        feedback = await feedback_service.submit_feedback(
            conversation_id=conversation_id,
            message_id=request.message_id,
            rating=rating,
            categories=categories,
            comment=request.comment,
        )

        logger.debug(
            "feedback_submitted_api",
            feedback_id=feedback.feedback_id,
            conversation_id=conversation_id,
            message_id=request.message_id,
            rating=request.rating.value,
        )

        # Convert to API response
        return FeedbackResponse(
            feedback_id=feedback.feedback_id,
            conversation_id=feedback.conversation_id,
            message_id=feedback.message_id,
            rating=feedback.rating.value,
            categories=(
                [cat.value for cat in feedback.categories]
                if feedback.categories
                else None
            ),
            comment=feedback.comment,
            timestamp=feedback.timestamp,
        )

    except ValueError as e:
        # Conversation or message not found
        logger.warning(
            "feedback_submission_not_found",
            conversation_id=conversation_id,
            message_id=request.message_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation or message not found: {str(e)}",
        ) from e

    except Exception as e:  # noqa: BLE001 - API error boundary
        logger.error(
            "feedback_submission_failed",
            conversation_id=conversation_id,
            message_id=request.message_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit feedback: {str(e)}",
        ) from e


# =============================================================================
# Performance Analytics Endpoints
# =============================================================================


@router.get(
    "/feedback/agents/{agent_name}/performance",
    response_model=AgentPerformanceResponse,
    summary="Get Agent Performance",
    description="Get performance metrics for an agent based on user feedback",
    responses={
        200: {"description": "Performance report generated successfully"},
        422: {"description": "Validation error", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def get_agent_performance(
    agent_name: str = Path(..., description="Name of the agent"),
    days: int = Query(
        7, ge=1, le=365, description="Number of days to include in report"
    ),
    container: ContainerDep = ...,  # type: ignore[assignment]
) -> AgentPerformanceResponse:
    """
    Get agent performance metrics based on user feedback.

    This endpoint generates a performance report for a specific agent,
    showing satisfaction rates, feedback counts, and negative feedback
    categories over a specified time period.

    Args:
        agent_name: Name of the agent (e.g., "query_agent", "job_agent")
        days: Number of days to include in the report (default: 7, max: 365)
        container: Dependency injection container (injected)

    Returns:
        AgentPerformanceResponse with satisfaction metrics and category breakdown

    Example:
        ```bash
        curl http://localhost:8000/api/v2/feedback/agents/query_agent/performance?days=30
        ```

        Response (200 OK):
        ```json
        {
          "agent_name": "query_agent",
          "period_days": 30,
          "total_feedback": 150,
          "positive_count": 125,
          "negative_count": 25,
          "satisfaction_rate": 0.833,
          "negative_categories": {
            "inaccurate": 8,
            "too_vague": 12,
            "missing_info": 5
          },
          "generated_at": "2025-11-22T12:00:00Z"
        }
        ```
    """
    try:
        # Create feedback service using container's feedback repository
        from starboard_server.services.feedback.feedback_service import FeedbackService

        feedback_service = FeedbackService(
            repository=container.feedback_repo,  # type: ignore[arg-type]
            conversation_repository=container.conversation_repo,
        )

        # Get performance report
        report = await feedback_service.get_agent_performance(
            agent_name=agent_name,
            days=days,
        )

        logger.debug(
            "performance_report_generated",
            agent_name=agent_name,
            period_days=days,
            total_feedback=report.total_feedback,
            satisfaction_rate=report.satisfaction_rate,
        )

        # Convert to API response
        return AgentPerformanceResponse(
            agent_name=report.agent_name,
            period_days=report.period_days,
            total_feedback=report.total_feedback,
            positive_count=report.positive_count,
            negative_count=report.negative_count,
            satisfaction_rate=report.satisfaction_rate,
            negative_categories=report.negative_categories,
            generated_at=report.generated_at,
        )

    except Exception as e:  # noqa: BLE001 - API error boundary
        logger.error(
            "performance_report_failed",
            agent_name=agent_name,
            period_days=days,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate performance report: {str(e)}",
        ) from e

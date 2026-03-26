"""Clarification API REST endpoints.

Provides HTTP endpoints for handling clarification requests:
- POST /conversations/{id}/clarifications/{clarification_id}/respond - Respond to clarification
"""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path, status

from starboard_server.api.dependencies import ContainerDep
from starboard_server.api.models import (
    ErrorResponse,
    RespondToClarificationRequest,
    RespondToClarificationResponse,
)
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["clarification"])


# =============================================================================
# Clarification Response Endpoints
# =============================================================================


@router.post(
    "/conversations/{conversation_id}/clarifications/{clarification_id}/respond",
    response_model=RespondToClarificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Respond to Clarification",
    description="Provide a response to a clarification request",
    responses={
        200: {"description": "Clarification response accepted"},
        404: {
            "description": "Conversation or clarification not found",
            "model": ErrorResponse,
        },
        422: {"description": "Validation error", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def respond_to_clarification(
    conversation_id: str = Path(..., description="Conversation ID"),
    clarification_id: str = Path(..., description="Clarification ID"),
    request: RespondToClarificationRequest = ...,  # type: ignore[assignment]
    container: ContainerDep = ...,  # type: ignore[assignment]
) -> RespondToClarificationResponse:
    """
    Respond to a clarification request.

    When the framework sends a clarification.request event (because it detected
    an ambiguous query), use this endpoint to provide the requested information.
    The framework will then enrich the original query and continue execution.

    Args:
        conversation_id: Unique conversation identifier
        clarification_id: Unique clarification identifier (from event)
        request: Clarification response with selected option or custom text
        container: Dependency injection container (injected)

    Returns:
        RespondToClarificationResponse with enriched query and status

    Raises:
        HTTPException: 404 if conversation/clarification not found, 422 for validation errors

    Example:
        ```bash
        # User selects option 2 (Medium warehouse size)
        curl -X POST http://localhost:8000/api/v2/conversations/conv_123/clarifications/clar_abc/respond \\
          -H "Content-Type: application/json" \\
          -d '{
            "clarification_id": "clar_abc",
            "response_type": "option_selected",
            "selected_option_id": "2"
          }'
        ```

        Response (200 OK):
        ```json
        {
          "response_id": "resp_xyz",
          "clarification_id": "clar_abc",
          "status": "accepted",
          "enriched_query": "create warehouse my-wh size Medium",
          "message": "Clarification accepted, continuing with execution",
          "created_at": "2025-11-24T12:00:00Z"
        }
        ```

        SSE Events (after response):
        ```
        event: agent.thinking
        data: {"content": "Creating warehouse with size Medium..."}

        event: tool.call
        data: {"tool_name": "create_warehouse", ...}
        ```
    """
    logger.debug(
        "clarification_response_received",
        conversation_id=conversation_id,
        clarification_id=clarification_id,
        response_type=request.response_type,
    )

    # Validate clarification_id matches
    if request.clarification_id != clarification_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Clarification ID mismatch: {request.clarification_id} != {clarification_id}",
        )

    try:
        # SIMPLIFIED: Router clarifications are ephemeral (not stored in DB)
        # Just determine the enriched query from the selected option
        enriched_query = None

        if request.response_type == "option_selected" and request.selected_option_id:
            # Map option to enriched query
            # For router clarifications, we just pass through the selected domain
            # The multi-agent manager will handle re-routing
            enriched_query = (
                f"help with {request.selected_option_id.replace('opt_', '')}"
            )

        elif request.response_type == "custom_text" and request.custom_text:
            enriched_query = request.custom_text
        else:
            raise ValueError(
                "Invalid clarification response: missing option or custom text"
            )

        logger.debug(
            "clarification_resolved",
            clarification_id=clarification_id,
            enriched_query=enriched_query,
        )

        # Re-inject as new user message to trigger agent processing
        # This mimics how request_user_input tool works
        await container.multi_agent_manager.enqueue_message(  # type: ignore[attr-defined]
            conversation_id=conversation_id,
            content=enriched_query,
            user_id="default_user",  # TODO(BACKLOG-001): Extract user_id from auth request context
        )

        # Generate response
        response_id = f"resp_{uuid4().hex[:12]}"
        return RespondToClarificationResponse(
            response_id=response_id,
            clarification_id=clarification_id,
            status="accepted",
            enriched_query=enriched_query,
            message="Clarification accepted, continuing with execution",
            created_at=datetime.now(UTC),
        )

    except ValueError as e:
        # Clarification not found or already resolved
        logger.warning(
            "clarification_response_not_found",
            conversation_id=conversation_id,
            clarification_id=clarification_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clarification not found or already resolved: {str(e)}",
        ) from e

    except Exception as e:  # noqa: BLE001 - API error boundary
        logger.error(
            "clarification_response_failed",
            conversation_id=conversation_id,
            clarification_id=clarification_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process clarification response: {str(e)}",
        ) from e

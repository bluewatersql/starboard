# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Message and interruption endpoints.

Provides HTTP endpoints for message handling and interruptible reasoning:
- POST /conversations/{id}/messages - Send message
- POST /conversations/{id}/inject-input - Inject input during reasoning
- POST /conversations/{id}/respond-to-solicitation - Respond to agent question
- GET /conversations/{id}/checkpoints - Get checkpoints for interruption
"""

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status

from starboard_server.api.dependencies import ContainerDep, MultiAgentManagerDep
from starboard_server.api.models import (
    CheckpointsResponse,
    ErrorResponse,
    InjectInputRequest,
    InjectInputResponse,
    MessageResponse,
    RespondToSolicitationRequest,
    RespondToSolicitationResponse,
    SendMessageRequest,
)
from starboard_server.api.ownership import verify_conversation_ownership
from starboard_server.infra.middleware.rate_limit import check_rate_limit
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.diagnostic.large_artifact_processor import (
    LARGE_FILE_THRESHOLD,
)

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send Message",
    description="Send a user message and trigger AI response (async processing)",
    responses={
        202: {"description": "Message accepted for processing"},
        404: {"description": "Conversation not found", "model": ErrorResponse},
        422: {"description": "Validation error", "model": ErrorResponse},
        429: {"description": "Rate limit exceeded", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def send_message(
    conversation_id: str,
    http_request: Request,
    request: SendMessageRequest,
    manager: MultiAgentManagerDep,
    container: ContainerDep,
) -> MessageResponse:
    """
    Send a user message in a conversation.

    This endpoint queues the message for processing and returns immediately.
    The actual AI response is generated asynchronously and streamed via the
    SSE endpoint (`/api/v2/chat/events/{conversation_id}`).

    Args:
        conversation_id: Unique conversation identifier
        request: Message content and optional attachments/metadata
        manager: ConversationManager instance (injected)

    Returns:
        MessageResponse with message_id and trace_id for tracking

    Raises:
        HTTPException: 404 if conversation not found, 422 for validation errors

    Example:
        ```bash
        curl -X POST http://localhost:8000/api/v2/chat/conversations/conv_abc123/messages \\
          -H "Content-Type: application/json" \\
          -d '{
            "content": "What is the status of job 12345?",
            "metadata": {"source": "ui", "session_id": "sess_xyz"}
          }'
        ```

        Response (202 Accepted):
        ```json
        {
          "message_id": "msg_xyz789",
          "conversation_id": "conv_abc123",
          "trace_id": "trace_def456",
          "status": "queued",
          "timestamp": "2025-11-16T12:35:00Z"
        }
        ```

        Then subscribe to SSE for real-time updates:
        ```bash
        curl -N http://localhost:8000/api/v2/chat/events/conv_abc123
        ```
    """
    # Apply rate limit: 30 requests per minute per user
    check_rate_limit(http_request, "30/minute")

    try:
        await verify_conversation_ownership(http_request, conversation_id, manager)

        # Process attachments: store large files in cache
        processed_attachments = None
        if request.attachments:
            processed_attachments = []
            cache = container.cache_factory.get_or_create("attachments")

            for attachment in request.attachments:
                # Determine if this is a large file
                size = attachment.size if hasattr(attachment, "size") else 0
                content = attachment.content if hasattr(attachment, "content") else None
                is_large = size >= LARGE_FILE_THRESHOLD or (
                    content and len(content) >= LARGE_FILE_THRESHOLD
                )

                if is_large and content:
                    # Store large file content in cache
                    attachment_id = f"att_{conversation_id}_{uuid4().hex[:8]}"
                    await cache.set(
                        attachment_id,
                        {
                            "content": content,
                            "filename": attachment.filename,
                            "size": size or len(content),
                        },
                    )

                    # Create lightweight attachment reference
                    processed_attachments.append(
                        {
                            "id": attachment_id,
                            "filename": attachment.filename,
                            "size": size or len(content),
                            "content_preview": content[:500] if content else None,
                            "is_large_file": True,
                        }
                    )

                    logger.debug(
                        "large_file_cached",
                        conversation_id=conversation_id,
                        attachment_id=attachment_id,
                        filename=attachment.filename,
                        size=size or len(content),
                    )
                else:
                    # Small file: pass through as-is
                    processed_attachments.append(
                        attachment.model_dump()
                        if hasattr(attachment, "model_dump")
                        else dict(attachment)
                        if isinstance(attachment, dict)
                        else {"filename": getattr(attachment, "filename", "unknown")}
                    )

        response = await manager.enqueue_message(
            conversation_id=conversation_id,
            content=request.content,
            attachments=processed_attachments,
            metadata=request.metadata,
        )

        logger.debug(
            "message_enqueued_api",
            conversation_id=conversation_id,
            message_id=response.message_id,
            trace_id=response.trace_id,
            content_length=len(request.content),
            attachment_count=len(processed_attachments) if processed_attachments else 0,
        )

        return response

    except ValueError as e:
        # Conversation not found
        logger.warning(
            "message_enqueue_conversation_not_found",
            conversation_id=conversation_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except Exception as e:  # noqa: BLE001 - API error boundary
        logger.error(
            "message_enqueue_failed",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue message: {str(e)}",
        ) from e


@router.post(
    "/conversations/{conversation_id}/inject-input",
    response_model=InjectInputResponse,
    status_code=status.HTTP_200_OK,
    summary="Inject User Input During Reasoning",
    description=(
        "Inject user context or interrupt signal during active reasoning. "
        "The input is queued and processed at the next checkpoint."
    ),
    responses={
        200: {"description": "Input accepted and queued"},
        400: {
            "description": "Invalid request or conversation not processing",
            "model": ErrorResponse,
        },
        404: {"description": "Conversation not found", "model": ErrorResponse},
    },
)
async def inject_input(
    conversation_id: str,
    http_request: Request,
    request: InjectInputRequest,
    manager: MultiAgentManagerDep,
) -> InjectInputResponse:
    """
    Inject user input during active reasoning.

    This endpoint allows users to:
    - Add context mid-reasoning (guide the agent)
    - Request a replan (change strategy)
    - Cancel reasoning (stop execution)
    - Override tool selection

    The input is queued and processed at the next checkpoint in the
    reasoning loop. The endpoint returns immediately without blocking.

    Args:
        conversation_id: ID of the conversation
        request: Input injection request
        manager: ConversationManager instance (injected)

    Returns:
        InjectInputResponse with input_id and status

    Raises:
        HTTPException: 400 if conversation not actively processing
        HTTPException: 404 if conversation not found

    Example:
        ```bash
        curl -X POST http://localhost:8000/api/v2/chat/conversations/conv_123/inject-input \\
          -H "Content-Type: application/json" \\
          -d '{
            "input_type": "context_injection",
            "content": "Focus on partition pruning optimizations"
          }'
        ```

        Response:
        ```json
        {
          "input_id": "input_abc123",
          "status": "accepted",
          "checkpoint_id": "ckpt_def456",
          "message": "Input will be processed at next checkpoint"
        }
        ```
    """
    logger.debug(
        "inject_input_requested",
        conversation_id=conversation_id,
        input_type=request.input_type,
    )

    try:
        await verify_conversation_ownership(http_request, conversation_id, manager)

        # Inject input through manager
        user_input = await manager.inject_input(  # type: ignore[attr-defined]
            conversation_id=conversation_id,
            input_type=request.input_type,
            content=request.content,
            checkpoint_id=request.checkpoint_id,
            metadata=request.metadata,
        )

        return InjectInputResponse(
            input_id=user_input.input_id,
            status="accepted",
            checkpoint_id=user_input.checkpoint_id,
            message="Input will be processed at next checkpoint",
        )

    except ValueError as e:
        logger.warning(
            "inject_input_failed",
            conversation_id=conversation_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post(
    "/conversations/{conversation_id}/respond-to-solicitation",
    response_model=RespondToSolicitationResponse,
    status_code=status.HTTP_200_OK,
    summary="Respond to Agent Solicitation",
    description=(
        "Respond to an agent's request for information (solicitation). "
        "The agent waits for this response before continuing."
    ),
    responses={
        200: {"description": "Response accepted"},
        400: {"description": "Invalid request", "model": ErrorResponse},
        404: {
            "description": "Solicitation not found or expired",
            "model": ErrorResponse,
        },
    },
)
async def respond_to_solicitation(
    conversation_id: str,
    http_request: Request,
    request: RespondToSolicitationRequest,
    manager: MultiAgentManagerDep,
) -> RespondToSolicitationResponse:
    """
    Respond to an agent solicitation.

    When the agent asks a question (solicitation), use this endpoint
    to provide the requested information. The agent is waiting for
    this response to continue reasoning.

    Args:
        conversation_id: ID of the conversation
        request: Solicitation response request
        manager: ConversationManager instance (injected)

    Returns:
        RespondToSolicitationResponse with response_id and timing

    Raises:
        HTTPException: 404 if solicitation not found or expired
        HTTPException: 400 if invalid request

    Example:
        ```bash
        curl -X POST http://localhost:8000/api/v2/chat/conversations/conv_123/respond-to-solicitation \\
          -H "Content-Type: application/json" \\
          -d '{
            "solicitation_id": "sol_abc123",
            "content": "Service principal: sp-prod-databricks"
          }'
        ```

        Response:
        ```json
        {
          "response_id": "resp_xyz789",
          "status": "accepted",
          "solicitation_id": "sol_abc123",
          "response_time_ms": 12345.6
        }
        ```
    """
    logger.debug(
        "respond_to_solicitation_requested",
        conversation_id=conversation_id,
        solicitation_id=request.solicitation_id,
    )

    try:
        await verify_conversation_ownership(http_request, conversation_id, manager)

        # Respond to solicitation through manager
        response = await manager.respond_to_solicitation(  # type: ignore[attr-defined]
            conversation_id=conversation_id,
            solicitation_id=request.solicitation_id,
            content=request.content,
            metadata=request.metadata,
        )

        return RespondToSolicitationResponse(
            response_id=response.user_input.input_id,
            status="accepted",
            solicitation_id=response.solicitation_id,
            response_time_ms=response.response_time_seconds * 1000,
        )

    except ValueError as e:
        logger.warning(
            "respond_to_solicitation_failed",
            conversation_id=conversation_id,
            solicitation_id=request.solicitation_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/conversations/{conversation_id}/checkpoints",
    response_model=CheckpointsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Recent Checkpoints",
    description=(
        "List recent checkpoints for a conversation. "
        "Shows where the agent is in its reasoning and which checkpoints can accept interrupts."
    ),
    responses={
        200: {"description": "Checkpoints retrieved"},
        404: {"description": "Conversation not found", "model": ErrorResponse},
    },
)
async def get_checkpoints(
    conversation_id: str,
    request: Request,
    manager: MultiAgentManagerDep,
    limit: int = 10,
) -> CheckpointsResponse:
    """
    Get recent checkpoints for a conversation.

    Returns the N most recent checkpoints, allowing clients to see:
    - Current reasoning progress
    - Which checkpoints can accept interrupts
    - Reasoning step history

    Args:
        conversation_id: ID of the conversation
        manager: ConversationManager instance (injected)
        limit: Maximum number of checkpoints to return (default: 10, max: 50)

    Returns:
        CheckpointsResponse with list of checkpoints

    Raises:
        HTTPException: 404 if conversation not found

    Example:
        ```bash
        curl http://localhost:8000/api/v2/chat/conversations/conv_123/checkpoints?limit=5
        ```

        Response:
        ```json
        {
          "checkpoints": [
            {
              "checkpoint_id": "ckpt_005",
              "step_number": 5,
              "checkpoint_type": "reasoning_step",
              "timestamp": "2025-11-17T10:35:22Z",
              "can_interrupt": true
            }
          ],
          "active_checkpoint": "ckpt_005"
        }
        ```
    """
    logger.debug(
        "get_checkpoints_requested",
        conversation_id=conversation_id,
        limit=limit,
    )

    # Validate limit
    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 50",
        )

    try:
        await verify_conversation_ownership(request, conversation_id, manager)

        # Get checkpoints through manager
        checkpoint_infos = await manager.get_checkpoints(  # type: ignore[attr-defined]
            conversation_id=conversation_id,
            limit=limit,
        )

        # Determine active checkpoint (most recent if any)
        active_checkpoint = (
            checkpoint_infos[0].checkpoint_id if checkpoint_infos else None
        )

        return CheckpointsResponse(
            checkpoints=checkpoint_infos,
            active_checkpoint=active_checkpoint,
        )

    except ValueError as e:
        logger.warning(
            "get_checkpoints_failed",
            conversation_id=conversation_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

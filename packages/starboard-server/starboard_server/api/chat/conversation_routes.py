# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Conversation management endpoints.

Provides HTTP endpoints for conversation CRUD operations:
- POST /conversations - Create new conversation
- GET /conversations - List user conversations
- GET /conversations/{id} - Get conversation metadata
- HEAD /conversations/{id} - Check if conversation exists
- GET /conversations/{id}/history - Get conversation history
- DELETE /conversations/{id} - Delete single conversation
- DELETE /conversations - Delete all user conversations (batch)
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from starboard_server.api.dependencies import MultiAgentManagerDep
from starboard_server.api.models import (
    ConversationHistory,
    ConversationResponse,
    CreateConversationRequest,
    ErrorResponse,
)
from starboard_server.api.ownership import verify_conversation_ownership
from starboard_server.infra.middleware.rate_limit import check_rate_limit
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Conversation",
    description="Create a new conversation session with optional configuration",
    responses={
        201: {"description": "Conversation created successfully"},
        422: {"description": "Validation error", "model": ErrorResponse},
        429: {"description": "Rate limit exceeded", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def create_conversation(
    request: Request,
    body: CreateConversationRequest,
    manager: MultiAgentManagerDep,
) -> ConversationResponse:
    """
    Create a new conversation session.

    This endpoint creates a new conversation that can be used to send messages
    and receive AI-generated responses. The conversation maintains context
    across multiple messages.

    Rate limited to 10 requests per minute per user.

    Note: user_id is now automatically extracted from authentication middleware
    via request.state.user (set by Databricks platform auth).

    Args:
        request: FastAPI Request object (contains authenticated user)
        body: Conversation creation request with optional context and config
        manager: ConversationManager instance (injected)

    Returns:
        ConversationResponse with conversation_id and configuration

    Example:
        ```bash
        curl -X POST http://localhost:8000/api/v2/chat/conversations \\
          -H "Content-Type: application/json" \\
          -H "X-Forwarded-User: user@example.com" \\
          -d '{
            "context": {"workspace_id": "ws_abc"},
            "config": {"temperature": 0.4, "max_tokens": 2048}
          }'
        ```

        Response:
        ```json
        {
          "conversation_id": "conv_abc123",
          "user_id": "user_123",
          "created_at": "2025-11-16T12:34:56Z",
          "config": {
            "temperature": 0.4,
            "max_tokens": 2048,
            "safe_mode": false,
            "streaming": true,
            "model": "gpt-4o-mini"
          }
        }
        ```
    """
    # Apply rate limit: 10 requests per minute per user
    check_rate_limit(request, "10/minute")

    try:
        # Get authenticated user from middleware (set by AuthMiddleware)
        user = request.state.user

        # NEW: UX vNext Phase 1 - Merge metadata into context
        # The lifecycle manager stores context as SharedAgentContext.metadata
        merged_context = body.context.copy() if body.context else {}
        if body.metadata:
            # Prefix metadata fields to avoid conflicts with context fields
            merged_context["_metadata"] = body.metadata

        # Create conversation
        response = await manager.create_conversation(
            user_id=user.id,
            context=merged_context if merged_context else None,
            config=body.config,
        )

        # NEW: UX vNext Phase 1 - If initial_message provided, enqueue it
        if body.initial_message:
            await manager.enqueue_message(
                conversation_id=response.conversation_id,
                content=body.initial_message,
                metadata={"source": "initial_prompt"},
            )
            logger.debug(
                "initial_message_enqueued",
                conversation_id=response.conversation_id,
                user_id=user.id,
                message_length=len(body.initial_message),
            )

        logger.debug(
            "conversation_created_api",
            conversation_id=response.conversation_id,
            user_id=user.id,
            username=user.username,
            has_initial_message=body.initial_message is not None,  # NEW
            has_metadata=body.metadata is not None,  # NEW
        )

        return response

    except Exception as e:  # noqa: BLE001 - API error boundary
        # Try to get user_id for logging if available
        user_id = "unknown"
        if hasattr(request.state, "user"):
            user_id = request.state.user.id

        logger.error(
            "conversation_creation_failed",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        # Do not leak internal exception text to the client; the full error is
        # logged above with exc_info for server-side diagnosis.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create conversation",
        ) from e


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
    summary="List Conversations",
    description="List all conversations for the authenticated user, ordered by most recent first",
    responses={
        200: {"description": "List of conversations"},
        422: {"description": "Validation error", "model": ErrorResponse},
    },
)
async def list_conversations(
    request: Request,
    manager: MultiAgentManagerDep,
    limit: int = 20,
    offset: int = 0,
) -> list[ConversationResponse]:
    """
    List conversations for the authenticated user.

    Returns conversations ordered by updated_at descending (most recent first).
    Supports pagination via limit and offset parameters.

    Note: user_id is automatically extracted from authentication middleware.

    Args:
        request: FastAPI Request object (contains authenticated user)
        manager: ConversationManager instance (injected)
        limit: Maximum number of conversations to return (default: 20, max: 100)
        offset: Pagination offset (default: 0)

    Returns:
        List of ConversationResponse objects with friendly names

    Example:
        ```bash
        curl "http://localhost:8000/api/v2/chat/conversations?limit=10" \\
          -H "X-Forwarded-User: user@example.com"
        ```

        Response:
        ```json
        [
          {
            "conversation_id": "conv_abc123",
            "friendly_name": "Query Optimization Session",
            "created_at": "2025-11-17T10:30:00Z",
            "config": {
              "temperature": 0.4,
              "max_tokens": 120000,
              "model": "databricks-claude-sonnet-4-5"
            }
          }
        ]
        ```
    """
    try:
        # Get authenticated user from middleware
        user = request.state.user

        # Validate limit
        if limit < 1 or limit > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="limit must be between 1 and 100",
            )

        if offset < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="offset must be non-negative",
            )

        conversations = await manager.list_conversations(
            user_id=user.id,
            limit=limit,
            offset=offset,
        )

        # Convert Conversation objects to ConversationResponse
        responses = [
            ConversationResponse(
                conversation_id=conv.conversation_id,
                user_id=conv.user_id,
                friendly_name=conv.friendly_name,
                created_at=conv.created_at,
                config=conv.config,
            )
            for conv in conversations
        ]

        logger.debug(
            "conversations_listed",
            user_id=user.id,
            username=user.username,
            count=len(responses),
            limit=limit,
            offset=offset,
        )

        return responses

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - API error boundary
        # Try to get user_id for logging if available
        user_id = "unknown"
        if hasattr(request.state, "user"):
            user_id = request.state.user.id

        logger.error(
            "list_conversations_failed",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list conversations: {str(e)}",
        ) from e


@router.get(
    "/conversations/{conversation_id}",
    response_model=dict[str, Any],
    summary="Get Conversation",
    description="Get conversation metadata",
    responses={
        200: {"description": "Conversation retrieved successfully"},
        404: {"description": "Conversation not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
@router.get(
    "/conversations/{conversation_id}/",
    response_model=dict[str, Any],
    include_in_schema=False,  # Don't duplicate in API docs
)
async def get_conversation(
    conversation_id: str,
    request: Request,
    manager: MultiAgentManagerDep,
) -> dict[str, Any]:
    """
    Get conversation metadata.

    Retrieves basic conversation information including conversation_id,
    user_id, and existence status. Useful for validating conversations
    after page reload or checking conversation state.

    Args:
        conversation_id: Conversation identifier to retrieve
        request: FastAPI Request object (contains authenticated user)
        manager: ConversationManager instance (injected)

    Returns:
        Dict with conversation metadata

    Raises:
        HTTPException: 404 if conversation not found or not owned by user

    Example:
        ```javascript
        // Fetch conversation metadata
        const response = await fetch(
            `/api/v2/chat/conversations/${conversationId}`
        );
        const data = await response.json();
        console.log(data);  // { conversation_id, user_id, exists: true }
        ```
    """
    try:
        await verify_conversation_ownership(request, conversation_id, manager)

        conversation = await manager.get_conversation(conversation_id)

        logger.debug(
            "conversation_retrieved",
            conversation_id=conversation_id,
        )

        return conversation  # type: ignore[return-value]

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - API error boundary
        logger.error(
            "conversation_retrieval_failed",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve conversation: {str(e)}",
        ) from e


@router.head(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Check if Conversation Exists",
    description=(
        "Lightweight check to verify if a conversation exists. "
        "Returns 204 if exists, 404 if not. No response body."
    ),
    responses={
        204: {"description": "Conversation exists"},
        404: {"description": "Conversation not found"},
    },
)
@router.head(
    "/conversations/{conversation_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,  # Don't duplicate in API docs
)
async def check_conversation_exists(
    conversation_id: str,
    request: Request,
    manager: MultiAgentManagerDep,
) -> None:
    """
    Check if a conversation exists without fetching full data.

    This is a lightweight endpoint for the UI to validate conversations
    before attempting to connect to SSE streams. Useful after page reload
    to detect if server was restarted and conversations were lost.

    Args:
        conversation_id: Conversation identifier to check
        request: FastAPI Request object (contains authenticated user)
        manager: ConversationManager instance (injected)

    Returns:
        None (HTTP 204 No Content if exists)

    Raises:
        HTTPException: 404 if conversation not found or not owned by user

    Example:
        ```javascript
        // Check if conversation exists before connecting
        const response = await fetch(
            `/api/v2/chat/conversations/${conversationId}`,
            { method: 'HEAD' }
        );
        if (response.ok) {
            // Safe to connect to SSE stream
            connectToSSE(conversationId);
        } else {
            // Conversation expired, remove from UI
            removeConversation(conversationId);
        }
        ```
    """
    await verify_conversation_ownership(request, conversation_id, manager)


@router.get(
    "/conversations/{conversation_id}/history",
    response_model=ConversationHistory,
    summary="Get Conversation History",
    description="Retrieve all messages and metadata for a conversation",
    responses={
        200: {"description": "History retrieved successfully"},
        404: {"description": "Conversation not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def get_conversation_history(
    conversation_id: str,
    request: Request,
    manager: MultiAgentManagerDep,
) -> ConversationHistory:
    """
    Get complete conversation history.

    Retrieves all messages in the conversation along with metadata like
    total tokens used, cost, and timestamps.

    Args:
        conversation_id: Unique conversation identifier
        manager: ConversationManager instance (injected)

    Returns:
        ConversationHistory with messages and metadata

    Raises:
        HTTPException: 404 if conversation not found

    Example:
        ```bash
        curl http://localhost:8000/api/v2/chat/conversations/conv_abc123/history
        ```

        Response:
        ```json
        {
          "conversation_id": "conv_abc123",
          "messages": [
            {
              "message_id": "msg_1",
              "role": "user",
              "content": "Hello",
              "timestamp": "2025-11-16T12:34:56Z",
              "status": "completed",
              "tool_calls": []
            },
            {
              "message_id": "msg_2",
              "role": "assistant",
              "content": "Hi! How can I help?",
              "timestamp": "2025-11-16T12:34:58Z",
              "status": "completed",
              "tool_calls": [],
              "metadata": {
                "tokens": 50,
                "cost": 0.0005,
                "latency_ms": 1200
              }
            }
          ],
          "metadata": {
            "total_messages": 2,
            "total_tokens": 50,
            "total_cost": 0.0005,
            "created_at": "2025-11-16T12:34:55Z",
            "updated_at": "2025-11-16T12:34:58Z"
          }
        }
        ```
    """
    try:
        await verify_conversation_ownership(request, conversation_id, manager)

        history = await manager.get_history(conversation_id)

        if history is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        logger.debug(
            "conversation_history_retrieved",
            conversation_id=conversation_id,
            message_count=len(history.messages),
        )

        return history

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - API error boundary
        logger.error(
            "conversation_history_retrieval_failed",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve conversation history: {str(e)}",
        ) from e


@router.delete(
    "/conversations",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete All Conversations",
    description="Delete all conversations for the authenticated user. Much more efficient than deleting individually.",
    responses={
        204: {"description": "All conversations deleted successfully"},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def delete_all_conversations(
    request: Request,
    manager: MultiAgentManagerDep,
) -> None:
    """
    Delete all conversations for authenticated user.

    This is a batch operation that's much more efficient than calling
    DELETE /conversations/{id} multiple times.

    Security:
        - User authentication required (via middleware)
        - Only deletes conversations owned by authenticated user
        - Cannot delete other users' conversations

    Args:
        request: FastAPI Request (contains authenticated user from middleware)
        manager: MultiAgentManager instance (injected)

    Returns:
        None (HTTP 204 No Content)

    Raises:
        HTTPException: 500 if deletion fails

    Example:
        ```bash
        # Delete all conversations for authenticated user
        curl -X DELETE http://localhost:8000/api/v2/chat/conversations \\
          -H "X-Forwarded-User: user@example.com"
        ```

        Response: 204 No Content (no body)
    """
    try:
        # Get authenticated user from middleware
        user = request.state.user

        # Delete all conversations for this user (batch operation)
        count = await manager.delete_all_conversations(user_id=user.id)

        logger.debug(
            "all_conversations_deleted_api",
            user_id=user.id,
            username=user.username,
            count=count,
        )

    except Exception as e:  # noqa: BLE001 - API error boundary
        user_id = "unknown"
        if hasattr(request.state, "user"):
            user_id = request.state.user.id

        logger.error(
            "delete_all_conversations_failed",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete conversations: {str(e)}",
        ) from e


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Conversation",
    description="Delete a conversation and all its messages",
    responses={
        204: {"description": "Conversation deleted successfully"},
        404: {"description": "Conversation not found"},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def delete_conversation(
    conversation_id: str,
    request: Request,
    manager: MultiAgentManagerDep,
) -> None:
    """
    Delete a conversation.

    Removes the conversation and all its messages. This action cannot be undone.
    Also cancels any ongoing message processing.

    Args:
        conversation_id: Unique conversation identifier
        manager: ConversationManager instance (injected)

    Raises:
        HTTPException: 404 if conversation not found

    Example:
        ```bash
        curl -X DELETE http://localhost:8000/api/v2/chat/conversations/conv_abc123
        ```
    """
    try:
        await verify_conversation_ownership(request, conversation_id, manager)

        # Delete from multi-agent manager
        deleted = await manager.delete_conversation(conversation_id)

        if not deleted:
            logger.warning(
                "conversation_delete_not_found",
                conversation_id=conversation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation {conversation_id} not found",
            )

        logger.debug(
            "conversation_deleted_api",
            conversation_id=conversation_id,
        )

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - API error boundary
        logger.error(
            "conversation_deletion_failed",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete conversation: {str(e)}",
        ) from e

"""Conversation ownership verification.

Prevents IDOR by ensuring the authenticated user owns the requested
conversation before any data access or mutation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request, status

from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


async def verify_conversation_ownership(
    request: Request,
    conversation_id: str,
    manager: Any,
) -> None:
    """Verify the authenticated user owns the given conversation.

    Returns 404 (not 403) to avoid leaking conversation existence
    to unauthorized users.

    Args:
        request: FastAPI request with authenticated user on state.
        conversation_id: The conversation to check.
        manager: Conversation manager for lookups.

    Raises:
        HTTPException: 404 if conversation not found or not owned by user.
    """
    user = request.state.user
    conversation = await manager.get_conversation(conversation_id)

    if conversation is None:
        logger.warning(
            "ownership_check_not_found",
            conversation_id=conversation_id,
            user_id=user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if conversation.get("user_id") != user.id:
        logger.warning(
            "ownership_check_denied",
            conversation_id=conversation_id,
            requesting_user_id=user.id,
            owning_user_id=conversation.get("user_id"),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

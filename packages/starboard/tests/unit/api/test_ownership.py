# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for conversation ownership verification (IDOR prevention).

Covers:
- Owner can access their conversation (passes)
- Non-owner gets 404 (not 403) to avoid leaking existence
- Nonexistent conversation returns 404
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starboard.api.ownership import verify_conversation_ownership


def _make_request(user_id: str) -> MagicMock:
    """Create a mock FastAPI Request with an authenticated user."""
    request = MagicMock()
    request.state.user = MagicMock()
    request.state.user.id = user_id
    return request


def _make_manager(conversation: dict | None) -> AsyncMock:
    """Create a mock manager that returns a specific conversation."""
    manager = AsyncMock()
    manager.get_conversation = AsyncMock(return_value=conversation)
    return manager


class TestVerifyConversationOwnership:
    """Tests for verify_conversation_ownership."""

    @pytest.mark.asyncio
    async def test_owner_can_access(self) -> None:
        request = _make_request("user_A")
        manager = _make_manager(
            {"conversation_id": "conv_1", "user_id": "user_A", "exists": True}
        )

        # Should not raise
        await verify_conversation_ownership(request, "conv_1", manager)
        manager.get_conversation.assert_awaited_once_with("conv_1")

    @pytest.mark.asyncio
    async def test_non_owner_gets_404(self) -> None:
        request = _make_request("user_B")
        manager = _make_manager(
            {"conversation_id": "conv_1", "user_id": "user_A", "exists": True}
        )

        with pytest.raises(HTTPException) as exc_info:
            await verify_conversation_ownership(request, "conv_1", manager)

        # Must be 404, NOT 403 (prevents leaking existence)
        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_conversation_returns_404(self) -> None:
        request = _make_request("user_A")
        manager = _make_manager(None)

        with pytest.raises(HTTPException) as exc_info:
            await verify_conversation_ownership(request, "conv_nonexistent", manager)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_non_owner_cannot_delete(self) -> None:
        """Simulates user B trying to access user A's conversation for deletion."""
        request = _make_request("user_B")
        manager = _make_manager(
            {"conversation_id": "conv_1", "user_id": "user_A", "exists": True}
        )

        with pytest.raises(HTTPException) as exc_info:
            await verify_conversation_ownership(request, "conv_1", manager)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_non_owner_cannot_list_messages(self) -> None:
        """Simulates user B trying to access user A's conversation history."""
        request = _make_request("user_B")
        manager = _make_manager(
            {"conversation_id": "conv_1", "user_id": "user_A", "exists": True}
        )

        with pytest.raises(HTTPException) as exc_info:
            await verify_conversation_ownership(request, "conv_1", manager)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_error_message_does_not_leak_ownership(self) -> None:
        """Verify the error message doesn't reveal the real owner."""
        request = _make_request("user_B")
        manager = _make_manager(
            {"conversation_id": "conv_1", "user_id": "user_A", "exists": True}
        )

        with pytest.raises(HTTPException) as exc_info:
            await verify_conversation_ownership(request, "conv_1", manager)

        # Should NOT contain user_A's ID in the detail
        assert "user_A" not in exc_info.value.detail

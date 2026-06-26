# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for Databricks auth provider — session validation behavior."""

from __future__ import annotations

import pytest
from starboard_server.infra.auth.providers.databricks import DatabricksAuthProvider


class TestValidateSession:
    """Verify validate_session() returns True (platform-delegated auth)."""

    @pytest.fixture
    def provider(self) -> DatabricksAuthProvider:
        """Create provider with mock dependencies."""
        # DatabricksAuthProvider.__init__ expects databricks_api and user_repository
        # but validate_session() doesn't use them, so we can pass None
        return DatabricksAuthProvider(
            databricks_api=None,  # type: ignore[arg-type]
            user_repository=None,  # type: ignore[arg-type]
        )

    @pytest.mark.asyncio
    async def test_validate_session_returns_true(
        self, provider: DatabricksAuthProvider
    ) -> None:
        """Platform-delegated auth always returns True for session validation."""
        result = await provider.validate_session("any-session-id")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_session_ignores_session_id(
        self, provider: DatabricksAuthProvider
    ) -> None:
        """Session ID is unused — any value should return True."""
        for session_id in ["", "abc-123", "invalid", None]:
            result = await provider.validate_session(session_id)  # type: ignore[arg-type]
            assert result is True

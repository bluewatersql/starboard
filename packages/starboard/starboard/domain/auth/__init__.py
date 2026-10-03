# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Authentication domain models and types.

This module contains pure domain logic for authentication, with no I/O dependencies.
"""

from starboard_core.domain.models.auth import User, UserSession, UserStatus

from starboard.domain.auth.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    SessionExpiredError,
    UserNotFoundError,
)

__all__ = [
    "AuthenticationError",
    "InvalidCredentialsError",
    "SessionExpiredError",
    "UserNotFoundError",
    "User",
    "UserSession",
    "UserStatus",
]

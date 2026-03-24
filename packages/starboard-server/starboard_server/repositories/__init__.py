"""Repositories for data access.

This package contains repository implementations for accessing
and persisting domain entities.
"""

from starboard_server.repositories.conversation_patterns_repository import (
    ConversationPatternsRepository,
)

__all__ = ["ConversationPatternsRepository"]

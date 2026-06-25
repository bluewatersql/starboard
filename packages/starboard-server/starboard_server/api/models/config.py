"""
API configuration models.

The canonical definitions of ``ConversationConfig`` and ``DomainModelConfig``
live in the domain layer (``starboard_server.domain.conversation.models``).
They are re-exported here so existing ``from ...api.models import X`` callers
keep working while preserving the api → domain dependency direction.
"""

from starboard_server.domain.conversation.models import (
    ConversationConfig,
    DomainModelConfig,
)

__all__ = ["ConversationConfig", "DomainModelConfig"]

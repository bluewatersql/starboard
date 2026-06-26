# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Chat API.

Provides REST and SSE endpoints for conversational AI interactions.
"""

from starboard_server.api.chat import router as chat_router
from starboard_server.api.clarification import router as clarification_router
from starboard_server.api.feedback import router as feedback_router
from starboard_server.api.streaming import router as streaming_router

__all__ = [
    "chat_router",
    "streaming_router",
    "feedback_router",
    "clarification_router",
]

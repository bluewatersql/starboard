# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""API models package."""

from starboard_server.api.models.clarification import (
    ClarificationRequestEventData,
    RespondToClarificationRequest,
    RespondToClarificationResponse,
)
from starboard_server.api.models.config import ConversationConfig, DomainModelConfig
from starboard_server.api.models.conversations import (
    ConversationHistory,
    ConversationListItem,
    ConversationMetadata,
    ConversationResponse,
    CreateConversationRequest,
)
from starboard_server.api.models.enums import (
    EventType,
    FeedbackCategoryEnum,
    FeedbackRatingEnum,
    MessageRole,
    MessageStatus,
)
from starboard_server.api.models.events import ChatEvent, ErrorResponse
from starboard_server.api.models.feedback import (
    FeedbackResponse,
    SubmitFeedbackRequest,
)
from starboard_server.api.models.messages import (
    Message,
    MessageResponse,
    SendMessageRequest,
    ToolCall,
)
from starboard_server.api.models.performance import AgentPerformanceResponse
from starboard_server.api.models.reasoning import (
    CheckpointInfo,
    CheckpointsResponse,
    InjectInputRequest,
    InjectInputResponse,
    RespondToSolicitationRequest,
    RespondToSolicitationResponse,
)
from starboard_server.api.models.visualization import RenderChartRequest

__all__ = [
    # Events
    "ChatEvent",
    "ErrorResponse",
    "EventType",
    # Conversations
    "ConversationConfig",
    "ConversationHistory",
    "ConversationListItem",
    "ConversationMetadata",
    "ConversationResponse",
    "CreateConversationRequest",
    "DomainModelConfig",
    # Messages
    "Message",
    "MessageResponse",
    "MessageRole",
    "MessageStatus",
    "ToolCall",
    # Reasoning
    "CheckpointInfo",
    "CheckpointsResponse",
    "InjectInputRequest",
    "InjectInputResponse",
    "RespondToSolicitationRequest",
    "RespondToSolicitationResponse",
    "SendMessageRequest",
    # Feedback
    "AgentPerformanceResponse",
    "FeedbackCategoryEnum",
    "FeedbackRatingEnum",
    "FeedbackResponse",
    "SubmitFeedbackRequest",
    # Clarification
    "ClarificationRequestEventData",
    "RespondToClarificationRequest",
    "RespondToClarificationResponse",
    # Visualization
    "RenderChartRequest",
]

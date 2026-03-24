"""
Package for conversation management components.

Modular components for multi-agent conversation management:
- ConversationLifecycleManager: CRUD operations for conversations
- AgentHandoffCoordinator: Agent routing and handoff coordination
- EventBroadcastCoordinator: SSE event broadcasting
- MessageQueueProcessor: Background message queue processing
- MultiAgentConversationManager: Thin orchestration facade

Clean architecture following single responsibility principle.
"""

from .event_broadcast_coordinator import EventBroadcastCoordinator
from .handoff_coordinator import AgentHandoffCoordinator
from .lifecycle_manager import ConversationLifecycleManager, ConversationListItem
from .message_queue_processor import MessageQueueProcessor
from .multi_agent_manager import MultiAgentConversationManager

__all__ = [
    "ConversationLifecycleManager",
    "ConversationListItem",
    "AgentHandoffCoordinator",
    "EventBroadcastCoordinator",
    "MessageQueueProcessor",
    "MultiAgentConversationManager",
]

"""Public entry point for creating Starboard server instances.

This module is the **canonical public API** for ``starboard_server``.  CLI,
SDK, and test code must import from here instead of reaching into internal
sub-packages.  This satisfies GUIDELINE-005 (package boundary enforcement).

Usage::

    from starboard_server.bootstrap import (
        create_application,
        # Agents / conversation
        MultiAgentConversationManager,
        AgentFactory,
        AgentConfig,
        IntentRouter,
        # Tools
        create_tool_registry,
        # Adapters
        AsyncDatabricksClient,
        AsyncSQLExecutor,
        create_llm_client,
        # State
        SQLiteStateStore,
        InMemoryConversationStateManager,
        # RAG / vector store
        LLMClientEmbeddingProvider,
        MultiCollectionStore,
        create_vector_store,
        # Context
        SharedContextProvider,
        # Config / logging
        EnvConfig,
        get_config,
        get_logger,
        # Events
        ErrorEvent,
        FinalOutputEvent,
        StepCompleteEvent,
        StreamingEvent,
        ThinkingEvent,
        ToolEndEvent,
        ToolStartEvent,
        UserInputRequestEvent,
        # Report formatting
        format_agent_report,
        # Discovery
        DiscoveryEngine,
        EngineConfig,
    )
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Adapters — Databricks
# ---------------------------------------------------------------------------
from starboard_server.adapters.databricks import AsyncDatabricksClient
from starboard_server.adapters.databricks.async_sql_executor import AsyncSQLExecutor

# ---------------------------------------------------------------------------
# Adapters — LLM
# ---------------------------------------------------------------------------
from starboard_server.adapters.llm import create_llm_client

# ---------------------------------------------------------------------------
# Adapters — State / SQLite
# ---------------------------------------------------------------------------
from starboard_server.adapters.state.sqlite.state_store import SQLiteStateStore

# ---------------------------------------------------------------------------
# Agents / conversation
# ---------------------------------------------------------------------------
from starboard_server.agents.agent_factory import AgentFactory
from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.agents.conversation import MultiAgentConversationManager

# ---------------------------------------------------------------------------
# Streaming events
# ---------------------------------------------------------------------------
from starboard_server.agents.events import (
    ErrorEvent,
    FinalOutputEvent,
    StepCompleteEvent,
    StreamingEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
    UserInputRequestEvent,
)

# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------
from starboard_server.agents.report_formatters import format_agent_report
from starboard_server.agents.routing.intent_router import IntentRouter
from starboard_server.agents.tools.tool_factory import create_tool_registry

# ---------------------------------------------------------------------------
# API utilities
# ---------------------------------------------------------------------------
from starboard_server.api.conversation_state_manager import (
    InMemoryConversationStateManager,
)

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
from starboard_server.discovery.engine import DiscoveryEngine, EngineConfig

# ---------------------------------------------------------------------------
# Config & logging
# ---------------------------------------------------------------------------
from starboard_server.infra.core.config import EnvConfig, get_config
from starboard_server.infra.observability.logging import get_logger

# ---------------------------------------------------------------------------
# RAG / vector store
# ---------------------------------------------------------------------------
from starboard_server.infra.rag.adapters.embedding.llm_client_provider import (
    LLMClientEmbeddingProvider,
)
from starboard_server.infra.rag.domain.protocols import MultiCollectionStore
from starboard_server.infra.rag.services.vector_store_factory import create_vector_store

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
from starboard_server.main import create_app

# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------
from starboard_server.services.context.provider import SharedContextProvider


def create_application(**kwargs):
    """Create and configure the Starboard FastAPI application.

    This is the public API for bootstrapping the server. All internal wiring
    (DI container, middleware, routes, agents) is handled by create_app.

    Args:
        **kwargs: Forwarded to create_app (e.g., config overrides).

    Returns:
        FastAPI application instance, fully configured and ready to serve.
    """
    return create_app(**kwargs)


__all__ = [
    # Application factory
    "create_application",
    # Agents / conversation
    "MultiAgentConversationManager",
    "AgentFactory",
    "AgentConfig",
    "IntentRouter",
    "create_tool_registry",
    # Events
    "ErrorEvent",
    "FinalOutputEvent",
    "StepCompleteEvent",
    "StreamingEvent",
    "ThinkingEvent",
    "ToolEndEvent",
    "ToolStartEvent",
    "UserInputRequestEvent",
    # Report formatting
    "format_agent_report",
    # Adapters — Databricks
    "AsyncDatabricksClient",
    "AsyncSQLExecutor",
    # Adapters — LLM
    "create_llm_client",
    # Adapters — State
    "SQLiteStateStore",
    # API utilities
    "InMemoryConversationStateManager",
    # Config / logging
    "EnvConfig",
    "get_config",
    "get_logger",
    # RAG / vector store
    "LLMClientEmbeddingProvider",
    "MultiCollectionStore",
    "create_vector_store",
    # Shared context
    "SharedContextProvider",
    # Discovery
    "DiscoveryEngine",
    "EngineConfig",
]

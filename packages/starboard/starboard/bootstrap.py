# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Public entry point for creating Starboard server instances.

This module is the **canonical public API** for ``starboard``.  CLI,
SDK, and test code must import from here instead of reaching into internal
sub-packages.  This satisfies GUIDELINE-005 (package boundary enforcement).

Usage::

    from starboard.bootstrap import (
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
from starboard.adapters.databricks import AsyncDatabricksClient
from starboard.adapters.databricks.async_sql_executor import AsyncSQLExecutor

# ---------------------------------------------------------------------------
# Adapters — LLM
# ---------------------------------------------------------------------------
from starboard.adapters.llm import create_llm_client

# ---------------------------------------------------------------------------
# Adapters — State / SQLite
# ---------------------------------------------------------------------------
from starboard.adapters.state.sqlite.state_store import SQLiteStateStore

# ---------------------------------------------------------------------------
# Agents / conversation
# ---------------------------------------------------------------------------
from starboard.agents.agent_factory import AgentFactory
from starboard.agents.config.agent_config import AgentConfig
from starboard.agents.conversation import MultiAgentConversationManager

# ---------------------------------------------------------------------------
# Streaming events
# ---------------------------------------------------------------------------
from starboard.agents.events import (
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
from starboard.agents.report_formatters import format_agent_report
from starboard.agents.routing.intent_router import IntentRouter
from starboard.agents.tools.tool_factory import create_tool_registry

# ---------------------------------------------------------------------------
# API utilities
# ---------------------------------------------------------------------------
from starboard.api.conversation_state_manager import (
    InMemoryConversationStateManager,
)

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
from starboard.discovery.engine import DiscoveryEngine, EngineConfig

# ---------------------------------------------------------------------------
# Config & logging
# ---------------------------------------------------------------------------
from starboard.infra.core.config import EnvConfig, get_config
from starboard.infra.observability.logging import get_logger

# ---------------------------------------------------------------------------
# RAG / vector store
# ---------------------------------------------------------------------------
from starboard.infra.rag.adapters.embedding.llm_client_provider import (
    LLMClientEmbeddingProvider,
)
from starboard.infra.rag.domain.protocols import MultiCollectionStore
from starboard.infra.rag.services.vector_store_factory import create_vector_store

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
from starboard.main import create_app

# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------
from starboard.services.context.provider import SharedContextProvider


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

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

import importlib
from typing import TYPE_CHECKING

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
# API utilities
# ---------------------------------------------------------------------------
from starboard.adapters.state.inmemory.conversation_state_manager import (
    InMemoryConversationStateManager,
)

# ---------------------------------------------------------------------------
# Adapters — State / SQLite  (lazy — requires the ``sqlite`` extra)
#
# ``SQLiteStateStore`` is NOT imported eagerly.  It is resolved on first
# attribute access via module-level ``__getattr__`` (PEP 562) so that
# ``import starboard.bootstrap`` does NOT pull aiosqlite into sys.modules on
# a default (store-free) install.  Explicit access still works:
# ``bootstrap.SQLiteStateStore`` → real class.
#
# The TYPE_CHECKING block below gives static analysers the concrete type
# without executing the import at runtime.
# ---------------------------------------------------------------------------
if TYPE_CHECKING:
    from starboard.adapters.state.sqlite.state_store import (
        SQLiteStateStore as SQLiteStateStore,
    )

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
# Discovery
# ---------------------------------------------------------------------------
from starboard.discovery.engine import DiscoveryEngine, EngineConfig
from starboard.discovery.query_packs.registry import create_default_registry

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

# ---------------------------------------------------------------------------
# Lazy-import registry — symbols that require optional extras.
#
# Placed after all eager imports so module-level import ordering (E402) is
# respected.  Python calls ``__getattr__`` only for names NOT already bound
# in the module's namespace, so symbols above are unaffected.
# ---------------------------------------------------------------------------
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "SQLiteStateStore": (
        "starboard.adapters.state.sqlite.state_store",
        "SQLiteStateStore",
    ),
}


def __getattr__(name: str) -> object:
    """Lazily resolve optional store-adapter symbols (PEP 562).

    Keeps ``import starboard.bootstrap`` free of optional store-driver deps
    (aiosqlite, asyncpg, …) on a default install.  Each symbol is pulled from
    its implementation module only on first explicit access.
    """
    entry = _LAZY_IMPORTS.get(name)
    if entry is not None:
        module_path, attr = entry
        try:
            module = importlib.import_module(module_path)
            return getattr(module, attr)
        except ImportError as exc:
            raise ModuleNotFoundError(
                f"{name!r} requires the 'sqlite' extra. "
                f"Install it with: pip install 'starboard[sqlite]'"
            ) from exc
    raise AttributeError(f"module 'starboard.bootstrap' has no attribute {name!r}")


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
    #
    # NOTE: ``SQLiteStateStore`` is intentionally NOT listed here. It resolves
    # lazily via ``__getattr__`` (PEP 562) so a default, store-free install can
    # ``import starboard.bootstrap`` without pulling in aiosqlite. Listing it in
    # ``__all__`` would make ``from starboard.bootstrap import *`` call
    # ``getattr`` for the name, forcing the eager driver import and failing on a
    # store-free install. Explicit ``from starboard.bootstrap import
    # SQLiteStateStore`` still works and stays the supported access path.
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
    "create_default_registry",
]

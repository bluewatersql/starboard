# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Dependency injection for API.

Provides FastAPI dependencies for shared resources.

This module manages singleton instances of:
- MultiAgentConversationManager: Multi-agent orchestration for domain-specific routing
- RequestUserInputTool: Handles synchronous user input during reasoning

The dependency pattern ensures proper initialization order and resource sharing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

from starboard_server.adapters.databricks import AsyncDatabricksClient
from starboard_server.agents.agent_factory import AgentFactory
from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.agents.routing.intent_router import IntentRouter
from starboard_server.agents.tools import create_tool_registry
from starboard_server.infra.core.config import get_config
from starboard_server.infra.core.container import Container
from starboard_server.infra.observability.logging import get_logger
from starboard_server.services.context.provider import SharedContextProvider

if TYPE_CHECKING:
    from starboard_server.agents.conversation import (
        MultiAgentConversationManager,
    )

logger = get_logger(__name__)

# Global singletons (initialized on first use)
# Note: Using module-level variables for singleton pattern is acceptable in FastAPI
# as the ASGI server ensures single-process initialization
_multi_agent_manager: MultiAgentConversationManager | None = None


async def get_multi_agent_manager(
    container: ContainerDep,
) -> MultiAgentConversationManager:
    """
    Get or create the MultiAgentConversationManager singleton.

    Uses the ConversationRepository from the Container, which is backed by
    the configured StateStore (SQLite, Postgres, or Databricks Lakebase).

    Args:
        container: Container with initialized state stores and repositories

    Returns:
        MultiAgentConversationManager instance

    Example:
        >>> @app.post("/chat/multi")
        >>> async def multi_chat(
        ...     manager: Annotated[MultiAgentConversationManager, Depends(get_multi_agent_manager)]
        ... ):
        ...     async for event in manager.handle_message_stream(...):
        ...         yield event
    """
    global _multi_agent_manager

    if _multi_agent_manager is None:
        config = get_config()
        from starboard_server.adapters.llm import create_llm_client
        from starboard_server.agents.conversation import (
            MultiAgentConversationManager,
        )

        logger.debug("initializing_multi_agent_manager")

        # Create LLM client using factory pattern
        llm_client = create_llm_client(cfg=config)

        # Create unified async Databricks client
        # AsyncDatabricksClient provides:
        # - Integrated caching with configurable TTLs
        # - All async operations (no event loop blocking)
        # - Streaming SQL execution for large results
        api = AsyncDatabricksClient(cfg=config)
        await api._initialize()  # Must initialize before use

        # Create shared context provider
        provider = SharedContextProvider(api)

        # Create tool registry (all tools - AgentFactory will filter per domain)
        # Pass cache_store from container to ensure visualization endpoint can access cached data
        # Pass cache_factory for diagnostic artifact exploration tools
        # Pass semantic_cache for intelligent query result caching
        # Pass reflexion_store for learning from query feedback
        # Pass vector_store and embedding_service for RAG discovery tools
        tool_registry, request_input_tool = create_tool_registry(
            api=api,
            provider=provider,
            events=None,
            input_callback=None,
            llm_client=llm_client,
            cache_store=container.cache_store,  # Share cache with visualization endpoint
            cache_factory=container.cache_factory,  # For artifact exploration
            semantic_cache=container.semantic_cache,  # For semantic query caching
            reflexion_store=container.reflexion_store,  # For query learning feedback
            vector_store=container.vector_store,  # For RAG discovery (Analytics Agent)
            embedding_service=container.embedding_provider,  # For RAG embeddings
        )

        # Create IntentRouter with disabled domains from config
        intent_router = IntentRouter(
            llm_client=llm_client, disabled_domains=config.disabled_agent_domains
        )

        # Create base agent config with domain-specific overrides
        base_agent_config = AgentConfig(
            model=config.llm_model,
            max_tokens=config.llm_max_tokens,
            temperature=config.llm_temperature,
            domain_model_overrides=config.domain_model_overrides or {},
            domain_temperature_overrides=config.domain_temperature_overrides or {},
        )

        # Create AgentFactory
        # Note: AgentFactory will create domain-specific agents with filtered tools
        agent_factory = AgentFactory(
            llm_client=llm_client,
            tool_registry=tool_registry,
            base_config=base_agent_config,
            events=None,  # No event emitter for now
        )

        # Use the ConversationRepository from the container
        # This is backed by the configured StateStore (SQLite/Postgres/Databricks)
        conversation_repo = container.conversation_repo

        logger.debug(
            "using_conversation_repository",
            state_store_type=type(container.state_store).__name__,
            database_backend=container.config.database_backend,
        )

        # Create MultiAgentConversationManager
        # Pass cache_store for shared caching between ServiceCatalogTool and container
        # Pass cache_factory for large file attachment storage
        _multi_agent_manager = MultiAgentConversationManager(
            agent_factory=agent_factory,
            intent_router=intent_router,
            state_manager=conversation_repo,  # Use the injected ConversationRepository
            disabled_agent_domains=config.disabled_agent_domains or [],
            request_input_tool=request_input_tool,  # Enable user input routing
            cache_store=container.cache_store,  # Share cache with visualization endpoint
            cache_factory=container.cache_factory,  # For large file attachment storage
        )

        logger.debug(
            "multi_agent_manager_initialized",
            base_model=config.llm_model,
            domain_overrides=(
                list(config.domain_model_overrides.keys())
                if config.domain_model_overrides
                else []
            ),
        )

    return _multi_agent_manager


def get_state_container() -> Container:
    """
    Get the global state Container instance.

    This provides access to state stores, memory stores, and repositories.

    Returns:
        Container instance with initialized stores

    Raises:
        RuntimeError: If container not initialized (server startup failed)

    Example:
        >>> @app.post("/api/endpoint")
        >>> async def endpoint(
        ...     container: Annotated[Container, Depends(get_state_container)]
        ... ):
        ...     conv_repo = container.conversation_repo
        ...     memory_repo = container.memory_repo
    """
    # Import here to avoid circular dependency
    from starboard_server.main import get_container

    try:
        container = get_container()
        logger.debug(
            "state_container_accessed",
            state_store_type=type(container.state_store).__name__,
            memory_store_type=type(container.memory_store).__name__,
        )
        return container
    except RuntimeError as e:
        logger.error("state_container_access_failed", error=str(e))
        raise


# Type alias for cleaner dependency injection
ContainerDep = Annotated[Container, Depends(get_state_container)]
MultiAgentManagerDep = Annotated[
    "MultiAgentConversationManager", Depends(get_multi_agent_manager)
]

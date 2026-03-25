# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Agent Factory for creating domain-specialized agents.

This module provides infrastructure to instantiate DomainAgent instances
with domain-specific configuration, filtered tools, and custom prompts.

Key Features:
- Lazy agent creation (on-demand)
- Agent caching (reuse instances)
- Tool filtering per domain
- Config-based customization via AgentConfig
- Model/temperature override support

Design:
- Uses AgentConfig.with_overrides() for customization
- Uses domain-specific prompt builders from domain_prompts module
- Uses tool filtering per domain
"""

from typing import Any

from starboard_server.adapters.llm.base import BaseLLMClient
from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.agents.domain import DomainAgent
from starboard_server.agents.tools import ToolRegistry
from starboard_server.infra.observability.events import EventEmitter
from starboard_server.infra.observability.logging import get_logger
from starboard_server.prompts import (
    AgentDomain,
    get_prompt_builder_for_domain,
)

logger = get_logger(__name__)


class AgentFactory:
    """
    Factory for creating and caching domain-specialized reasoning agents.

    The factory manages agent lifecycle:
    1. Creates agents on-demand (lazy initialization)
    2. Caches instances for reuse (one per domain)
    3. Applies domain-specific configuration
    4. Filters tools per domain
    5. Injects custom prompts

    Usage:
        >>> # Initialize factory
        >>> factory = AgentFactory(
        ...     llm_client=llm_client,
        ...     tool_registry=full_tool_registry,
        ...     base_config=AgentConfig(model="gpt-4o", temperature=0.5),
        ...     events=event_emitter
        ... )
        >>>
        >>> # Get domain agents (created on-demand, then cached)
        >>> query_agent = factory.get_agent("query")
        >>> job_agent = factory.get_agent("job")
        >>>
        >>> # Reusing same agent instance
        >>> query_agent_again = factory.get_agent("query")
        >>> assert query_agent is query_agent_again  # Same instance
        >>>
        >>> # Clear cache for testing
        >>> factory.clear_cache()

    Attributes:
        llm_client: LLM client for agent inference
        tool_registry: Full tool registry (will be filtered per domain)
        base_config: Base configuration (will be overridden per domain)
        events: Optional event emitter for observability

    Thread Safety:
        This class is NOT thread-safe. Create separate instances per thread
        or add external synchronization.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        tool_registry: ToolRegistry,
        base_config: AgentConfig,
        events: EventEmitter | None = None,
    ):
        """
        Initialize agent factory.

        Args:
            llm_client: LLM client for agent inference
            tool_registry: Full tool registry (will be filtered per domain)
            base_config: Base configuration (will be overridden per domain)
            events: Optional event emitter for observability

        Example:
            >>> factory = AgentFactory(
            ...     llm_client=OpenAIClient(),
            ...     tool_registry=full_registry,
            ...     base_config=AgentConfig(
            ...         model="gpt-4o",
            ...         temperature=0.5,
            ...         max_steps=12,
            ...         max_tokens=100000,
            ...         domain_model_overrides={"router": "gpt-4o-mini"},
            ...         domain_temperature_overrides={"diagnostic": 0.7},
            ...     ),
            ...     events=EventEmitter()
            ... )
        """
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.base_config = base_config
        self.events = events

        # Agent cache (domain -> DomainAgent)
        self._agents: dict[str, DomainAgent] = {}

        logger.debug(
            "AgentFactory initialized",
            extra={
                "base_model": base_config.model,
                "base_temperature": base_config.temperature,
                "total_tools": len(tool_registry.list_tools()),
                "model_overrides": list(base_config.domain_model_overrides.keys()),
                "temperature_overrides": list(
                    base_config.domain_temperature_overrides.keys()
                ),
            },
        )

    def get_agent(
        self,
        domain: AgentDomain,
        conversation_config: dict[str, Any] | None = None,
    ) -> DomainAgent:
        """
        Get or create agent for domain with optional conversation config.

        Agents are created on-demand and cached for reuse. If conversation_config
        is provided, creates a fresh agent with conversation-specific overrides
        (not cached, as each conversation may have different config).

        Args:
            domain: Agent domain (router, query, job, table, compute, diagnostic)
            conversation_config: Optional per-conversation config overrides

        Returns:
            Domain-specialized DomainAgent instance

        Raises:
            ValueError: If domain is not recognized

        Example:
            >>> # Cached agent (no conversation config)
            >>> query_agent = factory.get_agent("query")
            >>>
            >>> # Fresh agent with conversation config (not cached)
            >>> custom_agent = factory.get_agent(
            ...     "query",
            ...     conversation_config={"use_max_model_tokens": True}
            ... )
        """
        # If conversation config provided, create fresh agent (don't cache)
        if conversation_config:
            logger.debug(
                f"Creating fresh {domain} agent with conversation config",
                extra={
                    "domain": domain,
                    "config_keys": list(conversation_config.keys()),
                },
            )
            return self._create_agent(domain, conversation_config=conversation_config)

        # Otherwise, use cached agent
        if domain not in self._agents:
            logger.debug("Creating new {domain} agent (cache miss)")
            self._agents[domain] = self._create_agent(domain)
        else:
            logger.debug("Reusing cached {domain} agent")

        return self._agents[domain]

    def _create_agent(
        self,
        domain: AgentDomain,
        conversation_config: dict[str, Any] | None = None,
    ) -> DomainAgent:
        """
        Create a new domain-specialized agent.

        This creates an agent with:
        1. Filter tools for domain
        2. Get domain-specific model/temperature
        3. Apply conversation-specific config overrides
        4. Get domain-specific prompt builder
        5. Create config with overrides (immutable pattern)
        6. Instantiate DomainAgent

        Args:
            domain: Agent domain
            conversation_config: Optional per-conversation config overrides

        Returns:
            New DomainAgent configured for the domain

        Raises:
            ValueError: If domain is not recognized
        """
        logger.debug("Creating {domain} agent", extra={"domain": domain})

        # Step 0: Check for offline mode (disables Databricks API tools)
        offline_mode = (
            conversation_config.get("offline_mode", False)
            if conversation_config
            else False
        )

        # Step 1: Filter tools for domain (Phase 2.2: Tool Registry Filtering)
        # If offline_mode is enabled, online tools (requiring Databricks API) are filtered out
        domain_tools = self.tool_registry.filter_by_domain(
            domain, offline_mode=offline_mode
        )
        logger.debug(
            f"Filtered tools for {domain}",
            extra={
                "domain": domain,
                "offline_mode": offline_mode,
                "filtered_count": len(domain_tools.list_tools()),
                "total_count": len(self.tool_registry.list_tools()),
            },
        )

        # Step 2: Get domain-specific model and temperature (Phase 0: Config)
        domain_model = self.base_config.get_model_for_domain(domain)
        domain_temp = self.base_config.get_temperature_for_domain(domain)
        domain_max_tokens = self.base_config.max_tokens

        # Step 3: Apply conversation-specific overrides (TASK 1, 2 & 6)
        if conversation_config:
            # Check for domain-specific model override first (TASK 2)
            domain_overrides = conversation_config.get("domain_model_overrides") or {}
            if domain in domain_overrides:
                domain_model = domain_overrides[domain]
                logger.debug(
                    f"Conversation config domain override for {domain}",
                    extra={"domain": domain, "model": domain_model},
                )
            # Then check for global model override (ignore None/empty values)
            elif conversation_config.get("model"):
                domain_model = conversation_config["model"]
                logger.debug(
                    f"Conversation config overriding model for {domain}",
                    extra={"domain": domain, "model": domain_model},
                )

            # Override temperature if specified in conversation config
            # Check for domain-specific temperature override first
            temp_overrides = (
                conversation_config.get("domain_temperature_overrides") or {}
            )
            if domain in temp_overrides:
                domain_temp = temp_overrides[domain]
                logger.debug(
                    f"Conversation config domain temperature override for {domain}",
                    extra={"domain": domain, "temperature": domain_temp},
                )
            # Then check for global temperature override (ignore None values)
            elif conversation_config.get("temperature") is not None:
                domain_temp = conversation_config["temperature"]
                logger.debug(
                    f"Conversation config overriding temperature for {domain}",
                    extra={"domain": domain, "temperature": domain_temp},
                )

            # TASK 6: Handle use_max_model_tokens
            # When enabled, use the model's context window as the token budget
            # (not max_output_tokens, which is only for single response limits)
            if conversation_config.get("use_max_model_tokens", False):
                from starboard_server.infra.constraints.model_limits import (
                    get_model_limits,
                )

                model_limits = get_model_limits(domain_model)
                domain_max_tokens = model_limits.context_window
                logger.debug(
                    "using_max_model_tokens",
                    extra={
                        "domain": domain,
                        "model": domain_model,
                        "context_window": model_limits.context_window,
                        "max_output_tokens": model_limits.max_output_tokens,
                        "budget_set_to": domain_max_tokens,
                    },
                )
            elif "max_tokens" in conversation_config:
                # Use explicit max_tokens from conversation config
                domain_max_tokens = conversation_config["max_tokens"]
                logger.debug(
                    f"Conversation config overriding max_tokens for {domain}",
                    extra={"domain": domain, "max_tokens": domain_max_tokens},
                )

        # Step 4: Get domain-specific prompt builder (Phase 2.4: Prompt Builders)
        prompt_builder = get_prompt_builder_for_domain(domain)

        # Step 5: Create domain-specific config (immutable override pattern)
        domain_config = self.base_config.with_overrides(
            system_prompt_builder=prompt_builder,
            model=domain_model,
            temperature=domain_temp,
            max_tokens=domain_max_tokens,
            domain=domain,  # Set domain for complete tool schema selection
        )

        logger.debug(
            f"Created domain config for {domain}",
            extra={
                "domain": domain,
                "model": domain_model,
                "temperature": domain_temp,
                "has_custom_prompt": True,
                "tool_count": len(domain_tools.list_tools()),
            },
        )

        # Step 5: Create DomainAgent
        agent = DomainAgent(
            llm_client=self.llm_client,
            tool_registry=domain_tools,  # Filtered registry
            config=domain_config,  # Domain-customized config
            events=self.events,
            enable_metrics=True,
        )

        logger.debug(
            f"Created {domain} agent",
            extra={
                "domain": domain,
                "model": domain_model,
                "temperature": domain_temp,
                "tools": domain_tools.list_tools(),
            },
        )

        return agent

    def clear_cache(self) -> None:
        """
        Clear cached agents.

        Useful for testing or when you need to force recreation
        of agents (e.g., after config changes).

        Example:
            >>> factory.clear_cache()
            >>> # Next get_agent() call will create fresh agents
        """
        cleared_count = len(self._agents)
        self._agents.clear()
        logger.debug("Cleared agent cache", extra={"cleared_count": cleared_count})

    def list_cached_domains(self) -> list[str]:
        """
        List domains with cached agents.

        Returns:
            List of domain names with cached agents

        Example:
            >>> factory.get_agent("query")
            >>> factory.get_agent("job")
            >>> factory.list_cached_domains()
            ['query', 'job']
        """
        return list(self._agents.keys())

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache metrics

        Example:
            >>> stats = factory.get_cache_stats()
            >>> stats
            {
                'cached_agents': 2,
                'domains': ['query', 'job'],
                'cache_hit_rate': 0.75,  # Conceptual - tracking would need counters
            }
        """
        return {
            "cached_agents": len(self._agents),
            "domains": list(self._agents.keys()),
            "max_possible_agents": 6,  # 6 domains: router, query, job, table, compute, diagnostic
        }

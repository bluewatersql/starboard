"""
Domain model configuration generator.

Generates structured domain model configuration data for conversations,
handling model overrides and disabled domains.

Follows Python AI Agent Engineering Standards:
- Single responsibility (config generation only)
- Pure function design
- Type hints on all functions
- Explicit inputs/outputs
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starboard_server.agents.agent_factory import AgentFactory
    from starboard_server.domain.conversation.api_types import ConversationConfig


class DomainModelConfigGenerator:
    """
    Generates domain model configuration data for conversations.

    Determines which domains use non-default models and generates
    structured configuration data for frontend display.

    Design:
    - Respects disabled domains (excludes from output)
    - Follows model hierarchy: Conversation override > Env var > Base model
    - Only includes domains with non-default models

    Example:
        ```python
        generator = DomainModelConfigGenerator(
            agent_factory=factory,
            disabled_domains={"diagnostic"},
        )

        configs = generator.generate(conversation_config)
        # Returns: [
        #     {"domain": "Query Optimization", "domain_key": "query", "model": "gpt-4"},
        #     {"domain": "Job Analysis", "domain_key": "job", "model": "claude-3"},
        # ]
        ```
    """

    # Domain definitions (domain_key, friendly_name)
    DOMAINS = [
        ("query", "Query Optimization"),
        ("job", "Job Analysis"),
        ("uc", "Unity Catalog & Governance"),
        ("cluster", "Cluster Resources"),
        ("warehouse", "Warehouse Analysis"),
        ("diagnostic", "Diagnostics & Troubleshooting"),
        ("analytics", "Cost & Usage Analytics"),
    ]

    def __init__(
        self,
        agent_factory: AgentFactory,
        disabled_domains: set[str] | None = None,
    ) -> None:
        """
        Initialize domain model config generator.

        Args:
            agent_factory: Factory for accessing base agent config
            disabled_domains: Set of disabled domain keys to exclude (optional)
        """
        self.agent_factory = agent_factory
        self.disabled_domains = disabled_domains or set()

    def generate(
        self,
        conversation_config: ConversationConfig,
    ) -> list[dict[str, str]]:
        """
        Generate structured domain model configuration data.

        Only includes domains that:
        - Are NOT in disabled_agent_domains (completely disabled)
        - Use a different model than the default

        Args:
            conversation_config: Conversation-specific configuration

        Returns:
            List of dicts with domain, domain_key, and model.
            Empty list if all domains use default model.

        Example:
            >>> generator = DomainModelConfigGenerator(factory, set())
            >>> configs = generator.generate(conversation_config)
            >>> print(configs[0])
            {'domain': 'Query Optimization', 'domain_key': 'query', 'model': 'gpt-4'}
        """
        # Get base config from agent factory
        base_config = self.agent_factory.base_config

        # Extract conversation config as dict
        conv_config_dict = conversation_config.model_dump()

        # Determine the default model
        # Hierarchy: Conversation config > Base config model
        default_model = self._get_default_model(conv_config_dict, base_config)

        # Get domain model overrides from conversation config (if provided)
        domain_overrides = conv_config_dict.get("domain_model_overrides") or {}

        # Build domain-to-model mapping (only non-default)
        domain_configs = []
        for domain_key, domain_label in self.DOMAINS:
            if self._should_include_domain(
                domain_key, domain_label, domain_overrides, base_config, default_model
            ):
                domain_model = self._get_domain_model(
                    domain_key, domain_overrides, base_config
                )
                domain_configs.append(
                    {
                        "domain": domain_label,
                        "domain_key": domain_key,
                        "model": domain_model,
                    }
                )

        return domain_configs

    def _get_default_model(self, conv_config_dict: dict, base_config: Any) -> str:
        """
        Determine the default model for the conversation.

        Args:
            conv_config_dict: Conversation config as dictionary
            base_config: Base agent configuration

        Returns:
            Default model name
        """
        if conv_config_dict.get("model"):
            return conv_config_dict["model"]
        return base_config.model

    def _should_include_domain(
        self,
        domain_key: str,
        domain_label: str,  # noqa: ARG002
        domain_overrides: dict,
        base_config: Any,
        default_model: str,
    ) -> bool:
        """
        Check if domain should be included in config list.

        Args:
            domain_key: Domain identifier (e.g., "query")
            domain_label: Human-readable domain name
            domain_overrides: Conversation-specific domain overrides
            base_config: Base agent configuration
            default_model: Default model for conversation

        Returns:
            True if domain should be included, False otherwise
        """
        # Skip if this domain is disabled
        if domain_key in self.disabled_domains:
            return False

        # Get effective model for this domain
        domain_model = self._get_domain_model(domain_key, domain_overrides, base_config)

        # Only include if different from default
        return domain_model != default_model

    def _get_domain_model(
        self,
        domain_key: str,
        domain_overrides: dict,
        base_config: Any,
    ) -> str:
        """
        Get effective model for a specific domain.

        Hierarchy: Conversation domain override > Env var domain override > Base model

        Args:
            domain_key: Domain identifier
            domain_overrides: Conversation-specific domain overrides
            base_config: Base agent configuration

        Returns:
            Model name for the domain
        """
        if domain_key in domain_overrides:
            return domain_overrides[domain_key]
        return base_config.get_model_for_domain(domain_key)

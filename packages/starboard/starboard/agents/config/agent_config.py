# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Configuration for reasoning agent.

This module provides configuration dataclasses for the reasoning agent
architecture. All configurations use immutable dataclasses with sensible
defaults that can be overridden per-use-case.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from starboard_core.domain.models.llm import OptimizationMode

from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)

# Per-domain token budgets (total tokens per agent session)
DEFAULT_TOKEN_BUDGETS: dict[str, int] = {
    "router": 30_000,
    "query": 60_000,
    "cluster": 72_000,
    "warehouse": 72_000,
    "job": 95_000,
    "analytics": 95_000,
    "uc": 120_000,
    "diagnostic": 120_000,
}


@dataclass(frozen=True)
class AgentConfig:
    """
    Configuration for reasoning agent.

    This configuration controls the behavior of the reasoning agent, including
    model selection, budget limits, memory management, and execution parameters.

    Attributes:
        model: LLM model to use (e.g., "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet")
        temperature: Temperature for LLM calls (0.0-1.0, lower = more deterministic)
        max_tokens: Token budget for entire session (used for tracking/enforcement)
        max_steps: Maximum reasoning steps before termination
        enforce_budget: Whether to enforce token budget (default: True)
        max_messages: Maximum messages to keep in conversation history
        enable_tracing: Whether to capture detailed execution traces
        enable_debug: Whether to enable debug logging (includes LLM call tracing)
        enable_metrics: Whether to enable metrics collection
        cost_per_1k_input_tokens: Cost per 1K input tokens in USD (for tracking)
        cost_per_1k_output_tokens: Cost per 1K output tokens in USD (for tracking)
        system_prompt_template: Optional custom system prompt template string
        system_prompt_builder: Optional custom prompt builder function
        domain_model_overrides: Per-domain model overrides (multi-agent support)
        domain_temperature_overrides: Per-domain temperature overrides (multi-agent support)
        domain: Domain name for this agent (query, job, table, compute, diagnostic, router)

    Example:
        >>> # Use defaults (databricks-claude-sonnet-4-5, 25K tokens, budget enforced)
        >>> config = AgentConfig()
        >>>
        >>> # Override for production (gpt-4o, higher budget)
        >>> config = AgentConfig(
        ...     model="gpt-4o",
        ...     max_tokens=100_000,
        ...     temperature=0.2,
        ... )
        >>>
        >>> # Per-domain budget from DEFAULT_TOKEN_BUDGETS
        >>> budget = AgentConfig.get_budget_for_domain("query")  # 60_000
        >>> config = AgentConfig(max_tokens=budget, domain="query")
        >>>
        >>> # Disable budget enforcement for development
        >>> config = AgentConfig(
        ...     model="gpt-4o-mini",
        ...     enforce_budget=False,
        ...     enable_debug=True,
        ... )

    Note:
        This configuration is immutable (frozen=True). To modify, create a new
        instance using dataclasses.replace():

        >>> from dataclasses import replace
        >>> new_config = replace(config, max_tokens=80_000)
    """

    # Model configuration
    model: str = "databricks-claude-sonnet-4-5"
    temperature: float = 0.3

    # Budget configuration
    max_tokens: int = 25_000  # Token budget for tracking/enforcement
    max_steps: int = 20  # Maximum reasoning steps before termination
    enforce_budget: bool = True  # Enforce token budget (truncate at cap)

    # Memory configuration
    max_messages: int = 50

    # Behavior configuration
    enable_tracing: bool = True
    enable_debug: bool = False
    enable_metrics: bool = True

    # Cost tracking (approximate, varies by provider)
    cost_per_1k_input_tokens: float = 0.00015  # $0.15 per 1M for gpt-4o-mini
    cost_per_1k_output_tokens: float = 0.0006  # $0.60 per 1M for gpt-4o-mini

    # Multi-agent configuration (Phase 0)
    system_prompt_template: str | None = None
    """Optional custom system prompt template string (format with goal, mode, token_budget)"""

    system_prompt_builder: (
        Callable[[OptimizationMode, str, int, dict | None], str]
        | Callable[[OptimizationMode, str, int], str]
        | None
    ) = None
    """Optional custom system prompt builder function.

    Signature: (mode, goal, budget_remaining, context=None) -> str

    Context is optional - prompt builders that need agent context (like diagnostic
    with available_artifacts) accept it, others ignore it.
    """

    domain_model_overrides: dict[str, str] = field(default_factory=dict)
    """Per-domain model overrides (e.g., {"router": "gpt-4o-mini", "diagnostic": "gpt-4o"})"""

    domain_temperature_overrides: dict[str, float] = field(default_factory=dict)
    """Per-domain temperature overrides (e.g., {"router": 0.3, "diagnostic": 0.7})"""

    domain: str | None = None
    """Domain name for this agent (query, job, table, compute, diagnostic, router).
    Required for domain agents using detailed optimization schemas."""

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        # Validate temperature
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(
                f"Temperature must be between 0.0 and 2.0, got {self.temperature}"
            )

        # Validate max_tokens
        if self.max_tokens <= 0:
            raise ValueError(f"max_tokens must be positive, got {self.max_tokens}")

        # Validate max_steps
        if self.max_steps <= 0:
            raise ValueError(f"max_steps must be positive, got {self.max_steps}")

        # Validate max_messages
        if self.max_messages <= 0:
            raise ValueError(f"max_messages must be positive, got {self.max_messages}")

        # Log configuration when debug is enabled (without sensitive data)
        if self.enable_debug:
            logger.debug(
                f"AgentConfig initialized: model={self.model}, "
                f"max_tokens={self.max_tokens:,}, max_steps={self.max_steps}, "
                f"temperature={self.temperature}"
            )

    @staticmethod
    def get_budget_for_domain(domain: str) -> int:
        """
        Get the default token budget for a domain.

        Args:
            domain: Domain name (e.g., "query", "job", "diagnostic")

        Returns:
            Token budget for the domain, or 25_000 as fallback

        Example:
            >>> AgentConfig.get_budget_for_domain("query")
            60000
            >>> AgentConfig.get_budget_for_domain("unknown")
            25000
        """
        return DEFAULT_TOKEN_BUDGETS.get(domain, 25_000)

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Estimate cost for a given token usage.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Estimated cost in USD

        Example:
            >>> config = AgentConfig()
            >>> cost = config.estimate_cost(input_tokens=5000, output_tokens=1000)
            >>> print(f"${cost:.4f}")
            $0.0013
        """
        input_cost = (input_tokens / 1000) * self.cost_per_1k_input_tokens
        output_cost = (output_tokens / 1000) * self.cost_per_1k_output_tokens
        return input_cost + output_cost

    def with_overrides(self, **kwargs) -> AgentConfig:
        """
        Create new config with overrides (immutable pattern).

        This method uses dataclasses.replace() to create a new AgentConfig
        instance with specified fields overridden, preserving immutability.

        Args:
            **kwargs: Fields to override (must be valid AgentConfig fields)

        Returns:
            New AgentConfig instance with overrides applied

        Raises:
            TypeError: If invalid field names are provided

        Example:
            >>> base_config = AgentConfig(model="gpt-4o", temperature=0.5)
            >>> router_config = base_config.with_overrides(
            ...     model="gpt-4o-mini",
            ...     temperature=0.3,
            ...     max_steps=3
            ... )
            >>> router_config.model
            'gpt-4o-mini'
            >>> base_config.model  # Original unchanged
            'gpt-4o'
        """
        return replace(self, **kwargs)

    def get_model_for_domain(self, domain: str) -> str:
        """
        Get model for specific domain, fallback to default.

        Checks domain_model_overrides dictionary for domain-specific model,
        returns self.model if not found.

        Args:
            domain: Domain name (e.g., "router", "query", "job", "diagnostic")

        Returns:
            Model name string (e.g., "gpt-4o", "gpt-4o-mini")

        Example:
            >>> config = AgentConfig(
            ...     model="gpt-4o",
            ...     domain_model_overrides={"router": "gpt-4o-mini"}
            ... )
            >>> config.get_model_for_domain("router")
            'gpt-4o-mini'
            >>> config.get_model_for_domain("query")  # No override
            'gpt-4o'
        """
        return self.domain_model_overrides.get(domain, self.model)

    def get_temperature_for_domain(self, domain: str) -> float:
        """
        Get temperature for specific domain, fallback to default.

        Checks domain_temperature_overrides dictionary for domain-specific
        temperature, returns self.temperature if not found.

        Args:
            domain: Domain name (e.g., "router", "query", "job", "diagnostic")

        Returns:
            Temperature value (0.0-2.0)

        Example:
            >>> config = AgentConfig(
            ...     temperature=0.5,
            ...     domain_temperature_overrides={"router": 0.3, "diagnostic": 0.7}
            ... )
            >>> config.get_temperature_for_domain("router")
            0.3
            >>> config.get_temperature_for_domain("query")  # No override
            0.5
        """
        return self.domain_temperature_overrides.get(domain, self.temperature)


@dataclass(frozen=True)
class ModelConfig:
    """
    Configuration for specific model characteristics.

    This dataclass stores metadata about different LLM models to help with
    routing and optimization decisions.

    Attributes:
        name: Model identifier (e.g., "gpt-4o", "claude-3-5-sonnet")
        provider: Provider name (e.g., "openai", "anthropic", "google")
        context_window: Maximum context window size in tokens
        supports_tools: Whether model supports function/tool calling
        supports_streaming: Whether model supports streaming responses
        cost_per_1k_input: Cost per 1K input tokens in USD
        cost_per_1k_output: Cost per 1K output tokens in USD
        strengths: List of model strengths (for routing decisions)

    Example:
        >>> gpt4o_mini = ModelConfig(
        ...     name="gpt-4o-mini",
        ...     provider="openai",
        ...     context_window=128_000,
        ...     cost_per_1k_input=0.00015,
        ...     cost_per_1k_output=0.0006,
        ...     strengths=["fast", "cheap", "structured_output"],
        ... )
    """

    name: str
    provider: str
    context_window: int
    supports_tools: bool = True
    supports_streaming: bool = True
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    strengths: tuple[str, ...] = field(default_factory=tuple)

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Estimate cost for this model.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Estimated cost in USD
        """
        input_cost = (input_tokens / 1000) * self.cost_per_1k_input
        output_cost = (output_tokens / 1000) * self.cost_per_1k_output
        return input_cost + output_cost


# Common model configurations
GPT_4O_MINI = ModelConfig(
    name="gpt-4o-mini",
    provider="openai",
    context_window=128_000,
    cost_per_1k_input=0.00015,
    cost_per_1k_output=0.0006,
    strengths=("fast", "cheap", "structured_output"),
)

GPT_4O = ModelConfig(
    name="gpt-4o",
    provider="openai",
    context_window=128_000,
    cost_per_1k_input=0.0025,
    cost_per_1k_output=0.01,
    strengths=("reasoning", "complex_analysis", "accurate"),
)

CLAUDE_3_5_SONNET = ModelConfig(
    name="claude-3-5-sonnet-20241022",
    provider="anthropic",
    context_window=200_000,
    cost_per_1k_input=0.003,
    cost_per_1k_output=0.015,
    strengths=("reasoning", "code_analysis", "long_context"),
)

GEMINI_15_PRO = ModelConfig(
    name="gemini-1.5-pro",
    provider="google",
    context_window=2_000_000,
    cost_per_1k_input=0.00125,
    cost_per_1k_output=0.005,
    strengths=("balanced", "fast", "long_context"),
)

# Registry of available models
AVAILABLE_MODELS = {
    "gpt-4o-mini": GPT_4O_MINI,
    "gpt-4o": GPT_4O,
    "claude-3-5-sonnet": CLAUDE_3_5_SONNET,
    "claude-3-5-sonnet-20241022": CLAUDE_3_5_SONNET,
    "gemini-1.5-pro": GEMINI_15_PRO,
}


def get_model_config(model_name: str) -> ModelConfig | None:
    """
    Get configuration for a specific model.

    Args:
        model_name: Name of the model

    Returns:
        ModelConfig if found, None otherwise

    Example:
        >>> config = get_model_config("gpt-4o-mini")
        >>> if config:
        ...     print(f"Context window: {config.context_window:,}")
        Context window: 128,000
    """
    return AVAILABLE_MODELS.get(model_name)

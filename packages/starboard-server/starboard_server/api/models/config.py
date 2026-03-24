"""
API configuration models.

Models for configuring conversations and domain-specific settings:
- DomainModelConfig: Per-domain model configuration
- ConversationConfig: Session configuration

Extracted from models.py for better organization.
"""

from pydantic import BaseModel, Field


class DomainModelConfig(BaseModel):
    """
    Domain-specific model configuration.

    Args:
        domain: Domain name (e.g., "Query Optimization", "Job Analysis").
        domain_key: Internal domain key (e.g., "query", "job").
        model: LLM model identifier for this domain.

    Examples:
        >>> config = DomainModelConfig(
        ...     domain="Query Optimization",
        ...     domain_key="query",
        ...     model="databricks-gpt-5-1"
        ... )
    """

    domain: str = Field(..., description="Human-readable domain name")
    domain_key: str = Field(..., description="Internal domain key")
    model: str = Field(..., description="LLM model identifier for this domain")


class ConversationConfig(BaseModel):
    """
    Configuration for a conversation session.

    Args:
        temperature: LLM sampling temperature (0.1-1.0). Lower is more deterministic.
        max_tokens: Maximum tokens in response (10,000-200,000).
        use_max_model_tokens: If True, automatically use model's max output tokens.
        safe_mode: If True, disable destructive operations and external calls.
        streaming: If True, stream responses via SSE; else return complete response.
        model: LLM model identifier (supported models from Databricks).
        budget_enforced: If True, enforce session token budget limits.
        max_steps: Maximum reasoning steps allowed (5-25).
        logging_level: Logging verbosity level.
        domain_model_overrides: Per-domain model overrides (domain_key -> model_name).
        domain_temperature_overrides: Per-domain temperature overrides (domain_key -> temperature).

    Examples:
        >>> config = ConversationConfig(temperature=0.4, max_tokens=120000)
        >>> config.temperature
        0.4
        >>> config.budget_enforced
        False
        >>> config_with_overrides = ConversationConfig(
        ...     domain_model_overrides={"query": "databricks-gpt-5"},
        ...     domain_temperature_overrides={"diagnostic": 0.7}
        ... )
    """

    temperature: float = Field(
        default=0.4,
        ge=0.1,
        le=1.0,
        description="LLM sampling temperature",
    )
    max_tokens: int = Field(
        default=120000,
        ge=10000,
        le=200000,
        description="Maximum tokens in response",
    )
    use_max_model_tokens: bool = Field(
        default=False,
        description="Automatically use model's maximum output token limit",
    )
    safe_mode: bool = Field(
        default=False,
        description="Disable destructive operations if True",
    )
    streaming: bool = Field(
        default=True,
        description="Stream responses via SSE",
    )
    model: str = Field(
        default="databricks-claude-sonnet-4-5",
        min_length=1,
        max_length=100,
        description="LLM model identifier",
    )
    budget_enforced: bool = Field(
        default=False,
        description="Enforce session token budget limits",
    )
    max_steps: int = Field(
        default=20,
        ge=5,
        le=25,
        description="Maximum reasoning steps allowed",
    )
    logging_level: str = Field(
        default="INFO",
        description="Logging verbosity level",
    )
    domain_model_overrides: dict[str, str] | None = Field(
        default=None,
        description="Per-domain model overrides (domain_key -> model_name)",
    )
    domain_temperature_overrides: dict[str, float] | None = Field(
        default=None,
        description="Per-domain temperature overrides (domain_key -> temperature)",
    )
    offline_mode: bool = Field(
        default=False,
        description="Force OFFLINE mode - disables tools that require Databricks API calls",
    )

    model_config = {"frozen": True}  # Immutable after creation

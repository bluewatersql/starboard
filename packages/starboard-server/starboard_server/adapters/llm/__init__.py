"""
LLM client services.

This package provides LLM clients for various providers (OpenAI, etc.).
"""

from starboard_server.infra.observability.logging import get_logger
from typing import TYPE_CHECKING

from starboard_server.adapters.llm.base import BaseLLMClient
from starboard_server.adapters.llm.openai.client import OpenAIProvider

if TYPE_CHECKING:
    from starboard_server.infra.core.config import EnvConfig, get_config

logger = get_logger(__name__)

__all__ = ["BaseLLMClient", "OpenAIProvider", "create_llm_client"]

def create_llm_client(cfg: "EnvConfig | None" = None) -> BaseLLMClient:
    """
    Factory function to create the appropriate LLM client based on configuration.

    This function implements the provider pattern, selecting the correct
    LLM provider implementation based on the `llm_provider` configuration field.

    Args:
        cfg: Environment configuration. If None, loads from environment.

    Returns:
        BaseLLMClient instance configured for the specified provider.

    Raises:
        ValueError: If the provider is not supported or configuration is invalid.

    Example:
        >>> from starboard_server.infra.core.config import EnvConfig, get_config
        >>> config = EnvConfig.from_env()
        >>> client = create_llm_client(config)
        >>> # Use client for LLM operations
        >>> response = client.text_response([{"role": "user", "content": "Hello"}])

    Supported Providers:
        - "openai": OpenAIProvider (default)
        - Future: "anthropic", "azure", etc.

    Note:
        This factory centralizes LLM client creation, making it easy to:
        1. Add new providers without changing call sites
        2. Ensure consistent initialization across the codebase
        3. Validate provider configuration before instantiation
    """
    from starboard_server.infra.core.config import EnvConfig, get_config

    if cfg is None:
        cfg = get_config()

    provider = cfg.llm_provider.lower() if cfg.llm_provider else "openai"

    logger.debug(
        "creating_llm_client",
        extra={"provider": provider, "model": cfg.llm_model},
    )

    if provider == "openai":
        return OpenAIProvider(cfg=cfg)
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Supported providers: openai. "
            f"Set LLM_PROVIDER environment variable to a supported provider."
        )

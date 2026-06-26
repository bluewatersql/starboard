# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Model-specific limits and constraints.

This module defines maximum token limits, context windows, and other constraints
for various LLM providers and models. These limits are based on official provider
documentation and are used to automatically configure appropriate token limits.

References:
- OpenAI: https://platform.openai.com/docs/models
- Anthropic: https://docs.anthropic.com/claude/docs/models-overview
- Google: https://ai.google.dev/gemini-api/docs/models/gemini
- Databricks: Provider-specific documentation
"""

from __future__ import annotations

from dataclasses import dataclass

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ModelLimits:
    """
    Model-specific limits and constraints.

    Attributes:
        max_output_tokens: Maximum tokens the model can generate in a single response
        context_window: Total context window size (input + output)
        supports_streaming: Whether the model supports streaming responses
        supports_function_calling: Whether the model supports function/tool calling
    """

    max_output_tokens: int
    context_window: int
    supports_streaming: bool = True
    supports_function_calling: bool = True


# =============================================================================
# OpenAI Models
# =============================================================================

OPENAI_MODELS: dict[str, ModelLimits] = {
    # GPT-4.1 series (April 2025 - 1M context window)
    "gpt-4.1": ModelLimits(
        max_output_tokens=32_768,
        context_window=1_048_576,  # 1M tokens
    ),
    "gpt-4.1-mini": ModelLimits(
        max_output_tokens=16_384,
        context_window=1_048_576,  # 1M tokens
    ),
    "gpt-4.1-nano": ModelLimits(
        max_output_tokens=8_192,
        context_window=1_048_576,  # 1M tokens
    ),
    # GPT-4o series
    "gpt-4o": ModelLimits(
        max_output_tokens=16_384,
        context_window=128_000,
    ),
    "gpt-4o-mini": ModelLimits(
        max_output_tokens=16_384,
        context_window=128_000,
    ),
    # GPT-4 Turbo series
    "gpt-4-turbo": ModelLimits(
        max_output_tokens=4_096,
        context_window=128_000,
    ),
    "gpt-4-turbo-preview": ModelLimits(
        max_output_tokens=4_096,
        context_window=128_000,
    ),
    # GPT-4 series (original)
    "gpt-4": ModelLimits(
        max_output_tokens=8_192,
        context_window=8_192,
    ),
    "gpt-4-32k": ModelLimits(
        max_output_tokens=8_192,
        context_window=32_768,
    ),
    # GPT-3.5 Turbo series
    "gpt-3.5-turbo": ModelLimits(
        max_output_tokens=4_096,
        context_window=16_385,
    ),
    "gpt-3.5-turbo-16k": ModelLimits(
        max_output_tokens=4_096,
        context_window=16_385,
    ),
    # o1 series (reasoning models)
    "o1": ModelLimits(
        max_output_tokens=100_000,
        context_window=200_000,
        supports_streaming=False,
        supports_function_calling=True,
    ),
    "o1-preview": ModelLimits(
        max_output_tokens=32_768,
        context_window=128_000,
        supports_streaming=False,
        supports_function_calling=False,
    ),
    "o1-mini": ModelLimits(
        max_output_tokens=65_536,
        context_window=128_000,
        supports_streaming=False,
        supports_function_calling=False,
    ),
    # o3 series (reasoning models - December 2024)
    "o3": ModelLimits(
        max_output_tokens=100_000,
        context_window=200_000,
        supports_streaming=False,
        supports_function_calling=True,
    ),
    "o3-mini": ModelLimits(
        max_output_tokens=65_536,
        context_window=200_000,
        supports_streaming=False,
        supports_function_calling=True,
    ),
    # o4-mini (2025)
    "o4-mini": ModelLimits(
        max_output_tokens=100_000,
        context_window=200_000,
        supports_streaming=True,
        supports_function_calling=True,
    ),
    # GPT-5 series (August 2025)
    "gpt-5": ModelLimits(
        max_output_tokens=65_536,
        context_window=256_000,
    ),
    "gpt-5-turbo": ModelLimits(
        max_output_tokens=32_768,
        context_window=256_000,
    ),
    "gpt-5-mini": ModelLimits(
        max_output_tokens=16_384,
        context_window=128_000,
    ),
    # GPT-5.1 series
    "gpt-5-1": ModelLimits(
        max_output_tokens=65_536,
        context_window=256_000,
    ),
    "gpt-5-1-mini": ModelLimits(
        max_output_tokens=16_384,
        context_window=128_000,
    ),
}


# =============================================================================
# Anthropic Claude Models
# =============================================================================

ANTHROPIC_MODELS: dict[str, ModelLimits] = {
    # Claude 3.5 Sonnet (latest)
    "claude-3-5-sonnet-20241022": ModelLimits(
        max_output_tokens=8_192,
        context_window=200_000,
    ),
    "claude-3-5-sonnet-20240620": ModelLimits(
        max_output_tokens=8_192,
        context_window=200_000,
    ),
    "claude-3-5-sonnet": ModelLimits(  # Alias for latest
        max_output_tokens=8_192,
        context_window=200_000,
    ),
    # Claude 3 Opus
    "claude-3-opus-20240229": ModelLimits(
        max_output_tokens=4_096,
        context_window=200_000,
    ),
    "claude-3-opus": ModelLimits(  # Alias for latest
        max_output_tokens=4_096,
        context_window=200_000,
    ),
    # Claude 3 Sonnet
    "claude-3-sonnet-20240229": ModelLimits(
        max_output_tokens=4_096,
        context_window=200_000,
    ),
    "claude-3-sonnet": ModelLimits(  # Alias for latest
        max_output_tokens=4_096,
        context_window=200_000,
    ),
    # Claude 3 Haiku
    "claude-3-haiku-20240307": ModelLimits(
        max_output_tokens=4_096,
        context_window=200_000,
    ),
    "claude-3-haiku": ModelLimits(  # Alias for latest
        max_output_tokens=4_096,
        context_window=200_000,
    ),
    # Legacy Claude 2
    "claude-2.1": ModelLimits(
        max_output_tokens=4_096,
        context_window=200_000,
    ),
    "claude-2.0": ModelLimits(
        max_output_tokens=4_096,
        context_window=100_000,
    ),
}


# =============================================================================
# Google Gemini Models
# =============================================================================

GEMINI_MODELS: dict[str, ModelLimits] = {
    # Gemini 2.0
    "gemini-2.0-flash-exp": ModelLimits(
        max_output_tokens=8_192,
        context_window=1_048_576,  # 1M tokens
    ),
    # Gemini 1.5 Pro
    "gemini-1.5-pro": ModelLimits(
        max_output_tokens=8_192,
        context_window=2_097_152,  # 2M tokens
    ),
    "gemini-1.5-pro-002": ModelLimits(
        max_output_tokens=8_192,
        context_window=2_097_152,
    ),
    # Gemini 1.5 Flash
    "gemini-1.5-flash": ModelLimits(
        max_output_tokens=8_192,
        context_window=1_048_576,  # 1M tokens
    ),
    "gemini-1.5-flash-002": ModelLimits(
        max_output_tokens=8_192,
        context_window=1_048_576,
    ),
    # Gemini 1.0 Pro
    "gemini-1.0-pro": ModelLimits(
        max_output_tokens=2_048,
        context_window=32_760,
    ),
}


# =============================================================================
# Databricks Models (Foundation Model API)
# =============================================================================

DATABRICKS_MODELS: dict[str, ModelLimits] = {
    # Claude models via Databricks
    "databricks-claude-sonnet-4-5": ModelLimits(
        max_output_tokens=8_192,
        context_window=200_000,
    ),
    # GPT models via Databricks
    "databricks-gpt-5": ModelLimits(
        max_output_tokens=65_536,
        context_window=200_000,
    ),
    "databricks-gpt-5-1": ModelLimits(
        max_output_tokens=65_536,
        context_window=200_000,
    ),
    "databricks-gpt-5-2": ModelLimits(
        max_output_tokens=65_536,
        context_window=200_000,
    ),
    "databricks-gpt-5-mini": ModelLimits(
        max_output_tokens=16_384,
        context_window=128_000,
    ),
    # Gemini models via Databricks
    "databricks-gemini-2.5-pro": ModelLimits(
        max_output_tokens=8_192,
        context_window=2_097_152,
    ),
    "databricks-gemini-2.5-flash": ModelLimits(
        max_output_tokens=8_192,
        context_window=1_048_576,
    ),
    # Meta Llama models via Databricks
    "databricks-meta-llama-3-1-405b-instruct": ModelLimits(
        max_output_tokens=8_192,
        context_window=128_000,
    ),
    "databricks-meta-llama-3-1-70b-instruct": ModelLimits(
        max_output_tokens=8_192,
        context_window=128_000,
    ),
    # Qwen models via Databricks
    "databricks-qwen3-next-80b-a3b-instruct": ModelLimits(
        max_output_tokens=32_768,
        context_window=32_768,
    ),
    # Llama 4 Maverick (future model)
    "databricks-llama-4-maverick": ModelLimits(
        max_output_tokens=16_384,
        context_window=256_000,
    ),
}


# =============================================================================
# Default Limits (fallback for unknown models)
# =============================================================================

DEFAULT_MODEL_LIMITS = ModelLimits(
    max_output_tokens=4_096,  # Conservative default
    context_window=16_384,  # Conservative default
    supports_streaming=True,
    supports_function_calling=True,
)


# =============================================================================
# All registries for iteration
# =============================================================================

_ALL_REGISTRIES: list[dict[str, ModelLimits]] = [
    OPENAI_MODELS,
    ANTHROPIC_MODELS,
    GEMINI_MODELS,
    DATABRICKS_MODELS,
]


# =============================================================================
# Public API
# =============================================================================


def _lookup_model_limits(model: str) -> ModelLimits | None:
    """Look up model limits by exact match then fuzzy match across all registries.

    Args:
        model: Raw model identifier (will be normalized internally)

    Returns:
        ModelLimits if found, None otherwise
    """
    model_key = model.lower().strip()

    # Try exact match first
    for registry in _ALL_REGISTRIES:
        if model_key in registry:
            return registry[model_key]

    # Try fuzzy match for versioned models (e.g., "gpt-4o-2024-05-13")
    for registry in _ALL_REGISTRIES:
        for key, value in registry.items():
            if key in model_key or model_key.startswith(key):
                logger.debug(
                    "model_limits_fuzzy_match",
                    requested_model=model,
                    matched_key=key,
                )
                return value

    return None


def get_max_tokens_by_model(
    model: str,
    use_max: bool = False,
    fallback: int | None = None,
) -> int:
    """
    Get the maximum output tokens for a given model.

    Args:
        model: Model identifier (e.g., "gpt-4o", "claude-3-opus", "databricks-gpt-5")
        use_max: If True, return the model's max output tokens. If False, return a
                 conservative default suitable for general use.
        fallback: Optional fallback value if model is not found. If None, uses
                 DEFAULT_MODEL_LIMITS.max_output_tokens.

    Returns:
        Maximum output tokens for the model

    Example:
        >>> get_max_tokens_by_model("gpt-4o", use_max=True)
        16384
        >>> get_max_tokens_by_model("gpt-4o", use_max=False)
        4096  # Conservative default for general use
        >>> get_max_tokens_by_model("unknown-model", use_max=True)
        4096  # Fallback default
    """
    limits = _lookup_model_limits(model)

    if limits is None:
        fallback_value = (
            fallback if fallback is not None else DEFAULT_MODEL_LIMITS.max_output_tokens
        )
        logger.warning(
            "model_limits_not_found",
            model=model,
            fallback_max_tokens=fallback_value,
        )
        return fallback_value

    if use_max:
        return limits.max_output_tokens

    # Conservative default: 25% of max or 4K, whichever is smaller
    return min(limits.max_output_tokens // 4, 4_096)


def get_model_limits(model: str) -> ModelLimits:
    """
    Get complete limits information for a model.

    Args:
        model: Model identifier

    Returns:
        ModelLimits dataclass with all constraints

    Example:
        >>> limits = get_model_limits("gpt-4o")
        >>> limits.max_output_tokens
        16384
        >>> limits.context_window
        128000
        >>> limits.supports_streaming
        True
    """
    limits = _lookup_model_limits(model)

    if limits is not None:
        return limits

    logger.warning(
        "model_limits_not_found",
        model=model,
        using_defaults=True,
    )
    return DEFAULT_MODEL_LIMITS


def list_supported_models() -> dict[str, list[str]]:
    """
    List all models with defined limits, grouped by provider.

    Returns:
        Dictionary mapping provider name to list of model names

    Example:
        >>> models = list_supported_models()
        >>> models["openai"]
        ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', ...]
    """
    return {
        "openai": list(OPENAI_MODELS.keys()),
        "anthropic": list(ANTHROPIC_MODELS.keys()),
        "gemini": list(GEMINI_MODELS.keys()),
        "databricks": list(DATABRICKS_MODELS.keys()),
    }

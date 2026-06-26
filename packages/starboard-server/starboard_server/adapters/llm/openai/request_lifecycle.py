# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Request lifecycle management for OpenAI API calls.

Handles request parameter building, error handling, structured logging,
cost calculation, usage normalization, and phase-based model/temperature
selection.
"""

from __future__ import annotations

from typing import Any

from openai import (
    APIError,
    APITimeoutError,
    RateLimitError,
)
from opentelemetry import trace as otel_trace

from starboard_server.adapters.llm.openai.tokens import TokenBudget
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

# Approximate token pricing per model family (USD per 1K tokens).
INPUT_PRICE_PER_1K: dict[str, float] = {
    "gpt-4o": 0.0025,
    "gpt-4o-mini": 0.00015,
    "gpt-4-turbo": 0.01,
    "gpt-4": 0.03,
    "gpt-3.5-turbo": 0.0005,
    "gpt-5": 0.015,
    "o1": 0.015,
    "o3": 0.01,
}
OUTPUT_PRICE_PER_1K: dict[str, float] = {
    "gpt-4o": 0.01,
    "gpt-4o-mini": 0.0006,
    "gpt-4-turbo": 0.03,
    "gpt-4": 0.06,
    "gpt-3.5-turbo": 0.0015,
    "gpt-5": 0.06,
    "o1": 0.06,
    "o3": 0.04,
}
DEFAULT_INPUT_PRICE_PER_1K: float = 0.01
DEFAULT_OUTPUT_PRICE_PER_1K: float = 0.03


def get_current_span_id() -> str | None:
    """Return the current OpenTelemetry span ID as a hex string, or None."""
    try:
        span = otel_trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.span_id:
            return format(ctx.span_id, "016x")
    except Exception:  # noqa: BLE001 - LLM adapter boundary
        pass
    return None


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for an LLM call based on token counts and model.

    Args:
        model: Model identifier
        input_tokens: Number of prompt/input tokens
        output_tokens: Number of completion/output tokens

    Returns:
        Estimated cost in USD
    """
    model_lower = model.lower()
    input_price = DEFAULT_INPUT_PRICE_PER_1K
    output_price = DEFAULT_OUTPUT_PRICE_PER_1K
    for prefix, price in INPUT_PRICE_PER_1K.items():
        if prefix in model_lower:
            input_price = price
            output_price = OUTPUT_PRICE_PER_1K.get(prefix, DEFAULT_OUTPUT_PRICE_PER_1K)
            break
    return (input_tokens * input_price + output_tokens * output_price) / 1000.0


def log_llm_call(
    call_type: str,
    trace_id: str,
    model: str,
    temperature: float,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    phase: str | None = None,
    validated: bool = False,
    span_id: str | None = None,
    prompt_version: str | None = None,
    seed: int | None = None,
) -> None:
    """Log structured data for LLM API calls.

    Args:
        call_type: Type of call (text, json, text_stream, json_stream)
        trace_id: Request correlation ID
        model: Model used for the call
        temperature: Temperature used
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        latency_ms: Call latency in milliseconds
        phase: Optional phase name
        validated: Whether output was Pydantic validated
        span_id: Optional distributed tracing span ID
        prompt_version: Optional version string of the prompt template used
        seed: Optional seed value for deterministic output
    """
    cost_usd = compute_cost_usd(model, input_tokens, output_tokens)
    log_data: dict[str, object] = {
        "trace_id": trace_id,
        "model": model,
        "temperature": temperature,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
    }

    if span_id is not None:
        log_data["span_id"] = span_id
    if prompt_version is not None:
        log_data["prompt_version"] = prompt_version
    if phase:
        log_data["phase"] = phase
    if validated:
        log_data["validated"] = validated
    if seed is not None:
        log_data["seed"] = seed

    logger.info(f"llm_{call_type}_completed", **log_data)


def get_model_for_phase(
    phase: str | None,
    default_model: str,
    planning_model: str | None,
    judge_model: str | None,
    synth_model: str | None,
) -> str:
    """Get appropriate model based on phase.

    Maps phase to core category using TokenBudget.map_phase().

    Args:
        phase: Operation phase
        default_model: Default model to use
        planning_model: Model for planning phases
        judge_model: Model for critic/judge phases
        synth_model: Model for synthesis phases

    Returns:
        Model name to use for this phase
    """
    if not phase:
        return default_model

    core_phase = TokenBudget.map_phase(phase)

    match core_phase:
        case "planning":
            return planning_model or default_model
        case "critic":
            return judge_model or default_model
        case "synth":
            return synth_model or default_model
        case "analysis":
            return default_model
        case _:
            return default_model


def get_temperature_for_phase(
    phase: str | None,
    default_temperature: float,
    planning_temperature: float | None,
    judge_temperature: float | None,
    synth_temperature: float | None,
) -> float:
    """Get appropriate temperature based on phase.

    Maps phase to core category using TokenBudget.map_phase().

    Args:
        phase: Operation phase
        default_temperature: Default temperature to use
        planning_temperature: Temperature for planning phases
        judge_temperature: Temperature for critic/judge phases
        synth_temperature: Temperature for synthesis phases

    Returns:
        Temperature to use for this phase
    """
    if not phase:
        return default_temperature

    core_phase = TokenBudget.map_phase(phase)

    match core_phase:
        case "planning":
            return planning_temperature or default_temperature
        case "critic":
            return judge_temperature or default_temperature
        case "synth":
            return synth_temperature or default_temperature
        case "analysis":
            return default_temperature
        case _:
            return default_temperature


def normalize_usage(usage: Any) -> dict[str, int]:
    """Normalize token usage from different model providers.

    Handles multiple provider formats:
    - OpenAI: prompt_tokens, completion_tokens, total_tokens
    - Anthropic/Claude: input_tokens, output_tokens

    Args:
        usage: Usage object from API response

    Returns:
        Normalized dict with prompt_tokens, completion_tokens, total_tokens
    """
    if not usage:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    if hasattr(usage, "model_dump"):
        try:
            usage_dict = usage.model_dump(
                exclude_none=True, exclude_defaults=True, exclude_unset=True
            )
        except Exception:  # noqa: BLE001 - LLM adapter boundary
            usage_dict = {}
    elif isinstance(usage, dict):
        usage_dict = usage
    else:
        usage_dict = {}

    prompt_tokens = usage_dict.get("prompt_tokens") or getattr(
        usage, "prompt_tokens", None
    )
    completion_tokens = usage_dict.get("completion_tokens") or getattr(
        usage, "completion_tokens", None
    )

    if prompt_tokens is None:
        prompt_tokens = usage_dict.get("input_tokens") or getattr(
            usage, "input_tokens", None
        )
    if completion_tokens is None:
        completion_tokens = usage_dict.get("output_tokens") or getattr(
            usage, "output_tokens", None
        )

    prompt_tokens = int(prompt_tokens) if prompt_tokens is not None else 0
    completion_tokens = int(completion_tokens) if completion_tokens is not None else 0

    total_tokens = (
        usage_dict.get("total_tokens")
        or getattr(usage, "total_tokens", None)
        or (prompt_tokens + completion_tokens)
    )
    total_tokens = int(total_tokens) if total_tokens is not None else 0

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def handle_api_error(
    error: Exception,
    trace_id: str,
    phase: str | None = None,
) -> None:
    """Handle and log API errors consistently.

    Args:
        error: The API error to handle
        trace_id: Request correlation ID
        phase: Optional phase name

    Raises:
        The original error after logging
    """
    if isinstance(error, RateLimitError):
        logger.warning(
            "llm_rate_limit", trace_id=trace_id, phase=phase, error=str(error)
        )
    elif isinstance(error, APITimeoutError):
        logger.warning("llm_timeout", trace_id=trace_id, phase=phase, error=str(error))
    elif isinstance(error, APIError):
        logger.error(
            "llm_api_error",
            trace_id=trace_id,
            phase=phase,
            error=str(error),
            status_code=getattr(error, "status_code", None),
        )
    raise error

# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""OpenAI LLM client for API interactions.

Thin facade that delegates to extracted sub-modules:
- schema_adapter: JSON schema flattening, strict mode, tool preparation
- request_lifecycle: Request building, logging, cost, usage normalization
- response_validator: JSON parsing, Pydantic validation
- streaming_handler: Streaming iteration, chunk buffering, tool call accumulation
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any, override

import httpx
from openai import (
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from starboard.adapters.llm.base import BaseLLMClient
from starboard.adapters.llm.openai.request_lifecycle import (
    compute_cost_usd,
    get_current_span_id,
    get_model_for_phase,
    get_temperature_for_phase,
    log_llm_call,
    normalize_usage,
)
from starboard.adapters.llm.openai.response_validator import (
    parse_json_content,
    validate_with_pydantic,
)
from starboard.adapters.llm.openai.schema_adapter import (
    flatten_json_schema,
    is_gemini_model,
    is_gpt5_model,
    is_no_temperature_model,
    make_schema_strict,
    prepare_json_schema,
    prepare_tools_for_model,
    supports_structured_output,
)
from starboard.adapters.llm.openai.streaming_handler import (
    build_streaming_usage,
    yield_error_event,
)
from starboard.adapters.llm.openai.tokens import TokenBudget
from starboard.adapters.llm.types import LLMResponse, TokenUsage, ToolCall
from starboard.infra.core.config import EnvConfig
from starboard.infra.observability.logging import get_logger, get_request_id
from starboard.infra.observability.tracing import get_tracer
from starboard.infra.reliability.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
)
from starboard.infra.reliability.retry import retry_with_backoff

# Use structured logger
logger = get_logger(__name__)
_tracer = get_tracer("starboard.llm")

# Temperature constants for different call types
TEMPERATURE_STRUCTURAL = 0.2  # Planning, validation, schema generation
TEMPERATURE_ANALYTICAL = 0.4  # Analysis, recommendations
TEMPERATURE_CREATIVE = 0.7  # Report generation, explanations


def _prepend_schema_hint(
    messages: list[dict[str, Any]],
    json_schema_def: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Prepend a system message with the expected JSON schema.

    When ``response_format`` is unavailable, the LLM still needs to know
    what structure to produce.  This embeds the full JSON schema from the
    Pydantic model into the system prompt so the model can comply.
    """
    if json_schema_def is not None and "schema" in json_schema_def:
        schema_json = json.dumps(json_schema_def["schema"], indent=2)
        hint = (
            "Return ONLY valid JSON matching the following JSON Schema. "
            "Do not include any explanatory text before or after the JSON.\n\n"
            f"```json\n{schema_json}\n```"
        )
    else:
        hint = (
            "Return ONLY valid JSON for the requested structure. "
            "Do not include any explanatory text before or after the JSON."
        )
    return [{"role": "system", "content": hint}] + messages


class OpenAIProvider(BaseLLMClient):
    """OpenAI provider implementation for LLM interactions.

    This provider includes:
    - Circuit breaker protection against API failures
    - Structured logging with correlation IDs
    - Pydantic validation for type safety
    - Comprehensive error handling
    - Deterministic output via seed parameter
    """

    # Pricing tables (kept on class for backward compat)
    _INPUT_PRICE_PER_1K = {
        "gpt-4o": 0.0025,
        "gpt-4o-mini": 0.00015,
        "gpt-4-turbo": 0.01,
        "gpt-4": 0.03,
        "gpt-3.5-turbo": 0.0005,
        "gpt-5": 0.015,
        "o1": 0.015,
        "o3": 0.01,
    }
    _OUTPUT_PRICE_PER_1K = {
        "gpt-4o": 0.01,
        "gpt-4o-mini": 0.0006,
        "gpt-4-turbo": 0.03,
        "gpt-4": 0.06,
        "gpt-3.5-turbo": 0.0015,
        "gpt-5": 0.06,
        "o1": 0.06,
        "o3": 0.04,
    }
    _DEFAULT_INPUT_PRICE_PER_1K: float = 0.01
    _DEFAULT_OUTPUT_PRICE_PER_1K: float = 0.03

    def __init__(self, cfg: EnvConfig | None = None) -> None:
        """Initialize OpenAI provider.

        Args:
            cfg: Configuration containing OpenAI credentials and model

        Raises:
            ValueError: If OpenAI API key is missing
        """
        super().__init__()

        if cfg is None:
            cfg = EnvConfig.from_env()

        if not cfg.llm_api_key:
            raise ValueError("LLM_API_KEY is required.")

        self.cfg = cfg
        self.model = cfg.llm_model
        self.temperature = cfg.llm_temperature
        self.max_tokens = cfg.llm_max_tokens
        self.seed = cfg.llm_seed

        # Use None for base_url if empty string (defaults to OpenAI endpoint)
        base_url = cfg.llm_base_url if cfg.llm_base_url else None
        llm_timeout = httpx.Timeout(300.0, connect=30.0)
        self.async_client = AsyncOpenAI(
            api_key=cfg.llm_api_key,
            base_url=base_url,
            timeout=llm_timeout,
        )

        # Separate client for embeddings when embedding_base_url differs
        embedding_base_url = getattr(cfg, "embedding_base_url", "") or ""
        if embedding_base_url and embedding_base_url != (cfg.llm_base_url or ""):
            self._embedding_client = AsyncOpenAI(
                api_key=cfg.llm_api_key,
                base_url=embedding_base_url,
                timeout=httpx.Timeout(60.0, connect=15.0),
            )
        else:
            self._embedding_client = self.async_client

        # Circuit breaker for API resilience
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5, timeout_seconds=60, name="openai_api"
        )

    # ------------------------------------------------------------------
    # Delegate methods to extracted modules (preserve original signatures)
    # ------------------------------------------------------------------

    def _is_gemini_model(self, model: str) -> bool:
        return is_gemini_model(model)

    def _is_gpt5_model(self, model: str) -> bool:
        return is_gpt5_model(model)

    def _flatten_json_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        return flatten_json_schema(schema)

    def _prepare_tools_for_model(
        self, tools: list[dict[str, Any]], model: str
    ) -> list[dict[str, Any]]:
        return prepare_tools_for_model(tools, model)

    def _build_request_params(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        phase: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        call_model = model if model is not None else self._get_model_for_phase(phase)
        call_temperature = (
            temperature
            if temperature is not None
            else self._get_temperature_for_phase(phase)
        )

        # Provider constraint: GPT-5 models only support temperature=1.0
        if is_gpt5_model(call_model) and call_temperature != 1.0:
            logger.debug(
                "temperature_overridden_by_provider_constraint",
                model=call_model,
                requested_temperature=call_temperature,
                actual_temperature=1.0,
                reason="GPT-5 models only support temperature=1.0",
            )
            call_temperature = 1.0

        params: dict[str, Any] = {
            "model": call_model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": messages,
            "stream": stream,
        }

        # Provider constraint: Claude Opus 4+ rejects the temperature parameter entirely
        if is_no_temperature_model(call_model):
            logger.debug(
                "temperature_omitted_by_provider_constraint",
                model=call_model,
                reason="Claude Opus 4 does not support the temperature parameter",
            )
        else:
            params["temperature"] = call_temperature

        if self.seed is not None:
            params["seed"] = self.seed

        return params

    @staticmethod
    def _get_current_span_id() -> str | None:
        return get_current_span_id()

    def _compute_cost_usd(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        return compute_cost_usd(model, input_tokens, output_tokens)

    def _log_llm_call(
        self,
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
    ) -> None:
        log_llm_call(
            call_type=call_type,
            trace_id=trace_id,
            model=model,
            temperature=temperature,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            phase=phase,
            validated=validated,
            span_id=span_id,
            prompt_version=prompt_version,
            seed=self.seed,
        )

    def _get_model_for_phase(self, phase: str | None) -> str:
        return get_model_for_phase(
            phase=phase,
            default_model=self.model,
            planning_model=self.cfg.llm_planning_model,
            judge_model=self.cfg.llm_judge_model,
            synth_model=self.cfg.llm_synth_model,
        )

    def _get_temperature_for_phase(self, phase: str | None) -> float:
        return get_temperature_for_phase(
            phase=phase,
            default_temperature=self.temperature,
            planning_temperature=self.cfg.llm_planning_temperature,
            judge_temperature=self.cfg.llm_judge_temperature,
            synth_temperature=self.cfg.llm_synth_temperature,
        )

    def _normalize_usage(self, usage: Any) -> dict[str, int]:
        return normalize_usage(usage)

    def __collect_token_usage(self, usage: Any) -> None:
        """Collect and aggregate token usage from API response."""
        if not usage:
            return
        normalized = normalize_usage(usage)
        logger.debug("LLM USAGE: {normalized}")
        self.__aggregate_token_usage(normalized)

    def __aggregate_token_usage(self, usage: dict[str, Any]) -> None:
        if not usage:
            return
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                self.token_usage[key] = self.token_usage.get(key, 0) + int(value)

    @staticmethod
    def _make_schema_strict(schema: dict[str, Any]) -> dict[str, Any]:
        return make_schema_strict(schema)

    def _prepare_json_schema(
        self,
        schema: dict[str, Any] | type[BaseModel] | None,
        phase: str | None = None,
    ) -> tuple[dict[str, Any] | None, type[BaseModel] | None, bool]:
        return prepare_json_schema(schema, phase)

    def _parse_json_content(self, content: str, trace_id: str) -> dict[str, Any]:
        return parse_json_content(content, trace_id)

    def _validate_with_pydantic(
        self, data: dict[str, Any], model_class: type[BaseModel]
    ) -> dict[str, Any]:
        return validate_with_pydantic(data, model_class)

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    @override
    @retry_with_backoff(max_attempts=3, initial_delay=2.0, max_delay=60.0)
    async def text_response(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
        prompt_version: str | None = None,
    ) -> str:
        """Get a text response from the LLM.

        Args:
            messages: List of message dictionaries with role and content
            max_tokens: Optional maximum tokens for the response
            model: Optional model override
            temperature: Optional temperature override

        Returns:
            Response text from the LLM

        Raises:
            ValueError: If LLM returns empty response
            CircuitBreakerError: If circuit breaker is open
            RateLimitError: If API rate limit is exceeded
            APITimeoutError: If API request times out
        """
        trace_id = get_request_id()
        start_time = time.time()

        params = self._build_request_params(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )

        async def _make_request() -> str:
            try:
                resp = await self.async_client.chat.completions.create(**params)
                self.__collect_token_usage(resp.usage)

                normalized_usage = normalize_usage(resp.usage)

                latency_ms = (time.time() - start_time) * 1000
                self._log_llm_call(
                    call_type="text_call",
                    trace_id=trace_id,
                    model=params["model"],
                    temperature=params.get("temperature", 0.0),
                    input_tokens=normalized_usage["prompt_tokens"],
                    output_tokens=normalized_usage["completion_tokens"],
                    latency_ms=latency_ms,
                    span_id=get_current_span_id(),
                    prompt_version=prompt_version,
                )

                content = resp.choices[0].message.content
                if content is None:
                    raise ValueError("LLM returned empty response")

                return content

            except RateLimitError as e:
                logger.warning("llm_rate_limit", trace_id=trace_id, error=str(e))
                raise
            except APITimeoutError as e:
                logger.warning("llm_timeout", trace_id=trace_id, error=str(e))
                raise
            except APIError as e:
                logger.error(
                    "llm_api_error",
                    trace_id=trace_id,
                    error=str(e),
                    status_code=getattr(e, "status_code", None),
                )
                raise

        return await self.circuit_breaker.call(_make_request)

    @override
    async def text_response_stream(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
        prompt_version: str | None = None,
    ) -> AsyncIterator[str]:
        """Get a streaming text response from the LLM.

        Args:
            messages: List of message dictionaries with role and content
            max_tokens: Optional maximum tokens for the response
            model: Optional model override
            temperature: Optional temperature override

        Yields:
            Text chunks as they arrive from the LLM
        """
        trace_id = get_request_id()
        start_time = time.time()

        params = self._build_request_params(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        try:
            stream = await self.async_client.chat.completions.create(**params)

            input_tokens = 0
            output_tokens = 0
            chunk_count = 0

            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        chunk_count += 1
                        yield delta.content

                if hasattr(chunk, "usage") and chunk.usage:
                    self.__collect_token_usage(chunk.usage)
                    normalized_usage = normalize_usage(chunk.usage)
                    input_tokens = normalized_usage["prompt_tokens"]
                    output_tokens = normalized_usage["completion_tokens"]

            if chunk_count > 0:
                latency_ms = (time.time() - start_time) * 1000
                self._log_llm_call(
                    call_type="text_stream",
                    trace_id=trace_id,
                    model=params["model"],
                    temperature=params.get("temperature", 0.0),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    span_id=get_current_span_id(),
                    prompt_version=prompt_version,
                )
            else:
                raise ValueError("LLM returned empty streaming response")

        except RateLimitError as e:
            logger.warning("llm_rate_limit", trace_id=trace_id, error=str(e))
            raise
        except APITimeoutError as e:
            logger.warning("llm_timeout", trace_id=trace_id, error=str(e))
            raise
        except APIError as e:
            logger.error(
                "llm_api_error",
                trace_id=trace_id,
                error=str(e),
                status_code=getattr(e, "status_code", None),
            )
            raise

    @override
    @retry_with_backoff(max_attempts=3, initial_delay=2.0, max_delay=60.0)
    async def json_response(
        self,
        messages: list[dict[str, Any]],
        phase: str | None = None,
        schema: dict[str, Any] | type[BaseModel] | None = None,
        budget: TokenBudget | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
        prompt_version: str | None = None,
    ) -> dict[str, Any]:
        """Get JSON response with validation and error handling.

        Args:
            messages: List of message dictionaries
            phase: Phase name for budget tracking
            schema: Optional JSON schema dict or Pydantic model for validation
            budget: Optional token budget manager
            max_tokens: Maximum output tokens
            model: Optional model override
            temperature: Optional temperature override

        Returns:
            Parsed and validated JSON response dictionary
        """
        trace_id = get_request_id()
        start_time = time.time()

        json_schema_def, pydantic_model, is_pydantic = prepare_json_schema(
            schema, phase
        )

        if phase and budget:
            messages = budget.ensure_room(phase, messages)

        async def _make_json_request() -> dict[str, Any]:
            nonlocal start_time
            actual_usage = None

            try:
                if not isinstance(messages, list):
                    logger.error(
                        "invalid_messages_type",
                        trace_id=trace_id,
                        phase=phase,
                        messages_type=str(type(messages)),
                    )
                    raise ValueError(f"messages must be a list, got {type(messages)}")

                for idx, msg in enumerate(messages):
                    if not isinstance(msg, dict):
                        logger.error(
                            "invalid_message_item_type",
                            trace_id=trace_id,
                            phase=phase,
                            index=idx,
                            item_type=str(type(msg)),
                        )
                        raise ValueError(
                            f"Message at index {idx} must be a dict, got {type(msg)}"
                        )

                    if "role" not in msg or "content" not in msg:
                        logger.error(
                            "missing_message_fields",
                            trace_id=trace_id,
                            phase=phase,
                            index=idx,
                            message_keys=list(msg.keys()),
                        )
                        raise ValueError(
                            f"Message at index {idx} missing 'role' or 'content': {list(msg.keys())}"
                        )

                    if not isinstance(msg["content"], str):
                        logger.warning(
                            "non_string_content",
                            trace_id=trace_id,
                            phase=phase,
                            index=idx,
                            content_type=str(type(msg["content"])),
                            converting=True,
                        )
                        messages[idx] = {**msg, "content": str(msg["content"])}

                params = self._build_request_params(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    phase=phase,
                    stream=False,
                )

                use_schema = (
                    json_schema_def is not None
                    and supports_structured_output(params["model"])
                )

                if use_schema:
                    params["response_format"] = {
                        "type": "json_schema",
                        "json_schema": json_schema_def,
                    }
                else:
                    params["messages"] = _prepend_schema_hint(
                        list(params["messages"]), json_schema_def
                    )

                resp = await self.async_client.chat.completions.create(**params)

                if resp.usage:
                    logger.debug(
                        "api_token_usage",
                        phase=phase,
                        prompt_tokens=getattr(resp.usage, "prompt_tokens", 0),
                        completion_tokens=getattr(resp.usage, "completion_tokens", 0),
                        total_tokens=getattr(resp.usage, "total_tokens", 0),
                    )

                self.__collect_token_usage(resp.usage)
                actual_usage = resp.usage

                message = resp.choices[0].message
                if hasattr(message, "refusal") and message.refusal:
                    logger.error(
                        "llm_refusal",
                        trace_id=trace_id,
                        refusal=message.refusal,
                        model=params.get("model"),
                        phase=phase,
                    )
                    return {
                        "error": "llm_refused",
                        "raw": f"Refusal: {message.refusal}",
                    }

                content = message.content
                if content is None or content == "":
                    logger.error(
                        "llm_empty_content",
                        trace_id=trace_id,
                        finish_reason=resp.choices[0].finish_reason,
                        model=params.get("model"),
                        phase=phase,
                        has_response_format=("response_format" in params),
                        response_format_type=(
                            params.get("response_format", {}).get("type")
                            if "response_format" in params
                            else None
                        ),
                    )
                    return {
                        "error": "llm_empty_content",
                        "raw": f"Finish reason: {resp.choices[0].finish_reason}",
                    }

                result = parse_json_content(content, trace_id)

                if is_pydantic and pydantic_model and "error" not in result:
                    result = validate_with_pydantic(result, pydantic_model)

                normalized_usage = (
                    normalize_usage(actual_usage) if actual_usage else None
                )

                latency_ms = (time.time() - start_time) * 1000
                if normalized_usage:
                    self._log_llm_call(
                        call_type="json_call",
                        trace_id=trace_id,
                        model=params["model"],
                        temperature=params.get("temperature", 0.0),
                        input_tokens=normalized_usage["prompt_tokens"],
                        output_tokens=normalized_usage["completion_tokens"],
                        latency_ms=latency_ms,
                        phase=phase,
                        validated=is_pydantic,
                        span_id=get_current_span_id(),
                        prompt_version=prompt_version,
                    )

                if budget and normalized_usage and phase:
                    try:
                        budget.charge(
                            phase,
                            messages,
                            result,
                            prompt_tokens=normalized_usage["prompt_tokens"],
                            completion_tokens=normalized_usage["completion_tokens"],
                        )
                    except Exception as e:  # noqa: BLE001 - LLM adapter boundary
                        logger.warning(
                            "budget_charge_failed",
                            trace_id=trace_id,
                            phase=phase,
                            error=str(e),
                        )

                return result

            except RateLimitError as e:
                logger.warning(
                    "llm_rate_limit", trace_id=trace_id, phase=phase, error=str(e)
                )
                raise
            except APITimeoutError as e:
                logger.warning(
                    "llm_timeout", trace_id=trace_id, phase=phase, error=str(e)
                )
                raise
            except APIError as e:
                status_code = getattr(e, "status_code", None)
                error_str = str(e)
                logger.error(
                    "llm_api_error",
                    trace_id=trace_id,
                    phase=phase,
                    error=error_str,
                    status_code=status_code,
                )
                if status_code == 400:
                    return {"error": "invalid_request", "raw": error_str}
                raise
            except ValidationError:
                raise

        return await self.circuit_breaker.call(_make_json_request)

    @override
    async def json_response_stream(
        self,
        messages: list[dict[str, Any]],
        phase: str | None = None,
        schema: dict[str, Any] | type[BaseModel] | None = None,
        budget: TokenBudget | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
        prompt_version: str | None = None,
    ) -> AsyncIterator[str]:
        """Get a streaming JSON response from the LLM.

        Args:
            messages: List of message dictionaries
            phase: Phase name for budget tracking
            schema: Optional JSON schema dict or Pydantic model for validation
            budget: Optional token budget manager
            max_tokens: Maximum output tokens
            model: Optional model override
            temperature: Optional temperature override

        Yields:
            JSON content chunks as they arrive from the LLM
        """
        trace_id = get_request_id()
        start_time = time.time()

        json_schema_def, pydantic_model, is_pydantic = prepare_json_schema(
            schema, phase
        )

        if phase and budget:
            messages = budget.ensure_room(phase, messages)

        actual_usage = None
        accumulated_content = ""
        chunk_count = 0

        try:
            params = self._build_request_params(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                phase=phase,
                stream=True,
            )

            use_schema = (
                json_schema_def is not None
                and supports_structured_output(params["model"])
            )

            if use_schema:
                params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": json_schema_def,
                }
            else:
                params["messages"] = _prepend_schema_hint(
                    list(params["messages"]), json_schema_def
                )

            stream = await self.async_client.chat.completions.create(**params)

            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        chunk_count += 1
                        accumulated_content += delta.content
                        yield delta.content

                if hasattr(chunk, "usage") and chunk.usage:
                    self.__collect_token_usage(chunk.usage)
                    actual_usage = chunk.usage

            if chunk_count > 0:
                latency_ms = (time.time() - start_time) * 1000

                normalized_usage = (
                    normalize_usage(actual_usage) if actual_usage else None
                )
                input_tokens = (
                    normalized_usage["prompt_tokens"] if normalized_usage else 0
                )
                output_tokens = (
                    normalized_usage["completion_tokens"] if normalized_usage else 0
                )

                self._log_llm_call(
                    call_type="json_stream",
                    trace_id=trace_id,
                    model=params["model"],
                    temperature=params.get("temperature", 0.0),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    phase=phase,
                    validated=False,
                    span_id=get_current_span_id(),
                    prompt_version=prompt_version,
                )

                if budget and normalized_usage and phase:
                    try:
                        result = parse_json_content(accumulated_content, trace_id)
                        budget.charge(
                            phase,
                            messages,
                            result,
                            prompt_tokens=normalized_usage["prompt_tokens"],
                            completion_tokens=normalized_usage["completion_tokens"],
                        )
                    except Exception as e:  # noqa: BLE001 - LLM adapter boundary
                        logger.warning(
                            "budget_charge_failed",
                            trace_id=trace_id,
                            phase=phase,
                            error=str(e),
                        )
            else:
                raise ValueError("LLM returned empty streaming response")

        except RateLimitError as e:
            logger.warning(
                "llm_rate_limit", trace_id=trace_id, phase=phase, error=str(e)
            )
            raise
        except APITimeoutError as e:
            logger.warning("llm_timeout", trace_id=trace_id, phase=phase, error=str(e))
            raise
        except APIError as e:
            status_code = getattr(e, "status_code", None)
            error_str = str(e)
            logger.error(
                "llm_api_error",
                trace_id=trace_id,
                phase=phase,
                error=error_str,
                status_code=status_code,
            )
            raise
        except ValidationError:
            raise

    @override
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts using the configured model.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        model = self.cfg.embedding_model or "databricks-bge-large-en"
        response = await self._embedding_client.embeddings.create(
            model=model, input=texts
        )
        return [data.embedding for data in response.data]

    @override
    @retry_with_backoff(max_attempts=3, initial_delay=2.0, max_delay=60.0)
    async def call_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
        prompt_version: str | None = None,
    ) -> Any:  # Returns LLMResponse
        """Call LLM with tool/function calling support.

        Args:
            messages: List of message dictionaries with role and content
            tools: List of tool definitions in OpenAI format
            max_tokens: Optional maximum tokens for the response
            model: Optional model override
            temperature: Optional temperature override

        Returns:
            LLMResponse object with content, tool_calls, usage, etc.
        """
        trace_id = get_request_id()
        start_time = time.time()

        params = self._build_request_params(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )

        if tools:
            params["tools"] = prepare_tools_for_model(tools, params["model"])
            params["tool_choice"] = "auto"

        async def _make_tool_call_request() -> Any:
            try:
                resp = await self.async_client.chat.completions.create(**params)
                self.__collect_token_usage(resp.usage)

                normalized = normalize_usage(resp.usage)

                message = resp.choices[0].message
                finish_reason = resp.choices[0].finish_reason

                content = message.content

                tool_calls_list = []
                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tc in message.tool_calls:
                        tool_calls_list.append(
                            ToolCall(
                                id=tc.id,
                                name=tc.function.name,
                                arguments=tc.function.arguments,
                            )
                        )

                usage = TokenUsage(
                    prompt_tokens=normalized["prompt_tokens"],
                    completion_tokens=normalized["completion_tokens"],
                    total_tokens=normalized["total_tokens"],
                )

                latency_ms = (time.time() - start_time) * 1000
                self._log_llm_call(
                    call_type="tool_call",
                    trace_id=trace_id,
                    model=params["model"],
                    temperature=params.get("temperature", 0.0),
                    input_tokens=normalized["prompt_tokens"],
                    output_tokens=normalized["completion_tokens"],
                    latency_ms=latency_ms,
                    span_id=get_current_span_id(),
                    prompt_version=prompt_version,
                )

                response = LLMResponse(
                    content=content,
                    tool_calls=tuple(tool_calls_list),
                    usage=usage,
                    finish_reason=finish_reason,
                    model=params["model"],
                )

                logger.debug(
                    "llm_tool_call_completed",
                    trace_id=trace_id,
                    has_content=response.has_content(),
                    tool_call_count=len(tool_calls_list),
                    finish_reason=finish_reason,
                )

                return response

            except RateLimitError as e:
                logger.warning("llm_rate_limit", trace_id=trace_id, error=str(e))
                raise
            except APITimeoutError as e:
                logger.warning("llm_timeout", trace_id=trace_id, error=str(e))
                raise
            except APIError as e:
                logger.error(
                    "llm_api_error",
                    trace_id=trace_id,
                    error=str(e),
                    status_code=getattr(e, "status_code", None),
                )
                raise

        return await self.circuit_breaker.call(_make_tool_call_request)

    @override
    async def call_with_tools_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
        prompt_version: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Call LLM with tool/function calling support (streaming mode).

        Implements smart buffering:
        - Text tokens: Yielded immediately for real-time display
        - Tool calls: Buffered until complete, then yielded as full calls

        Args:
            messages: List of message dictionaries with role and content
            tools: List of tool definitions in OpenAI format
            max_tokens: Optional maximum tokens for the response
            model: Optional model override
            temperature: Optional temperature override

        Yields:
            Streaming event dicts with type, content, tool_calls, or usage
        """
        trace_id = get_request_id()
        start_time = time.time()
        llm_span = _tracer.start_span(
            "llm.call",
            attributes={
                "llm.model": model or self.model,
                "llm.temperature": temperature or self.temperature,
                "llm.stream": True,
            },
        )

        params = self._build_request_params(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        if tools:
            params["tools"] = prepare_tools_for_model(tools, params["model"])
            params["tool_choice"] = "auto"

        async def _make_streaming_request() -> AsyncIterator[dict[str, Any]]:
            try:
                stream = await self.async_client.chat.completions.create(**params)

                tool_calls_buffer: dict[int, dict[str, Any]] = {}
                finish_reason = None
                total_tokens_estimate = 0

                async for chunk in stream:
                    if not chunk.choices or len(chunk.choices) == 0:
                        continue

                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason or finish_reason

                    if hasattr(delta, "content") and delta.content:
                        total_tokens_estimate += 1
                        yield {
                            "type": "content_delta",
                            "content": delta.content,
                            "finish_reason": finish_reason,
                        }

                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index

                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "name": "",
                                    "arguments": "",
                                }

                            if hasattr(tc_delta, "id") and tc_delta.id:
                                tool_calls_buffer[idx]["id"] = tc_delta.id
                            if hasattr(tc_delta, "function"):
                                if (
                                    hasattr(tc_delta.function, "name")
                                    and tc_delta.function.name
                                ):
                                    tool_calls_buffer[idx]["name"] = (
                                        tc_delta.function.name
                                    )
                                if (
                                    hasattr(tc_delta.function, "arguments")
                                    and tc_delta.function.arguments
                                ):
                                    tool_calls_buffer[idx]["arguments"] += (
                                        tc_delta.function.arguments
                                    )

                if tool_calls_buffer:
                    sorted_calls = [
                        {
                            "id": call["id"],
                            "name": call["name"],
                            "arguments": call["arguments"],
                        }
                        for _, call in sorted(tool_calls_buffer.items())
                    ]
                    yield {
                        "type": "tool_calls_delta",
                        "tool_calls": sorted_calls,
                        "finish_reason": finish_reason,
                    }

                usage_data = build_streaming_usage(
                    stream,
                    messages,
                    total_tokens_estimate,
                    self.__collect_token_usage,
                )

                yield {
                    "type": "usage",
                    "usage": usage_data,
                    "finish_reason": finish_reason,
                }

                latency_ms = (time.time() - start_time) * 1000
                self._log_llm_call(
                    call_type="tool_call_stream",
                    trace_id=trace_id,
                    model=params["model"],
                    temperature=params.get("temperature", 0.0),
                    input_tokens=usage_data["prompt_tokens"],
                    output_tokens=usage_data["completion_tokens"],
                    latency_ms=latency_ms,
                    span_id=get_current_span_id(),
                    prompt_version=prompt_version,
                )

                logger.debug(
                    "llm_streaming_call_completed",
                    trace_id=trace_id,
                    tool_call_count=len(tool_calls_buffer),
                    finish_reason=finish_reason,
                    total_tokens=usage_data["total_tokens"],
                )

            except RateLimitError as e:
                logger.warning("llm_stream_rate_limit", trace_id=trace_id, error=str(e))
                yield yield_error_event(e)
                raise
            except APITimeoutError as e:
                logger.warning("llm_stream_timeout", trace_id=trace_id, error=str(e))
                yield yield_error_event(e)
                raise
            except APIError as e:
                logger.error(
                    "llm_stream_api_error",
                    trace_id=trace_id,
                    error=str(e),
                    status_code=e.status_code if hasattr(e, "status_code") else None,
                )
                yield yield_error_event(e)
                raise
            except (
                httpx.RemoteProtocolError,
                httpx.ReadTimeout,
                httpx.ConnectTimeout,
            ) as e:
                logger.error(
                    "llm_stream_network_error",
                    trace_id=trace_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    message="Network connection interrupted during streaming. This is typically a transient error.",
                )
                yield yield_error_event(e)
                raise
            except Exception as e:  # noqa: BLE001 - LLM adapter boundary
                logger.error(
                    "llm_stream_unexpected_error",
                    trace_id=trace_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
                yield yield_error_event(e)
                raise

        try:
            async for chunk in _make_streaming_request():
                yield chunk
            llm_span.set_attribute("llm.latency_ms", (time.time() - start_time) * 1000)
            llm_span.end()
        except CircuitBreakerError:
            logger.error("circuit_breaker_open_streaming", trace_id=trace_id)
            llm_span.record_exception(CircuitBreakerError())
            llm_span.end()
            yield {
                "type": "error",
                "error_type": "CircuitBreakerError",
                "error_message": "Circuit breaker is open due to repeated failures",
            }
        except Exception:  # noqa: BLE001 - LLM adapter boundary
            llm_span.end()
            raise

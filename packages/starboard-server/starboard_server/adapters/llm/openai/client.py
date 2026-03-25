"""OpenAI LLM client for API interactions."""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any, cast, override

import httpx
from openai import (
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from opentelemetry import trace as otel_trace
from pydantic import BaseModel, ValidationError

from starboard_server.adapters.llm.base import BaseLLMClient
from starboard_server.adapters.llm.openai.tokens import TokenBudget
from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.observability.logging import get_logger, get_request_id
from starboard_server.infra.observability.tracing import get_tracer
from starboard_server.infra.reliability.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
)
from starboard_server.infra.reliability.retry import retry_with_backoff
from starboard_server.infra.serialization import json_loads

# Use structured logger
logger = get_logger(__name__)
_tracer = get_tracer("starboard.llm")

# Temperature constants for different call types
TEMPERATURE_STRUCTURAL = 0.2  # Planning, validation, schema generation
TEMPERATURE_ANALYTICAL = 0.4  # Analysis, recommendations
TEMPERATURE_CREATIVE = 0.7  # Report generation, explanations


class OpenAIProvider(BaseLLMClient):
    """OpenAI provider implementation for LLM interactions.


    This provider includes:
    - Circuit breaker protection against API failures
    - Structured logging with correlation IDs
    - Pydantic validation for type safety
    - Comprehensive error handling
    - Deterministic output via seed parameter
    """

    def __init__(self, cfg: EnvConfig | None = None) -> None:
        """
        Initialize OpenAI provider.

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

    def _is_gemini_model(self, model: str) -> bool:
        """
        Check if a model is a Google Gemini model.

        Gemini models have specific limitations on JSON Schema support:
        - No support for $defs
        - No support for $ref
        - Schemas must be fully inlined

        Args:
            model: Model identifier

        Returns:
            True if this is a Gemini model
        """
        model_lower = model.lower()
        return "gemini" in model_lower or "google" in model_lower

    def _is_gpt5_model(self, model: str) -> bool:
        """
        Check if a model is a GPT-5 variant.

        GPT-5 models have provider constraints:
        - Only support temperature=1.0
        - Other temperature values are not allowed

        Args:
            model: Model identifier

        Returns:
            True if this is a GPT-5 model variant
        """
        model_lower = model.lower()
        # Match gpt-5, gpt-5-turbo, gpt-5-mini, databricks-gpt-5, etc.
        return "gpt-5" in model_lower or "gpt5" in model_lower

    def _flatten_json_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """
        Flatten a JSON schema by resolving $ref and inlining $defs.

        Google Gemini models don't support JSON Schema $defs or $ref,
        so we need to flatten these into inline definitions.

        Args:
            schema: JSON schema dictionary (potentially with $defs and $ref)

        Returns:
            Flattened schema with all references resolved
        """
        # If no $defs, return as-is
        if "$defs" not in schema:
            return schema

        defs = schema.get("$defs", {})

        def resolve_refs(obj: Any) -> Any:
            """Recursively resolve $ref in nested structures."""
            if isinstance(obj, dict):
                # If this object has a $ref, replace it with the definition
                if "$ref" in obj:
                    ref_path = obj["$ref"]
                    # Handle #/$defs/SomeName format
                    if ref_path.startswith("#/$defs/"):
                        def_name = ref_path.split("/")[-1]
                        if def_name in defs:
                            # Recursively resolve the definition itself
                            resolved = resolve_refs(defs[def_name].copy())
                            # Preserve any additional properties from the $ref object
                            for key, value in obj.items():
                                if key != "$ref":
                                    resolved[key] = value
                            return resolved
                    return obj  # Can't resolve, return as-is
                else:
                    # Recursively process all values
                    return {k: resolve_refs(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [resolve_refs(item) for item in obj]
            else:
                return obj

        # Resolve all references in the schema
        flattened = resolve_refs(schema)

        # Remove $defs from the flattened schema
        if isinstance(flattened, dict) and "$defs" in flattened:
            flattened = {k: v for k, v in flattened.items() if k != "$defs"}

        return flattened

    def _prepare_tools_for_model(
        self, tools: list[dict[str, Any]], model: str
    ) -> list[dict[str, Any]]:
        """
        Prepare tool definitions for a specific model.

        Different LLM providers have different requirements for tool schemas:
        - OpenAI/Claude: Support full JSON Schema with $defs and $ref
        - Gemini: Require flattened schemas without $defs or $ref

        Args:
            tools: List of tool definitions in OpenAI format
            model: Target model identifier

        Returns:
            Tool definitions adapted for the target model
        """
        # If not Gemini, return tools as-is
        if not self._is_gemini_model(model):
            return tools

        # For Gemini, flatten all tool schemas
        logger.debug(
            "gemini_schema_flattening",
            model=model,
            tool_count=len(tools),
            tool_names=[t.get("function", {}).get("name", "unknown") for t in tools],
        )
        flattened_tools = []
        for tool in tools:
            tool_copy = tool.copy()
            if "function" in tool_copy and "parameters" in tool_copy["function"]:
                parameters = tool_copy["function"]["parameters"]
                has_refs = "$defs" in parameters or "$ref" in str(parameters)
                flattened = self._flatten_json_schema(parameters)
                tool_copy["function"]["parameters"] = flattened
                if has_refs:
                    logger.debug(
                        "schema_flattened",
                        tool_name=tool_copy["function"].get("name", "unknown"),
                        had_refs=True,
                    )
            flattened_tools.append(tool_copy)

        return flattened_tools

    def _build_request_params(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        phase: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """
        Build common request parameters for API calls.

        Args:
            messages: Message list for the conversation
            model: Optional model override
            temperature: Optional temperature override
            max_tokens: Optional max tokens override
            phase: Optional phase for phase-specific defaults
            stream: Whether this is a streaming request

        Returns:
            Dictionary of API request parameters
        """
        call_model = model if model is not None else self._get_model_for_phase(phase)
        call_temperature = (
            temperature
            if temperature is not None
            else self._get_temperature_for_phase(phase)
        )

        # Provider constraint: GPT-5 models only support temperature=1.0
        # Override temperature if using a GPT-5 variant
        if self._is_gpt5_model(call_model) and call_temperature != 1.0:
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
            "temperature": call_temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": messages,
            "stream": stream,
        }

        # Only add seed if configured (not all APIs support it)
        if self.seed is not None:
            params["seed"] = self.seed

        return params

    # Approximate token pricing per model family (USD per 1K tokens).
    # These are conservative estimates; override via subclass if needed.
    _INPUT_PRICE_PER_1K: dict[str, float] = {
        "gpt-4o": 0.0025,
        "gpt-4o-mini": 0.00015,
        "gpt-4-turbo": 0.01,
        "gpt-4": 0.03,
        "gpt-3.5-turbo": 0.0005,
        "gpt-5": 0.015,
        "o1": 0.015,
        "o3": 0.01,
    }
    _OUTPUT_PRICE_PER_1K: dict[str, float] = {
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

    @staticmethod
    def _get_current_span_id() -> str | None:
        """Return the current OpenTelemetry span ID as a hex string, or None."""
        try:
            span = otel_trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.span_id:
                return format(ctx.span_id, "016x")
        except Exception:
            pass
        return None

    def _compute_cost_usd(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Estimate cost in USD for an LLM call based on token counts and model.

        Args:
            model: Model identifier
            input_tokens: Number of prompt/input tokens
            output_tokens: Number of completion/output tokens

        Returns:
            Estimated cost in USD
        """
        model_lower = model.lower()
        input_price = self._DEFAULT_INPUT_PRICE_PER_1K
        output_price = self._DEFAULT_OUTPUT_PRICE_PER_1K
        for prefix, price in self._INPUT_PRICE_PER_1K.items():
            if prefix in model_lower:
                input_price = price
                output_price = self._OUTPUT_PRICE_PER_1K.get(
                    prefix, self._DEFAULT_OUTPUT_PRICE_PER_1K
                )
                break
        return (input_tokens * input_price + output_tokens * output_price) / 1000.0

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
        """
        Log structured data for LLM API calls.

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
        """
        cost_usd = self._compute_cost_usd(model, input_tokens, output_tokens)
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
        if self.seed is not None:
            log_data["seed"] = self.seed

        logger.info(f"llm_{call_type}_completed", **log_data)

    def _get_model_for_phase(self, phase: str | None) -> str:
        """
        Get appropriate model based on phase.

        Maps phase to core category (planning, critic, analysis, synth) using
        TokenBudget.map_phase() and selects corresponding model.

        Args:
            phase: Operation phase (can be any variant like replanning, judge, etc.)

        Returns:
            Model name to use for this phase
        """
        if not phase:
            return self.model

        # Map to core category
        core_phase = TokenBudget.map_phase(phase)

        # Select model based on core category
        match core_phase:
            case "planning":
                return self.cfg.llm_planning_model or self.model
            case "critic":
                return self.cfg.llm_judge_model or self.model
            case "synth":
                return self.cfg.llm_synth_model or self.model
            case "analysis":
                return self.model  # Use default model for analysis
            case _:
                return self.model

    def _get_temperature_for_phase(self, phase: str | None) -> float:
        """
        Get appropriate temperature based on phase.

        Maps phase to core category (planning, critic, analysis, synth) using
        TokenBudget.map_phase() and selects corresponding temperature.

        Args:
            phase: Operation phase (can be any variant like replanning, judge, etc.)

        Returns:
            Temperature to use for this phase
        """
        if not phase:
            return self.temperature

        # Map to core category
        core_phase = TokenBudget.map_phase(phase)

        # Select temperature based on core category
        match core_phase:
            case "planning":
                return self.cfg.llm_planning_temperature or self.temperature
            case "critic":
                return self.cfg.llm_judge_temperature or self.temperature
            case "synth":
                return self.cfg.llm_synth_temperature or self.temperature
            case "analysis":
                return self.temperature  # Use default temperature for analysis
            case _:
                return self.temperature

    def _normalize_usage(self, usage: Any) -> dict[str, int]:
        """
        Normalize token usage from different model providers.

        Handles multiple provider formats:
        - OpenAI: prompt_tokens, completion_tokens, total_tokens
        - Anthropic/Claude: input_tokens, output_tokens
        - Others: Falls back gracefully

        Args:
            usage: Usage object from API response

        Returns:
            Normalized dict with prompt_tokens, completion_tokens, total_tokens
        """
        if not usage:
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # Try to extract as dict first
        if hasattr(usage, "model_dump"):
            try:
                usage_dict = usage.model_dump(
                    exclude_none=True, exclude_defaults=True, exclude_unset=True
                )
            except Exception:
                usage_dict = {}
        elif isinstance(usage, dict):
            usage_dict = usage
        else:
            usage_dict = {}

        # Extract tokens with provider-specific fallbacks
        # OpenAI format: prompt_tokens, completion_tokens
        prompt_tokens = usage_dict.get("prompt_tokens") or getattr(
            usage, "prompt_tokens", None
        )
        completion_tokens = usage_dict.get("completion_tokens") or getattr(
            usage, "completion_tokens", None
        )

        # Anthropic/Claude format: input_tokens, output_tokens
        if prompt_tokens is None:
            prompt_tokens = usage_dict.get("input_tokens") or getattr(
                usage, "input_tokens", None
            )
        if completion_tokens is None:
            completion_tokens = usage_dict.get("output_tokens") or getattr(
                usage, "output_tokens", None
            )

        # Convert to int, default to 0
        prompt_tokens = int(prompt_tokens) if prompt_tokens is not None else 0
        completion_tokens = (
            int(completion_tokens) if completion_tokens is not None else 0
        )

        # Calculate total
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

    def __collect_token_usage(self, usage: Any) -> None:
        """Collect and aggregate token usage from API response."""
        if not usage:
            return

        normalized = self._normalize_usage(usage)
        logger.debug("LLM USAGE: {normalized}")
        self.__aggregate_token_usage(normalized)

    def __aggregate_token_usage(self, usage: dict[str, Any]) -> None:
        if not usage:
            return

        for key, value in usage.items():
            # Only aggregate numeric values (skip nested dicts like prompt_tokens_details)
            if isinstance(value, (int, float)):
                self.token_usage[key] = self.token_usage.get(key, 0) + int(value)

    @override
    @retry_with_backoff(max_attempts=3, initial_delay=2.0, max_delay=60.0)
    async def text_response(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """
        Get a text response from the LLM.

        Args:
            messages: List of message dictionaries with role and content
            max_tokens: Optional maximum tokens for the response
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

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

        # Build request parameters using helper
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

                # Normalize usage for multi-provider compatibility
                normalized_usage = self._normalize_usage(resp.usage)

                # Log successful call
                latency_ms = (time.time() - start_time) * 1000
                self._log_llm_call(
                    call_type="text_call",
                    trace_id=trace_id,
                    model=params["model"],
                    temperature=params["temperature"],
                    input_tokens=normalized_usage["prompt_tokens"],
                    output_tokens=normalized_usage["completion_tokens"],
                    latency_ms=latency_ms,
                    span_id=self._get_current_span_id(),
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
    ) -> AsyncIterator[str]:
        """
        Get a streaming text response from the LLM.

        Args:
            messages: List of message dictionaries with role and content
            max_tokens: Optional maximum tokens for the response
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Yields:
            Text chunks as they arrive from the LLM

        Raises:
            ValueError: If LLM returns empty response
            CircuitBreakerError: If circuit breaker is open
            RateLimitError: If API rate limit is exceeded
            APITimeoutError: If API request times out
        """
        trace_id = get_request_id()
        start_time = time.time()

        # Build request parameters using helper
        params = self._build_request_params(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        try:
            stream = await self.async_client.chat.completions.create(**params)

            # Track token usage for streaming
            input_tokens = 0
            output_tokens = 0
            chunk_count = 0

            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        chunk_count += 1
                        yield delta.content

                # Collect usage if available (usually in the last chunk)
                if hasattr(chunk, "usage") and chunk.usage:
                    self.__collect_token_usage(chunk.usage)
                    normalized_usage = self._normalize_usage(chunk.usage)
                    input_tokens = normalized_usage["prompt_tokens"]
                    output_tokens = normalized_usage["completion_tokens"]

            # Log successful streaming call
            if chunk_count > 0:
                latency_ms = (time.time() - start_time) * 1000
                self._log_llm_call(
                    call_type="text_stream",
                    trace_id=trace_id,
                    model=params["model"],
                    temperature=params["temperature"],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    span_id=self._get_current_span_id(),
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

    def _prepare_json_schema(
        self,
        schema: dict[str, Any] | type[BaseModel] | None,
        phase: str | None = None,
    ) -> tuple[dict[str, Any] | None, type[BaseModel] | None, bool]:
        """
        Prepare JSON schema for API request.

        Args:
            schema: Optional JSON schema dict or Pydantic model for validation
            phase: Phase name for schema naming

        Returns:
            Tuple of (json_schema_def, pydantic_model, is_pydantic)
            - json_schema_def: Formatted schema dict for API
            - pydantic_model: Pydantic model class if provided
            - is_pydantic: Whether schema is a Pydantic model
        """
        # Check if schema is a Pydantic model
        is_pydantic = (
            schema is not None
            and isinstance(schema, type)
            and issubclass(schema, BaseModel)
        )

        if is_pydantic:
            pydantic_model = cast(type[BaseModel], schema)
            schema_dict = pydantic_model.model_json_schema()
            schema_dict = self._make_schema_strict(schema_dict)
            schema_name = pydantic_model.__name__
            json_schema_def: dict[str, Any] = {
                "name": schema_name,
                "schema": schema_dict,
                "strict": True,
            }
            return json_schema_def, pydantic_model, True

        elif schema is not None:
            # At this point schema is a dict
            schema_dict_val = cast(dict[str, Any], schema)
            # Handle two formats:
            # 1. New format: {"name": "...", "schema": {...}, "strict": ...}
            # 2. Old format: {...schema dict...}
            if "name" in schema_dict_val and "schema" in schema_dict_val:
                # Already in new format - ensure strict is set if missing
                if "strict" not in schema_dict_val:
                    schema_dict_val = {**schema_dict_val, "strict": True}
                return schema_dict_val, None, False
            else:
                # Old format - wrap it with strict mode
                schema_name = phase or "response_schema"
                json_schema_def = {
                    "name": schema_name,
                    "schema": schema_dict_val,
                    "strict": True,
                }
                return json_schema_def, None, False

        return None, None, False

    @staticmethod
    def _make_schema_strict(schema: dict[str, Any]) -> dict[str, Any]:
        """Add ``additionalProperties: false`` to every object in a JSON schema.

        OpenAI structured-output and compatible endpoints reject schemas that
        omit this flag.  Pydantic's ``model_json_schema()`` does not emit it,
        so we patch it here.  Also inlines ``$defs`` references so the schema
        is fully self-contained.
        """

        def _patch(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(node, dict):
                return node

            # Resolve $ref first
            if "$ref" in node:
                ref_path = node["$ref"]  # e.g. "#/$defs/Evidence"
                ref_name = ref_path.rsplit("/", 1)[-1]
                if ref_name in defs:
                    resolved = _patch(defs[ref_name].copy(), defs)
                    extra = {k: v for k, v in node.items() if k != "$ref"}
                    resolved.update(extra)
                    return resolved
                return node

            result = dict(node)

            if result.get("type") == "object" or "properties" in result:
                result.setdefault("additionalProperties", False)

            # Recurse into properties and ensure all are required
            if "properties" in result:
                result["properties"] = {
                    k: _patch(v, defs) for k, v in result["properties"].items()
                }
                result["required"] = list(result["properties"].keys())

            # Recurse into array items
            if "items" in result:
                result["items"] = _patch(result["items"], defs)

            # anyOf / oneOf / allOf
            for combo_key in ("anyOf", "oneOf", "allOf"):
                if combo_key in result:
                    result[combo_key] = [_patch(v, defs) for v in result[combo_key]]

            return result

        defs = schema.get("$defs", schema.get("definitions", {}))
        patched = _patch(schema, defs)
        patched.pop("$defs", None)
        patched.pop("definitions", None)
        return patched

    def _parse_json_content(self, content: str, trace_id: str) -> dict[str, Any]:
        """
        Parse JSON content from LLM response with fallback extraction.

        Args:
            content: Raw content string from LLM
            trace_id: Request correlation ID for logging

        Returns:
            Parsed JSON dictionary or error dict if parsing fails
        """
        if not content:
            logger.error(
                "json_parse_failed_empty_content",
                trace_id=trace_id,
            )
            return {"error": "llm_parse_failed", "raw": ""}

        try:
            return json_loads(content)
        except json.JSONDecodeError as e:
            # Try to extract JSON from response (handle markdown code blocks, etc.)
            # First try to extract from markdown code fences: ```json\n{...}\n```
            fence_match = re.search(r"```(?:json)?\s*\n(\{[\s\S]*?\})\s*\n```", content)
            if fence_match:
                try:
                    return json_loads(fence_match.group(1))
                except json.JSONDecodeError:
                    pass  # Fall through to next attempt

            # Try to find any JSON object in the content
            match = re.search(r"\{[\s\S]*?\}", content)
            if match:
                try:
                    return json_loads(match.group(0))
                except json.JSONDecodeError:
                    logger.error(
                        "json_parse_failed_after_extraction",
                        trace_id=trace_id,
                        content_preview=content[:500] if content else None,
                        content_length=len(content),
                        parse_error=str(e),
                    )
                    return {"error": "llm_parse_failed", "raw": content}

            logger.error(
                "json_parse_failed_no_json_found",
                trace_id=trace_id,
                content_preview=content[:500] if content else None,
                content_length=len(content),
                parse_error=str(e),
            )
            return {"error": "llm_parse_failed", "raw": content}

    def _validate_with_pydantic(
        self, data: dict[str, Any], model_class: type[BaseModel]
    ) -> dict[str, Any]:
        """
        Validate LLM response with Pydantic model.

        Args:
            data: Raw dictionary from LLM
            model_class: Pydantic model class for validation

        Returns:
            Validated and cleaned dictionary

        Raises:
            ValidationError: If validation fails
        """
        try:
            validated = model_class.model_validate(data)
            return validated.model_dump()
        except ValidationError as e:
            logger.error(
                "pydantic_validation_failed",
                trace_id=get_request_id(),
                model=model_class.__name__,
                errors=str(e),
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
    ) -> dict[str, Any]:
        """
        Get JSON response with validation and error handling.

        Args:
            messages: List of message dictionaries
            phase: Phase name for budget tracking
            schema: Optional JSON schema dict or Pydantic model for validation
            budget: Optional token budget manager
            max_tokens: Maximum output tokens
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Returns:
            Parsed and validated JSON response dictionary

        Raises:
            ValidationError: If Pydantic validation fails
            CircuitBreakerError: If circuit breaker is open
            RateLimitError: If API rate limit is exceeded
            APITimeoutError: If API request times out
        """
        trace_id = get_request_id()
        start_time = time.time()

        # Prepare schema
        json_schema_def, pydantic_model, is_pydantic = self._prepare_json_schema(
            schema, phase
        )

        # Apply budget if provided
        if phase and budget:
            messages = budget.ensure_room(phase, messages)

        async def _make_json_request() -> dict[str, Any]:
            nonlocal start_time
            actual_usage = None

            try:
                # Validate messages format before sending
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

                    # Check required fields
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

                    # Ensure content is a string
                    if not isinstance(msg["content"], str):
                        logger.warning(
                            "non_string_content",
                            trace_id=trace_id,
                            phase=phase,
                            index=idx,
                            content_type=str(type(msg["content"])),
                            converting=True,
                        )
                        # Convert to string
                        messages[idx] = {**msg, "content": str(msg["content"])}

                # Build request - use system message if no schema provided
                if json_schema_def is None:
                    system_msg = {
                        "role": "system",
                        "content": "Return ONLY valid JSON for the requested structure. Do not include any explanatory text before or after the JSON.",
                    }
                    request_messages = [system_msg] + messages
                    params = self._build_request_params(
                        messages=request_messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        phase=phase,
                        stream=False,
                    )
                else:
                    # Use structured output with schema
                    params = self._build_request_params(
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        phase=phase,
                        stream=False,
                    )
                    params["response_format"] = {
                        "type": "json_schema",
                        "json_schema": json_schema_def,
                    }

                # Make async API call
                resp = await self.async_client.chat.completions.create(**params)

                # Log actual API token usage for verification
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

                # Check for refusal (structured outputs can be refused)
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

                # Parse JSON content
                result = self._parse_json_content(content, trace_id)

                # Validate with Pydantic if model provided
                if is_pydantic and pydantic_model and "error" not in result:
                    result = self._validate_with_pydantic(result, pydantic_model)

                # Normalize usage for multi-provider compatibility
                normalized_usage = (
                    self._normalize_usage(actual_usage) if actual_usage else None
                )

                # Log successful call
                latency_ms = (time.time() - start_time) * 1000
                if normalized_usage:
                    self._log_llm_call(
                        call_type="json_call",
                        trace_id=trace_id,
                        model=params["model"],
                        temperature=params["temperature"],
                        input_tokens=normalized_usage["prompt_tokens"],
                        output_tokens=normalized_usage["completion_tokens"],
                        latency_ms=latency_ms,
                        phase=phase,
                        validated=is_pydantic,
                        span_id=self._get_current_span_id(),
                    )

                # Charge budget if provided
                if budget and normalized_usage and phase:
                    try:
                        budget.charge(
                            phase,
                            messages,
                            result,
                            prompt_tokens=normalized_usage["prompt_tokens"],
                            completion_tokens=normalized_usage["completion_tokens"],
                        )
                    except Exception as e:
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
                logger.error(
                    "llm_api_error",
                    trace_id=trace_id,
                    phase=phase,
                    error=str(e),
                    status_code=status_code,
                )
                if status_code == 400:
                    # Bad request - may be moderation flag or invalid input
                    return {"error": "invalid_request", "raw": str(e)}
                raise
            except ValidationError:
                # Pydantic validation error - already logged in _validate_with_pydantic
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
    ) -> AsyncIterator[str]:
        """
        Get a streaming JSON response from the LLM.

        Args:
            messages: List of message dictionaries
            phase: Phase name for budget tracking
            schema: Optional JSON schema dict or Pydantic model for validation
            budget: Optional token budget manager
            max_tokens: Maximum output tokens
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Yields:
            JSON content chunks as they arrive from the LLM

        Note:
            - Chunks are raw text that when combined form valid JSON
            - Budget charging happens after streaming completes
            - Validation (if schema provided) must be done by caller after collecting all chunks
            - For real-time JSON parsing, consider using a streaming JSON parser
        """
        trace_id = get_request_id()
        start_time = time.time()

        # Prepare schema
        json_schema_def, pydantic_model, is_pydantic = self._prepare_json_schema(
            schema, phase
        )

        # Apply budget if provided
        if phase and budget:
            messages = budget.ensure_room(phase, messages)

        actual_usage = None
        accumulated_content = ""
        chunk_count = 0

        try:
            # Build request - use system message if no schema provided
            if json_schema_def is None:
                system_msg = {
                    "role": "system",
                    "content": "Return ONLY valid JSON for the requested structure. Do not include any explanatory text before or after the JSON.",
                }
                request_messages = [system_msg] + messages
                params = self._build_request_params(
                    messages=request_messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    phase=phase,
                    stream=True,
                )
            else:
                # Use structured output with schema
                params = self._build_request_params(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    phase=phase,
                    stream=True,
                )
                params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": json_schema_def,
                }

            # Make async streaming API call
            stream = await self.async_client.chat.completions.create(**params)

            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        chunk_count += 1
                        accumulated_content += delta.content
                        yield delta.content

                # Collect usage if available (usually in the last chunk)
                if hasattr(chunk, "usage") and chunk.usage:
                    self.__collect_token_usage(chunk.usage)
                    actual_usage = chunk.usage

            # Log successful streaming call
            if chunk_count > 0:
                latency_ms = (time.time() - start_time) * 1000

                # Normalize usage for multi-provider compatibility
                normalized_usage = (
                    self._normalize_usage(actual_usage) if actual_usage else None
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
                    temperature=params["temperature"],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    phase=phase,
                    validated=False,  # Validation must be done by caller
                    span_id=self._get_current_span_id(),
                )

                # Charge budget if provided (parse accumulated content for result)
                if budget and normalized_usage and phase:
                    try:
                        result = self._parse_json_content(accumulated_content, trace_id)
                        budget.charge(
                            phase,
                            messages,
                            result,
                            prompt_tokens=normalized_usage["prompt_tokens"],
                            completion_tokens=normalized_usage["completion_tokens"],
                        )
                    except Exception as e:
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
            logger.error(
                "llm_api_error",
                trace_id=trace_id,
                phase=phase,
                error=str(e),
                status_code=getattr(e, "status_code", None),
            )
            raise
        except ValidationError:
            # Pydantic validation error - already logged in _validate_with_pydantic
            raise

    @override
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for texts using the configured model.

        Uses a separate client when ``embedding_base_url`` is configured,
        allowing embeddings to target a different provider than chat.

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
    ) -> Any:  # Returns LLMResponse
        """
        Call LLM with tool/function calling support.

        This method enables the LLM to request tool executions as part of
        its response. The LLM can either return text content, request one
        or more tool calls, or both.

        Args:
            messages: List of message dictionaries with role and content
            tools: List of tool definitions in OpenAI format
            max_tokens: Optional maximum tokens for the response
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Returns:
            LLMResponse object with content, tool_calls, usage, etc.

        Raises:
            ValueError: If LLM returns invalid response
            CircuitBreakerError: If circuit breaker is open
            RateLimitError: If API rate limit is exceeded
            APITimeoutError: If API request times out
        """
        # Import here to avoid circular dependency
        from starboard_server.agents.output.llm_responses import (
            LLMResponse,
            TokenUsage,
            ToolCall,
        )

        trace_id = get_request_id()
        start_time = time.time()

        # Build request parameters
        params = self._build_request_params(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )

        # Add tools to request (adapt schema format for target model)
        if tools:
            params["tools"] = self._prepare_tools_for_model(tools, params["model"])
            # Let model choose whether to call tools
            params["tool_choice"] = "auto"

        async def _make_tool_call_request() -> Any:  # Returns LLMResponse
            try:
                resp = await self.async_client.chat.completions.create(**params)
                self.__collect_token_usage(resp.usage)

                # Normalize usage for multi-provider compatibility
                normalized_usage = self._normalize_usage(resp.usage)

                # Extract message from response
                message = resp.choices[0].message
                finish_reason = resp.choices[0].finish_reason

                # Extract content (may be None if only tool calls)
                content = message.content

                # Extract tool calls (may be None or empty)
                tool_calls_list = []
                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tc in message.tool_calls:
                        # OpenAI tool call structure:
                        # - id: str
                        # - type: "function"
                        # - function: {name: str, arguments: str (JSON)}
                        tool_calls_list.append(
                            ToolCall(
                                id=tc.id,
                                name=tc.function.name,
                                arguments=tc.function.arguments,
                            )
                        )

                # Create usage object
                usage = TokenUsage(
                    prompt_tokens=normalized_usage["prompt_tokens"],
                    completion_tokens=normalized_usage["completion_tokens"],
                    total_tokens=normalized_usage["total_tokens"],
                )

                # Log successful call
                latency_ms = (time.time() - start_time) * 1000
                self._log_llm_call(
                    call_type="tool_call",
                    trace_id=trace_id,
                    model=params["model"],
                    temperature=params["temperature"],
                    input_tokens=normalized_usage["prompt_tokens"],
                    output_tokens=normalized_usage["completion_tokens"],
                    latency_ms=latency_ms,
                )

                # Build response
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
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Call LLM with tool/function calling support (streaming mode).

        Implements smart buffering:
        - Text tokens: Yielded immediately for real-time display
        - Tool calls: Buffered until complete, then yielded as full calls

        Args:
            messages: List of message dictionaries with role and content
            tools: List of tool definitions in OpenAI format
            max_tokens: Optional maximum tokens for the response
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Yields:
            Streaming event dicts with type, content, tool_calls, or usage

        Raises:
            ValueError: If LLM returns invalid response
            CircuitBreakerError: If circuit breaker is open
            RateLimitError: If API rate limit is exceeded
            APITimeoutError: If API request times out
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

        # Build request parameters
        params = self._build_request_params(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,  # Enable streaming
        )

        # Add tools to request (adapt schema format for target model)
        if tools:
            params["tools"] = self._prepare_tools_for_model(tools, params["model"])
            # Let model choose whether to call tools or reason
            params["tool_choice"] = "auto"

        async def _make_streaming_request() -> AsyncIterator[dict[str, Any]]:
            try:
                # Call OpenAI streaming API (async)
                stream = await self.async_client.chat.completions.create(**params)

                # Smart buffering: track tool calls as they accumulate
                tool_calls_buffer: dict[int, dict[str, Any]] = {}
                finish_reason = None
                total_tokens_estimate = 0

                async for chunk in stream:
                    # Skip chunks with empty choices array (can happen during streaming)
                    if not chunk.choices or len(chunk.choices) == 0:
                        continue

                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason or finish_reason

                    # Handle content deltas (thinking/reasoning text)
                    if hasattr(delta, "content") and delta.content:
                        total_tokens_estimate += 1  # Rough estimate (1 token per delta)
                        yield {
                            "type": "content_delta",
                            "content": delta.content,
                            "finish_reason": finish_reason,
                        }

                    # Handle tool call deltas (buffered until complete)
                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index

                            # Initialize buffer for this tool call if needed
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "name": "",
                                    "arguments": "",
                                }

                            # Accumulate tool call data
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

                # Stream complete - yield buffered tool calls if any
                if tool_calls_buffer:
                    # Sort by index and yield complete tool calls
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

                # Get final usage from stream (if available)
                # Note: OpenAI streaming may not provide usage in all cases
                # We'll estimate if needed
                if hasattr(stream, "usage") and stream.usage:
                    usage_data = {
                        "prompt_tokens": stream.usage.prompt_tokens,
                        "completion_tokens": stream.usage.completion_tokens,
                        "total_tokens": stream.usage.total_tokens,
                    }
                    self.__collect_token_usage(stream.usage)
                else:
                    # Estimate usage (rough approximation)
                    prompt_tokens = (
                        sum(len(str(m.get("content", "")).split()) for m in messages)
                        * 1.3
                    )
                    usage_data = {
                        "prompt_tokens": int(prompt_tokens),
                        "completion_tokens": total_tokens_estimate,
                        "total_tokens": int(prompt_tokens) + total_tokens_estimate,
                    }

                # Yield final usage
                yield {
                    "type": "usage",
                    "usage": usage_data,
                    "finish_reason": finish_reason,
                }

                # Log successful streaming call
                latency_ms = (time.time() - start_time) * 1000
                self._log_llm_call(
                    call_type="tool_call_stream",
                    trace_id=trace_id,
                    model=params["model"],
                    temperature=params["temperature"],
                    input_tokens=usage_data["prompt_tokens"],
                    output_tokens=usage_data["completion_tokens"],
                    latency_ms=latency_ms,
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
                yield {
                    "type": "error",
                    "error_type": "RateLimitError",
                    "error_message": str(e),
                }
                raise
            except APITimeoutError as e:
                logger.warning("llm_stream_timeout", trace_id=trace_id, error=str(e))
                yield {
                    "type": "error",
                    "error_type": "APITimeoutError",
                    "error_message": str(e),
                }
                raise
            except APIError as e:
                logger.error(
                    "llm_stream_api_error",
                    trace_id=trace_id,
                    error=str(e),
                    status_code=e.status_code if hasattr(e, "status_code") else None,
                )
                yield {
                    "type": "error",
                    "error_type": "APIError",
                    "error_message": str(e),
                }
                raise
            except (
                httpx.RemoteProtocolError,
                httpx.ReadTimeout,
                httpx.ConnectTimeout,
            ) as e:
                # Network/connection errors - these are transient and should be retried
                logger.error(
                    "llm_stream_network_error",
                    trace_id=trace_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    message="Network connection interrupted during streaming. This is typically a transient error.",
                )
                yield {
                    "type": "error",
                    "error_type": type(e).__name__,
                    "error_message": f"Network error: {str(e)}. The connection was interrupted - this may be due to timeout or network issues.",
                    "recoverable": True,
                }
                raise
            except Exception as e:
                logger.error(
                    "llm_stream_unexpected_error",
                    trace_id=trace_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
                yield {
                    "type": "error",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                }
                raise

        # Run through circuit breaker (async generator)
        # Note: We yield from the async generator
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
        except Exception:
            llm_span.end()
            raise

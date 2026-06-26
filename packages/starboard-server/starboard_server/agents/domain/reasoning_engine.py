# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Pure reasoning logic for domain agents.

This module extracts the LLM reasoning logic from DomainAgent,
making it testable and reusable.

Responsibilities:
- Build messages for LLM calls
- Call LLM for next reasoning step
- Parse LLM responses (thinking + tool calls)
- Determine completion criteria
- Update agent state based on reasoning

Does NOT:
- Execute tools (that's ToolExecutor)
- Emit events (that's EventStreamer)
- Format outputs (that's OutputBuilder)
"""

from __future__ import annotations

import asyncio
import dataclasses
import random
from collections.abc import AsyncIterator
from typing import Any

from openai import RateLimitError

from starboard_server.adapters.llm.base import BaseLLMClient
from starboard_server.agents.state.agent_state import AgentState
from starboard_server.agents.tools import ToolRegistry
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class ReasoningStep:
    """
    Result of a single reasoning step.

    Attributes:
        thinking_content: Text content from LLM (reasoning/explanation)
        tool_calls: List of tool calls requested by LLM
        completed: Whether reasoning is complete (complete tool called)
        usage: Token usage information from LLM
        error: Error message if reasoning failed
    """

    thinking_content: str
    tool_calls: list[dict[str, Any]]
    completed: bool
    usage: dict[str, int] | None = None
    error: str | None = None


class ReasoningEngine:
    """
    Pure reasoning engine for domain agents.

    Handles LLM interactions and reasoning logic without I/O side effects
    (except for LLM calls). Stateless - all state passed in and returned.

    Example:
        >>> engine = ReasoningEngine(llm_client, tool_registry, max_steps=15)
        >>> async for chunk in engine.execute_step_stream(state):
        ...     if chunk["type"] == "thinking":
        ...         print(chunk["content"])
        ...     elif chunk["type"] == "complete":
        ...         step_result = chunk["step"]
        ...         print(f"Tool calls: {len(step_result.tool_calls)}")
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        tool_registry: ToolRegistry,
        max_steps: int = 15,
        temperature: float = 0.4,
    ):
        """
        Initialize reasoning engine.

        Args:
            llm_client: LLM client for reasoning calls
            tool_registry: Available tools for this domain
            max_steps: Maximum reasoning steps before stopping
            temperature: LLM temperature for reasoning (default: 0.4 for deterministic)
        """
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.max_steps = max_steps
        self.temperature = temperature

    async def execute_step_stream(
        self,
        state: AgentState,
        max_tokens: int = 4096,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute one reasoning step with streaming.

        Streams thinking content as it arrives from LLM, then yields
        complete step result with tool calls.

        Args:
            state: Current agent state
            max_tokens: Maximum tokens for LLM response

        Yields:
            Dictionaries with streaming updates:
            - {"type": "thinking", "content": str, "is_complete": bool}
            - {"type": "tool_calls", "tool_calls": list}
            - {"type": "usage", "usage": dict}
            - {"type": "complete", "step": ReasoningStep}

        Example:
            >>> async for chunk in engine.execute_step_stream(state):
            ...     if chunk["type"] == "thinking":
            ...         ui.update_thinking(chunk["content"])
            ...     elif chunk["type"] == "complete":
            ...         step = chunk["step"]
            ...         # Process tool calls
        """
        # Check if max steps reached
        if state.current_step >= self.max_steps:
            logger.warning(
                "max_steps_reached_before_reasoning",
                step=state.current_step,
                max_steps=self.max_steps,
            )
            yield {
                "type": "complete",
                "step": ReasoningStep(
                    thinking_content="Maximum reasoning steps reached.",
                    tool_calls=[],
                    completed=True,
                    error="max_steps_reached",
                ),
            }
            return

        # Get available tool schemas for this step
        tool_schemas = self._get_tool_schemas_for_step(state)

        # Build messages for LLM
        messages = self._build_messages(state)

        logger.debug(
            "reasoning_engine_calling_llm",
            step=state.current_step,
            message_count=len(messages),
            available_tools=len(tool_schemas),
        )

        # Call LLM with streaming, with rate-limit retry/backoff
        _max_rate_limit_retries = 3
        _rate_limit_base_delay = (
            30.0  # seconds – workspace TPM limits need longer waits
        )
        _rate_limit_max_delay = 120.0

        accumulated_content = ""
        accumulated_tool_calls: list[dict[str, Any]] = []
        usage_data: dict[str, Any] | None = None

        for _attempt in range(_max_rate_limit_retries + 1):
            accumulated_content = ""
            accumulated_tool_calls = []
            usage_data = None

            try:
                async for chunk in self.llm_client.call_with_tools_stream(  # type: ignore[attr-defined]
                    messages=messages,
                    tools=tool_schemas,
                    temperature=self.temperature,
                    max_tokens=max_tokens,
                ):
                    chunk_type = chunk.get("type")

                    # Stream thinking content as it arrives
                    if chunk_type == "content_delta":
                        content = chunk.get("content", "")
                        if content:
                            accumulated_content += content
                            yield {
                                "type": "thinking",
                                "content": content,
                                "is_complete": False,
                            }

                    # Buffer tool calls (arrive complete from LLM client)
                    elif chunk_type == "tool_calls_delta":
                        accumulated_tool_calls = chunk.get("tool_calls", [])
                        yield {
                            "type": "tool_calls",
                            "tool_calls": accumulated_tool_calls,
                        }

                    # Capture usage data
                    elif chunk_type == "usage":
                        usage_data = chunk.get("usage", {})
                        yield {
                            "type": "usage",
                            "usage": usage_data,
                        }

                # Mark thinking as complete
                if accumulated_content:
                    yield {
                        "type": "thinking",
                        "content": "",
                        "is_complete": True,
                    }

                # Determine if reasoning is complete (complete tool called)
                is_complete = any(
                    tc.get("name") == "complete" for tc in accumulated_tool_calls
                )

                # Build final step result
                step_result = ReasoningStep(
                    thinking_content=accumulated_content,
                    tool_calls=accumulated_tool_calls,
                    completed=is_complete,
                    usage=usage_data,
                )

                logger.debug(
                    "reasoning_step_complete",
                    step=state.current_step,
                    thinking_length=len(accumulated_content),
                    tool_calls_count=len(accumulated_tool_calls),
                    completed=is_complete,
                    tokens_used=usage_data.get("total_tokens") if usage_data else None,
                )

                yield {
                    "type": "complete",
                    "step": step_result,
                }
                return  # success – exit the retry loop

            except RateLimitError as e:
                if _attempt < _max_rate_limit_retries:
                    base_delay = min(
                        _rate_limit_base_delay * (2.0**_attempt),
                        _rate_limit_max_delay,
                    )
                    delay = base_delay * random.uniform(0.75, 1.25)
                    logger.warning(
                        "reasoning_step_rate_limit_retry",
                        step=state.current_step,
                        attempt=_attempt + 1,
                        max_retries=_max_rate_limit_retries,
                        retry_delay_s=round(delay, 1),
                        error=str(e),
                    )
                    yield {
                        "type": "thinking",
                        "content": (
                            f"\n⏳ Rate limit reached – waiting {delay:.0f}s before retry "
                            f"(attempt {_attempt + 1}/{_max_rate_limit_retries})…"
                        ),
                        "is_complete": False,
                    }
                    await asyncio.sleep(delay)
                    continue  # retry

                # Final attempt exhausted – surface as an error step
                logger.error(
                    "reasoning_step_rate_limit_exhausted",
                    step=state.current_step,
                    max_retries=_max_rate_limit_retries,
                    error=str(e),
                )
                yield {
                    "type": "complete",
                    "step": ReasoningStep(
                        thinking_content=accumulated_content,
                        tool_calls=[],
                        completed=False,
                        error=f"Rate limit exceeded after {_max_rate_limit_retries} retries: {e}",
                    ),
                }
                return

            except Exception as e:  # noqa: BLE001 - reasoning step boundary
                logger.error(
                    "reasoning_step_failed",
                    step=state.current_step,
                    error=str(e),
                    exc_info=True,
                )

                # Return error step
                yield {
                    "type": "complete",
                    "step": ReasoningStep(
                        thinking_content=accumulated_content,
                        tool_calls=[],
                        completed=False,
                        error=str(e),
                    ),
                }
                return

    def _get_tool_schemas_for_step(
        self,
        state: AgentState,
    ) -> list[dict[str, Any]]:
        """
        Get tool schemas for current step, filtered by already-used tools.

        Args:
            state: Current agent state with working memory

        Returns:
            List of tool schemas in OpenAI format, excluding used tools
            (but always including the 'complete' tool)
        """
        all_schemas = self.tool_registry.get_tool_schemas()
        used_tools = state.working_memory.tools_used

        # Filter out used tools, but always keep 'complete' available
        available_schemas = [
            schema
            for schema in all_schemas
            if schema.get("function", {}).get("name") not in used_tools
            or schema.get("function", {}).get("name") == "complete"
        ]

        logger.debug(
            "filtered_tools_for_reasoning_step",
            step=state.current_step,
            total_tools=len(all_schemas),
            used_tools=list(used_tools),
            available_tools=[
                s.get("function", {}).get("name") for s in available_schemas
            ],
        )

        return available_schemas

    def _build_messages(self, state: AgentState) -> list[dict[str, Any]]:
        """
        Build message history for LLM call.

        Converts Message objects to dicts suitable for LLM API,
        handling tool_calls metadata and content filtering.

        Args:
            state: Current agent state with conversation history

        Returns:
            List of message dicts for LLM API
        """
        result = []
        for msg in state.conversation_history:
            msg_dict = dataclasses.asdict(msg)

            # Remove None values for cleaner API requests
            msg_dict = {k: v for k, v in msg_dict.items() if v is not None}

            # Extract tool_calls from metadata if present
            if "metadata" in msg_dict and "tool_calls" in msg_dict.get("metadata", {}):
                tool_calls = msg_dict["metadata"]["tool_calls"]
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    if not (fn.get("arguments") or "").strip():
                        fn["arguments"] = "{}"
                msg_dict["tool_calls"] = tool_calls

            # Always remove metadata from API requests (internal only)
            if "metadata" in msg_dict:
                del msg_dict["metadata"]

            # Remove empty content from assistant messages with tool_calls
            # (Some LLM providers require this)
            if (
                msg_dict.get("role") == "assistant"
                and "tool_calls" in msg_dict
                and msg_dict.get("content") == ""
            ):
                del msg_dict["content"]

            result.append(msg_dict)

        return result

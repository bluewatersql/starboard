"""
Tool execution with error handling, retries, and circuit breaking.

This module extracts tool execution logic from DomainAgent,
providing robust tool invocation with proper error handling.

Responsibilities:
- Execute tool calls from reasoning engine
- Handle tool errors gracefully
- Retry failed tool calls (configurable)
- Circuit breaking for failing tools
- Parallel execution of independent tools
- Metrics collection

Does NOT:
- Decide which tools to call (that's ReasoningEngine)
- Format tool results for output (that's OutputBuilder)
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from typing import Any

from starboard_server.agents.output.llm_responses import ToolCall
from starboard_server.agents.tools import ToolRegistry
from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.observability.tracing import get_tracer
from starboard_server.infra.reliability.circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitBreakerError,
)

logger = get_logger(__name__)
_tracer = get_tracer("starboard.tools")


@dataclasses.dataclass(frozen=True)
class ToolExecutionResult:
    """
    Result of executing a tool.

    Attributes:
        tool_call: Original tool call request
        success: Whether execution succeeded
        result: Tool result object (if successful)
        error: Error message (if failed)
        duration_seconds: Execution duration
        arguments: Parsed arguments used
    """

    tool_call: ToolCall
    success: bool
    result: Any | None
    error: str | None = None
    duration_seconds: float = 0.0
    arguments: dict[str, Any] = dataclasses.field(default_factory=dict)


class ToolExecutor:
    """
    Execute tools with error handling, retries, and circuit breaking.

    Handles tool execution robustly with:
    - Parallel execution of independent tool calls
    - Exponential backoff retry for transient failures
    - Circuit breakers to prevent cascading failures
    - Comprehensive error handling and logging

    Example:
        >>> executor = ToolExecutor(tool_registry, enable_retry=True, max_retries=2)
        >>> tool_calls = [ToolCall(id="1", name="search", arguments='{"query": "x"}')]
        >>> results = await executor.execute_tools_parallel(tool_calls, agent_context={})
        >>> for result in results:
        ...     if result.success:
        ...         print(f"Tool {result.tool_call.name} succeeded")
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        enable_retry: bool = True,
        max_retries: int = 2,
        circuit_breaker_threshold: int = 5,
    ):
        """
        Initialize tool executor.

        Args:
            tool_registry: Registry of available tools
            enable_retry: Whether to retry failed tool calls
            max_retries: Maximum number of retries per tool
            circuit_breaker_threshold: Number of failures before circuit opens
        """
        self.tool_registry = tool_registry
        self.enable_retry = enable_retry
        self.max_retries = max_retries
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self._circuit_breakers: dict[str, AsyncCircuitBreaker] = {}

    async def execute_tools_parallel(
        self,
        tool_calls: tuple[ToolCall, ...] | list[ToolCall],
        agent_context: dict[str, Any],
    ) -> list[ToolExecutionResult]:
        """
        Execute multiple tool calls in parallel (batch mode - waits for all).

        Runs all tool calls concurrently using asyncio.gather for better
        performance when LLM requests multiple independent tools.

        Note: For streaming results as they complete, use execute_tools_streaming().

        Args:
            tool_calls: Tool calls to execute
            agent_context: Context to pass to tools (workspace_id, etc.)

        Returns:
            List of ToolExecutionResult in same order as tool_calls

        Example:
            >>> calls = [
            ...     ToolCall(id="1", name="get_table_metadata", arguments='{"table": "x"}'),
            ...     ToolCall(id="2", name="get_table_metadata", arguments='{"table": "y"}'),
            ... ]
            >>> results = await executor.execute_tools_parallel(calls, {"workspace_id": "ws123"})
            >>> assert len(results) == 2
        """
        if not tool_calls:
            return []

        logger.debug(
            "executing_tools_in_parallel",
            num_calls=len(tool_calls),
            tool_names=[tc.name for tc in tool_calls],
        )

        # Execute all tools in parallel
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self._execute_single_tool(tc, agent_context))
                for tc in tool_calls
            ]
        results = [t.result() for t in tasks]

        # Log summary
        successful_count = sum(1 for r in results if r.success)
        logger.info(
            "tool_batch_completed",
            total_calls=len(tool_calls),
            successful_calls=successful_count,
            failed_calls=len(tool_calls) - successful_count,
        )

        return results

    async def execute_tools_streaming(
        self,
        tool_calls: tuple[ToolCall, ...] | list[ToolCall],
        agent_context: dict[str, Any],
    ):
        """
        Execute multiple tool calls in parallel, yielding results as they complete.

        Unlike execute_tools_parallel which waits for all tools to finish,
        this method yields each result immediately when a tool completes.
        This enables real-time streaming of tool results to the frontend.

        Args:
            tool_calls: Tool calls to execute
            agent_context: Context to pass to tools (workspace_id, etc.)

        Yields:
            ToolExecutionResult as each tool completes

        Example:
            >>> calls = [ToolCall(...), ToolCall(...)]
            >>> async for result in executor.execute_tools_streaming(calls, ctx):
            ...     print(f"Tool {result.tool_call.name} completed!")
        """
        if not tool_calls:
            return

        logger.debug(
            "executing_tools_streaming",
            num_calls=len(tool_calls),
            tool_names=[tc.name for tc in tool_calls],
        )

        # Create tasks with tool_call reference for identification
        tasks = {
            asyncio.create_task(self._execute_single_tool(tc, agent_context)): tc
            for tc in tool_calls
        }

        successful_count = 0
        failed_count = 0

        # Yield results as they complete using as_completed
        for completed_task in asyncio.as_completed(tasks.keys()):
            result = await completed_task

            if result.success:
                successful_count += 1
            else:
                failed_count += 1

            logger.debug(
                "tool_execution_streamed",
                tool_name=result.tool_call.name,
                success=result.success,
                duration_seconds=result.duration_seconds,
            )

            yield result

        logger.info(
            "tool_batch_completed",
            total_calls=len(tool_calls),
            successful_calls=successful_count,
            failed_calls=failed_count,
        )


    async def _execute_single_tool(
        self,
        tool_call: ToolCall,
        agent_context: dict[str, Any],
    ) -> ToolExecutionResult:
        """
        Execute a single tool call with retry logic and circuit breaking.

        The circuit breaker wraps each tool execution attempt, automatically
        recording successes and failures. When the failure threshold is reached,
        subsequent calls are rejected immediately with CircuitBreakerError.

        Args:
            tool_call: Tool call to execute
            agent_context: Context to pass to tool

        Returns:
            ToolExecutionResult with success status and result
        """
        span = _tracer.start_span(
            f"tool.{tool_call.name}",
            attributes={"tool.name": tool_call.name},
        )

        # Parse arguments
        try:
            parsed_args = tool_call.parse_arguments()
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.error(
                "tool_argument_parsing_failed",
                tool_name=tool_call.name,
                error=str(e),
            )
            span.set_attribute("tool.success", False)
            span.end()
            return ToolExecutionResult(
                tool_call=tool_call,
                success=False,
                result=None,
                error=f"Failed to parse arguments: {str(e)}",
                arguments={},
            )

        # Get or create circuit breaker for this tool
        circuit_breaker = self._get_circuit_breaker(tool_call.name)

        # Execute with retries — circuit breaker wraps each attempt
        start_time = time.time()
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                # Circuit breaker wraps execution: automatically records
                # success/failure and raises CircuitBreakerError when open
                tool_result = await circuit_breaker.call(
                    self.tool_registry.execute_tool,
                    tool_name=tool_call.name,
                    agent_context=agent_context,
                    **parsed_args,
                )

                duration = time.time() - start_time

                # Check if tool returned an error result
                if tool_result.error:
                    logger.warning(
                        "tool_returned_error_result",
                        tool_name=tool_call.name,
                        error=tool_result.error,
                        duration_seconds=duration,
                    )
                    span.set_attribute("tool.success", False)
                    span.set_attribute("tool.duration_seconds", duration)
                    span.end()
                    return ToolExecutionResult(
                        tool_call=tool_call,
                        success=False,
                        result=tool_result,
                        error=tool_result.error,
                        duration_seconds=duration,
                        arguments=parsed_args,
                    )

                # Success
                logger.debug(
                    "tool_execution_success",
                    tool_name=tool_call.name,
                    duration_seconds=duration,
                    attempt=attempt + 1,
                )

                span.set_attribute("tool.success", True)
                span.set_attribute("tool.duration_seconds", duration)
                span.end()
                return ToolExecutionResult(
                    tool_call=tool_call,
                    success=True,
                    result=tool_result,
                    duration_seconds=duration,
                    arguments=parsed_args,
                )

            except CircuitBreakerError:
                # Circuit is open — reject immediately without retrying
                logger.warning(
                    "tool_circuit_breaker_open",
                    tool_name=tool_call.name,
                )
                span.set_attribute("tool.success", False)
                span.end()
                return ToolExecutionResult(
                    tool_call=tool_call,
                    success=False,
                    result=None,
                    error=f"Circuit breaker open for {tool_call.name} (too many recent failures)",
                    duration_seconds=time.time() - start_time,
                    arguments=parsed_args,
                )

            except Exception as e:
                duration = time.time() - start_time
                last_error = str(e)

                logger.error(
                    "tool_execution_exception",
                    tool_name=tool_call.name,
                    error=last_error,
                    attempt=attempt + 1,
                    max_attempts=self.max_retries + 1,
                    duration_seconds=duration,
                    exc_info=True,
                )

                # Retry if enabled and not last attempt
                if attempt < self.max_retries and self.enable_retry:
                    # Exponential backoff: 1s, 2s, 4s, ...
                    backoff_seconds = 2**attempt
                    logger.debug(
                        "tool_execution_retry",
                        tool_name=tool_call.name,
                        attempt=attempt + 1,
                        backoff_seconds=backoff_seconds,
                    )
                    await asyncio.sleep(backoff_seconds)
                    continue

                # No more retries, return failure
                break

        # All retries exhausted
        duration = time.time() - start_time
        span.set_attribute("tool.success", False)
        span.set_attribute("tool.duration_seconds", duration)
        span.end()
        return ToolExecutionResult(
            tool_call=tool_call,
            success=False,
            result=None,
            error=last_error or "Unknown error",
            duration_seconds=duration,
            arguments=parsed_args,
        )

    def _get_circuit_breaker(self, tool_name: str) -> AsyncCircuitBreaker:
        """
        Get or create circuit breaker for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            AsyncCircuitBreaker instance for this tool
        """
        if tool_name not in self._circuit_breakers:
            self._circuit_breakers[tool_name] = AsyncCircuitBreaker(
                failure_threshold=self.circuit_breaker_threshold,
                timeout_seconds=60,  # Reset after 60 seconds
                name=f"tool_{tool_name}",
            )
        return self._circuit_breakers[tool_name]

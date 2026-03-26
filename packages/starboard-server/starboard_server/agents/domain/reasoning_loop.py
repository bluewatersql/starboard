# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Reasoning loop orchestration for domain agents.

This module extracts the main reasoning loop from DomainAgent, coordinating
the ReasoningEngine, ToolExecutor, and EventStreamer components in a
step-by-step reasoning cycle.

Responsibilities:
- Orchestrate the reasoning loop (reason -> execute tools -> stream events)
- Check continuation criteria (completion, budget, max steps)
- Handle stuck agent detection (consecutive empty steps)

Does NOT:
- Initialize state (that's StateInitializer)
- Build final output (that's OutputBuilder)
- Register tools (that's complete_tool module)
- Generate partial reports (that's partial_report module)
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.agents.domain.event_streamer import EventStreamer
from starboard_server.agents.domain.message_helpers import (
    add_assistant_message,
    add_tool_message,
)
from starboard_server.agents.domain.partial_report import generate_partial_report
from starboard_server.agents.domain.reasoning_engine import ReasoningEngine
from starboard_server.agents.domain.tool_executor import ToolExecutor
from starboard_server.agents.events import (
    StreamingEvent,
    create_error_event,
    create_final_output_event,
)
from starboard_server.agents.events.user_events import FinalOutputEvent
from starboard_server.agents.observability.metrics import AgentMetrics
from starboard_server.agents.output.llm_responses import ToolCall
from starboard_server.agents.state.agent_state import AgentState
from starboard_server.agents.tool_display import (
    generate_sub_task,
    get_thinking_step_id,
    get_thinking_step_title,
)
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

# Budget reservation for guaranteed completion
# Reserve enough tokens for the complete tool to generate a full structured response
FINALIZATION_BUDGET = 2000  # tokens reserved for complete tool


def should_continue_reasoning(
    state: AgentState,
    config: AgentConfig,
) -> bool:
    """
    Check if agent should continue reasoning.

    Considers:
    1. state.completed - Has agent called complete tool?
    2. state.current_step vs max_steps - Hit step limit?
    3. state.budget_remaining vs FINALIZATION_BUDGET - Reserve budget for completion

    Args:
        state: Current agent state
        config: Agent configuration

    Returns:
        True if reasoning should continue, False if should stop
    """
    # Stop if already completed
    if state.completed:
        return False

    # Stop if max steps reached
    if state.current_step >= config.max_steps:
        return False

    # Stop if budget at or below finalization threshold
    # This ensures we always have budget for the complete tool
    if config.enforce_budget and (state.budget_remaining <= FINALIZATION_BUDGET):
        logger.info(
            "budget_at_finalization_threshold",
            budget_remaining=state.budget_remaining,
            finalization_budget=FINALIZATION_BUDGET,
            current_step=state.current_step,
        )
        return False

    return True


async def reasoning_loop_stream(
    state: AgentState,
    config: AgentConfig,
    reasoning: ReasoningEngine,
    executor: ToolExecutor,
    streamer: EventStreamer,
    builder: Any,  # OutputBuilder - avoid circular import
    metrics: AgentMetrics | None,
) -> AsyncIterator[StreamingEvent | FinalOutputEvent]:
    """
    Main reasoning loop - orchestrates all components.

    Pattern:
    1. ReasoningEngine.execute_step_stream() -> yields thinking/tool_calls
    2. ToolExecutor.execute_tools_parallel() -> executes tools
    3. EventStreamer.create_*_event() -> creates events
    4. Update state from results
    5. OutputBuilder.build() -> final output

    Args:
        state: Initial agent state
        config: Agent configuration
        reasoning: ReasoningEngine for LLM calls
        executor: ToolExecutor for tool execution
        streamer: EventStreamer for event creation
        builder: OutputBuilder for final output
        metrics: Optional metrics tracker

    Yields:
        StreamingEvent or FinalOutputEvent instances
    """
    # Track consecutive empty responses to detect stuck agent
    consecutive_empty_steps = 0
    max_empty_steps = 3  # Force completion after 3 empty responses in a row

    # Track whether previous step had tool calls (for "Generating Analysis" indicator)
    previous_step_had_tools = False
    generating_analysis_start_time: float | None = None

    # Use centralized reasoning continuation check (respects finalization budget)
    while should_continue_reasoning(state, config):
        state = dataclasses.replace(state, current_step=state.current_step + 1)

        logger.debug("reasoning_step_started", step=state.current_step)

        # If previous step had tool calls, we're now generating analysis
        # Emit a progress indicator so users know the agent is working
        if previous_step_had_tools:
            generating_analysis_start_time = time.time()
            yield streamer.create_thinking_step_update(
                step=state.current_step,
                step_id="generating_analysis",
                title="Generating Analysis",
                status="in_progress",
                start_time=generating_analysis_start_time,
                sub_tasks=[],
            )

        try:
            # === STEP 1: REASONING (via ReasoningEngine) ===
            reasoning_result = None

            async for chunk in reasoning.execute_step_stream(state, config.max_tokens):
                if chunk["type"] == "thinking":
                    # Stream thinking content
                    event = streamer.create_thinking_event(
                        content=chunk["content"],
                        step=state.current_step,
                        is_complete=chunk.get("is_complete", False),
                    )
                    yield event

                elif chunk["type"] == "complete":
                    reasoning_result = chunk["step"]

                    # Update metrics from LLM usage
                    if reasoning_result.usage and metrics:
                        usage = reasoning_result.usage
                        metrics.input_tokens += usage.get("prompt_tokens", 0)
                        metrics.output_tokens += usage.get("completion_tokens", 0)
                        metrics.total_tokens += usage.get("total_tokens", 0)

                        # Update cost
                        step_cost = config.estimate_cost(
                            input_tokens=usage.get("prompt_tokens", 0),
                            output_tokens=usage.get("completion_tokens", 0),
                        )
                        metrics.estimated_cost_usd += step_cost

                        # Update budget
                        tokens_used = usage.get("total_tokens", 0)
                        state = dataclasses.replace(
                            state,
                            budget_remaining=max(
                                0, state.budget_remaining - tokens_used
                            ),
                        )

            if not reasoning_result:
                logger.error("reasoning_produced_no_result", step=state.current_step)
                break

            # Mark "Generating Analysis" as complete if it was active
            if generating_analysis_start_time is not None:
                yield streamer.create_thinking_step_update(
                    step=state.current_step,
                    step_id="generating_analysis",
                    title="Generating Analysis",
                    status="completed",
                    start_time=generating_analysis_start_time,
                    end_time=time.time(),
                    sub_tasks=[],
                )
                generating_analysis_start_time = None

            # Check for error
            if reasoning_result.error:
                yield create_error_event(
                    step=state.current_step,
                    error=reasoning_result.error,
                    error_type="reasoning_error",
                    is_recoverable=False,
                )
                break

            # Update state with assistant message
            state = add_assistant_message(state, reasoning_result)

            # === STEP 2: TOOL EXECUTION (via ToolExecutor) ===
            if reasoning_result.tool_calls:
                # Convert to ToolCall objects
                tool_call_objects = tuple(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("name", ""),
                        arguments=tc.get("arguments", "{}"),
                    )
                    for tc in reasoning_result.tool_calls
                )

                # Track tool execution start times
                tool_start_times: dict[str, float] = {}

                # Emit enhanced thinking step + tool start events
                for tc in tool_call_objects:
                    try:
                        args = tc.parse_arguments()
                    except (json.JSONDecodeError, ValueError, TypeError) as parse_err:
                        logger.debug(
                            "tool_call_argument_parse_failed",
                            tool_call_id=tc.id,
                            error=str(parse_err),
                        )
                        args = {}

                    # Record start time
                    start_time = time.time()
                    tool_start_times[tc.id] = start_time

                    # Emit ThinkingStepUpdate (in_progress)
                    yield streamer.create_thinking_step_update(
                        step=state.current_step,
                        step_id=get_thinking_step_id(tc.name),
                        title=get_thinking_step_title(tc.name),
                        status="in_progress",
                        start_time=start_time,
                        sub_tasks=[generate_sub_task(tc.name, "in_progress")],
                    )

                    # Emit tool start event
                    logger.debug(
                        "yielding_tool_start_event",
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        step=state.current_step,
                    )
                    yield streamer.create_tool_start_event(
                        step=state.current_step,
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        arguments=args,
                    )

                    # SAFEGUARD: Yield control to event loop after each tool start event
                    # This ensures SSE events are sent before potentially blocking tool execution
                    await asyncio.sleep(0)

                    # Special handling for request_user_input tool:
                    # Yield UserInputRequestEvent BEFORE execution so frontend
                    # can display the question while the tool waits for response
                    if tc.name == "request_user_input":
                        from starboard_server.agents.events import (
                            UserInputRequestEvent,
                        )

                        question = args.get("question", "")
                        context = args.get("context")
                        suggestions = args.get("suggestions", [])
                        timeout = args.get("timeout", 300)
                        request_id = f"input_{uuid.uuid4().hex[:8]}"

                        yield UserInputRequestEvent(
                            step=state.current_step,
                            question=question,
                            context=context,
                            suggestions=suggestions,
                            timeout_seconds=int(timeout),
                            request_id=request_id,
                        )

                # Execute tools (via ToolExecutor) - STREAMING mode
                # Results are yielded as each tool completes, not batched
                logger.debug(
                    "starting_tool_execution",
                    tool_names=[tc.name for tc in tool_call_objects],
                    num_tools=len(tool_call_objects),
                )
                async for result in executor.execute_tools_streaming(
                    tool_call_objects,
                    agent_context=state.context,
                ):
                    # Record metrics
                    if metrics:
                        metrics.record_tool(
                            tool_name=result.tool_call.name,
                            success=result.success,
                            duration=result.duration_seconds,
                            error_type=result.error if result.error else None,
                        )

                    # Emit tool end event IMMEDIATELY when tool completes
                    logger.debug(
                        "yielding_tool_end_event",
                        tool_name=result.tool_call.name,
                        tool_call_id=result.tool_call.id,
                        success=result.success,
                        duration_seconds=result.duration_seconds,
                    )
                    yield streamer.create_tool_end_event(
                        step=state.current_step,
                        tool_execution=result,
                    )

                    # Emit ThinkingStepUpdate (completed/failed)
                    end_time = time.time()
                    start_time = tool_start_times.get(result.tool_call.id, end_time)
                    status = "completed" if result.success else "failed"

                    yield streamer.create_thinking_step_update(
                        step=state.current_step,
                        step_id=get_thinking_step_id(result.tool_call.name),
                        title=get_thinking_step_title(result.tool_call.name),
                        status=status,
                        start_time=start_time,
                        end_time=end_time,
                        sub_tasks=[
                            generate_sub_task(
                                result.tool_call.name,
                                status,
                                result=result.result,
                                error=result.error,
                            )
                        ],
                    )

                    # Update state with tool result
                    state = add_tool_message(state, result)

            # === STEP 3: CHECK COMPLETION ===
            if reasoning_result.completed:
                state = dataclasses.replace(state, completed=True)
                logger.debug("agent_completed", step=state.current_step)
                break

            # === SAFEGUARD: Detect stuck agent (empty responses) ===
            # If LLM returns no content AND no tool calls, it's likely stuck
            has_content = bool(
                reasoning_result.thinking_content
                and reasoning_result.thinking_content.strip()
            )
            has_tools = bool(reasoning_result.tool_calls)

            if not has_content and not has_tools:
                consecutive_empty_steps += 1
                logger.warning(
                    "empty_reasoning_step_detected",
                    step=state.current_step,
                    consecutive_empty=consecutive_empty_steps,
                    max_allowed=max_empty_steps,
                )

                if consecutive_empty_steps >= max_empty_steps:
                    logger.warning(
                        "forcing_completion_due_to_stuck_agent",
                        step=state.current_step,
                        consecutive_empty=consecutive_empty_steps,
                        note="Agent returned empty responses repeatedly, forcing completion",
                    )
                    state = dataclasses.replace(state, completed=True)
                    break
            else:
                # Reset counter on any productive step
                consecutive_empty_steps = 0

            # Emit step complete event
            tokens_used = (
                reasoning_result.usage.get("total_tokens", 0)
                if reasoning_result.usage
                else 0
            )
            yield streamer.create_step_complete_event(
                step=state.current_step,
                tools_called=len(reasoning_result.tool_calls),
                tokens_used=tokens_used,
                budget_remaining=state.budget_remaining,
                is_final=reasoning_result.completed,
            )

            # Track if this step had tool calls for next iteration's "Generating Analysis"
            previous_step_had_tools = has_tools

        except Exception as e:  # noqa: BLE001 - step-level error boundary
            # Intentional: step-level error boundary — log and emit error
            # event to client, then break the reasoning loop gracefully.
            logger.error(
                "reasoning_step_failed",
                step=state.current_step,
                error=str(e),
                exc_info=True,
            )
            yield create_error_event(
                step=state.current_step,
                error="Step failed: " + str(e),
                error_type="step_error",
                is_recoverable=False,
            )
            break

    # === STEP 4: HANDLE BUDGET EXHAUSTION ===
    # If loop exited due to budget threshold (not completion), generate partial report
    if config.enforce_budget and (
        not state.completed and state.budget_remaining <= FINALIZATION_BUDGET
    ):
        logger.warning(
            "generating_partial_report_budget_exhausted",
            budget_remaining=state.budget_remaining,
            finalization_budget=FINALIZATION_BUDGET,
            tools_used=list(state.working_memory.tools_used),
            step=state.current_step,
        )
        # Generate minimal partial report from gathered data
        partial_report = generate_partial_report(state, config)
        state = dataclasses.replace(
            state,
            final_output=partial_report,
            completed=True,  # Mark as completed (partial)
        )
        logger.info(
            "partial_report_generated",
            has_summary=partial_report.get("summary") is not None,
            has_analysis=partial_report.get("analysis") is not None,
            has_next_steps=partial_report.get("next_steps") is not None,
        )

    # === STEP 4b: FALLBACK REPORT FOR MISSING COMPLETE TOOL ===
    # When the agent finishes (max steps, stuck detection, or regular tool
    # completion) without calling the `complete` tool, state.final_output
    # remains None.  Extract results from the conversation history so the
    # CLI / API always returns meaningful content.
    if state.final_output is None:
        tools_used = list(state.working_memory.tools_used)
        logger.warning(
            "generating_fallback_report_no_complete_tool",
            completed=state.completed,
            current_step=state.current_step,
            tools_used=tools_used,
        )
        fallback_report = generate_partial_report(state, config)
        fallback_report["budget_exhausted"] = False
        fallback_report["summary"]["overview"] = (
            f"Analysis completed using {len(tools_used)} tool"
            f"{'s' if len(tools_used) != 1 else ''} "
            f"({', '.join(tools_used) if tools_used else 'none'}). "
            f"Results extracted from tool outputs."
        )
        if fallback_report.get("summary", {}).get("current_state"):
            fallback_report["summary"]["current_state"]["key_symptoms"] = []
        state = dataclasses.replace(
            state,
            final_output=fallback_report,
            completed=True,
        )
        logger.info(
            "fallback_report_generated",
            has_summary=fallback_report.get("summary") is not None,
            has_analysis=fallback_report.get("analysis") is not None,
            findings_count=len(
                fallback_report.get("analysis", {}).get("findings", [])
            ),
        )

    # === STEP 5: BUILD FINAL OUTPUT (via OutputBuilder) ===
    output = builder.build(state)

    # Inject pre-rendered discovery markdown if available.
    # The discovery pipeline produces a rich per-domain report that should
    # bypass the LLM's generic summarization.
    synth_adapter = executor.tool_registry.get_tool("synthesize_discovery_report")
    if synth_adapter is not None:
        tool_instance = getattr(synth_adapter, "tool_instance", None)
        discovery_md = getattr(tool_instance, "get_discovery_markdown", lambda: None)()
        if discovery_md:
            output = dataclasses.replace(output, formatted_markdown=discovery_md)

    yield create_final_output_event(output)

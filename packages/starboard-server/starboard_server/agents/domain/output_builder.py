"""
Output building and formatting for domain agents.

This module extracts output building logic from DomainAgent,
providing structured output formatting with recommendations and handoffs.

Responsibilities:
- Build AgentOutput from final state
- Extract recommendations from complete_report
- Determine execution status
- Calculate metrics (tokens, cost, duration)
- Format primary answer
- Generate handoff recommendations
- Extract in-domain next steps

Does NOT:
- Execute reasoning or tools (that's ReasoningEngine/ToolExecutor)
- Emit events (that's EventStreamer)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast

from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.agents.observability.metrics import AgentMetrics
from starboard_server.agents.state.agent_state import AgentOutput, AgentState
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class OutputBuilder:
    """
    Build structured outputs from agent state.

    Formats agent outputs with recommendations, metrics, and handoff
    suggestions for cross-domain collaboration.

    Example:
        >>> builder = OutputBuilder(config=agent_config, metrics=agent_metrics)
        >>> output = builder.build(final_state)
        >>> print(output.status)
        "success"
        >>> print(len(output.recommendations))
        5
    """

    def __init__(
        self,
        config: AgentConfig,
        metrics: AgentMetrics | None = None,
    ):
        """
        Initialize output builder.

        Args:
            config: Agent configuration
            metrics: Optional agent metrics for token/cost tracking
        """
        self.config = config
        self.metrics = metrics

    def build(self, state: AgentState) -> AgentOutput:
        """
        Build final agent output from state.

        Args:
            state: Final agent state

        Returns:
            AgentOutput with formatted results, recommendations, and metadata

        Example:
            >>> output = builder.build(final_state)
            >>> print(f"Status: {output.status}")
            >>> print(f"Recommendations: {len(output.recommendations)}")
            >>> print(f"Cost: ${output.cost_usd:.4f}")
        """
        # Extract recommendations from final output
        recommendations = self._extract_recommendations(state)

        # Determine execution status
        status = self._determine_status(state)

        # Calculate metrics
        tokens_used, cost_usd, duration_seconds = self._calculate_metrics(state)

        # Build reasoning trace
        reasoning_trace = self._build_reasoning_trace(state)

        # Get tools used
        tools_used = list(state.working_memory.tools_used)

        # Get complete report
        complete_report = self._get_complete_report(state)

        # Extract next steps
        next_steps = self._extract_next_steps(complete_report)

        # Build base agent output
        AgentStatus = Literal[
            "success", "budget_exceeded", "max_steps_reached", "error"
        ]
        agent_output = AgentOutput(
            status=cast(AgentStatus, status),
            recommendations=recommendations,
            reasoning_trace=reasoning_trace,
            steps_taken=state.current_step,
            tools_used=tools_used,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            duration_seconds=duration_seconds,
            error_message=getattr(state, "error", None),
            complete_report=complete_report,
            next_steps=next_steps,
        )

        # Generate handoff recommendations
        handoff_recommendations = self._generate_handoff_recommendations(
            state, agent_output
        )

        # If no handoffs, return base output
        if not handoff_recommendations:
            return agent_output

        # Wrap in DomainAgentOutput with handoffs
        return self._build_domain_output(agent_output, handoff_recommendations)

    def _extract_recommendations(self, state: AgentState) -> list[dict[str, Any]]:
        """
        Extract recommendations from final output.

        Args:
            state: Agent state with final_output

        Returns:
            List of recommendation dictionaries
        """
        recommendations: list[dict[str, Any]] = []

        if not hasattr(state, "final_output") or not state.final_output:
            logger.warning(
                "no_final_output_in_state",
                note="agent may not have called complete tool",
            )
            return recommendations

        if not isinstance(state.final_output, dict):
            logger.warning(
                "final_output_not_dict",
                data_type=type(state.final_output).__name__,
            )
            return recommendations

        # Try extracting from analysis.findings structure
        analysis = state.final_output.get("analysis", {})
        if isinstance(analysis, dict) and analysis:
            recommendations = analysis.get("findings", [])
            if recommendations:
                logger.debug(
                    "found_recommendations_in_analysis",
                    count=len(recommendations),
                )
                return recommendations

        # Fallback to top-level recommendations
        recommendations = state.final_output.get("recommendations", [])
        if recommendations:
            logger.debug(
                "found_recommendations_top_level",
                count=len(recommendations),
            )
            return recommendations

        # No recommendations found
        logger.warning(
            "no_recommendations_extracted",
            final_output_keys=(
                list(state.final_output.keys())
                if isinstance(state.final_output, dict)
                else []
            ),
        )

        return recommendations

    def _determine_status(self, state: AgentState) -> str:
        """
        Determine execution status from state.

        Args:
            state: Agent state

        Returns:
            Status string: "success", "error", "max_steps_reached", "budget_exceeded"
        """
        # Import finalization budget constant
        from starboard_server.agents.domain.reasoning_loop import FINALIZATION_BUDGET

        if hasattr(state, "error") and state.error:
            return "error"

        # Check for budget exhaustion (including finalization threshold)
        # This must be checked before "success" since partial reports are marked completed
        if state.final_output and state.final_output.get("budget_exhausted"):
            return "budget_exceeded"

        if state.completed:
            return "success"

        if state.current_step >= self.config.max_steps:
            return "max_steps_reached"

        # Budget exhausted below finalization threshold
        if self.config.enforce_budget and state.budget_remaining <= FINALIZATION_BUDGET:
            return "budget_exceeded"

        # Budget completely exhausted (enforce_budget mode)
        if self.config.enforce_budget and state.budget_remaining <= 0:
            return "budget_exceeded"

        return "success"  # Default

    def _calculate_metrics(self, state: AgentState) -> tuple[int, float, float]:
        """
        Calculate execution metrics.

        Args:
            state: Agent state

        Returns:
            Tuple of (tokens_used, cost_usd, duration_seconds)
        """
        if self.metrics:
            tokens_used = self.metrics.total_tokens
            cost_usd = self.metrics.estimated_cost_usd
            duration_seconds = (
                datetime.now(UTC) - self.metrics.start_time
            ).total_seconds()
        else:
            # Fallback to budget calculation
            tokens_used = self.config.max_tokens - state.budget_remaining
            cost_usd = self.config.estimate_cost(
                input_tokens=int(tokens_used * 0.7),
                output_tokens=int(tokens_used * 0.3),
            )
            duration_seconds = 0.0

        return tokens_used, cost_usd, duration_seconds

    def _build_reasoning_trace(self, state: AgentState) -> list[dict[str, Any]]:
        """
        Build reasoning trace from conversation history.

        Extracts actual step data (tool calls, thinking summaries) from
        the assistant and tool messages recorded during the reasoning loop.

        Args:
            state: Agent state with conversation history

        Returns:
            List of reasoning step dictionaries
        """
        trace: list[dict[str, Any]] = []
        step = 0

        for msg in state.conversation_history:
            if msg.role != "assistant":
                continue

            step += 1
            tool_names: list[str] = []
            if msg.metadata and "tool_calls" in msg.metadata:
                tool_names = [
                    tc.get("function", {}).get("name", "unknown")
                    for tc in msg.metadata["tool_calls"]
                ]

            thinking = (msg.content or "").strip()
            thinking_preview = thinking[:300]
            if len(thinking) > 300:
                thinking_preview += "..."

            action = ", ".join(tool_names) if tool_names else "reasoning"

            trace.append(
                {
                    "step": step,
                    "action": action,
                    "thinking": thinking_preview if thinking_preview else None,
                    "tool_calls": tool_names if tool_names else None,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

        if not trace:
            trace = [
                {
                    "step": i + 1,
                    "action": "reasoning",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                for i in range(state.current_step)
            ]

        return trace

    def _get_complete_report(self, state: AgentState) -> dict[str, Any] | None:
        """
        Get complete report from state.

        Args:
            state: Agent state

        Returns:
            Complete report dict or None
        """
        if state.final_output:
            return state.final_output
        return None

    def _extract_next_steps(
        self,
        complete_report: dict[str, Any] | None,
    ) -> list[Any] | None:
        """
        Extract next steps from complete report.

        Handles both legacy format (rank, action, expected_impact, effort, category)
        and new format (id, number, title, description, action_type, target_agent,
        tool_name, parameters).

        Field mapping:
        - rank → number
        - action → title
        - expected_impact → description

        Args:
            complete_report: Complete report dictionary

        Returns:
            List of next step option dicts or None
        """
        if not complete_report or not isinstance(complete_report, dict):
            return None

        raw_next_steps = complete_report.get("next_steps", [])
        if not raw_next_steps:
            return None

        # Convert dicts to NextStepOption objects
        from starboard_server.domain.models.conversation_patterns import (
            ActionType,
            NextStepOption,
        )

        next_steps = []
        for idx, step in enumerate(raw_next_steps):
            if isinstance(step, dict):
                try:
                    # Detect and log legacy field usage (deprecation tracking)
                    legacy_fields_used = []
                    if "rank" in step and "number" not in step:
                        legacy_fields_used.append("rank→number")
                    if "action" in step and "title" not in step:
                        legacy_fields_used.append("action→title")
                    if "expected_impact" in step and "description" not in step:
                        legacy_fields_used.append("expected_impact→description")

                    if legacy_fields_used:
                        logger.warning(
                            "next_step_legacy_fields_detected",
                            legacy_fields=legacy_fields_used,
                            step_index=idx,
                            note="LLM produced deprecated next_step format. Update prompts to use canonical fields.",
                        )

                    # Map LLM output fields to NextStepOption fields
                    # Support both legacy (rank/action) and new (number/title) formats
                    # DEPRECATED: Legacy field mapping - prompts should use canonical fields
                    number = step.get("number") or step.get("rank", idx + 1)
                    title = step.get("title") or step.get("action", "")
                    description = step.get("description") or step.get("expected_impact")
                    step_id = step.get("id", f"step_{number}")

                    # Extract action_type with fallback to "continue"
                    action_type_str = step.get("action_type", "continue")
                    try:
                        action_type = ActionType(action_type_str)
                    except ValueError:
                        action_type = ActionType.CONTINUE

                    # Extract target_agent for cross-domain routing
                    target_agent = step.get("target_agent")

                    # Extract parameters for context passing
                    parameters = step.get("parameters")

                    next_steps.append(
                        NextStepOption(
                            id=step_id,
                            number=number,
                            title=title,
                            description=description,
                            action_type=action_type,
                            target_agent=target_agent,
                            tool_name=step.get("tool_name"),
                            parameters=parameters,
                        )
                    )

                    # Log cross-domain handoff detection for observability
                    if action_type == ActionType.ROUTE and target_agent:
                        logger.debug(
                            "next_step_cross_domain_handoff_detected",
                            step_id=step_id,
                            target_agent=target_agent,
                            has_parameters=parameters is not None,
                            parameter_keys=(
                                list(parameters.keys()) if parameters else []
                            ),
                        )

                except (ValueError, KeyError) as e:
                    # Log and skip malformed next step
                    logger.warning(
                        "malformed_next_step",
                        step=step,
                        error=str(e),
                    )
                    continue

        return next_steps if next_steps else None

    def _generate_handoff_recommendations(
        self,
        state: AgentState,  # noqa: ARG002
        output: AgentOutput,  # noqa: ARG002
    ) -> list[Any]:
        """
        Generate cross-domain handoff recommendations.

        Args:
            state: Agent state
            output: Agent output

        Returns:
            List of HandoffRecommendation objects
        """
        # Use mixin method if available (DomainAgentOutputMixin provides these)
        # For now, return empty - will be populated via mixin when integrated
        return []

    def _build_domain_output(
        self,
        agent_output: AgentOutput,
        handoff_recommendations: list[Any],
    ) -> Any:
        """
        Build DomainAgentOutput with handoff recommendations.

        Args:
            agent_output: Base agent output
            handoff_recommendations: List of handoff recommendations

        Returns:
            DomainAgentOutput with handoffs
        """
        from starboard_server.domain.models.agent_output import DomainAgentOutput

        # Format primary answer
        primary_answer = self._format_primary_answer(agent_output)

        # Extract in-domain next steps
        in_domain_steps = self._extract_in_domain_next_steps(agent_output)

        return DomainAgentOutput(
            primary_answer=primary_answer,
            in_domain_next_steps=tuple(in_domain_steps) if in_domain_steps else None,
            handoff_recommendations=tuple(handoff_recommendations),
            metadata={
                "agent_output": {
                    "status": agent_output.status,
                    "tokens_used": agent_output.tokens_used,
                    "cost_usd": agent_output.cost_usd,
                    "duration_seconds": agent_output.duration_seconds,
                    "steps_taken": agent_output.steps_taken,
                    "recommendations": agent_output.recommendations,
                    "reasoning_trace": agent_output.reasoning_trace,
                    "tools_used": agent_output.tools_used,
                }
            },
        )

    def _format_primary_answer(self, output: AgentOutput) -> str:
        """
        Format primary answer from agent output.

        Args:
            output: Agent output

        Returns:
            Formatted answer string
        """
        from starboard_server.agents.report_formatters import format_agent_report

        if not output.complete_report or not isinstance(output.complete_report, dict):
            # No report, create simple message
            if output.recommendations:
                rec_count = len(output.recommendations)
                return f"Analysis complete. Found {rec_count} recommendation{'s' if rec_count != 1 else ''}."
            return "Analysis complete."

        # Use centralized formatter
        return format_agent_report(output.complete_report)

    def _extract_in_domain_next_steps(self, output: AgentOutput) -> list[Any]:  # noqa: ARG002
        """
        Extract actionable in-domain next steps.

        NOTE: This should use DomainAgentOutputMixin methods when integrated.
        For now, returns empty list to maintain clean separation.

        Args:
            output: Agent output

        Returns:
            List of InDomainNextStep objects
        """
        # Will be populated via mixin when integrated
        return []

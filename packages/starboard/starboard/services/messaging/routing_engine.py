# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Routing engine for agent-to-agent handoffs.

Phase 3 Component 2: Routing Decision Engine

Determines when and where to route conversations based on user option
selections. Routes conversations to specialized agents seamlessly.

Examples:
    >>> from starboard.services.messaging.routing_engine import RoutingEngine
    >>> from starboard.agents.config.registry import agent_registry
    >>>
    >>> engine = RoutingEngine(registry=agent_registry)
    >>>
    >>> # User selects option that routes to performance analyzer
    >>> decision = engine.should_route(
    ...     selected_option=option,
    ...     current_agent="query_optimizer",
    ...     conversation_summary="User analyzing query performance",
    ... )
    >>>
    >>> if decision.should_route:
    ...     print(f"Routing to {decision.target_agent_id}")
    ...     print(f"Context: {decision.handoff_context}")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starboard.agents.config.registry import AgentRegistry
from starboard.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RoutingDecision:
    """Decision about routing to another agent.

    Represents the outcome of analyzing a selected option to determine
    if it requires routing to a different agent.

    Attributes:
        should_route: Whether routing is needed
        target_agent_id: ID of target agent (None if no routing)
        capability_id: Capability being invoked (None if not determined)
        handoff_context: Context to pass to target agent
        confidence: Confidence level (0.0-1.0) in routing decision
        reasoning: Human-readable explanation of decision

    Examples:
        >>> # Routing needed
        >>> decision = RoutingDecision(
        ...     should_route=True,
        ...     target_agent_id="performance_analyzer",
        ...     capability_id="identify_slow_queries",
        ...     handoff_context={"warehouse_id": "prod_dw"},
        ...     confidence=1.0,
        ...     reasoning="Explicit routing to Performance Analyzer",
        ... )
        >>>
        >>> # No routing needed
        >>> decision = RoutingDecision(
        ...     should_route=False,
        ...     target_agent_id=None,
        ...     capability_id=None,
        ...     handoff_context={},
        ...     confidence=1.0,
        ...     reasoning="Tool call does not require routing",
        ... )
    """

    should_route: bool
    target_agent_id: str | None
    capability_id: str | None
    handoff_context: dict[str, Any]
    confidence: float
    reasoning: str


class RoutingEngine:
    """Determines when and where to route conversations.

    The routing engine analyzes selected options to determine if they
    require routing to a different specialized agent. Only options with
    action_type="route" trigger routing.

    Attributes:
        registry: AgentRegistry for looking up target agents

    Examples:
        >>> engine = RoutingEngine(registry=agent_registry)
        >>>
        >>> # Check if option requires routing
        >>> decision = engine.should_route(
        ...     selected_option=option,
        ...     current_agent="query_optimizer",
        ...     conversation_summary="User asked about performance",
        ... )
        >>>
        >>> if decision.should_route:
        ...     # Initiate handoff
        ...     handoff_manager.initiate_handoff(decision)
    """

    def __init__(self, registry: AgentRegistry) -> None:
        """Initialize routing engine.

        Args:
            registry: AgentRegistry for agent lookup
        """
        self.registry = registry

    def should_route(
        self,
        selected_option: NextStepOption,
        current_agent: str,
        conversation_summary: str,
    ) -> RoutingDecision:
        """Determine if selected option requires routing to another agent.

        Only options with action_type="route" trigger routing. Tool calls
        and continue actions stay with the current agent.

        Args:
            selected_option: The option user selected
            current_agent: ID of current agent
            conversation_summary: Brief summary of conversation so far

        Returns:
            RoutingDecision with target agent and context

        Examples:
            >>> # Route option triggers routing
            >>> option = NextStepOption(
            ...     action_type=ActionType.ROUTE,
            ...     target_agent="performance_analyzer",
            ...     ...
            ... )
            >>> decision = engine.should_route(option, "query_optimizer", "...")
            >>> assert decision.should_route is True
            >>>
            >>> # Tool call doesn't trigger routing
            >>> option = NextStepOption(
            ...     action_type=ActionType.TOOL_CALL,
            ...     tool_name="optimize_query",
            ...     ...
            ... )
            >>> decision = engine.should_route(option, "query_optimizer", "...")
            >>> assert decision.should_route is False
        """
        # Check if option explicitly specifies routing
        if selected_option.action_type == ActionType.ROUTE:
            return self._handle_routing(
                selected_option=selected_option,
                current_agent=current_agent,
                conversation_summary=conversation_summary,
            )

        # For non-routing options, no routing needed
        return RoutingDecision(
            should_route=False,
            target_agent_id=None,
            capability_id=None,
            handoff_context={},
            confidence=1.0,
            reasoning="Option does not require agent routing",
        )

    def _handle_routing(
        self,
        selected_option: NextStepOption,
        current_agent: str,
        conversation_summary: str,
    ) -> RoutingDecision:
        """Handle routing logic for route action type.

        Args:
            selected_option: Selected option with route action
            current_agent: Current agent ID
            conversation_summary: Conversation summary

        Returns:
            RoutingDecision with routing details or failure
        """
        # Look up target agent in registry
        target_agent = self.registry.get_agent(selected_option.target_agent)  # type: ignore[arg-type]

        if not target_agent:
            logger.error(
                "routing_target_not_found",
                target_agent_id=selected_option.target_agent,
                option_id=selected_option.id,
            )
            return RoutingDecision(
                should_route=False,
                target_agent_id=None,
                capability_id=None,
                handoff_context={},
                confidence=0.0,
                reasoning="Target agent not found in registry",
            )

        # Build handoff context
        handoff_context = self._build_handoff_context(
            selected_option=selected_option,
            current_agent=current_agent,
            conversation_summary=conversation_summary,
        )

        # Infer capability from option
        capability_id = self._infer_capability(
            target_agent_metadata=target_agent,
            selected_option=selected_option,
        )

        return RoutingDecision(
            should_route=True,
            target_agent_id=target_agent.agent_id,
            capability_id=capability_id,
            handoff_context=handoff_context,
            confidence=1.0,
            reasoning=f"Explicit routing to {target_agent.agent_name}",
        )

    def _build_handoff_context(
        self,
        selected_option: NextStepOption,
        current_agent: str,
        conversation_summary: str,
    ) -> dict[str, Any]:
        """Build context to pass to target agent.

        Args:
            selected_option: Selected option
            current_agent: Current agent ID
            conversation_summary: Conversation summary

        Returns:
            Dictionary with handoff context

        Examples:
            >>> context = engine._build_handoff_context(...)
            >>> context.keys()
            dict_keys(['source_agent', 'handoff_reason', 'parameters', 'conversation_summary'])
        """
        return {
            "source_agent": current_agent,
            "handoff_reason": selected_option.title,
            "parameters": selected_option.parameters or {},
            "conversation_summary": conversation_summary,
        }

    def _infer_capability(
        self,
        target_agent_metadata: Any,  # AgentMetadata from registry
        selected_option: NextStepOption,
    ) -> str | None:
        """Infer which capability the option is invoking.

        Matches option title/description to capability keywords to determine
        which specific capability is being invoked.

        Args:
            target_agent_metadata: Metadata of target agent
            selected_option: Selected option

        Returns:
            Capability ID if match found, None otherwise

        Examples:
            >>> # Option with "slowest queries" should match
            >>> # capability with keywords ("slow", "slowest", "queries")
            >>> capability_id = engine._infer_capability(agent, option)
            >>> capability_id
            'identify_slow_queries'
        """
        # Build searchable text from option
        option_text = (
            f"{selected_option.title} {selected_option.description or ''}".lower()
        )

        best_match = None
        best_score = 0.0

        # Score each capability by keyword matches
        for cap in target_agent_metadata.capabilities:
            score = sum(1 for kw in cap.keywords if kw.lower() in option_text)

            if score > best_score:
                best_score = score
                best_match = cap.capability_id

        return best_match

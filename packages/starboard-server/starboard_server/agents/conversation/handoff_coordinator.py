"""
Agent handoff coordination for multi-agent routing.

Handles:
- Intent classification and routing decisions
- Agent handoff coordination between domains
- Clarification handling for ambiguous requests
- Specialist agent execution coordination

Extracted from MultiAgentConversationManager for clean separation of concerns.
Follows Single Responsibility Principle - only coordinates agent handoffs.

Design:
- Delegates intent classification to IntentRouter
- Uses ClarificationHandler for user clarification
- Coordinates specialist agent selection via AgentFactory
- Records transitions in shared context

Example:
    >>> coordinator = AgentHandoffCoordinator(
    ...     intent_router=router,
    ...     agent_factory=factory,
    ...     disabled_domains=["compute"],
    ... )
    >>>
    >>> # Classify and route
    >>> route_decision = await coordinator.classify_and_route(
    ...     user_message="Optimize query q123",
    ...     conversation_history=[...],
    ...     conversation_id="conv_123",
    ... )
    >>>
    >>> if route_decision.should_route():
    ...     specialist = coordinator.get_specialist(
    ...         domain=route_decision.domain,
    ...         conversation_config={...},
    ...     )
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from starboard_server.agents.agent_factory import AgentFactory
from starboard_server.agents.clarification.clarification_handler import (
    ClarificationHandler,
)
from starboard_server.agents.clarification.clarification_response_parser import (
    ClarificationResponseParser,
)
from starboard_server.agents.events import StreamingEvent
from starboard_server.agents.events.user_events import FinalOutputEvent
from starboard_server.agents.routing.intent_router import IntentRouter
from starboard_server.agents.routing.routing_models import (
    AgentDomain,
    AgentTransition,
    RouteDecision,
)
from starboard_server.agents.state.agent_state import Message
from starboard_server.agents.state.shared_context import SharedAgentContext
from starboard_server.api.models import ChatEvent, EventType
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class AgentHandoffCoordinator:
    """
    Coordinates agent handoffs and routing in multi-agent system.

    Responsibilities:
    - Classify user intent and make routing decisions
    - Handle clarification when intent is ambiguous
    - Coordinate specialist agent selection
    - Record agent transitions in shared context
    - Generate routing and transition events

    Does NOT:
    - Execute specialist agents (that's the facade's job)
    - Manage conversation CRUD (ConversationLifecycleManager)
    - Handle SSE broadcasting (EventBroadcastManager)
    - Process message queues (MessageQueueProcessor)

    Example:
        >>> coordinator = AgentHandoffCoordinator(
        ...     intent_router=router,
        ...     agent_factory=factory,
        ...     disabled_domains=[],
        ... )
        >>>
        >>> # Classify intent
        >>> route_decision = await coordinator.classify_and_route(
        ...     user_message="Optimize job 456",
        ...     conversation_history=[...],
        ...     conversation_id="conv_123",
        ... )
        >>>
        >>> # Get specialist if routing
        >>> if route_decision.should_route():
        ...     specialist = coordinator.get_specialist(
        ...         domain=route_decision.domain,
        ...         conversation_config=config,
        ...     )
    """

    def __init__(
        self,
        intent_router: IntentRouter,
        agent_factory: AgentFactory,
        disabled_domains: list[str] | None = None,
    ):
        """
        Initialize agent handoff coordinator.

        Args:
            intent_router: Router for classifying user intent
            agent_factory: Factory for creating domain-specific agents
            disabled_domains: List of disabled domain keys
        """
        self.intent_router = intent_router
        self.agent_factory = agent_factory
        self.disabled_domains = disabled_domains or []

        # Track clarification pending state per conversation
        self._clarification_pending: dict[str, bool] = {}

    async def classify_and_route(
        self,
        user_message: str,
        conversation_history: tuple[Message, ...] | list[Message],
        conversation_id: str,
        attachments: list[dict] | None = None,
    ) -> RouteDecision:
        """
        Classify user intent and make routing decision.

        Handles three paths:
        1. Large file attachments -> route to diagnostic (deterministic)
        2. If user is responding to clarification -> parse response directly
        3. Otherwise -> use IntentRouter to classify intent

        Args:
            user_message: User's input message
            conversation_history: Full conversation history
            conversation_id: Unique conversation identifier
            attachments: Optional list of file attachments

        Returns:
            RouteDecision with domain, confidence, and reasoning

        Example:
            >>> route_decision = await coordinator.classify_and_route(
            ...     user_message="Optimize query q123",
            ...     conversation_history=[...],
            ...     conversation_id="conv_123",
            ... )
            >>> print(route_decision.domain)  # "query"
        """
        logger.debug("classifying_intent", conversation_id=conversation_id)

        # Check if user is responding to a clarification prompt
        clarification_response = self._parse_clarification_response(
            user_message, conversation_id
        )

        if clarification_response:
            # User responded to clarification - route directly without LLM call
            # Clear the pending flag since we're handling the response
            self._clarification_pending[conversation_id] = False

            logger.debug(
                "clarification_response_detected",
                user_input=user_message,
                detected_domain=clarification_response,
            )

            # Create a high-confidence route decision
            route_decision = RouteDecision(
                domain=cast(AgentDomain, clarification_response),
                confidence=0.95,
                extracted_ids={},
                context={},
                clarification_needed=False,
                reasoning=f"User selected '{clarification_response}' in response to clarification prompt",
            )
        else:
            # Normal routing with LLM (passes attachments for large file detection)
            route_decision = await self.intent_router.classify_intent(
                user_message,
                list(conversation_history),
                attachments=attachments,
            )

        logger.debug(
            "routing_decision",
            domain=route_decision.domain,
            confidence=route_decision.confidence,
            reasoning=route_decision.reasoning,
        )

        return route_decision

    def _parse_clarification_response(
        self, user_input: str, conversation_id: str
    ) -> str | None:
        """
        Parse user response to clarification prompt.

        Detects if we just sent a clarification prompt and parses
        the user's response (number or keyword) to a domain.

        Args:
            user_input: User's message
            conversation_id: Conversation ID

        Returns:
            Domain string if clarification response detected, None otherwise
        """
        # Check if we just sent a clarification
        if not self._clarification_pending.get(conversation_id, False):
            return None

        # Use ClarificationResponseParser to parse the response
        from starboard_server.agents.clarification.clarification_handler import (
            DEFAULT_DOMAIN_OPTIONS,
        )

        parser = ClarificationResponseParser(
            domain_options=DEFAULT_DOMAIN_OPTIONS,
            disabled_domains=self.disabled_domains,
        )

        return parser.parse(user_input)

    def should_request_clarification(self, route_decision: RouteDecision) -> bool:
        """
        Check if clarification should be requested from user.

        Args:
            route_decision: Routing decision from classification

        Returns:
            True if clarification needed, False otherwise
        """
        return not route_decision.should_route()

    def generate_clarification_events(
        self, conversation_id: str
    ) -> list[StreamingEvent | FinalOutputEvent]:
        """
        Generate clarification events for user.

        Uses ClarificationHandler to generate user-facing events asking
        which domain they want to use.

        Args:
            conversation_id: Conversation ID for tracking

        Returns:
            List of StreamingEvent or FinalOutputEvent objects

        Example:
            >>> events = coordinator.generate_clarification_events("conv_123")
            >>> for event in events:
            ...     yield event
        """
        clarification_handler = ClarificationHandler(
            disabled_domains=self.disabled_domains
        )

        # Check if any options are available
        if not clarification_handler.has_available_options():
            logger.warning(
                "all_domains_disabled_no_clarification",
                conversation_id=conversation_id,
            )
            return []

        # Generate clarification events
        events = list(clarification_handler.generate_clarification_events())

        # Mark that we're waiting for clarification response
        self._clarification_pending[conversation_id] = True

        return events  # type: ignore[return-value]

    def create_routing_event(self, route_decision: RouteDecision) -> ChatEvent:
        """
        Create routing decision event for broadcasting.

        Args:
            route_decision: Routing decision to broadcast

        Returns:
            ChatEvent with routing information
        """
        return ChatEvent(
            event_id=f"evt_{uuid4().hex[:12]}",
            type=EventType.ROUTING_DECISION,
            data={
                "domain": route_decision.domain,
                "confidence": route_decision.confidence,
                "reasoning": route_decision.reasoning,
                "clarification_needed": not route_decision.should_route(),
            },
            timestamp=datetime.now(UTC),
        )

    def create_friendly_name_event(
        self, route_decision: RouteDecision, user_message: str | None = None
    ) -> ChatEvent | None:
        """
        Create friendly name update event if routing.

        Args:
            route_decision: Routing decision
            user_message: Optional user message for context

        Returns:
            ChatEvent with friendly name, or None if not routing
        """
        if not route_decision.should_route():
            return None

        # Use lifecycle manager's name generation logic
        # (we don't have an instance, so we'll duplicate the logic)
        friendly_name = self._generate_friendly_name(
            domain=route_decision.domain,
            extracted_ids=route_decision.extracted_ids,
            user_message=user_message,
        )

        return ChatEvent(
            event_id=f"evt_{uuid4().hex[:12]}",
            type=EventType.FRIENDLY_NAME_UPDATE,
            data={"friendly_name": friendly_name},
            timestamp=datetime.now(UTC),
        )

    def _generate_friendly_name(
        self,
        domain: str,
        extracted_ids: dict[str, str],
        user_message: str | None = None,
    ) -> str:
        """
        Generate friendly name for conversation.

        Prioritizes topical, concise names over raw user message echoing.
        Format: "{Domain Action}: {identifier or topic}"

        Args:
            domain: Agent domain
            extracted_ids: Extracted IDs from routing
            user_message: Optional user message for context

        Returns:
            Friendly conversation name (max 60 chars)
        """
        import re

        # Map domain to friendly action prefixes
        domain_prefixes = {
            "query": "Query Optimization",
            "job": "Job Optimization",
            "uc": "Unity Catalog",
            "cluster": "Cluster Analysis",
            "warehouse": "Warehouse Analysis",
            "diagnostic": "Diagnostics",
            "analytics": "Cost Analysis",
        }

        prefix = domain_prefixes.get(domain, "Conversation")

        # Primary ID keys by domain
        primary_id_keys = {
            "query": ["query_id", "statement_id"],
            "job": ["job_id", "job_name", "run_id"],
            "uc": ["table_name", "catalog", "schema"],
            "cluster": ["cluster_id"],
            "warehouse": ["warehouse_id"],
            "diagnostic": ["error_id", "issue_id"],
            "analytics": ["metric_name", "report_id"],
        }

        # PRIORITY 1: If we have a specific ID, use prefix + ID
        # This gives clear technical names like "Job Optimization: 781745507530049"
        if extracted_ids:
            keys_to_try = primary_id_keys.get(domain, [])
            for key in keys_to_try:
                if key in extracted_ids:
                    value = extracted_ids[key]
                    # Truncate very long IDs (like UUIDs)
                    if len(value) > 20:
                        value = f"{value[:8]}...{value[-8:]}"
                    return f"{prefix}: {value}"

        # PRIORITY 2: Extract topic from user message
        if user_message:
            context = user_message.strip()

            # Strip [Option N] prefix from user message (from next step selections)
            option_pattern = r"^\[Option \d+\]\s*"
            context = re.sub(option_pattern, "", context)

            # Skip messages that are mostly IDs (e.g., "The job is 781745507530049")
            # These should use the extracted_ids path above
            id_pattern = r"^\s*(?:the\s+)?\w+\s+(?:is|id|:)\s*\d{5,}\s*$"
            if re.match(id_pattern, context, re.IGNORECASE):
                # Extract the ID and use prefix format
                id_match = re.search(r"(\d{5,})", context)
                if id_match:
                    return f"{prefix}: {id_match.group(1)}"

            # Extract key topic phrases for analytics queries
            topic_patterns = [
                (r"top\s*\d*\s*(?:most\s+)?expensive\s+(\w+)", r"Top Expensive \1"),
                (r"cost\s+(?:of|for|by)\s+(\w+)", r"Cost Analysis: \1"),
                (r"(?:show|list|get)\s+(?:me\s+)?(?:my\s+)?(\w+)", r"\1 Overview"),
                (r"how\s+much\s+(?:did|do)\s+(?:I|we)\s+spend", "Spend Analysis"),
                (r"dbu\s+(?:usage|consumption|cost)", "DBU Usage"),
            ]

            for pattern, replacement in topic_patterns:
                match = re.search(pattern, context, re.IGNORECASE)
                if match:
                    # Use the replacement pattern
                    topic = re.sub(
                        pattern, replacement, match.group(0), flags=re.IGNORECASE
                    )
                    topic = topic.strip().title()
                    return topic[:60]

            # Fallback: Clean and truncate the user message
            context = context[:50]
            if context:
                context = context[0].upper() + context[1:]
                context = context.rstrip(".!?,")
                # If message is short and not useful, fall back to prefix
                if len(context) < 10:
                    return prefix
                return context

        # PRIORITY 3: Fall back to just the domain prefix
        return prefix

    def get_specialist(
        self,
        domain: AgentDomain,
        conversation_config: dict[str, Any] | None = None,
    ) -> Any:
        """
        Get specialist agent for domain.

        Args:
            domain: Agent domain (query, job, table, compute, diagnostic, analytics)
            conversation_config: Optional conversation-specific configuration

        Returns:
            DomainAgent instance for the specialist

        Example:
            >>> specialist = coordinator.get_specialist(
            ...     domain="query",
            ...     conversation_config={"temperature": 0.4},
            ... )
        """
        return self.agent_factory.get_agent(
            domain,  # type: ignore[arg-type]
            conversation_config=conversation_config,
        )

    def record_transition(
        self,
        shared_context: SharedAgentContext,
        route_decision: RouteDecision,
        from_agent: str = "router",
    ) -> AgentTransition:
        """
        Record agent transition in shared context.

        Args:
            shared_context: Shared agent context to update
            route_decision: Routing decision
            from_agent: Source agent name (default: "router")

        Returns:
            AgentTransition object that was added

        Example:
            >>> transition = coordinator.record_transition(
            ...     shared_context=context,
            ...     route_decision=route_decision,
            ... )
        """
        transition = AgentTransition(
            from_agent=from_agent,
            to_agent=route_decision.domain,
            timestamp=datetime.now(UTC),
            reason=route_decision.reasoning,
            context_passed=route_decision.context,
        )

        shared_context.add_transition(transition)

        logger.debug(
            "agent_transition_recorded",
            from_agent=from_agent,
            to_agent=route_decision.domain,
        )

        return transition

    def create_transition_event(self, transition: AgentTransition) -> ChatEvent:
        """
        Create agent transition event for broadcasting.

        Args:
            transition: Agent transition to broadcast

        Returns:
            ChatEvent with transition information
        """
        return ChatEvent(
            event_id=f"evt_{uuid4().hex[:12]}",
            type=EventType.AGENT_TRANSITION,
            data={
                "from_agent": transition.from_agent,
                "to_agent": transition.to_agent,
                "reason": transition.reason,
                "context_passed": transition.context_passed,
            },
            timestamp=transition.timestamp,
        )

    def clear_clarification_pending(self, conversation_id: str) -> None:
        """
        Clear clarification pending state for conversation.

        Args:
            conversation_id: Conversation ID
        """
        if conversation_id in self._clarification_pending:
            del self._clarification_pending[conversation_id]

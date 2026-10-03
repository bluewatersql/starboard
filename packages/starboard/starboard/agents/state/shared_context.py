# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Shared context for multi-agent conversations (Phase 3, Task 3.1).

This module provides the `SharedAgentContext` dataclass that maintains state
across multiple agents in a conversation. It tracks conversation history,
working memory, and agent transitions for coordinated multi-agent reasoning.

Key Features:
- Immutable conversation history
- Shared working memory across agents
- Agent transition tracking (handoffs)
- Serialization for persistence
- Context passing between specialist agents

Design:
- Each conversation has one SharedAgentContext
- Router and specialists read/update the shared context
- Context persists across agent transitions
- Working memory accumulates across agents
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from starboard.agents.routing.routing_models import AgentTransition
from starboard.agents.state.agent_state import Message, WorkingMemory
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SharedAgentContext:
    """
    Context shared across all agents in a multi-agent conversation.

    This context maintains state that needs to be accessible to all agents:
    - Conversation history (all messages exchanged)
    - Working memory (accumulated facts and summaries)
    - Agent transitions (handoffs between specialists)

    The context is passed to each specialist agent and updated as the
    conversation progresses through multiple agent invocations.

    Attributes:
        conversation_id: Unique conversation identifier
        user_id: User identifier (for multi-tenancy)
        conversation_history: All messages in the conversation
        working_memory: Accumulated working memory from all agents
        agent_transitions: Record of agent handoffs
        metadata: Additional conversation-level metadata

    Example:
        >>> # Create new context
        >>> context = SharedAgentContext(
        ...     conversation_id="conv_123",
        ...     user_id="user_456",
        ...     conversation_history=[
        ...         Message(role="user", content="Optimize query abc123")
        ...     ],
        ...     working_memory=WorkingMemory(),
        ... )
        >>>
        >>> # Add agent transition
        >>> transition = AgentTransition(
        ...     from_agent="router",
        ...     to_agent="query",
        ...     timestamp=datetime.now(timezone.utc),
        ...     reason="User provided statement_id",
        ...     context_passed={"statement_id": "abc123"}
        ... )
        >>> context.add_transition(transition)
        >>>
        >>> # Serialize for agent context
        >>> agent_ctx = context.to_dict()
        >>> # Pass to specialist agent
        >>> await specialist.run(context=agent_ctx)
    """

    conversation_id: str
    user_id: str
    conversation_history: list[Message]
    working_memory: WorkingMemory
    agent_transitions: list[AgentTransition] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate context after initialization."""
        if not self.conversation_id:
            raise ValueError("conversation_id cannot be empty")

        if not self.user_id:
            raise ValueError("user_id cannot be empty")

        # Ensure conversation_history is a list (not tuple or other)
        if not isinstance(self.conversation_history, list):
            raise TypeError(
                f"conversation_history must be a list, got {type(self.conversation_history)}"
            )

        # Ensure all messages are Message instances
        for msg in self.conversation_history:
            if not isinstance(msg, Message):
                raise TypeError(
                    f"All conversation_history items must be Message instances, "
                    f"got {type(msg)}"
                )

        # Ensure working_memory is WorkingMemory instance
        if not isinstance(self.working_memory, WorkingMemory):
            raise TypeError(
                f"working_memory must be a WorkingMemory instance, "
                f"got {type(self.working_memory)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert context to dictionary for agent consumption.

        This method serializes the shared context into a dictionary format
        that can be passed to specialist agents as their context parameter.
        The dictionary includes all necessary information for the agent to
        understand the conversation state and history.

        Returns:
            Dictionary with serialized context

        Example:
            >>> context = SharedAgentContext(...)
            >>> agent_ctx = context.to_dict()
            >>> await agent.run(context=agent_ctx)
            >>>
            >>> # Result structure:
            >>> {
            ...     "conversation_id": "conv_123",
            ...     "user_id": "user_456",
            ...     "conversation_history": [
            ...         {"role": "user", "content": "...", "metadata": {}},
            ...         {"role": "assistant", "content": "...", "metadata": {}},
            ...     ],
            ...     "working_memory": {
            ...         "summaries": {...},
            ...         "facts": [...],
            ...         "tools_used": [...],
            ...         ...
            ...     },
            ...     "agent_transitions": [
            ...         {
            ...             "from_agent": "router",
            ...             "to_agent": "query",
            ...             "reason": "...",
            ...             "timestamp": "2025-11-18T13:00:00Z",
            ...             "context_passed": {...}
            ...         }
            ...     ],
            ...     "metadata": {...}
            ... }
        """
        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "conversation_history": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "name": msg.name,
                    "tool_call_id": msg.tool_call_id,
                    "metadata": msg.metadata,
                }
                for msg in self.conversation_history
            ],
            "working_memory": self.working_memory.to_dict(),
            "agent_transitions": [
                {
                    "from_agent": t.from_agent,
                    "to_agent": t.to_agent,
                    "reason": t.reason,
                    "timestamp": t.timestamp.isoformat(),
                    "context_passed": t.context_passed,
                }
                for t in self.agent_transitions
            ],
            "metadata": self.metadata,
        }

    def add_transition(self, transition: AgentTransition) -> None:
        """
        Record an agent transition (handoff).

        This method tracks when control passes from one agent to another,
        recording the transition for observability and debugging. Transitions
        are logged and appended to the transition history.

        Args:
            transition: AgentTransition describing the handoff

        Example:
            >>> context = SharedAgentContext(...)
            >>>
            >>> # Router hands off to query agent
            >>> transition = AgentTransition(
            ...     from_agent="router",
            ...     to_agent="query",
            ...     timestamp=datetime.now(timezone.utc),
            ...     reason="User provided statement_id: abc123",
            ...     context_passed={"statement_id": "abc123"}
            ... )
            >>> context.add_transition(transition)
            >>>
            >>> # Check transition history
            >>> len(context.agent_transitions)
            1
            >>> context.agent_transitions[0].to_agent
            'query'
        """
        if not isinstance(transition, AgentTransition):
            raise TypeError(
                f"transition must be an AgentTransition instance, "
                f"got {type(transition)}"
            )

        self.agent_transitions.append(transition)

        logger.debug(
            f"Agent transition: {transition.from_agent} → {transition.to_agent}",
            extra={
                "from_agent": transition.from_agent,
                "to_agent": transition.to_agent,
                "reason": transition.reason,
                "context_keys": (
                    list(transition.context_passed.keys())
                    if transition.context_passed
                    else []
                ),
                "timestamp": transition.timestamp.isoformat(),
            },
        )

    def add_message(self, message: Message) -> None:
        """
        Add a message to conversation history.

        Convenience method to append a message to the conversation history
        with validation.

        Args:
            message: Message to add

        Example:
            >>> context = SharedAgentContext(...)
            >>> context.add_message(
            ...     Message(role="user", content="Optimize this query")
            ... )
            >>> len(context.conversation_history)
            1
        """
        if not isinstance(message, Message):
            raise TypeError(f"message must be a Message instance, got {type(message)}")

        self.conversation_history.append(message)

    def get_last_user_message(self) -> Message | None:
        """
        Get the most recent user message.

        Returns:
            Last user message or None if no user messages exist

        Example:
            >>> context = SharedAgentContext(...)
            >>> context.add_message(Message(role="user", content="Hello"))
            >>> context.add_message(Message(role="assistant", content="Hi"))
            >>> last_user = context.get_last_user_message()
            >>> last_user.content
            'Hello'
        """
        for msg in reversed(self.conversation_history):
            if msg.role == "user":
                return msg
        return None

    def get_transition_count(self) -> int:
        """
        Get total number of agent transitions.

        Returns:
            Count of agent transitions

        Example:
            >>> context = SharedAgentContext(...)
            >>> context.add_transition(AgentTransition(...))
            >>> context.add_transition(AgentTransition(...))
            >>> context.get_transition_count()
            2
        """
        return len(self.agent_transitions)

    def get_current_agent(self) -> str | None:
        """
        Get the current agent (from last transition).

        Returns:
            Agent name or None if no transitions

        Example:
            >>> context = SharedAgentContext(...)
            >>> context.add_transition(
            ...     AgentTransition(
            ...         from_agent="router",
            ...         to_agent="query",
            ...         timestamp=datetime.now(timezone.utc),
            ...         reason="...",
            ...         context_passed={}
            ...     )
            ... )
            >>> context.get_current_agent()
            'query'
        """
        if not self.agent_transitions:
            return None
        return self.agent_transitions[-1].to_agent

    def merge_working_memory(self, other_memory: WorkingMemory) -> None:
        """
        Merge another working memory into this context.

        This allows accumulating working memory from multiple agent executions.
        Uses the WorkingMemory.merge() method to combine facts, summaries, etc.

        Args:
            other_memory: WorkingMemory to merge

        Example:
            >>> context = SharedAgentContext(
            ...     working_memory=WorkingMemory(facts=["fact1"])
            ... )
            >>> new_memory = WorkingMemory(facts=["fact2"])
            >>> context.merge_working_memory(new_memory)
            >>> len(context.working_memory.facts)
            2
        """
        if not isinstance(other_memory, WorkingMemory):
            raise TypeError(
                f"other_memory must be a WorkingMemory instance, "
                f"got {type(other_memory)}"
            )

        # Merge working memories (this creates a new WorkingMemory)
        self.working_memory = self.working_memory.merge(other_memory)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SharedAgentContext":
        """
        Create SharedAgentContext from dictionary.

        This is the inverse of to_dict(), useful for deserializing context
        from storage or API responses.

        Args:
            data: Dictionary with context data

        Returns:
            SharedAgentContext instance

        Raises:
            ValueError: If required fields are missing or invalid

        Example:
            >>> data = {
            ...     "conversation_id": "conv_123",
            ...     "user_id": "user_456",
            ...     "conversation_history": [
            ...         {"role": "user", "content": "Hello"}
            ...     ],
            ...     "working_memory": {...},
            ...     "agent_transitions": [],
            ...     "metadata": {}
            ... }
            >>> context = SharedAgentContext.from_dict(data)
            >>> context.conversation_id
            'conv_123'
        """
        # Reconstruct conversation history
        conversation_history = [
            Message(
                role=msg["role"],
                content=msg["content"],
                name=msg.get("name"),
                tool_call_id=msg.get("tool_call_id"),
                metadata=msg.get("metadata", {}),
            )
            for msg in data.get("conversation_history", [])
        ]

        # Reconstruct working memory
        working_memory_data = data.get("working_memory", {})
        working_memory = WorkingMemory.from_dict(working_memory_data)

        # Reconstruct agent transitions
        agent_transitions = [
            AgentTransition(
                from_agent=t["from_agent"],
                to_agent=t["to_agent"],
                timestamp=datetime.fromisoformat(t["timestamp"]),
                reason=t["reason"],
                context_passed=t.get("context_passed", {}),
            )
            for t in data.get("agent_transitions", [])
        ]

        return cls(
            conversation_id=data["conversation_id"],
            user_id=data["user_id"],
            conversation_history=conversation_history,
            working_memory=working_memory,
            agent_transitions=agent_transitions,
            metadata=data.get("metadata", {}),
        )

    # =========================================================================
    # Phase 2: Context Enrichment Methods (Conversation Extension Pattern)
    # =========================================================================

    def enrich_from_intent(
        self,
        classification: Any,  # IntentClassification (avoid circular import)
    ) -> None:
        """
        Enrich context with entities from intent classification.

        Part of Phase 2: Conversation Extension Pattern. This method adds
        extracted entities from user intent classification to the working
        memory, enabling agents to access user constraints and context.

        Args:
            classification: IntentClassification with extracted entities

        Example:
            >>> from starboard.domain.models.conversation_patterns import (
            ...     IntentClassification, UserIntentType
            ... )
            >>> context = SharedAgentContext(...)
            >>> classification = IntentClassification(
            ...     intent_type=UserIntentType.EXTENSION,
            ...     confidence=0.85,
            ...     reasoning="User added temporal constraint",
            ...     extracted_entities={"timeframe": "morning", "warehouse": "prod_dw"},
            ... )
            >>> context.enrich_from_intent(classification)
            >>> context.get_user_constraints()
            {'timeframe': 'morning', 'warehouse': 'prod_dw'}
        """
        # Store intent metadata
        self.metadata["last_intent"] = {
            "intent_type": classification.intent_type.value,
            "confidence": classification.confidence,
            "reasoning": classification.reasoning,
        }

        # If entities exist, add them to working memory as user constraints
        # Store in metrics dict since WorkingMemory is immutable and facts is a tuple
        if classification.extracted_entities:
            # Get existing constraints from metrics or create new dict
            if "user_constraints" not in self.working_memory.metrics:
                self.working_memory.metrics["user_constraints"] = {}

            # Merge new entities into existing constraints
            self.working_memory.metrics["user_constraints"].update(
                classification.extracted_entities
            )

            logger.debug(
                "Enriched context with entities",
                extra={
                    "intent_type": classification.intent_type.value,
                    "entities": list(classification.extracted_entities.keys()),
                    "total_constraints": len(
                        self.working_memory.metrics["user_constraints"]
                    ),
                },
            )

    def enrich_from_option_selection(
        self,
        parameters: dict[str, Any],
        option_metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Enrich context with parameters from selected next step option.

        When a user selects a next step option, the option may contain
        parameters (e.g., job_id, query_id, warehouse_id) that provide
        context for the agent's next action. This method adds those
        parameters to the working memory so agents can access them.

        This follows the same pattern as enrich_from_intent() but for
        option selection parameters instead of intent entities.

        Args:
            parameters: Parameters from selected_option.parameters
            option_metadata: Optional metadata about the selected option
                (id, action_type, target_agent) for tracking

        Example:
            >>> context = SharedAgentContext(...)
            >>> parameters = {
            ...     "job_id": "31942593021809",
            ...     "handoff_context": "Analyze high-frequency execution"
            ... }
            >>> option_metadata = {
            ...     "id": "analyze_job_1",
            ...     "action_type": "route",
            ...     "target_agent": "job"
            ... }
            >>> context.enrich_from_option_selection(parameters, option_metadata)
            >>> context.get_user_constraints()
            {'job_id': '31942593021809', 'handoff_context': '...'}
        """
        # Handle None parameters gracefully (can happen with continue actions)
        if parameters is None:
            parameters = {}

        # Store option selection metadata for tracking
        self.metadata["last_option_selection"] = {
            "parameters": list(parameters.keys()),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Add option metadata if provided
        if option_metadata:
            self.metadata["last_option_selection"].update(option_metadata)

        # Add parameters to working memory as user constraints
        # Initialize user_constraints dict if it doesn't exist
        if "user_constraints" not in self.working_memory.metrics:
            self.working_memory.metrics["user_constraints"] = {}

        # Merge parameters into constraints (accumulate, don't replace)
        self.working_memory.metrics["user_constraints"].update(parameters)

        logger.debug(
            "enriched_context_from_option_selection",
            parameter_keys=list(parameters.keys()),
            total_constraints=len(self.working_memory.metrics["user_constraints"]),
            option_id=option_metadata.get("id") if option_metadata else None,
            action_type=option_metadata.get("action_type") if option_metadata else None,
        )

    def get_last_option_selection(self) -> dict[str, Any] | None:
        """
        Get last option selection metadata.

        Returns the most recent option selection that was used to
        enrich this context, or None if no enrichment has occurred.

        Returns:
            Dictionary with option selection metadata or None

        Example:
            >>> context = SharedAgentContext(...)
            >>> # After option selection enrichment
            >>> selection = context.get_last_option_selection()
            >>> selection["id"]
            'analyze_job_1'
            >>> selection["action_type"]
            'route'
        """
        return self.metadata.get("last_option_selection")

    def get_conversation_depth(self) -> int:
        """
        Get conversation depth (number of turns).

        A "turn" is defined as a user message. This helps track how deep
        the conversation has progressed, useful for deciding when to
        summarize or simplify context.

        Returns:
            Number of user messages in conversation history

        Example:
            >>> context = SharedAgentContext(...)
            >>> context.add_message(Message(role="user", content="Hello"))
            >>> context.add_message(Message(role="assistant", content="Hi"))
            >>> context.add_message(Message(role="user", content="Help me"))
            >>> context.get_conversation_depth()
            2
        """
        return sum(1 for msg in self.conversation_history if msg.role == "user")

    def get_user_constraints(self) -> dict[str, Any]:
        """
        Get accumulated user constraints from working memory.

        These are entities extracted from user messages via intent
        classification, such as timeframes, warehouse names, metrics, etc.

        Returns:
            Dictionary of user constraints

        Example:
            >>> context = SharedAgentContext(...)
            >>> # After intent enrichment
            >>> constraints = context.get_user_constraints()
            >>> constraints["timeframe"]
            'morning'
            >>> constraints["warehouse"]
            'prod_dw'
        """
        return self.working_memory.metrics.get("user_constraints", {})

    def needs_summarization(self, threshold: int = 10) -> bool:
        """
        Check if conversation needs summarization.

        Long conversations can become unwieldy for agents to process.
        This method checks if the conversation has exceeded a threshold
        and should be summarized to maintain context quality.

        Args:
            threshold: Number of turns before summarization (default: 10)

        Returns:
            True if conversation depth exceeds threshold, False otherwise

        Example:
            >>> context = SharedAgentContext(...)
            >>> # Add many messages...
            >>> if context.needs_summarization():
            ...     summary = generate_summary(context)
            ...     context.mark_as_summarized(summary)
        """
        return self.get_conversation_depth() > threshold

    def mark_as_summarized(self, summary: str) -> None:
        """
        Mark conversation as summarized with summary text.

        This records that a conversation summary has been generated,
        allowing agents to use the summary instead of full history
        for context.

        Args:
            summary: Human-readable summary of conversation so far

        Example:
            >>> context = SharedAgentContext(...)
            >>> context.mark_as_summarized(
            ...     "User asked about query optimization for prod_dw warehouse, "
            ...     "focusing on morning performance."
            ... )
            >>> context.metadata["summarized"]
            True
        """
        self.metadata["summarized"] = True
        self.metadata["summary"] = summary
        self.metadata["summarized_at"] = datetime.now(UTC).isoformat()

        logger.debug(
            "Conversation marked as summarized",
            extra={
                "conversation_id": self.conversation_id,
                "summary_length": len(summary),
                "turns": self.get_conversation_depth(),
            },
        )

    def clear_user_constraints(self) -> None:
        """
        Clear accumulated user constraints.

        Useful when user starts a completely new query (NEW_QUERY intent)
        to avoid carrying over constraints from previous context.

        Example:
            >>> context = SharedAgentContext(...)
            >>> # User asks new unrelated question
            >>> if intent.intent_type == UserIntentType.NEW_QUERY:
            ...     context.clear_user_constraints()
        """
        if "user_constraints" in self.working_memory.metrics:
            self.working_memory.metrics["user_constraints"] = {}

        logger.debug(
            "Cleared user constraints",
            extra={"conversation_id": self.conversation_id},
        )

    def get_last_intent(self) -> dict[str, Any] | None:
        """
        Get last classified intent metadata.

        Returns the most recent intent classification that was used to
        enrich this context, or None if no enrichment has occurred.

        Returns:
            Dictionary with intent metadata or None

        Example:
            >>> context = SharedAgentContext(...)
            >>> # After intent enrichment
            >>> intent = context.get_last_intent()
            >>> intent["intent_type"]
            'extension'
            >>> intent["confidence"]
            0.85
        """
        return self.metadata.get("last_intent")

    # =========================================================================
    # Entity Tracking (Robust Context Passing)
    # =========================================================================

    def track_entity(self, entity_type: str, value: str) -> None:
        """
        Track a discovered entity for cross-agent context passing.

        When tools discover entities (tables, query IDs, job IDs, etc.),
        they should call this method to track them. These entities are
        automatically passed to subsequent agents during handoffs.

        Entities accumulate across conversation turns, ensuring that
        context is preserved when routing between agents.

        Args:
            entity_type: Type of entity (tables, query_ids, job_ids,
                        cluster_ids, warehouse_ids)
            value: The entity value (e.g., "catalog.schema.table")

        Example:
            >>> context = SharedAgentContext(...)
            >>> # Tool discovers a table
            >>> context.track_entity("tables", "cprice_main.core.orders")
            >>> context.track_entity("tables", "cprice_main.core.products")
            >>> # Later, get all discovered entities
            >>> entities = context.get_discovered_entities()
            >>> entities["tables"]
            ['cprice_main.core.orders', 'cprice_main.core.products']
        """
        # Initialize discovered_entities if not present
        if "discovered_entities" not in self.working_memory.metrics:
            self.working_memory.metrics["discovered_entities"] = {}

        entities = self.working_memory.metrics["discovered_entities"]

        # Initialize entity type list if not present
        if entity_type not in entities:
            entities[entity_type] = []

        # Add value if not already tracked (avoid duplicates)
        if value not in entities[entity_type]:
            entities[entity_type].append(value)
            logger.debug(
                "entity_tracked",
                entity_type=entity_type,
                value=value,
                total_count=len(entities[entity_type]),
            )

    def get_discovered_entities(self) -> dict[str, list[str]]:
        """
        Get all discovered entities from the conversation.

        Returns accumulated entities that tools have tracked during
        the conversation. Used for automatic context passing during
        agent handoffs.

        Returns:
            Dictionary mapping entity types to lists of values.
            Empty dict if no entities tracked.

        Example:
            >>> context = SharedAgentContext(...)
            >>> context.track_entity("tables", "main.sales.orders")
            >>> context.track_entity("query_ids", "stmt_abc123")
            >>> entities = context.get_discovered_entities()
            >>> entities
            {'tables': ['main.sales.orders'], 'query_ids': ['stmt_abc123']}
        """
        return self.working_memory.metrics.get("discovered_entities", {})

    def clear_discovered_entities(self) -> None:
        """
        Clear all tracked entities.

        Use when starting a genuinely new topic/query where previous
        context is no longer relevant.

        Example:
            >>> context = SharedAgentContext(...)
            >>> context.track_entity("tables", "old_table")
            >>> context.clear_discovered_entities()
            >>> context.get_discovered_entities()
            {}
        """
        if "discovered_entities" in self.working_memory.metrics:
            self.working_memory.metrics["discovered_entities"] = {}
            logger.debug(
                "discovered_entities_cleared",
                conversation_id=self.conversation_id,
            )

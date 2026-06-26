# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
State management for reasoning agent.

This module provides immutable dataclasses for managing agent state throughout
the reasoning loop. All state updates create new instances rather than mutating
existing ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Message:
    """
    Single message in conversation history.

    Messages form the conversation history between the user, assistant, and tools.
    Each message is immutable and contains role, content, and optional metadata.

    Attributes:
        role: Message role ("system", "user", "assistant", "tool")
        content: Message content (text)
        name: Optional name for tool messages (tool function name)
        tool_call_id: Optional ID linking tool response to tool call
        tool_calls: Optional list of tool calls (for assistant messages with tool invocations)
        metadata: Additional structured data (timestamps, costs, etc.)

    Example:
        >>> # System message
        >>> msg = Message(
        ...     role="system",
        ...     content="You are a Databricks optimization expert",
        ... )
        >>>
        >>> # User message
        >>> msg = Message(
        ...     role="user",
        ...     content="Optimize query abc123",
        ... )
        >>>
        >>> # Tool result message
        >>> msg = Message(
        ...     role="tool",
        ...     name="resolve_query",
        ...     content="Query resolved: SELECT * FROM users",
        ...     metadata={"execution_time_ms": 45},
        ... )
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate message after initialization."""
        valid_roles = {"system", "user", "assistant", "tool"}
        if self.role not in valid_roles:
            raise ValueError(
                f"Invalid role '{self.role}'. Must be one of: {valid_roles}"
            )

        if self.role == "tool" and not self.name:
            logger.warning("Tool message without name - this may cause issues")

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dict for storage.

        Returns:
            Dictionary representation
        """
        return {
            "role": self.role,
            "content": self.content,
            "name": self.name,
            "tool_call_id": self.tool_call_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """
        Deserialize from dict.

        Args:
            data: Dictionary with message data

        Returns:
            Message instance
        """
        return cls(
            role=data["role"],
            content=data["content"],
            name=data.get("name"),
            tool_call_id=data.get("tool_call_id"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class WorkingMemory:
    """
    Scratchpad for intermediate results and discovered facts.

    WorkingMemory stores compact summaries and high-level facts rather than
    full tool outputs. This prevents context overflow while maintaining
    important information for reasoning.

    Attributes:
        summaries: Compact summaries of tool results (tool_name -> summary)
        facts: High-level facts discovered during reasoning
        tools_used: List of tools that have been called
        metrics: Key metrics extracted from tool results
        user_context: User-provided context from interrupts (Phase 2)
        clarifications: User clarifications received during reasoning (Phase 2)

    Example:
        >>> memory = WorkingMemory(
        ...     summaries={
        ...         "resolve_query": "Query resolved from statement_id",
        ...         "analyze_query_plan": "Found expensive join operation",
        ...     },
        ...     facts=[
        ...         "Query references 3 tables",
        ...         "Users table has 1M rows",
        ...         "Missing index on user_id",
        ...     ],
        ...     tools_used=["resolve_query", "analyze_query_plan", "get_table_metadata"],
        ...     metrics={"query_duration_ms": 5420, "rows_produced": 10500},
        ... )
    """

    summaries: dict[str, str] = field(default_factory=dict)
    facts: tuple[str, ...] = field(default_factory=tuple)
    tools_used: tuple[str, ...] = field(default_factory=tuple)
    metrics: dict[str, Any] = field(default_factory=dict)

    # Interruptible Reasoning (Phase 2)
    user_context: tuple[str, ...] = field(default_factory=tuple)
    """User-provided context from interrupts (e.g., 'Focus on partition pruning')"""

    clarifications: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    """User clarifications as (question, answer) pairs"""

    def add_summary(self, tool_name: str, summary: str) -> WorkingMemory:
        """
        Add a tool result summary.

        Args:
            tool_name: Name of the tool
            summary: Compact summary of result

        Returns:
            New WorkingMemory with added summary
        """
        return replace(
            self,
            summaries={**self.summaries, tool_name: summary},
        )

    def add_fact(self, fact: str) -> WorkingMemory:
        """
        Add a discovered fact.

        Args:
            fact: High-level fact discovered

        Returns:
            New WorkingMemory with added fact
        """
        return replace(
            self,
            facts=self.facts + (fact,),
        )

    def add_tool_used(self, tool_name: str) -> WorkingMemory:
        """
        Record that a tool was used.

        Args:
            tool_name: Name of tool that was called

        Returns:
            New WorkingMemory with tool added
        """
        return replace(
            self,
            tools_used=self.tools_used + (tool_name,),
        )

    def update_metrics(self, new_metrics: dict[str, Any]) -> WorkingMemory:
        """
        Update metrics with new values.

        Args:
            new_metrics: Dictionary of new metrics to merge

        Returns:
            New WorkingMemory with updated metrics
        """
        return replace(
            self,
            metrics={**self.metrics, **new_metrics},
        )

    # =========================================================================
    # Interruptible Reasoning Methods (Phase 2)
    # =========================================================================

    def add_user_context(self, context: str) -> WorkingMemory:
        """
        Add user-provided context from interrupt.

        User context is information the user provides during active reasoning
        to guide or clarify the agent's approach.

        Args:
            context: User's context message

        Returns:
            New WorkingMemory with context added

        Example:
            >>> memory = WorkingMemory()
            >>> new_memory = memory.add_user_context("Focus on partition pruning")
            >>> assert "Focus on partition pruning" in new_memory.user_context
        """
        return replace(
            self,
            user_context=self.user_context + (context,),
        )

    def add_clarification(self, question: str, answer: str) -> WorkingMemory:
        """
        Add a user clarification (question/answer pair).

        Clarifications are specific Q&A exchanges where the agent asks for
        information and the user provides it.

        Args:
            question: The question the agent asked
            answer: The user's answer

        Returns:
            New WorkingMemory with clarification added

        Example:
            >>> memory = WorkingMemory()
            >>> new_memory = memory.add_clarification(
            ...     question="Which service principal should I use?",
            ...     answer="Use sp-prod-reader",
            ... )
            >>> assert len(new_memory.clarifications) == 1
            >>> assert new_memory.clarifications[0] == (
            ...     "Which service principal should I use?",
            ...     "Use sp-prod-reader",
            ... )
        """
        return replace(
            self,
            clarifications=self.clarifications + ((question, answer),),
        )

    def merge(self, other: WorkingMemory) -> WorkingMemory:
        """
        Merge another WorkingMemory into this one.

        This combines facts, summaries, tools_used, metrics, user_context,
        and clarifications from both memories.

        Args:
            other: WorkingMemory to merge

        Returns:
            New WorkingMemory with merged contents

        Example:
            >>> memory1 = WorkingMemory(facts=("fact1",))
            >>> memory2 = WorkingMemory(facts=("fact2",))
            >>> merged = memory1.merge(memory2)
            >>> assert "fact1" in merged.facts
            >>> assert "fact2" in merged.facts
        """
        return replace(
            self,
            summaries={**self.summaries, **other.summaries},
            facts=self.facts + other.facts,
            tools_used=self.tools_used + other.tools_used,
            metrics={**self.metrics, **other.metrics},
            user_context=self.user_context + other.user_context,
            clarifications=self.clarifications + other.clarifications,
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert WorkingMemory to dictionary.

        Returns:
            Dictionary representation

        Example:
            >>> memory = WorkingMemory(facts=("fact1",))
            >>> data = memory.to_dict()
            >>> assert data["facts"] == ["fact1"]
        """
        return {
            "summaries": self.summaries,
            "facts": list(self.facts),
            "tools_used": list(self.tools_used),
            "metrics": self.metrics,
            "user_context": list(self.user_context),
            "clarifications": [
                {"question": q, "answer": a} for q, a in self.clarifications
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkingMemory:
        """
        Create WorkingMemory from dictionary.

        Args:
            data: Dictionary with working memory data

        Returns:
            WorkingMemory instance

        Example:
            >>> data = {"facts": ["fact1"], "summaries": {}, "tools_used": []}
            >>> memory = WorkingMemory.from_dict(data)
            >>> assert "fact1" in memory.facts
        """
        # Handle clarifications (could be list of dicts or list of tuples)
        clarifications_data = data.get("clarifications", [])
        if clarifications_data and isinstance(clarifications_data[0], dict):
            clarifications = tuple(
                (c["question"], c["answer"]) for c in clarifications_data
            )
        else:
            clarifications = tuple(clarifications_data)

        return cls(
            summaries=data.get("summaries", {}),
            facts=tuple(data.get("facts", [])),
            tools_used=tuple(data.get("tools_used", [])),
            metrics=data.get("metrics", {}),
            user_context=tuple(data.get("user_context", [])),
            clarifications=clarifications,
        )


@dataclass(frozen=True)
class AgentState:
    """
    Immutable agent state for reasoning loop.

    AgentState represents the complete state of the agent at any point in time.
    All updates create new instances via dataclasses.replace() to maintain
    immutability and enable easy state tracking.

    Attributes:
        user_id: Authenticated user ID (from auth middleware)
        conversation_history: Tuple of messages in chronological order
        working_memory: Scratchpad with summaries and facts
        current_step: Current reasoning step number (0-indexed)
        goal: User's optimization goal
        mode: Optimization mode (ONLINE, OFFLINE, DIAGNOSTIC)
        context: Additional context (warehouse_id, cluster_id, etc.)
        budget_remaining: Remaining token budget
        completed: Whether reasoning is complete
        final_output: Final recommendations (if completed)
        error: Error message (if failed)
        is_interruptible: Whether interrupts are enabled (Phase 2)
        checkpoint_controller: Reference to checkpoint controller (Phase 2)
        current_checkpoint_id: Most recent checkpoint ID (Phase 2)
        user_input_history: IDs of user inputs received (Phase 2)

    Example:
        >>> from starboard_core.domain.models.llm import OptimizationMode
        >>>
        >>> # Initial state
        >>> state = AgentState(
        ...     user_id="user_123",
        ...     conversation_history=(
        ...         Message(role="system", content="You are an expert..."),
        ...         Message(role="user", content="Optimize query abc123"),
        ...     ),
        ...     working_memory=WorkingMemory(),
        ...     current_step=0,
        ...     goal="Optimize query abc123",
        ...     mode=OptimizationMode.ONLINE,
        ...     context={"warehouse_id": "abc"},
        ...     budget_remaining=120_000,
        ... )
        >>>
        >>> # Update state after tool call
        >>> new_state = replace(
        ...     state,
        ...     current_step=state.current_step + 1,
        ...     working_memory=state.working_memory.add_fact("Query resolved"),
        ... )
    """

    # User context
    user_id: str

    # Core state
    conversation_history: tuple[Message, ...]
    working_memory: WorkingMemory
    current_step: int

    # Goal and context
    goal: str
    mode: str  # OptimizationMode value
    context: dict[str, Any]

    # Budget
    budget_remaining: int

    # Completion
    completed: bool = False
    final_output: dict[str, Any] | None = None

    # Error tracking
    error: str | None = None
    failed_tool_calls: tuple[tuple[str, str], ...] = ()
    """History of failed tool calls as (tool_name, error_message) pairs for loop detection"""

    # Interruptible Reasoning (Phase 2)
    is_interruptible: bool = False
    """Whether this agent session supports interrupts (checkpoints, user input injection)"""

    checkpoint_controller: Any | None = (
        None  # CheckpointController (avoid circular import)
    )
    """Reference to checkpoint controller if interruptible reasoning is enabled"""

    current_checkpoint_id: str | None = None
    """ID of the most recent checkpoint created during reasoning"""

    user_input_history: tuple[str, ...] = ()
    """History of user input IDs injected during this reasoning session"""

    def __post_init__(self) -> None:
        """Validate state after initialization."""
        if self.current_step < 0:
            raise ValueError(f"current_step must be >= 0, got {self.current_step}")

        # Note: budget_remaining can be negative when enforce_budget=False (track only)

        if self.completed and not self.final_output:
            logger.warning("State marked as completed but no final_output provided")

    def add_message(self, message: Message) -> AgentState:
        """
        Add a message to conversation history.

        Args:
            message: Message to add

        Returns:
            New AgentState with message added
        """
        return replace(
            self,
            conversation_history=self.conversation_history + (message,),
        )

    def increment_step(self) -> AgentState:
        """
        Increment the current step counter.

        Returns:
            New AgentState with incremented step
        """
        return replace(
            self,
            current_step=self.current_step + 1,
        )

    def consume_budget(self, tokens: int, enforce: bool = False) -> AgentState:
        """
        Consume tokens from budget.

        Args:
            tokens: Number of tokens to consume
            enforce: If True, raise error on insufficient budget. If False, allow negative.

        Returns:
            New AgentState with reduced budget

        Raises:
            ValueError: If budget is insufficient and enforce=True
        """
        new_budget = self.budget_remaining - tokens
        if new_budget < 0 and enforce:
            raise ValueError(
                f"Insufficient budget: requested {tokens}, "
                f"remaining {self.budget_remaining}"
            )

        return replace(
            self,
            budget_remaining=new_budget,
        )

    def mark_completed(self, output: dict[str, Any]) -> AgentState:
        """
        Mark state as completed with final output.

        Args:
            output: Final output from reasoning

        Returns:
            New AgentState marked as completed
        """
        return replace(
            self,
            completed=True,
            final_output=output,
        )

    def mark_error(self, error_message: str) -> AgentState:
        """
        Mark state as having an error.

        Args:
            error_message: Description of the error

        Returns:
            New AgentState with error set
        """
        return replace(
            self,
            error=error_message,
            completed=True,
        )

    # =========================================================================
    # Interruptible Reasoning Methods (Phase 2)
    # =========================================================================

    def enable_interrupts(self, checkpoint_controller: Any) -> AgentState:
        """
        Enable interruptible reasoning for this state.

        Args:
            checkpoint_controller: CheckpointController instance

        Returns:
            New AgentState with interrupts enabled

        Example:
            >>> from starboard_server.agents.checkpoint import CheckpointController
            >>>
            >>> controller = CheckpointController(conversation_id="conv_123")
            >>> interruptible_state = state.enable_interrupts(controller)
            >>> assert interruptible_state.is_interruptible is True
        """
        return replace(
            self,
            is_interruptible=True,
            checkpoint_controller=checkpoint_controller,
        )

    def set_checkpoint(self, checkpoint_id: str) -> AgentState:
        """
        Set the current checkpoint ID.

        Args:
            checkpoint_id: ID of checkpoint just created

        Returns:
            New AgentState with checkpoint ID set

        Example:
            >>> new_state = state.set_checkpoint("ckpt_abc123")
            >>> assert new_state.current_checkpoint_id == "ckpt_abc123"
        """
        return replace(
            self,
            current_checkpoint_id=checkpoint_id,
        )

    def add_user_input(self, input_id: str) -> AgentState:
        """
        Record that user input was received.

        Args:
            input_id: ID of user input

        Returns:
            New AgentState with input ID in history

        Example:
            >>> new_state = state.add_user_input("input_xyz789")
            >>> assert "input_xyz789" in new_state.user_input_history
        """
        return replace(
            self,
            user_input_history=self.user_input_history + (input_id,),
        )

    def record_tool_failure(self, tool_name: str, error_message: str) -> AgentState:
        """
        Record a failed tool call for loop detection.

        Args:
            tool_name: Name of the tool that failed
            error_message: Error message from the failure

        Returns:
            New AgentState with failure recorded

        Example:
            >>> new_state = state.record_tool_failure("resolve_job", "Job not found")
            >>> assert len(new_state.failed_tool_calls) == len(state.failed_tool_calls) + 1
        """
        return replace(
            self,
            failed_tool_calls=self.failed_tool_calls + ((tool_name, error_message),),
        )

    def get_recent_failures(self, tool_name: str, window: int = 3) -> int:
        """
        Count how many times a tool has failed in the recent window.

        Args:
            tool_name: Name of the tool to check
            window: Number of recent failures to check (default: 3)

        Returns:
            Count of recent failures for the given tool

        Example:
            >>> # After 3 failed resolve_job calls
            >>> count = state.get_recent_failures("resolve_job", window=3)
            >>> assert count == 3
        """
        # Get the last 'window' failures
        recent = self.failed_tool_calls[-window:] if self.failed_tool_calls else ()
        return sum(1 for name, _ in recent if name == tool_name)


@dataclass(frozen=True)
class AgentOutput:
    """
    Final output from reasoning agent.

    AgentOutput represents the complete result of a reasoning session,
    including recommendations, execution trace, and metrics.

    Attributes:
        status: Execution status
        recommendations: List of recommendation dictionaries
        reasoning_trace: Step-by-step execution trace
        steps_taken: Number of reasoning steps executed
        tools_used: List of tools that were called
        tokens_used: Total tokens consumed
        cost_usd: Estimated cost in USD
        duration_seconds: Total execution time
        error_message: Error message (if status is "error")
        next_steps: Optional suggested next steps for user (Phase 1: Pattern 1)

    Example:
        >>> output = AgentOutput(
        ...     status="success",
        ...     recommendations=[
        ...         {
        ...             "category": "performance",
        ...             "title": "Add index on user_id",
        ...             "description": "Query performance will improve by 10x",
        ...             "priority": "high",
        ...         }
        ...     ],
        ...     reasoning_trace=[
        ...         {"step": 1, "action": "resolve_query", "result": "..."},
        ...         {"step": 2, "action": "analyze_plan", "result": "..."},
        ...     ],
        ...     steps_taken=5,
        ...     tools_used=["resolve_query", "analyze_plan", "finish"],
        ...     tokens_used=12_450,
        ...     cost_usd=0.0019,
        ...     duration_seconds=45.3,
        ... )
    """

    status: Literal["success", "budget_exceeded", "max_steps_reached", "error"]
    recommendations: list[dict[str, Any]]
    reasoning_trace: list[dict[str, Any]]
    steps_taken: int
    tools_used: list[str]
    tokens_used: int
    cost_usd: float
    duration_seconds: float
    error_message: str | None = None
    complete_report: dict[str, Any] | None = None  # Full structured report
    next_steps: list[Any] | None = None
    formatted_markdown: str | None = (
        None  # Formatted report for display (populated during streaming)  # List[NextStepOption] - avoid circular import
    )

    def __post_init__(self) -> None:
        """Validate output after initialization."""
        if self.steps_taken < 0:
            raise ValueError(f"steps_taken must be >= 0, got {self.steps_taken}")

        if self.tokens_used < 0:
            raise ValueError(f"tokens_used must be >= 0, got {self.tokens_used}")

        if self.cost_usd < 0:
            raise ValueError(f"cost_usd must be >= 0, got {self.cost_usd}")

        if self.duration_seconds < 0:
            raise ValueError(
                f"duration_seconds must be >= 0, got {self.duration_seconds}"
            )

        if self.status == "error" and not self.error_message:
            logger.warning("Status is 'error' but no error_message provided")

        # Validate next_steps (Phase 1: Pattern 1)
        if self.next_steps is not None:
            if len(self.next_steps) > 9:
                raise ValueError(
                    f"next_steps must contain 1-9 options, got {len(self.next_steps)}"
                )

            # Verify sequential numbering
            if self.next_steps:
                for i, option in enumerate(self.next_steps, start=1):
                    if option.number != i:
                        raise ValueError(
                            f"next_steps numbers must be sequential starting from 1, "
                            f"expected {i} but got {option.number}"
                        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert output to dictionary.

        Returns:
            Dictionary representation of output
        """
        result = {
            "status": self.status,
            "recommendations": self.recommendations,
            "reasoning_trace": self.reasoning_trace,
            "steps_taken": self.steps_taken,
            "tools_used": self.tools_used,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "complete_report": self.complete_report,
            "formatted_markdown": self.formatted_markdown,
        }

        logger.debug(
            "agent_output_to_dict_called",
            extra={
                "has_formatted_markdown": self.formatted_markdown is not None,
                "formatted_markdown_length": (
                    len(self.formatted_markdown) if self.formatted_markdown else 0
                ),
                "result_keys": list(result.keys()),
            },
        )

        # Include next_steps if present (convert NextStepOption objects to dicts)
        if self.next_steps:
            from starboard_server.agents.serialization import serialize_step

            result["next_steps"] = [serialize_step(step) for step in self.next_steps]

        return result

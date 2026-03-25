# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
State initialization for domain agents.

This module extracts state initialization logic from DomainAgent,
handling system prompt building, context enrichment, and handoff context.

Responsibilities:
- Build initial AgentState from user input and context
- Enrich user input with handoff context from previous agents
- Extract discovered entities and user constraints
- Build handoff context summary from conversation history

Does NOT:
- Execute reasoning or tools (that's ReasoningEngine/ToolExecutor)
- Emit events (that's EventStreamer)
- Format outputs (that's OutputBuilder)
"""

from __future__ import annotations

from typing import Any

from starboard_core.domain.models.llm import OptimizationMode

from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.agents.state.agent_state import AgentState, Message, WorkingMemory
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class StateInitializer:
    """
    Initialize agent state from user input and context.

    Handles the complex logic of building initial state including:
    - System prompt construction via prompt builders
    - Context enrichment from previous agent handoffs
    - Discovered entity and constraint extraction
    - Handoff context building from conversation history

    Example:
        >>> initializer = StateInitializer(config=agent_config)
        >>> state = initializer.initialize(
        ...     user_input="Optimize query abc123",
        ...     mode=OptimizationMode.ONLINE,
        ...     user_id="user_123",
        ...     context={"workspace_id": "ws1"},
        ... )
        >>> assert state.goal == "Optimize query abc123"
    """

    def __init__(self, config: AgentConfig):
        """
        Initialize state initializer.

        Args:
            config: Agent configuration with prompt builder and settings
        """
        self.config = config

    def initialize(
        self,
        user_input: str,
        mode: OptimizationMode,
        user_id: str,
        context: dict[str, Any],
    ) -> AgentState:
        """
        Initialize agent state.

        Args:
            user_input: User's request text
            mode: Optimization mode
            user_id: Authenticated user ID
            context: Additional context (workspace_id, conversation_history, etc.)

        Returns:
            Initialized AgentState ready for reasoning loop
        """
        # Build system prompt
        prompt_builder = self.config.system_prompt_builder
        if prompt_builder:
            # Try passing context (new signature), fall back to old 3-arg signature
            try:
                system_prompt = prompt_builder(
                    mode,
                    user_input,
                    self.config.max_tokens,
                    context,  # type: ignore[call-arg]
                )
            except TypeError:
                # Prompt builder doesn't accept context (legacy signature)
                system_prompt = prompt_builder(mode, user_input, self.config.max_tokens)  # type: ignore[call-arg]
        else:
            mode_value = mode.value if hasattr(mode, "value") else mode
            system_prompt = f"You are an optimization expert. Mode: {mode_value}"

        # Extract user_constraints from context working_memory if present
        # These are parameters from previous agent's next_step options
        user_constraints = {}
        discovered_entities: dict[str, list[str]] = {}
        if context and "working_memory" in context:
            wm = context["working_memory"]
            if isinstance(wm, dict):
                metrics = wm.get("metrics", {})
                user_constraints = metrics.get("user_constraints", {})
                discovered_entities = metrics.get("discovered_entities", {})
            elif isinstance(getattr(wm, "metrics", None), dict):
                user_constraints = wm.metrics.get("user_constraints", {})  # type: ignore[union-attr]
                discovered_entities = wm.metrics.get("discovered_entities", {})  # type: ignore[union-attr]

        # Enrich user_input with context from previous agent if this is a handoff
        # This ensures the LLM knows about job_id, cluster_id, etc. from the previous step
        enriched_input = user_input
        context_parts: list[str] = []
        has_structured_context = False  # Track if we have structured context
        has_raw_handoff_context = False  # Track if raw message context was used

        # Add discovered entities (ROBUST: programmatically tracked by tools)
        # This is the primary source of cross-agent context - more reliable than
        # LLM-generated parameters since entities are captured at discovery time
        if discovered_entities:
            for entity_type, values in discovered_entities.items():
                if values:
                    # Format entity type for display (e.g., "tables" -> "tables")
                    formatted_values = ", ".join(str(v) for v in values)
                    context_parts.append(f"{entity_type}: {formatted_values}")
                    has_structured_context = True
            logger.info(
                "discovered_entities_included_in_context",
                entity_types=list(discovered_entities.keys()),
                entity_counts={k: len(v) for k, v in discovered_entities.items()},
            )

        # Add ID parameters from user_constraints (fallback/additional context)
        if user_constraints:
            for key, value in user_constraints.items():
                if key in (
                    "job_id",
                    "cluster_id",
                    "warehouse_id",
                    "statement_id",
                    "table_name",
                    "query_id",  # System query ID for analytics continuations
                ):
                    context_parts.append(f"{key}: {value}")
                    has_structured_context = True
                elif key == "context":
                    context_parts.append(f"Context: {value}")
                    has_structured_context = True
                elif key == "suggested_prompt":
                    # Include suggested prompt as context for continuation
                    context_parts.append(f"Suggested action: {value}")
                elif key == "continuation_context":
                    # Include full context summary from budget-exhausted partial analysis
                    # This enables resuming analysis from where it left off
                    context_parts.append(value)
                    has_structured_context = True
                    logger.info(
                        "continuation_context_injected",
                        context_length=len(str(value)),
                    )
                elif key == "resume_from":
                    # Track that this is a continuation (for logging/metrics)
                    context_parts.append(f"Resuming from: {value}")
                    has_structured_context = True
                elif key == "handoff_context" and isinstance(value, dict):
                    # Extract nested handoff context from previous agent
                    # This is populated by NextStepGenerator from HandoffRecommendation.context_to_pass
                    for hc_key, hc_value in value.items():
                        if hc_key in (
                            "job_id",
                            "cluster_id",
                            "warehouse_id",
                            "statement_id",
                            "table_name",
                            "query_id",
                            "tables",  # List of table names from query analysis
                        ):
                            # Format lists nicely (e.g., discovered tables)
                            if isinstance(hc_value, list):
                                context_parts.append(
                                    f"{hc_key}: {', '.join(str(v) for v in hc_value)}"
                                )
                            else:
                                context_parts.append(f"{hc_key}: {hc_value}")
                            has_structured_context = True
                        elif hc_key == "context" or hc_key == "summary":
                            context_parts.append(f"From previous agent: {hc_value}")
                            has_structured_context = True

        # Use ConversationContextStrategy for multi-turn context enrichment.
        # This replaces the old single-message build_handoff_context() approach
        # and provides tiered summarization for long conversations.
        if not has_structured_context:
            conversation_history = (
                context.get("conversation_history", []) if context else []
            )

            if len(conversation_history) > 1:
                from starboard_server.agents.state.context_strategy import (
                    ConversationContextStrategy,
                )

                strategy = ConversationContextStrategy()
                ctx_window = strategy.prepare_context(
                    conversation_history=conversation_history,
                    working_memory=context.get("working_memory") if context else None,
                    existing_summary=context.get("metadata", {}).get("summary")
                    if context
                    else None,
                )

                enriched_via_strategy = strategy.build_enriched_input(
                    user_input="", context_window=ctx_window
                )
                if enriched_via_strategy.strip():
                    context_parts.append(enriched_via_strategy.strip())
                    has_raw_handoff_context = True
            else:
                raw_handoff_context = build_handoff_context(conversation_history)
                if raw_handoff_context:
                    context_parts.append(
                        f"Previous analysis summary:\n{raw_handoff_context}"
                    )
                    has_raw_handoff_context = True

        if context_parts:
            context_str = "\n".join(context_parts)
            enriched_input = f"{user_input}\n\n[Handoff Context]\n{context_str}"
            logger.debug(
                "enriched_user_input_with_handoff_context",
                original_length=len(user_input),
                enriched_length=len(enriched_input),
                constraint_keys=(
                    list(user_constraints.keys()) if user_constraints else []
                ),
                has_structured_context=has_structured_context,
                has_raw_handoff_context=has_raw_handoff_context,
            )

        # Create initial messages
        initial_messages = (
            Message(role="system", content=system_prompt),
            Message(role="user", content=enriched_input),
        )

        mode_value = mode.value if hasattr(mode, "value") else str(mode)

        # Restore working memory from context if available, preserving constraints and entities
        working_memory = WorkingMemory()
        if user_constraints:
            working_memory.metrics["user_constraints"] = user_constraints
        if discovered_entities:
            working_memory.metrics["discovered_entities"] = discovered_entities

        return AgentState(
            user_id=user_id,
            goal=user_input,
            mode=mode_value,
            current_step=0,
            completed=False,
            conversation_history=initial_messages,
            working_memory=working_memory,
            context=context,
            budget_remaining=self.config.max_tokens,
            final_output=None,
        )


def build_handoff_context(
    conversation_history: list[dict[str, Any] | Message],
) -> str:
    """
    Build a handoff context summary from the previous conversation.

    Extracts the last assistant message content to provide context
    about what was previously analyzed. This ensures the new agent
    knows what the previous agent discovered.

    Args:
        conversation_history: List of conversation messages

    Returns:
        Summary string of previous assistant findings, or empty string
    """
    if not conversation_history:
        return ""

    # Find the last assistant message (the previous agent's response)
    last_assistant_content = ""
    for msg in reversed(conversation_history):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        content = (
            msg.get("content")
            if isinstance(msg, dict)
            else getattr(msg, "content", None)
        )

        if role == "assistant" and content:
            last_assistant_content = content
            break

    if not last_assistant_content:
        return ""

    # Truncate to reasonable length for context (avoid token bloat)
    max_context_length = 2000
    if len(last_assistant_content) > max_context_length:
        # Try to find a good break point
        truncated = last_assistant_content[:max_context_length]
        # Find last complete sentence
        for end_char in [". ", ".\n", "! ", "!\n", "? ", "?\n"]:
            last_end = truncated.rfind(end_char)
            if last_end > max_context_length // 2:
                truncated = truncated[: last_end + 1]
                break
        last_assistant_content = truncated + "..."

    logger.debug(
        "built_handoff_context",
        context_length=len(last_assistant_content),
    )

    return last_assistant_content

# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Conversation context window management strategy.

Manages what context is passed to agents as conversations grow,
preventing token budget exhaustion while preserving relevant context.

Implements a tiered approach:
- Short conversations (<=N turns): full history verbatim
- Medium conversations (<=M turns): recent turns + summary of earlier
- Long conversations (>M turns): rolling summary + recent window

This mirrors industry patterns (LangChain ConversationSummaryBufferMemory,
OpenAI Assistants thread truncation).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from starboard.agents.state.agent_state import Message
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class ContextWindow:
    """Prepared context for agent consumption.

    Attributes:
        summary: Summary of earlier conversation (empty for short convos).
        recent_messages: Recent messages passed verbatim to the agent.
        working_memory_snapshot: Key facts, entities, and constraints.
        turn_count: Total turns in the conversation.
        was_summarized: Whether summarization was applied.
    """

    summary: str
    recent_messages: list[dict[str, Any]]
    working_memory_snapshot: dict[str, Any]
    turn_count: int
    was_summarized: bool


class ConversationContextStrategy:
    """Manage context passed to agents as conversations grow.

    Applies a tiered strategy:
    - ``turn_count <= full_history_threshold``: Pass all messages.
    - ``turn_count <= summary_threshold``: Summarize earlier, keep recent.
    - ``turn_count > summary_threshold``: Rolling summary + recent window.

    Args:
        full_history_threshold: Max turns before summarization kicks in.
        summary_threshold: Max turns before aggressive compression.
        recent_window_turns: Number of recent *turns* (user+assistant pairs)
            to keep verbatim when summarizing.

    Example:
        >>> strategy = ConversationContextStrategy()
        >>> window = strategy.prepare_context(shared_context)
        >>> # window.summary is empty for short conversations
        >>> # window.recent_messages contains the verbatim messages
    """

    def __init__(
        self,
        full_history_threshold: int = 5,
        summary_threshold: int = 10,
        recent_window_turns: int = 3,
    ) -> None:
        self._full_threshold = full_history_threshold
        self._summary_threshold = summary_threshold
        self._recent_window = recent_window_turns

    def prepare_context(
        self,
        conversation_history: list[Message] | list[dict[str, Any]],
        working_memory: Any | None = None,
        existing_summary: str | None = None,
    ) -> ContextWindow:
        """Prepare context window from conversation state.

        Args:
            conversation_history: All messages in the conversation.
            working_memory: WorkingMemory instance or dict with metrics.
            existing_summary: Previously generated summary (avoids re-summarizing).

        Returns:
            ContextWindow with summary and recent messages ready for the agent.
        """
        turn_count = sum(1 for m in conversation_history if _get_role(m) == "user")

        wm_snapshot = _extract_working_memory_snapshot(working_memory)

        if turn_count <= self._full_threshold:
            return ContextWindow(
                summary="",
                recent_messages=[_msg_to_dict(m) for m in conversation_history],
                working_memory_snapshot=wm_snapshot,
                turn_count=turn_count,
                was_summarized=False,
            )

        recent = self._extract_recent_messages(conversation_history)
        earlier = conversation_history[: len(conversation_history) - len(recent)]
        summary = existing_summary or self._build_extractive_summary(earlier)

        logger.debug(
            "context_window_prepared",
            turn_count=turn_count,
            recent_messages=len(recent),
            earlier_messages=len(earlier),
            summary_length=len(summary),
        )

        return ContextWindow(
            summary=summary,
            recent_messages=[_msg_to_dict(m) for m in recent],
            working_memory_snapshot=wm_snapshot,
            turn_count=turn_count,
            was_summarized=True,
        )

    def build_enriched_input(
        self,
        user_input: str,
        context_window: ContextWindow,
    ) -> str:
        """Build enriched user input that includes prior context.

        Combines the current user message with a summary of prior
        conversation and key working memory facts for the agent.

        Args:
            user_input: Current user message.
            context_window: Prepared context window.

        Returns:
            Enriched user input string with prior context prepended.
        """
        if (
            not context_window.was_summarized
            and not context_window.working_memory_snapshot
        ):
            return user_input

        parts: list[str] = []

        if context_window.summary:
            parts.append(f"[Prior Conversation Summary]\n{context_window.summary}")

        wm = context_window.working_memory_snapshot
        if wm.get("discovered_entities"):
            entity_lines = []
            for etype, values in wm["discovered_entities"].items():
                if values:
                    entity_lines.append(
                        f"  {etype}: {', '.join(str(v) for v in values)}"
                    )
            if entity_lines:
                parts.append("[Discovered Entities]\n" + "\n".join(entity_lines))

        if wm.get("user_constraints"):
            constraint_lines = []
            for k, v in wm["user_constraints"].items():
                constraint_lines.append(f"  {k}: {v}")
            if constraint_lines:
                parts.append("[Active Constraints]\n" + "\n".join(constraint_lines))

        if wm.get("key_facts"):
            parts.append(
                "[Key Facts]\n" + "\n".join(f"  - {f}" for f in wm["key_facts"])
            )

        if parts:
            context_block = "\n\n".join(parts)
            return f"{user_input}\n\n{context_block}"

        return user_input

    def _extract_recent_messages(
        self,
        conversation_history: list[Message] | list[dict[str, Any]],
    ) -> list[Message] | list[dict[str, Any]]:
        """Extract the most recent N turns (user+assistant pairs) from history."""
        user_indices = [
            i for i, m in enumerate(conversation_history) if _get_role(m) == "user"
        ]

        if len(user_indices) <= self._recent_window:
            return conversation_history

        cutoff_idx = user_indices[-self._recent_window]
        return conversation_history[cutoff_idx:]

    def _build_extractive_summary(
        self,
        messages: list[Message] | list[dict[str, Any]],
    ) -> str:
        """Build an extractive summary from earlier messages.

        Extracts key content from user queries and assistant responses
        without requiring an LLM call.

        Args:
            messages: Earlier messages to summarize.

        Returns:
            Extractive summary string.
        """
        if not messages:
            return ""

        summary_parts: list[str] = []
        turn_num = 0

        for msg in messages:
            role = _get_role(msg)
            content = _get_content(msg)
            if not content:
                continue

            if role == "user":
                turn_num += 1
                summary_parts.append(
                    f"Turn {turn_num} — User: {_truncate(content, 200)}"
                )
            elif role == "assistant":
                summary_parts.append(
                    f"Turn {turn_num} — Agent: {_truncate(content, 400)}"
                )

        return "\n".join(summary_parts)


def _get_role(msg: Any) -> str:
    """Extract role from Message object or dict."""
    if isinstance(msg, dict):
        return msg.get("role", "")
    return getattr(msg, "role", "")


def _get_content(msg: Any) -> str:
    """Extract content from Message object or dict."""
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", "")


def _msg_to_dict(msg: Any) -> dict[str, Any]:
    """Convert a Message to dict if needed."""
    if isinstance(msg, dict):
        return msg
    return {
        "role": getattr(msg, "role", ""),
        "content": getattr(msg, "content", ""),
        "name": getattr(msg, "name", None),
        "tool_call_id": getattr(msg, "tool_call_id", None),
        "metadata": getattr(msg, "metadata", {}),
    }


def _truncate(text: str, max_length: int) -> str:
    """Truncate text at a sentence boundary if possible."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    for end in [". ", ".\n", "! ", "? "]:
        last = truncated.rfind(end)
        if last > max_length // 2:
            return truncated[: last + 1] + "…"
    return truncated + "…"


def _extract_working_memory_snapshot(wm: Any) -> dict[str, Any]:
    """Extract key working memory fields into a flat snapshot dict."""
    if wm is None:
        return {}

    if isinstance(wm, dict):
        metrics = wm.get("metrics", {})
    elif isinstance(getattr(wm, "metrics", None), dict):
        metrics = wm.metrics  # type: ignore[union-attr]
    else:
        return {}

    snapshot: dict[str, Any] = {}

    if metrics.get("discovered_entities"):
        snapshot["discovered_entities"] = metrics["discovered_entities"]

    if metrics.get("user_constraints"):
        snapshot["user_constraints"] = metrics["user_constraints"]

    facts = wm.get("facts") if isinstance(wm, dict) else getattr(wm, "facts", None)

    if facts:
        fact_list = list(facts) if not isinstance(facts, list) else facts
        if fact_list:
            snapshot["key_facts"] = fact_list[:10]

    return snapshot

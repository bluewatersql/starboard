# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Memory consolidation service for background processing."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime

from starboard_core.models.conversation import Conversation
from starboard_core.models.memory import Episode, Fact

from starboard.exceptions import AdapterError
from starboard.infra.core.container import Container
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


class MemoryConsolidationService:
    """
    Background service for memory consolidation.

    Periodically:
    1. Identifies conversations ready for consolidation
    2. Generates summaries and extracts key points
    3. Creates episodes with embeddings
    4. Extracts facts from conversations
    5. Updates user profiles

    Example:
        service = MemoryConsolidationService(container)
        await service.start()  # Starts background task
        # ... application runs ...
        await service.stop()   # Stops background task
    """

    def __init__(self, container: Container):
        """
        Initialize consolidation service.

        Args:
            container: DI container with repositories
        """
        self.container = container
        self.config = container.config
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """
        Start background consolidation task.

        Raises:
            RuntimeError: If already running
        """
        if self._running:
            logger.warning("consolidation_already_running")
            return

        if not self.config.memory_consolidation_enabled:
            logger.debug("consolidation_disabled_by_config")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.debug(
            "consolidation_started",
            interval_seconds=self.config.memory_consolidation_interval,
        )

    async def stop(self) -> None:
        """Stop background consolidation task."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.debug("consolidation_stopped")

    async def _run_loop(self) -> None:
        """Main consolidation loop."""
        while self._running:
            try:
                await self._consolidate_memories()
                await asyncio.sleep(self.config.memory_consolidation_interval)
            except asyncio.CancelledError:
                break
            except (AdapterError, ValueError, TimeoutError) as e:
                logger.error(
                    "consolidation_error",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Wait 1 minute before retrying on error
                await asyncio.sleep(60)

    async def _consolidate_memories(self) -> None:
        """
        Run memory consolidation cycle.

        Process conversations that need consolidation and create
        episodes and facts from them.
        """
        logger.debug("consolidation_cycle_start")

        try:
            # In a real implementation, this would:
            # 1. Query for conversations updated since last consolidation
            # 2. For each conversation, generate summary and extract facts
            # 3. Store episodes and facts in memory store

            # For Phase 4, we provide the structure but simplified logic
            # Full LLM integration can be added later

            logger.debug("consolidation_cycle_complete")

        except (AdapterError, ValueError, TimeoutError) as e:
            logger.error(
                "consolidation_cycle_error",
                error=str(e),
                error_type=type(e).__name__,
            )

    async def consolidate_conversation(
        self,
        conversation_id: str,
        embedding: list[float] | None = None,
    ) -> str:
        """
        Consolidate a single conversation into memory.

        Args:
            conversation_id: Conversation to consolidate
            embedding: Optional pre-generated embedding for the summary

        Returns:
            Episode ID that was created

        Raises:
            ValueError: If conversation not found or empty
        """
        conv_repo = self.container.conversation_repo
        mem_repo = self.container.memory_repo

        # Get conversation
        conv = await conv_repo.get(conversation_id)
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found")

        if not conv.messages:
            raise ValueError(f"Conversation {conversation_id} is empty")

        logger.debug(
            "consolidating_conversation",
            conversation_id=conversation_id,
            user_id=conv.user_id,
            message_count=len(conv.messages),
        )

        # Generate summary (simplified - use LLM in production)
        summary = self._generate_summary(conv)
        key_points = self._extract_key_points(conv)

        # Create episode
        episode = Episode(
            id=str(uuid.uuid4()),
            user_id=conv.user_id,
            conversation_id=conversation_id,
            summary=summary,
            key_points=key_points,
            embedding=embedding,
            created_at=datetime.now(UTC),
            metadata={
                "message_count": len(conv.messages),
                "consolidated_at": datetime.now(UTC).isoformat(),
            },
        )

        episode_id = await mem_repo.remember_conversation(
            user_id=episode.user_id,
            conversation_id=conversation_id,  # Use original param, not episode attr
            conversation_summary=episode.summary,
            key_points=episode.key_points,
            embedding=episode.embedding,
        )

        # Extract facts (simplified)
        facts = self._extract_facts(conv)
        for fact in facts:
            await mem_repo.learn_fact(
                user_id=fact.user_id,
                statement=fact.statement,
                category=fact.category,
                confidence=fact.confidence,
                source=fact.source,
            )

        logger.debug(
            "conversation_consolidated",
            conversation_id=conversation_id,
            episode_id=episode_id,
            facts_extracted=len(facts),
        )

        return episode_id

    def _generate_summary(self, conversation: Conversation) -> str:
        """
        Generate summary from conversation.

        Args:
            conversation: Conversation to summarize

        Returns:
            Summary text

        Note:
            Simplified implementation. In production, use LLM to generate
            higher quality summaries.
        """
        message_count = len(conversation.messages)

        # Simple summary based on message count and content length
        total_chars = sum(len(msg.content) for msg in conversation.messages)

        # Get first user message as context
        first_user_msg = next(
            (msg.content for msg in conversation.messages if msg.role == "user"),
            "conversation",
        )

        summary = (
            f"Conversation with {message_count} messages "
            f"({total_chars} characters) about {first_user_msg[:50]}..."
        )

        return summary

    def _extract_key_points(self, conversation: Conversation) -> list[str]:
        """
        Extract key points from conversation.

        Args:
            conversation: Conversation to extract from

        Returns:
            List of key points

        Note:
            Simplified implementation. In production, use LLM to identify
            important topics and decisions.
        """
        key_points = []

        # Simple heuristic: get first 3 user messages as key points
        user_messages = [
            msg.content for msg in conversation.messages if msg.role == "user"
        ]

        for i, msg in enumerate(user_messages[:3], 1):
            # Truncate to 100 chars
            point = f"Point {i}: {msg[:100]}"
            key_points.append(point)

        return key_points

    def _extract_facts(self, conversation: Conversation) -> list[Fact]:
        """
        Extract facts from conversation.

        Args:
            conversation: Conversation to extract from

        Returns:
            List of extracted facts

        Note:
            Simplified implementation. In production, use LLM to identify
            facts, preferences, and context.
        """
        facts = []

        # Simple heuristic: look for statements that might be facts
        # In production, use LLM with structured output

        for msg in conversation.messages:
            if msg.role == "user" and len(msg.content) > 20:
                # Create a fact for longer user messages
                fact = Fact(
                    id=str(uuid.uuid4()),
                    user_id=conversation.user_id,
                    statement=msg.content[:200],  # Truncate
                    category="extracted",
                    confidence=0.5,  # Low confidence for simple extraction
                    source=f"conversation:{conversation.id}",
                    verified=False,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    metadata={
                        "extraction_method": "simple",
                        "message_timestamp": msg.timestamp.isoformat(),
                    },
                )
                facts.append(fact)

        return facts

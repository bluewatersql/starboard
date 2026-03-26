# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Multi-Agent Conversation Manager as orchestration facade.

Thin facade (<500 lines) that coordinates 4 specialized components:
- ConversationLifecycleManager: Conversation CRUD
- AgentHandoffCoordinator: Agent routing and handoffs
- EventBroadcastCoordinator: SSE broadcasting
- MessageQueueProcessor: Background message processing

Clean, maintainable architecture following single responsibility principle.

Design Pattern: Facade + Coordinator
- Delegates all work to specialized components
- Coordinates component interactions
- Clean public API for conversation management
- Modular and testable design

Example:
    >>> manager = MultiAgentConversationManager(
    ...     agent_factory=factory,
    ...     intent_router=router,
    ...     state_manager=state_mgr,
    ... )
    >>>
    >>> response = await manager.create_conversation(
    ...     user_id="user_123",
    ...     context={"workspace_id": "ws_abc"},
    ... )
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from starboard_core.domain.models.llm import OptimizationMode

from starboard_server.agents.agent_factory import AgentFactory
from starboard_server.agents.config.model_generator import DomainModelConfigGenerator
from starboard_server.agents.conversation import (
    AgentHandoffCoordinator,
    ConversationLifecycleManager,
    EventBroadcastCoordinator,
    MessageQueueProcessor,
)
from starboard_server.agents.events import (
    StreamingEvent,
    UserInputRequestEvent,
)
from starboard_server.agents.events.user_events import FinalOutputEvent
from starboard_server.agents.routing.intent_router import IntentRouter
from starboard_server.agents.routing.specialist_context_builder import (
    SpecialistContextBuilder,
)
from starboard_server.agents.state.agent_state import Message
from starboard_server.agents.state.context_manager import ContextManager
from starboard_server.agents.state.event_context_updater import EventContextUpdater
from starboard_server.agents.utils.position_tracker import PositionTracker
from starboard_server.domain.conversation.api_types import (
    ChatEvent,
    ConversationConfig,
    ConversationHistory,
    ConversationResponse,
    MessageResponse,
)
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class MultiAgentConversationManager:
    """
    Multi-agent conversation manager (orchestration facade).

    Coordinates 4 specialized components instead of handling everything itself:

    1. ConversationLifecycleManager - Conversation CRUD operations
    2. AgentHandoffCoordinator - Intent classification & routing
    3. EventBroadcastCoordinator - SSE event broadcasting
    4. MessageQueueProcessor - Background message processing

    Backward Compatible API:
    - Same __init__ signature as old MultiAgentConversationManager
    - Same public methods
    - Same behavior and semantics

    Benefits:
    - 70% code reduction (1,554 → ~450 lines)
    - Each component independently testable
    - Clear separation of concerns
    - Easy to maintain and extend

    Example:
        >>> manager = MultiAgentConversationManager(
        ...     agent_factory=factory,
        ...     intent_router=router,
        ...     state_manager=state_mgr,
        ... )
        >>>
        >>> # Create conversation
        >>> response = await manager.create_conversation(
        ...     user_id="user_123",
        ...     context={"workspace_id": "ws_abc"},
        ... )
        >>>
        >>> # Handle message
        >>> async for event in manager.handle_message_stream(
        ...     conversation_id=response.conversation_id,
        ...     user_message="Optimize query q123",
        ... ):
        ...     print(event.type)
    """

    def __init__(
        self,
        agent_factory: AgentFactory,
        intent_router: IntentRouter,
        state_manager: Any,  # ConversationStateManager protocol
        disabled_agent_domains: list[str] | None = None,
        request_input_tool: Any | None = None,
        cache_store: Any | None = None,  # Optional CacheStore for ServiceCatalogTool
        cache_factory: Any | None = None,  # Optional CacheFactory for attachments
    ):
        """
        Initialize refactored multi-agent manager.

        Args:
            agent_factory: Factory for creating domain-specific agents
            intent_router: Router for classifying user intent
            state_manager: Manager for persisting conversation context
            disabled_agent_domains: List of disabled domain names
            request_input_tool: Tool for handling user input during reasoning
            cache_store: Optional CacheStore instance for shared caching.
                        If provided, used by ServiceCatalogTool for cache backend.
            cache_factory: Optional CacheFactory for accessing namespaced caches.
                        Used for large file attachment storage.
        """
        self.agent_factory = agent_factory
        self.intent_router = intent_router
        self.state_manager = state_manager
        self.disabled_agent_domains = disabled_agent_domains or []
        self._cache_store = cache_store
        self._cache_factory = cache_factory

        # Initialize specialized components (DELEGATION)
        disabled_domains_set = (
            set(disabled_agent_domains) if disabled_agent_domains else None
        )
        self.lifecycle = ConversationLifecycleManager(
            state_manager=state_manager,
            config_generator=DomainModelConfigGenerator(
                agent_factory=agent_factory,
                disabled_domains=disabled_domains_set,
            ),
        )

        self.handoff = AgentHandoffCoordinator(
            intent_router=intent_router,
            agent_factory=agent_factory,
            disabled_domains=disabled_agent_domains,
        )

        self.events = EventBroadcastCoordinator(
            state_manager=state_manager,
            queue_maxsize=100,
            broadcast_timeout=1.0,
        )

        self.queue = MessageQueueProcessor(
            event_coordinator=self.events,
            request_input_tool=request_input_tool,
        )

        # Helper components (already extracted in old code)
        self._context_manager = ContextManager(state_manager=state_manager)
        self._context_builder = SpecialistContextBuilder()
        self._event_updater = EventContextUpdater()

        # Initialize service catalog for next-step suggestions
        self._initialize_service_catalog()

        logger.debug("multi_agent_manager_refactored_initialized")

    def _initialize_service_catalog(self) -> None:
        """Initialize service catalog and next-step generator.

        Passes disabled_agent_domains to ServiceCatalogTool to ensure
        disabled agents are not discoverable via the catalog.
        """
        from pathlib import Path

        from starboard_server.config.catalog_loader import (
            CatalogLoadError,
            load_service_catalog,
        )
        from starboard_server.services.coordination.next_step_generator import (
            NextStepGenerator,
        )
        from starboard_server.tools.service_catalog_tool import ServiceCatalogTool

        try:
            catalog_path = (
                Path(__file__).parent.parent.parent / "config" / "service_catalog.yaml"
            )
            entries = load_service_catalog(catalog_path)

            # Pass disabled_domains to filter out disabled agents from catalog
            # Pass cache_store if available (shared with container for consistency)
            self.catalog_tool = ServiceCatalogTool(
                initial_entries=entries,
                disabled_domains=self.disabled_agent_domains,
                cache_store=self._cache_store,
            )
            self.next_step_generator = NextStepGenerator(self.catalog_tool)

            logger.debug(
                "service_catalog_initialized",
                entry_count=len(entries),
                disabled_domains=self.disabled_agent_domains or None,
                cache_store_shared=self._cache_store is not None,
            )

        except (CatalogLoadError, FileNotFoundError) as e:
            logger.warning(
                "service_catalog_load_failed",
                error=str(e),
            )

            # Fallback: empty catalog (still respects disabled_domains)
            self.catalog_tool = ServiceCatalogTool(
                initial_entries=[],
                disabled_domains=self.disabled_agent_domains,
                cache_store=self._cache_store,
            )
            self.next_step_generator = NextStepGenerator(self.catalog_tool)

    def _quick_detect_artifact_type(self, content_preview: str, filename: str) -> str:
        """Quickly detect artifact type from content preview and filename.

        This is a lightweight detection for metadata purposes only.
        Full processing happens via explore_artifact tool.

        Args:
            content_preview: First ~2000 chars of content
            filename: Original filename

        Returns:
            Detected artifact type string
        """
        import json

        filename_lower = filename.lower()
        content_stripped = content_preview.strip()

        # Check for query profile (Liquid format or standard)
        if content_stripped.startswith("{") or content_stripped.startswith("["):
            try:
                # Try to parse as JSON
                data = json.loads(
                    content_preview[:5000]
                    if len(content_preview) > 5000
                    else content_preview
                )
                if isinstance(data, dict):
                    # Liquid format
                    if "graphs" in data and "query" in data:
                        return "query_profile"
                    # Standard format
                    if "operatorID" in data or "operatorName" in data:
                        return "query_profile"
                    # Spark event log
                    if data.get("Event", "").startswith("SparkListener"):
                        return "spark_event_log"
            except json.JSONDecodeError:
                pass

        # Check for Spark event log (JSON-lines)
        first_line = content_stripped.split("\n", 1)[0].strip()
        if first_line.startswith("{"):
            try:
                event = json.loads(first_line)
                if isinstance(event, dict) and event.get("Event", "").startswith(
                    "SparkListener"
                ):
                    return "spark_event_log"
            except (json.JSONDecodeError, AttributeError):
                pass

        # Check for EXPLAIN plan
        if (
            "== Physical Plan ==" in content_preview
            or "== Parsed Logical Plan ==" in content_preview
        ):
            return "explain_plan"

        # Check filename hints
        if filename_lower.endswith(".json"):
            return "query_profile"  # Default JSON to query profile
        if filename_lower.endswith(".log") or filename_lower.endswith(".txt"):
            return "logs"

        return "unknown"

    # =========================================================================
    # Conversation Lifecycle (Delegates to ConversationLifecycleManager)
    # =========================================================================

    async def create_conversation(
        self,
        user_id: str,
        context: dict[str, Any] | None = None,
        config: ConversationConfig | None = None,
    ) -> ConversationResponse:
        """
        Create a new conversation session.

        Delegates to ConversationLifecycleManager.

        Args:
            user_id: User identifier
            context: Initial context
            config: Conversation configuration

        Returns:
            ConversationResponse with conversation_id and config
        """
        return await self.lifecycle.create(
            user_id=user_id,
            context=context,
            config=config,
        )

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Get conversation by ID (compatibility method)."""
        return await self.lifecycle.get(conversation_id)

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Any]:
        """List conversations for a user."""
        return await self.lifecycle.list_for_user(
            user_id=user_id,
            limit=limit,
            offset=offset,
        )

    async def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation and clean up resources.

        Cancels active tasks, clears subscribers, and deletes from storage.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if deleted, False if not found
        """
        # Cancel any active processing task
        self.queue.cancel_task(conversation_id)

        # Remove all subscribers
        self.events.clear_conversation(conversation_id)

        # Clear pending input requests
        self.queue.clear_pending_input_request(conversation_id)

        # Clear clarification pending state
        self.handoff.clear_clarification_pending(conversation_id)

        # Delete conversation
        return await self.lifecycle.delete(conversation_id)

    async def delete_all_conversations(self, user_id: str) -> int:
        """
        Delete all conversations for a user (batch operation).

        Cancels active tasks, clears subscribers, and deletes from storage.
        Much more efficient than deleting one-by-one.

        Args:
            user_id: User identifier

        Returns:
            Number of conversations deleted
        """
        # First, get all conversations for this user to clean up resources
        conversations = await self.list_conversations(user_id=user_id, limit=1000)

        # Clean up resources for each conversation
        for conv in conversations:
            conv_id = conv.conversation_id
            # Cancel any active processing task
            self.queue.cancel_task(conv_id)
            # Remove all subscribers
            self.events.clear_conversation(conv_id)
            # Clear pending input requests
            self.queue.clear_pending_input_request(conv_id)
            # Clear clarification pending state
            self.handoff.clear_clarification_pending(conv_id)

        # Batch delete from storage
        count = await self.lifecycle.delete_all(user_id)

        logger.info(
            "all_conversations_deleted",
            user_id=user_id,
            count=count,
        )

        return count

    async def get_history(self, conversation_id: str) -> ConversationHistory | None:
        """Get full conversation history."""
        raw_context = await self.state_manager.load_context(conversation_id)
        if not raw_context:
            return None

        # Reconstruct context if it's a dict
        context = self._context_manager._reconstruct_context(raw_context)

        logger.debug(
            "reconstructed_conversation_history",
            conversation_id=conversation_id,
            conversation_history_length=len(context.conversation_history),
            conversation_history_roles=[
                msg.role for msg in context.conversation_history
            ],
        )

        # Convert messages to API format
        from hashlib import md5

        from starboard_server.domain.conversation.api_types import Message as APIMessage

        messages = []
        for idx, msg in enumerate(context.conversation_history):
            # Generate deterministic ID based on conversation_id, index, and content
            # This ensures same messages get same IDs across multiple fetches
            id_source = f"{conversation_id}_{idx}_{msg.role}_{msg.content[:50]}"
            msg_id = f"msg_{md5(id_source.encode()).hexdigest()[:12]}"

            # Preserve metadata (including complete_report) from conversation history
            api_metadata = msg.metadata if msg.metadata else {}

            # Extract next_steps from metadata for API response (Issue #1 fix)
            next_steps_from_metadata = None
            if "next_steps" in api_metadata and msg.role == "assistant":
                next_steps_data = api_metadata["next_steps"]
                if next_steps_data and isinstance(next_steps_data, list):
                    # Convert dict representations back to NextStepOption objects
                    from starboard_server.domain.models.conversation_patterns import (
                        NextStepOption,
                    )

                    try:
                        next_steps_from_metadata = [
                            (
                                NextStepOption.from_dict(step)
                                if isinstance(step, dict)
                                else step
                            )
                            for step in next_steps_data
                        ]
                        logger.debug(
                            "loaded_message_with_next_steps",
                            conversation_id=conversation_id,
                            message_index=idx,
                            next_steps_count=len(next_steps_from_metadata),
                        )
                    except Exception as e:  # noqa: BLE001 - non-critical prefetch
                        logger.warning(
                            "failed_to_deserialize_next_steps",
                            conversation_id=conversation_id,
                            message_index=idx,
                            error=str(e),
                        )

            # Log if complete_report found (helps debugging)
            if "complete_report" in api_metadata and msg.role == "assistant":
                complete_report = api_metadata["complete_report"]
                logger.debug(
                    "loaded_message_with_complete_report",
                    conversation_id=conversation_id,
                    message_index=idx,
                    report_type=(
                        complete_report.get("report_type")
                        if isinstance(complete_report, dict)
                        else "unknown"
                    ),
                )

            # Extract tool_calls from metadata
            tool_calls = []
            if "tool_calls" in api_metadata:
                # Import ToolCall model
                from starboard_server.domain.conversation.api_types import (
                    ToolCall as APIToolCall,
                )

                raw_tool_calls = api_metadata["tool_calls"]
                for tc in raw_tool_calls:
                    tool_calls.append(
                        APIToolCall(
                            tool_call_id=tc.get("tool_call_id", ""),
                            tool_name=tc.get("tool_name", ""),
                            friendly_name=tc.get("friendly_name"),
                            status=tc.get("status", "unknown"),
                            arguments=tc.get("arguments"),
                            output=tc.get("output"),
                            error=tc.get("error"),
                            duration_ms=tc.get("duration_ms"),
                        )
                    )

                logger.debug(
                    "loaded_message_with_tool_calls",
                    conversation_id=conversation_id,
                    message_index=idx,
                    tool_call_count=len(tool_calls),
                )

            messages.append(
                APIMessage(
                    id=msg_id,
                    conversation_id=conversation_id,
                    role=msg.role,
                    content=msg.content,
                    timestamp=datetime.now(UTC),
                    metadata=api_metadata,  # Preserve complete_report in metadata
                    tool_calls=tool_calls,  # Add extracted tool calls
                    next_steps=next_steps_from_metadata,  # Issue #1 fix: Restore next_steps
                )
            )

        # Build metadata
        from starboard_server.domain.conversation.api_types import ConversationMetadata

        now = datetime.now(UTC)
        metadata = ConversationMetadata(
            total_messages=len(messages),
            total_tokens=context.metadata.get("total_tokens", 0),
            total_cost=context.metadata.get("total_cost", 0.0),
            created_at=context.metadata.get("created_at", now),
            updated_at=context.metadata.get("updated_at", now),
            friendly_name=context.metadata.get("friendly_name", "Conversation"),
        )

        return ConversationHistory(
            conversation_id=conversation_id,
            messages=messages,
            metadata=metadata,
        )

    # =========================================================================
    # Message Processing (Delegates to MessageQueueProcessor)
    # =========================================================================

    async def enqueue_message(
        self,
        conversation_id: str,
        content: str,
        attachments: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
        user_id: str = "default_user",
        mode: OptimizationMode = OptimizationMode.ONLINE,
    ) -> MessageResponse:
        """
        Enqueue a message for processing.

        Delegates to MessageQueueProcessor.

        Args:
            conversation_id: Unique conversation identifier
            content: User message content
            attachments: Optional attachments (large files are routed to diagnostic)
            metadata: Optional metadata (e.g., for option selections)
            user_id: User identifier
            mode: Optimization mode

        Returns:
            MessageResponse with message_id and status
        """
        # Store attachments in metadata for handler access
        enriched_metadata = metadata.copy() if metadata else {}
        if attachments:
            enriched_metadata["attachments"] = attachments

        return await self.queue.enqueue(
            conversation_id=conversation_id,
            content=content,
            handler=self.handle_message_stream,
            user_id=user_id,
            mode=mode,
            metadata=enriched_metadata,
        )

    async def handle_message_stream(
        self,
        conversation_id: str,
        user_message: str,
        mode: OptimizationMode = OptimizationMode.ONLINE,
        user_id: str = "default_user",
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamingEvent | FinalOutputEvent]:
        """
        Handle user message with multi-agent routing (streaming version).

        Main orchestration method that coordinates all components:
        1. Load/create context (ContextManager)
        2. Classify intent (AgentHandoffCoordinator)
        3. Route to specialist (AgentHandoffCoordinator)
        4. Execute specialist (AgentFactory)
        5. Stream events (yields)
        6. Update and save context

        Args:
            conversation_id: Unique conversation identifier
            user_message: User's input message
            mode: Optimization mode
            user_id: User identifier
            metadata: Optional message metadata (e.g., for option selections)

        Yields:
            StreamingEvent objects
        """
        logger.debug(
            "handling_message",
            conversation_id=conversation_id,
            mode=mode.value if hasattr(mode, "value") else mode,
            has_metadata=metadata is not None,
        )

        # Prompt injection guardrail (log-only, does not block)
        from starboard_server.agents.guardrails.injection_detector import (
            scan_for_injection,
        )

        injection_result = scan_for_injection(user_message)
        if injection_result.is_suspicious:
            logger.warning(
                "prompt_injection_scan_suspicious",
                conversation_id=conversation_id,
                user_id=user_id,
                matched_patterns=injection_result.matched_patterns,
                confidence=injection_result.confidence,
            )

        # Load or create shared context
        shared_context = await self._context_manager.load_or_create(
            conversation_id, user_id
        )

        # Add user message to history with metadata (for option selection context)
        shared_context.add_message(
            Message(role="user", content=user_message, metadata=metadata or {})
        )

        # Extract and apply parameters from option selection
        if metadata and metadata.get("is_option_selection"):
            selected_option = metadata.get("selected_option", {})
            # Use "or {}" because .get() returns None if key exists with None value
            parameters = selected_option.get("parameters") or {}

            # Extract option metadata for tracking (always track, even with empty params)
            option_metadata = {
                "id": selected_option.get("id"),
                "action_type": selected_option.get("action_type"),
                "target_agent": selected_option.get("target_agent"),
            }

            # Enrich context with option parameters (tracks metadata even if params empty)
            shared_context.enrich_from_option_selection(
                parameters=parameters,
                option_metadata=option_metadata,
            )

            if parameters:
                logger.debug(
                    "option_selection_parameters_applied",
                    conversation_id=conversation_id,
                    option_id=selected_option.get("id"),
                    action_type=selected_option.get("action_type"),
                    target_agent=selected_option.get("target_agent"),
                    parameter_keys=list(parameters.keys()),
                )

        # Save context immediately
        await self.state_manager.save_context(shared_context)

        # Check if this is an option selection with explicit target_agent
        # If so, bypass intent classification and route directly to the target agent
        # This enables seamless cross-domain handoffs from next steps
        route_decision = None
        if metadata and metadata.get("is_option_selection"):
            selected_option = metadata.get("selected_option", {})
            target_agent = selected_option.get("target_agent")

            if target_agent:
                # Use canonical ROUTABLE_DOMAINS constant
                from starboard_server.prompts.base import ROUTABLE_DOMAINS

                if target_agent in ROUTABLE_DOMAINS:
                    from starboard_server.agents.routing.routing_models import (
                        RouteDecision,
                    )

                    # Create direct route decision - bypass intent router
                    route_decision = RouteDecision(
                        domain=target_agent,
                        confidence=1.0,  # High confidence - explicit user selection
                        extracted_ids=selected_option.get("parameters", {}),
                        context=selected_option.get("parameters", {}),
                        clarification_needed=False,
                        reasoning=f"User selected next step with target agent: {target_agent}",
                    )

                    logger.info(
                        "direct_agent_handoff",
                        conversation_id=conversation_id,
                        target_agent=target_agent,
                        option_id=selected_option.get("id"),
                        option_title=selected_option.get("title"),
                    )

        # If no direct handoff, use normal intent classification
        if route_decision is None:
            # Extract attachments from metadata for routing
            attachments = metadata.get("attachments") if metadata else None

            route_decision = await self.handoff.classify_and_route(
                user_message=user_message,
                conversation_history=shared_context.conversation_history,
                conversation_id=conversation_id,
                attachments=attachments,
            )

        # Broadcast routing decision
        routing_event = self.handoff.create_routing_event(route_decision)
        await self.events.broadcast(conversation_id, routing_event)

        # Generate friendly name if routing
        friendly_name_event = self.handoff.create_friendly_name_event(
            route_decision, user_message=user_message
        )
        if friendly_name_event:
            logger.debug(
                "broadcasting_friendly_name_event",
                conversation_id=conversation_id,
                friendly_name=friendly_name_event.data.get("friendly_name"),
                domain=route_decision.domain,
            )
            await self.events.broadcast(conversation_id, friendly_name_event)

        # If clarification needed, ask user
        if self.handoff.should_request_clarification(route_decision):
            logger.debug("clarification_needed")

            events = self.handoff.generate_clarification_events(conversation_id)
            if events:
                for event in events:
                    yield event

                # Save context with user message
                await self.state_manager.save_context(shared_context)
                return

        # === PHASE 2: Execute Specialist (via AgentHandoffCoordinator + AgentFactory) ===
        logger.debug("invoking_specialist_agent", domain=route_decision.domain)

        # === LARGE FILE METADATA DETECTION ===
        # If diagnostic agent and large file attachments, detect types for metadata
        # Agent will use explore_artifact tool for intent-aware extraction
        if route_decision.domain == "diagnostic":
            large_file_attachments = route_decision.context.get(
                "large_file_attachments"
            )
            if large_file_attachments and self._cache_factory:
                from starboard_server.agents.events import ThinkingEvent

                cache = self._cache_factory.get_or_create("attachments")

                for attachment in large_file_attachments:
                    attachment_id = attachment.get("id")
                    if not attachment_id:
                        continue

                    # Load content from cache for type detection only
                    cached_data = await cache.get(attachment_id)
                    if not cached_data or not cached_data.get("content"):
                        logger.warning(
                            "large_file_not_found_in_cache",
                            attachment_id=attachment_id,
                        )
                        continue

                    # Quick type detection from content preview
                    content_preview = cached_data["content"][:2000]
                    detected_type = self._quick_detect_artifact_type(
                        content_preview, attachment.get("filename", "")
                    )

                    # Update attachment with detected type for context builder
                    attachment["detected_type"] = detected_type

                    # Emit metadata event (not full processing)
                    from starboard_server.domain.conversation.api_types import (
                        convert_streaming_event_to_chat_event,
                    )

                    thinking_event = ThinkingEvent(
                        step=0,
                        content=f"📁 Large file available: {attachment.get('filename', 'unknown')} "
                        f"({cached_data.get('size', 0):,} bytes, {detected_type})",
                    )
                    chat_event = convert_streaming_event_to_chat_event(
                        thinking_event, conversation_id
                    )
                    await self.events.broadcast(conversation_id, chat_event)

                    logger.info(
                        "large_file_metadata_detected",
                        attachment_id=attachment_id,
                        detected_type=detected_type,
                        size=cached_data.get("size", 0),
                    )

        # Get specialist agent
        conversation_config = shared_context.metadata.get("conversation_config")
        specialist = self.handoff.get_specialist(
            domain=route_decision.domain,
            conversation_config=conversation_config,
        )

        # Record transition
        transition = self.handoff.record_transition(
            shared_context=shared_context,
            route_decision=route_decision,
        )

        # Broadcast transition
        transition_event = self.handoff.create_transition_event(transition)
        await self.events.broadcast(conversation_id, transition_event)

        # Build specialist context
        specialist_context = self._context_builder.build(
            shared_context=shared_context,
            route_decision=route_decision,
        )

        # Track assistant response content to add to conversation history
        assistant_response_parts: list[str] = []
        complete_report_data: dict[str, Any] | None = (
            None  # Track complete_report for history
        )
        next_steps_data: list[Any] | None = (
            None  # Track next_steps for history (Issue #1 fix)
        )
        tool_calls_list: list[dict[str, Any]] = []  # Track tool_calls for history
        thinking_steps_list: list[
            dict[str, Any]
        ] = []  # Track thinking steps for history

        # Phase 2: Initialize position tracker for streaming tool positions
        # Calculates positions during streaming, not after
        position_tracker = PositionTracker()

        # Stream specialist's response
        async for event in specialist.run_stream(
            user_id=user_id,
            user_input=user_message,
            mode=mode,
            context=specialist_context,
        ):
            # Update shared context from events (mutates in place)
            self._event_updater.update(shared_context, event)

            # Accumulate assistant response content
            if hasattr(event, "content") and event.content:
                # Phase 2: Track content for position calculation
                position_tracker.add_thinking(event.content)
                assistant_response_parts.append(event.content)

            # Capture ThinkingStepUpdate events for history persistence
            from starboard_server.agents.events import (
                ThinkingStepUpdate,
                ToolEndEvent,
                ToolStartEvent,
            )

            if isinstance(event, ThinkingStepUpdate):
                # Convert to dict for storage in metadata
                thinking_steps_list.append(
                    {
                        "id": event.step_id,
                        "title": event.title,
                        "status": event.status,
                        "start_time": event.start_time,
                        "end_time": event.end_time,
                        "progress": event.progress,
                        "sub_tasks": [
                            {
                                "id": t.id,
                                "description": t.description,
                                "status": t.status,
                                "value": t.value,
                            }
                            for t in event.sub_tasks
                        ],
                        "metadata": event.metadata,
                    }
                )

            if isinstance(event, ToolStartEvent):
                # Phase 2: Calculate position for this tool during streaming
                tool_position = position_tracker.add_tool_position(
                    tool_call_id=event.tool_call_id,
                    tool_name=event.tool_name,
                )

                # Add single newline for position calculation (frontend handles spacing)
                # Reduced from \n\n to \n since InlineToolSummary handles visual spacing
                if assistant_response_parts:
                    line_break = "\n"
                    assistant_response_parts.append(line_break)
                    position_tracker.add_thinking(line_break)
                    # Yield the line break so frontend content updates in real-time
                    from starboard_server.agents.events import ThinkingEvent

                    yield ThinkingEvent(step=event.step, content=line_break)

                # Store tool call info when it starts
                tool_calls_list.append(
                    {
                        "tool_call_id": event.tool_call_id,
                        "tool_name": event.tool_name,
                        "friendly_name": event.friendly_name,
                        "arguments": event.arguments,
                        "status": "running",
                    }
                )

                # Phase 2: Yield tool start with position (no markers!)
                # Frontend will accumulate positions as they arrive
                yield ToolStartEvent(
                    step=event.step,
                    tool_name=event.tool_name,
                    tool_call_id=event.tool_call_id,
                    arguments=event.arguments,
                    friendly_name=event.friendly_name,
                    tool_positions=[tool_position.to_dict()],
                )
                continue  # Don't yield original event

            elif isinstance(event, ToolEndEvent):
                # Update tool call status when it completes
                for tc in tool_calls_list:
                    if tc["tool_call_id"] == event.tool_call_id:
                        tc["status"] = "completed" if event.success else "failed"
                        tc["output"] = event.result_summary
                        tc["duration_ms"] = int(event.duration_seconds * 1000)
                        if not event.success and event.error:
                            tc["error"] = event.error
                        break

            # Capture complete_report and next_steps from FinalOutputEvent for history
            from starboard_server.agents.events import FinalOutputEvent

            if isinstance(event, FinalOutputEvent):
                output = event.output
                complete_report = getattr(output, "complete_report", None)
                if complete_report:
                    # Ensure complete_report is a dict
                    if not isinstance(complete_report, dict):
                        if hasattr(complete_report, "model_dump"):
                            complete_report_data = complete_report.model_dump()
                    else:
                        complete_report_data = complete_report

                # Extract next_steps for persistence (Issue #1 fix)
                next_steps = getattr(output, "next_steps", None)
                if next_steps:
                    # Serialize to dicts for storage
                    from starboard_server.agents.serialization import serialize_step

                    next_steps_data = [serialize_step(step) for step in next_steps]
                    logger.debug(
                        "next_steps_captured_for_persistence",
                        conversation_id=conversation_id,
                        next_steps_count=len(next_steps_data),
                    )

            # Handle user input requests
            if isinstance(event, UserInputRequestEvent):
                logger.debug("user_input_requested", request_id=event.request_id)

            yield event

        # Add assistant response to conversation history with complete_report in metadata
        if assistant_response_parts:
            full_response = "".join(assistant_response_parts)

            # Build metadata with complete_report if available
            metadata = {}
            message_content = full_response

            if complete_report_data:
                metadata["complete_report"] = complete_report_data

                # Format the report to markdown and store in metadata
                # Keep message.content as thinking text for tool expansions
                try:
                    from starboard_server.agents.report_formatters import (
                        format_agent_report,
                    )

                    formatted_markdown = format_agent_report(complete_report_data)
                    metadata["formatted_markdown"] = formatted_markdown
                except Exception as fmt_err:  # noqa: BLE001 - optional formatting
                    logger.debug(
                        "report_formatting_failed",
                        error=str(fmt_err),
                    )

            # Add tool_calls to metadata if any were captured
            if tool_calls_list:
                metadata["tool_calls"] = tool_calls_list

                # Phase 2: Store final positions from tracker
                # Positions were calculated during streaming, not after
                final_positions = position_tracker.get_all_positions()
                if final_positions:
                    metadata["tool_positions"] = final_positions
                    logger.debug(
                        "tool_positions_stored",
                        conversation_id=conversation_id,
                        position_count=len(final_positions),
                        method="streaming",  # Calculated during streaming
                    )

            # Add next_steps to metadata for persistence (Issue #1 fix)
            if next_steps_data:
                metadata["next_steps"] = next_steps_data

            # Add thinking_steps to metadata for history reload (B2 fix)
            if thinking_steps_list:
                # Deduplicate steps by id - keep the last (most complete) version
                steps_by_id: dict[str, dict[str, Any]] = {}
                for step in thinking_steps_list:
                    steps_by_id[step["id"]] = step
                metadata["thinking_steps"] = list(steps_by_id.values())
                logger.debug(
                    "thinking_steps_stored",
                    conversation_id=conversation_id,
                    step_count=len(steps_by_id),
                )

            shared_context.add_message(
                Message(role="assistant", content=message_content, metadata=metadata)
            )
            logger.debug(
                "assistant_response_added_to_history",
                conversation_id=conversation_id,
                response_length=len(message_content),
                conversation_history_length=len(shared_context.conversation_history),
                has_complete_report=complete_report_data is not None,
                has_next_steps=next_steps_data is not None,
            )

        # Save updated context
        await self.state_manager.save_context(shared_context)

        logger.info("message_handling_completed", conversation_id=conversation_id)

    # =========================================================================
    # SSE Event Broadcasting (Delegates to EventBroadcastCoordinator)
    # =========================================================================

    async def subscribe(self, conversation_id: str) -> asyncio.Queue[ChatEvent]:
        """Subscribe to events for a conversation."""
        return await self.events.subscribe(conversation_id)

    async def unsubscribe(
        self, conversation_id: str, queue: asyncio.Queue[ChatEvent]
    ) -> None:
        """Unsubscribe from events for a conversation."""
        await self.events.unsubscribe(conversation_id, queue)

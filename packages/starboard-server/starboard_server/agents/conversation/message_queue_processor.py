# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Message queue processor for background message handling.

Handles:
- Enqueu

ing messages for background processing
- Processing messages through the multi-agent system
- Broadcasting streaming events to SSE subscribers
- Managing background tasks and callbacks
- Handling pending user input requests

Extracted from MultiAgentConversationManager for clean separation of concerns.

Design:
- Manages asyncio background tasks for message processing
- Coordinates with EventBroadcastCoordinator for SSE broadcasting
- Handles task lifecycle (creation, tracking, cleanup)
- Supports user input injection for agent clarifications

Example:
    >>> processor = MessageQueueProcessor(
    ...     event_coordinator=event_coordinator,
    ...     request_input_tool=request_input_tool,
    ... )
    >>>
    >>> # Enqueue message for processing
    >>> response = await processor.enqueue(
    ...     conversation_id="conv_123",
    ...     content="Optimize query q123",
    ...     handler=manager.handle_message_stream,
    ... )
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starboard_core.domain.models.llm import OptimizationMode

from starboard_server.adapters.conversation.event_converter import (
    convert_streaming_event_to_chat_event,
)
from starboard_server.agents.events import (
    UserInputRequestEvent,
)
from starboard_server.domain.conversation.api_types import (
    ChatEvent,
    EventType,
    MessageResponse,
    MessageStatus,
)
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class MessageQueueProcessor:
    """
    Processes messages in the background and broadcasts events to subscribers.

    Responsibilities:
    - Enqueue messages for background processing
    - Manage background asyncio tasks
    - Process message streams and broadcast events
    - Handle task completion and cleanup
    - Track pending user input requests

    Does NOT:
    - Execute agent logic (that's handle_message_stream's job)
    - Manage conversation CRUD (ConversationLifecycleManager)
    - Route between agents (AgentHandoffCoordinator)
    - Handle subscription management (EventBroadcastCoordinator)

    Example:
        >>> processor = MessageQueueProcessor(
        ...     event_coordinator=event_coordinator,
        ...     request_input_tool=request_input_tool,
        ... )
        >>>
        >>> # Enqueue message
        >>> response = await processor.enqueue(
        ...     conversation_id="conv_123",
        ...     content="Optimize query",
        ...     handler=manager.handle_message_stream,
        ... )
        >>>
        >>> # Check task status
        >>> has_task = processor.has_active_task("conv_123")
    """

    # Grace period in seconds after injecting a user response
    # Don't cancel tasks that just received input (prevents duplicate cancellation bug)
    INPUT_INJECTION_GRACE_PERIOD_SECONDS = 30

    def __init__(
        self,
        event_coordinator: Any,  # EventBroadcastCoordinator
        request_input_tool: Any | None = None,  # RequestUserInputTool
    ):
        """
        Initialize message queue processor.

        Args:
            event_coordinator: Coordinator for broadcasting events
            request_input_tool: Tool for handling user input during reasoning
        """
        self.event_coordinator = event_coordinator
        self.request_input_tool = request_input_tool

        # Track background processing tasks
        self._processing_tasks: dict[str, asyncio.Task] = {}

        # Track pending user input requests
        self._pending_input_requests: dict[str, dict[str, str]] = {}

        # Track continuation message IDs (for events after user input)
        self._continuation_message_ids: dict[str, str] = {}

        # Track when user responses were injected (for grace period protection)
        # Prevents duplicate submissions from cancelling legitimately processing tasks
        self._last_input_injection: dict[str, datetime] = {}

    async def enqueue(
        self,
        conversation_id: str,
        content: str,
        handler: Callable,  # handle_message_stream method
        user_id: str = "default_user",
        mode: OptimizationMode = OptimizationMode.ONLINE,  # noqa: ARG002
        metadata: dict[str, Any] | None = None,
    ) -> MessageResponse:
        """
        Enqueue a message for background processing.

        If there's a pending user input request, routes the message as a response
        to that request. Otherwise, starts a new background processing task.

        Args:
            conversation_id: Unique conversation identifier
            content: User message content
            handler: The handle_message_stream method to call
            user_id: User identifier
            mode: Optimization mode
            metadata: Optional metadata (e.g., for option selections)

        Returns:
            MessageResponse with message_id and status

        Example:
            >>> response = await processor.enqueue(
            ...     conversation_id="conv_123",
            ...     content="Optimize query q123",
            ...     handler=manager.handle_message_stream,
            ... )
        """
        message_id = f"msg_{uuid4().hex[:12]}"
        trace_id = f"trace_{uuid4().hex[:8]}"

        # Check if there's a pending user input request
        has_pending = conversation_id in self._pending_input_requests
        request_input_tool = self.request_input_tool
        has_tool = request_input_tool is not None
        has_active_task = self.has_active_task(conversation_id)

        logger.debug(
            "enqueue_state_check",
            conversation_id=conversation_id,
            has_pending_input_request=has_pending,
            has_request_input_tool=has_tool,
            has_active_task=has_active_task,
            content_preview=content[:50],
        )

        if has_pending and request_input_tool is not None:
            # Route this message as a response to the pending request
            pending_request = self._pending_input_requests[conversation_id]
            request_id = pending_request["request_id"]

            # IMPORTANT: Check if the task is still active (waiting for input)
            # If the task already completed/timed out, we should start a new one
            if not has_active_task:
                logger.warning(
                    "pending_request_but_no_active_task",
                    conversation_id=conversation_id,
                    request_id=request_id,
                    note="Task may have timed out or completed. Clearing stale pending request and starting new task.",
                )
                # Clear the stale pending request and fall through to start a new task
                del self._pending_input_requests[conversation_id]
                # Don't return - fall through to start a new task below
            else:
                # Task is active and waiting - inject the response
                logger.debug(
                    "routing_message_to_pending_input_request",
                    conversation_id=conversation_id,
                    request_id=request_id,
                    content_length=len(content),
                )

                # Inject the response into the tool
                # The original agent task is waiting on input_queue.get() and will
                # resume automatically when this response is injected
                request_input_tool.inject_response(request_id, content)

                # Clear the pending request
                del self._pending_input_requests[conversation_id]

                # Record injection timestamp for grace period protection
                # This prevents duplicate submissions from cancelling the task
                self._last_input_injection[conversation_id] = datetime.now(UTC)

                logger.debug(
                    "user_response_injected_to_waiting_agent",
                    conversation_id=conversation_id,
                    request_id=request_id,
                    message_id=message_id,
                    injection_timestamp=self._last_input_injection[
                        conversation_id
                    ].isoformat(),
                    note="Original agent task will resume with user response",
                )

                # Create a new message_id for the agent's continuation
                # This ensures the continuation appears AFTER the user's response in the UI
                continuation_message_id = f"msg_{uuid4().hex[:12]}"

                logger.debug(
                    "emitting_continuation_message_start",
                    conversation_id=conversation_id,
                    old_message_id=message_id,
                    new_message_id=continuation_message_id,
                )

                # Emit MESSAGE_START for the continuation
                continuation_start = ChatEvent(
                    event_id=f"evt_start_{conversation_id}_cont",
                    type=EventType.MESSAGE_START,
                    data={
                        "content": "",
                        "message_id": continuation_message_id,
                        "continuation": True,
                    },
                    timestamp=datetime.now(UTC),
                )
                await self.event_coordinator.broadcast(
                    conversation_id, continuation_start
                )

                # Store the new message_id for subsequent events from the agent
                # This is used by _process_and_broadcast to associate events with the right message
                self._continuation_message_ids[conversation_id] = (
                    continuation_message_id
                )

                # Return PENDING status - the original agent task is still running
                # and will continue processing after receiving the injected response.
                # DO NOT start a new task - that would re-route through intent router
                # and lose the agent's context.
                return MessageResponse(
                    message_id=message_id,
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    status=MessageStatus.PENDING,
                    timestamp=datetime.now(UTC),
                )

        # Check for active processing task and cancel it (Interruptible Reasoning)
        # This prevents parallel execution and ensures new message overrides old one
        # BUT: Don't cancel if we just injected a user response (grace period)
        if conversation_id in self._processing_tasks:
            existing_task = self._processing_tasks[conversation_id]
            if not existing_task.done():
                # Check grace period - don't cancel tasks that just received user input
                # This prevents duplicate submissions from incorrectly cancelling tasks
                last_injection = self._last_input_injection.get(conversation_id)
                if last_injection:
                    seconds_since_injection = (
                        datetime.now(UTC) - last_injection
                    ).total_seconds()
                    if (
                        seconds_since_injection
                        < self.INPUT_INJECTION_GRACE_PERIOD_SECONDS
                    ):
                        logger.debug(
                            "skipping_cancellation_recent_input_injection",
                            conversation_id=conversation_id,
                            seconds_since_injection=seconds_since_injection,
                            grace_period=self.INPUT_INJECTION_GRACE_PERIOD_SECONDS,
                            reason="Task is processing recently injected user response",
                        )
                        # Return PENDING - let the existing task continue processing
                        # This prevents duplicate submissions from breaking agent flow
                        return MessageResponse(
                            message_id=message_id,
                            conversation_id=conversation_id,
                            trace_id=trace_id,
                            status=MessageStatus.PENDING,
                            timestamp=datetime.now(UTC),
                        )

                logger.debug(
                    "cancelling_active_task_for_new_message",
                    conversation_id=conversation_id,
                    reason="interruption",
                )
                existing_task.cancel()
                # We don't await cancellation here to keep enqueue responsive
                # The task callback will clean up _processing_tasks entry

        logger.debug(
            "message_enqueued",
            conversation_id=conversation_id,
            message_id=message_id,
            content_preview=content[:50],
            has_metadata=metadata is not None,
        )

        # Start background processing task
        task = asyncio.create_task(
            self._process_and_broadcast(
                conversation_id=conversation_id,
                user_message=content,
                user_id=user_id,
                handler=handler,
                metadata=metadata,
            )
        )

        # Store task reference
        self._processing_tasks[conversation_id] = task
        task.add_done_callback(lambda t: self._on_task_complete(t, conversation_id))

        return MessageResponse(
            message_id=message_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            status=MessageStatus.PENDING,
            timestamp=datetime.now(UTC),
        )

    async def _process_and_broadcast(
        self,
        conversation_id: str,
        user_message: str,
        user_id: str,
        handler: Callable,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Process a message and broadcast events to SSE subscribers.

        This runs in a background task. It calls the handler (handle_message_stream)
        and broadcasts all events to connected SSE clients.

        Args:
            conversation_id: Unique conversation identifier
            user_message: User's message content
            user_id: User identifier
            handler: The handle_message_stream method
            metadata: Optional message metadata (e.g., for option selections)
        """
        event_count = 0
        user_input_request_active = False

        try:
            logger.debug(
                "starting_message_processing",
                conversation_id=conversation_id,
                content_preview=user_message[:50],
            )

            # Generate stable message_id for the assistant's response
            message_id = f"msg_{uuid4().hex[:12]}"

            # Send message.start event
            start_event = ChatEvent(
                event_id=f"evt_start_{conversation_id}",
                type=EventType.MESSAGE_START,
                data={"content": user_message, "message_id": message_id},
                timestamp=datetime.now(UTC),
            )
            await self.event_coordinator.broadcast(conversation_id, start_event)

            logger.debug(
                "message_start_event_broadcasted",
                conversation_id=conversation_id,
                message_id=message_id,
            )

            # Stream events from the handler
            async for event in handler(
                conversation_id=conversation_id,
                user_message=user_message,
                user_id=user_id,
                metadata=metadata,
            ):
                event_count += 1
                # Use INFO level for event timing visibility
                logger.debug(
                    "event_yielded_from_handler",
                    conversation_id=conversation_id,
                    event_count=event_count,
                    event_type=type(event).__name__,
                )

                # Handle user input request events
                if isinstance(event, UserInputRequestEvent):
                    # Store pending request
                    self._pending_input_requests[conversation_id] = {
                        "request_id": event.request_id,
                        "question": event.question,
                    }
                    user_input_request_active = True
                    logger.debug(
                        "user_input_request_pending",
                        conversation_id=conversation_id,
                        request_id=event.request_id,
                    )

                    # Immediately send MESSAGE_END when requesting user input
                    # This marks the message as complete (waiting for input) so the UI
                    # shows "completed" instead of "processing" during the 5 minute wait
                    end_event_early = ChatEvent(
                        event_id=f"evt_end_{conversation_id}_input",
                        type=EventType.MESSAGE_END,
                        data={
                            "message_id": message_id,
                            "waiting_for_input": True,
                        },
                        timestamp=datetime.now(UTC),
                    )

                    # Broadcast the event first, then send MESSAGE_END
                    chat_event = convert_streaming_event_to_chat_event(
                        event, conversation_id, message_id=message_id
                    )
                    await self.event_coordinator.broadcast(conversation_id, chat_event)
                    await self.event_coordinator.broadcast(
                        conversation_id, end_event_early
                    )

                    logger.debug(
                        "message_end_sent_for_user_input",
                        conversation_id=conversation_id,
                        request_id=event.request_id,
                    )

                    # Continue to next event (the tool will block for user input)
                    continue

                # Check if we should use continuation message_id (after user input response)
                # This ensures events after user responds appear in the new message bubble
                effective_message_id = self._continuation_message_ids.get(
                    conversation_id, message_id
                )

                # Convert to ChatEvent and broadcast
                chat_event = convert_streaming_event_to_chat_event(
                    event, conversation_id, message_id=effective_message_id
                )

                # Log tool and friendly_name events for debugging
                if chat_event.type in (
                    EventType.TOOL_CALL_START,
                    EventType.TOOL_CALL_RESULT,
                ):
                    # Phase 2: Log tool_positions for streaming positions debugging
                    tool_positions = chat_event.data.get("tool_positions")
                    logger.debug(
                        "broadcasting_tool_event",
                        conversation_id=conversation_id,
                        event_type=chat_event.type.value,
                        tool_name=chat_event.data.get("tool_call", {}).get("tool_name"),
                        has_tool_positions=tool_positions is not None,
                        tool_positions_count=(
                            len(tool_positions) if tool_positions else 0
                        ),
                    )
                elif chat_event.type == EventType.FRIENDLY_NAME_UPDATE:
                    logger.debug(
                        "broadcasting_friendly_name_event_from_processor",
                        conversation_id=conversation_id,
                        friendly_name=chat_event.data.get("friendly_name"),
                    )

                await self.event_coordinator.broadcast(conversation_id, chat_event)

            # Always send message.end event to mark message as complete
            # Even when waiting for user input, the message content IS complete -
            # it's asking the user a question. The status should show "completed".
            final_message_id = self._continuation_message_ids.get(
                conversation_id, message_id
            )
            end_event = ChatEvent(
                event_id=f"evt_end_{conversation_id}",
                type=EventType.MESSAGE_END,
                data={
                    "message_id": final_message_id,
                    "waiting_for_input": user_input_request_active,
                },
                timestamp=datetime.now(UTC),
            )
            await self.event_coordinator.broadcast(conversation_id, end_event)

            # Clean up continuation message_id
            self._continuation_message_ids.pop(conversation_id, None)

            if user_input_request_active:
                logger.debug(
                    "message_processing_completed_awaiting_input",
                    conversation_id=conversation_id,
                    event_count=event_count,
                )
            else:
                logger.debug(
                    "message_processing_completed",
                    conversation_id=conversation_id,
                    event_count=event_count,
                )

        except Exception as e:  # noqa: BLE001 - message handler boundary
            logger.error(
                "message_processing_failed",
                conversation_id=conversation_id,
                error=str(e),
                exc_info=True,
            )

            # Broadcast error event (format must match frontend ErrorDataSchema)
            error_event = ChatEvent(
                event_id=f"evt_error_{conversation_id}",
                type=EventType.ERROR,
                data={
                    "error": {
                        "message": str(e),
                        "code": type(e).__name__,
                    }
                },
                timestamp=datetime.now(UTC),
            )
            await self.event_coordinator.broadcast(conversation_id, error_event)

    def _on_task_complete(
        self,
        task: asyncio.Task,
        conversation_id: str,
    ) -> None:
        """
        Callback when a processing task completes.

        Args:
            task: The completed task
            conversation_id: Conversation identifier
        """
        # Remove task from tracking ONLY if it's the one currently tracked
        # This prevents removing a new task that replaced this old one
        if (
            conversation_id in self._processing_tasks
            and self._processing_tasks[conversation_id] == task
        ):
            del self._processing_tasks[conversation_id]

        # Clean up injection timestamp (no longer needed after task completes)
        self._last_input_injection.pop(conversation_id, None)

        try:
            # Check if task raised an exception
            exception = task.exception()
            if exception:
                logger.error(
                    "background_task_failed",
                    conversation_id=conversation_id,
                    error=str(exception),
                )
        except Exception as e:  # noqa: BLE001 - queue handler boundary
            logger.error(
                "task_completion_callback_failed",
                conversation_id=conversation_id,
                error=str(e),
            )

    def has_active_task(self, conversation_id: str) -> bool:
        """
        Check if there's an active processing task for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if task exists and is not done, False otherwise
        """
        if conversation_id not in self._processing_tasks:
            return False

        task = self._processing_tasks[conversation_id]
        return not task.done()

    def cancel_task(self, conversation_id: str) -> bool:
        """
        Cancel active processing task for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if task was cancelled, False if no task found
        """
        if conversation_id not in self._processing_tasks:
            return False

        task = self._processing_tasks[conversation_id]
        if not task.done():
            task.cancel()
            logger.debug(
                "cancelled_processing_task",
                conversation_id=conversation_id,
            )
            return True

        return False

    def clear_pending_input_request(self, conversation_id: str) -> None:
        """
        Clear pending user input request for a conversation.

        Args:
            conversation_id: Conversation identifier
        """
        if conversation_id in self._pending_input_requests:
            del self._pending_input_requests[conversation_id]

    def has_pending_input_request(self, conversation_id: str) -> bool:
        """
        Check if there's a pending user input request.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if pending input request exists, False otherwise
        """
        return conversation_id in self._pending_input_requests

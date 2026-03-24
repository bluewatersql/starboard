"""
Tool for requesting user input during reasoning (V2 interface).

This tool allows the agent to pause execution and wait for user response
when critical information is missing.

IMPORTANT: This tool includes validation to reject questions that should
use defaults instead of asking the user. This prevents agents from being
overly cautious and asking unnecessary clarifying questions.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from starboard_server.infra.observability.events import EventEmitter
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# BLOCKED QUESTION PATTERNS (SAFETY NET)
# =============================================================================
# These patterns are a SAFETY NET - the real fix is in parameter_validator.py
# which auto-applies defaults for date parameters. These patterns catch cases
# where agents still try to ask about dates.

BLOCKED_QUESTION_PATTERNS = [
    # Questions containing BOTH "rolling" and "calendar" - asking user to choose
    r"rolling.*calendar",
    r"calendar.*rolling",
    # Asking what date/time range to use
    r"which\s*(time|date)\s*(range|period)",
    r"what\s*(date|time)\s*(range|period)",
    # Clarifying "last month" interpretation
    r"(did you mean|do you mean).*(calendar|rolling)",
]

# Compile patterns for efficiency
_BLOCKED_PATTERNS_COMPILED = [
    re.compile(pattern, re.IGNORECASE) for pattern in BLOCKED_QUESTION_PATTERNS
]


def _is_blocked_question(question: str) -> tuple[bool, str]:
    """
    Check if a question should be blocked because it asks about something
    that has a known default.

    Args:
        question: The question the agent wants to ask

    Returns:
        Tuple of (is_blocked, reason_message)
    """
    question_lower = question.lower()

    for pattern in _BLOCKED_PATTERNS_COMPILED:
        if pattern.search(question_lower):
            return True, (
                "This question is about date ranges or time periods. "
                "USE THE DEFAULT: start_date='30 days ago', end_date='today'. "
                "Do NOT ask the user to clarify - proceed with the 30-day default immediately."
            )

    return False, ""


class RequestUserInputTool:
    """
    Tool for requesting user input with timeout.

    This tool enables the agent to ask specific questions and wait for
    user responses. It emits a UserInputRequestEvent and blocks until
    a response is received or timeout occurs.

    Attributes:
        input_queue: Async queue for receiving user responses
        timeout_seconds: Default timeout for user responses (5 minutes)
        events: Event emitter for status updates
    """

    def __init__(
        self, events: EventEmitter | None = None, timeout_seconds: float = 300.0
    ):
        """
        Initialize the request user input tool.

        Args:
            events: Event emitter for status updates
            timeout_seconds: Default timeout in seconds (default: 300 = 5 minutes)
        """
        self.events = events if events is not None else EventEmitter()
        self.input_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.timeout_seconds = timeout_seconds

    def inject_response(self, request_id: str, response: str) -> None:
        """
        Inject a user response for a pending request.

        This method is called by the API layer when a user responds
        to a solicitation.

        Args:
            request_id: The request ID to respond to
            response: The user's response text

        Example:
            >>> tool.inject_response("input_abc123", "Option A")
        """
        try:
            self.input_queue.put_nowait(
                {"request_id": request_id, "response": response}
            )
            logger.debug(
                "user_response_injected",
                request_id=request_id,
                response_length=len(response),
            )
        except asyncio.QueueFull:
            logger.warning(
                "input_queue_full",
                request_id=request_id,
                note="Dropped response due to full queue",
            )

    async def request_user_input(
        self,
        question: str,
        context: str | None = None,
        suggestions: list[str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Request user input and wait for response (V2 interface).

        This tool PAUSES execution and waits for the user to respond.
        If no response is received within the timeout period, it returns
        an error and reasoning continues without the answer.

        Args:
            question: The question to ask the user (required)
            context: Why this info is needed (optional)
            suggestions: Suggested answers (optional)
            timeout: Override default timeout in seconds (optional)

        Returns:
            Dict with status, user_response, request_id, and instructions

        Example:
            >>> result = await tool.request_user_input(
            ...     question="Which query should I optimize?",
            ...     suggestions=["query_abc", "query_xyz"],
            ... )
            >>> print(result["user_response"])
            # "query_abc" (or None if timeout)
        """
        # Validate required parameters
        if not question:
            raise ValueError("question parameter is required")

        # =================================================================
        # VALIDATION: Block questions that should use defaults
        # =================================================================
        # This prevents agents from asking unnecessary clarifying questions
        # about things like date ranges, time periods, etc.
        is_blocked, block_reason = _is_blocked_question(question)
        if is_blocked:
            logger.info(
                "request_user_input_blocked",
                question=question[:100],
                reason="Question matches blocked pattern - should use defaults",
            )
            return {
                "status": "rejected",
                "error": block_reason,
                "instruction": (
                    "DO NOT ask the user this question. Use the default values and "
                    "proceed with your analysis. For date ranges, ALWAYS use "
                    "start_date='30 days ago' and end_date='today'."
                ),
                "question_rejected": question,
            }

        # Set defaults
        suggestions = suggestions or []
        timeout = timeout if timeout is not None else self.timeout_seconds

        # Generate unique request ID
        request_id = f"input_{uuid.uuid4().hex[:8]}"

        logger.debug(
            "requesting_user_input",
            request_id=request_id,
            question=question,
            timeout_seconds=timeout,
        )

        # Emit event for API/UI to display
        from starboard_server.agents.events import UserInputRequestEvent

        if self.events:
            event = UserInputRequestEvent(
                step=0,  # Will be set by agent if available
                question=question,
                context=context,
                suggestions=suggestions,
                timeout_seconds=int(timeout),
                request_id=request_id,
            )
            self.events.emit(event)  # type: ignore[arg-type]

        # Wait for response with timeout
        try:
            logger.debug("waiting_for_user_response", timeout_seconds=timeout)
            response_data = await asyncio.wait_for(
                self.input_queue.get(),
                timeout=timeout,
            )

            user_response = response_data.get("response", "")

            logger.debug(
                "user_response_received",
                request_id=request_id,
                response_length=len(user_response),
            )

            # Emit completion event to notify UI that input was received
            if self.events:
                from starboard_server.agents.events import (
                    UserInputResponseEvent,
                )

                response_event = UserInputResponseEvent(
                    step=0,
                    request_id=request_id,
                    user_response=user_response,
                    timed_out=False,
                )
                self.events.emit(response_event)  # type: ignore[arg-type]

            # Format result to make it crystal clear what the user provided
            # Include context to help agent remember what it was trying to do
            result_content = {
                "status": "success",
                "question_asked": question,
                "user_provided": user_response,
            }

            # Add context if it was provided to help agent remember the original goal
            if context:
                result_content["context"] = context
                result_content["instruction"] = (
                    f"The user provided: '{user_response}'. "
                    f"Context: {context}. "
                    f"Use this information to continue with the original goal. Do NOT ask for it again."
                )
            else:
                result_content["instruction"] = (
                    f"The user provided: '{user_response}'. "
                    f"Use this to continue with the original goal. Do NOT ask for it again."
                )

            return result_content

        except TimeoutError:
            error_msg = (
                f"User did not respond within {timeout} seconds. "
                "Proceeding with best-effort recommendations based on available information."
            )

            logger.warning(
                "user_input_timeout",
                request_id=request_id,
                timeout_seconds=timeout,
                message=error_msg,
            )

            # Emit timeout event to notify UI
            if self.events:
                from starboard_server.agents.events import (
                    UserInputResponseEvent,
                )

                timeout_event = UserInputResponseEvent(
                    step=0,
                    request_id=request_id,
                    user_response="",
                    timed_out=True,
                )
                self.events.emit(timeout_event)  # type: ignore[arg-type]

            return {
                "status": "timeout",
                "user_response": None,
                "request_id": request_id,
                "timed_out": True,
                "error": error_msg,
            }

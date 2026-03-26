"""Message processor service.

Processes incoming user messages to detect option selections and extract
executable actions. Part of Phase 1: Foundation - Component 6.

This service bridges user input with the agent workflow:
1. Checks if user is responding to presented options
2. Uses OptionSelectionProcessor to detect selections
3. Extracts executable actions (tool calls, routing, continue)
4. Falls back to free text processing if no option selected

Examples:
    >>> processor = MessageProcessor()
    >>>
    >>> # User selects an option
    >>> result = processor.process_message("2", available_options)
    >>> result.processing_type
    'option_selected'
    >>> result.action_to_execute
    {'type': 'tool_call', 'tool_name': '...', 'parameters': {...}}
    >>>
    >>> # User enters free text
    >>> result = processor.process_message("Tell me more", available_options)
    >>> result.processing_type
    'free_text'
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from starboard_core.models.conversation import Message  # Phase 2

from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    IntentClassification,  # Phase 2
    NextStepOption,
    OptionSelection,
)
from starboard_server.infra.observability.logging import get_logger
from starboard_server.services.clarification.option_selection import (
    OptionSelectionProcessor,
)
from starboard_server.services.intent.intent_classifier import (
    IntentClassifierService,
)  # Phase 2

logger = get_logger(__name__)


class ProcessingType(StrEnum):
    """Types of message processing results."""

    OPTION_SELECTED = "option_selected"
    FREE_TEXT = "free_text"
    INTENT_CLASSIFIED = "intent_classified"  # Phase 2
    ROUTING = "routing"  # Phase 3
    ROUTING_REJECTED = "routing_rejected"  # Phase 3
    CLARIFICATION_NEEDED = "clarification_needed"  # Phase 7


@dataclass(frozen=True)
class MessageProcessingResult:
    """Result of message processing.

    Attributes:
        processing_type: Whether user selected an option or entered free text
        original_input: The raw user input
        selected_option: The NextStepOption if an option was selected
        action_to_execute: Extracted action details (tool call, route, continue)
        confidence: Confidence level of the classification (0.0-1.0)
        intent_classification: Intent classification result (Phase 2, optional)
        routing_decision: Routing decision if routing was attempted (Phase 3, optional)
        handoff_id: UUID of initiated handoff if routing succeeded (Phase 3, optional)

    Examples:
        >>> # Phase 1: Option selection
        >>> result = MessageProcessingResult(
        ...     processing_type=ProcessingType.OPTION_SELECTED,
        ...     original_input="2",
        ...     selected_option=some_option,
        ...     action_to_execute={'type': 'tool_call', ...},
        ...     confidence=1.0,
        ...     intent_classification=None,
        ...     routing_decision=None,
        ...     handoff_id=None,
        ... )
        >>>
        >>> # Phase 2: Intent classification
        >>> result = MessageProcessingResult(
        ...     processing_type=ProcessingType.INTENT_CLASSIFIED,
        ...     original_input="What about mornings?",
        ...     selected_option=None,
        ...     action_to_execute=None,
        ...     confidence=0.85,
        ...     intent_classification=IntentClassification(...),
        ...     routing_decision=None,
        ...     handoff_id=None,
        ... )
        >>>
        >>> # Phase 3: Agent routing
        >>> result = MessageProcessingResult(
        ...     processing_type=ProcessingType.ROUTING,
        ...     original_input="1",
        ...     selected_option=route_option,
        ...     action_to_execute={'type': 'route', ...},
        ...     confidence=1.0,
        ...     intent_classification=None,
        ...     routing_decision=RoutingDecision(...),
        ...     handoff_id=uuid4(),
        ... )
    """

    processing_type: ProcessingType
    original_input: str
    selected_option: NextStepOption | None
    action_to_execute: dict[str, Any] | None
    confidence: float
    intent_classification: IntentClassification | None = None  # Phase 2
    routing_decision: Any | None = (
        None  # Phase 3 (RoutingDecision, avoiding circular import)
    )
    handoff_id: Any | None = None  # Phase 3 (UUID, avoiding import)
    clarification_request: Any | None = (
        None  # Phase 7 (ClarificationRequest, avoiding import)
    )


class MessageProcessor:
    """Processes user messages to detect option selections and classify intent.

    This service coordinates message processing across the conversation
    pattern system. It determines if a user message is selecting a
    previously presented option or is new free-form input, and optionally
    classifies the intent of free-form messages (Phase 2).

    Workflow:
        1. Check if options are available from previous agent response
        2. Use OptionSelectionProcessor to detect selection
        3. Extract executable action if option selected
        4. If free text and intent classification enabled, classify intent
        5. Return processing result with action details and/or intent

    Attributes:
        option_selector: OptionSelectionProcessor instance for detection
        intent_classifier: IntentClassifierService instance (if enabled)
        classify_intent: Whether to classify intent for free text (Phase 2)

    Examples:
        >>> # Phase 1: Option selection only
        >>> processor = MessageProcessor()
        >>> result = processor.process_message(
        ...     user_input="2",
        ...     available_options=agent_response.next_steps,
        ... )
        >>>
        >>> # Phase 2: With intent classification
        >>> processor = MessageProcessor(classify_intent=True)
        >>> result = processor.process_message(
        ...     user_input="What about mornings?",
        ...     available_options=None,
        ...     conversation_history=history,
        ...     previous_agent_response=None,
        ... )
        >>> if result.intent_classification:
        ...     print(result.intent_classification.intent_type)  # EXTENSION
    """

    def __init__(
        self,
        classify_intent: bool = False,
        routing_engine: Any | None = None,  # Phase 3 (RoutingEngine)
        handoff_manager: Any | None = None,  # Phase 3 (HandoffManager)
        clarification_manager: Any | None = None,  # Phase 7 (ClarificationManager)
        enable_clarification: bool = False,  # Phase 7 feature flag
    ) -> None:
        """Initialize message processor.

        Creates internal OptionSelectionProcessor instance for
        detecting option selections, and optionally creates
        IntentClassifierService for intent classification (Phase 2).

        Args:
            classify_intent: Whether to classify intent for free text messages
                            (default: False for backward compatibility)
            routing_engine: RoutingEngine for agent routing (Phase 3, optional)
            handoff_manager: HandoffManager for handoff management (Phase 3, optional)
            clarification_manager: ClarificationManager for ambiguity detection (Phase 7, optional)
            enable_clarification: Whether to enable clarification detection (Phase 7, default: False)
        """
        self.option_selector = OptionSelectionProcessor()
        self.classify_intent = classify_intent
        self.intent_classifier = IntentClassifierService() if classify_intent else None
        self.routing_engine = routing_engine  # Phase 3
        self.handoff_manager = handoff_manager  # Phase 3
        self.clarification_manager = clarification_manager  # Phase 7
        self.enable_clarification = enable_clarification  # Phase 7

    async def process_message(
        self,
        user_input: str,
        available_options: tuple[NextStepOption, ...] | None,
        conversation_history: tuple[Message, ...] | None = None,  # Phase 2
        previous_agent_response_content: str | None = None,  # Phase 2/3
        conversation_id: str | None = None,  # Phase 3
        current_agent: str | None = None,  # Phase 3
        target_tool: str | None = None,  # Phase 7 (for clarification)
        message_id: str | None = None,  # Phase 7 (for clarification tracking)
    ) -> MessageProcessingResult:
        """Process a user message to detect option selections and route if needed.

        Determines if the user is selecting a previously presented option
        or entering new free-form text. Extracts executable actions if
        an option is selected. Optionally classifies intent for free-form
        messages (Phase 2). Handles agent routing if a ROUTE option is
        selected (Phase 3).

        Args:
            user_input: Raw user message
            available_options: Options from previous agent response (if any)
            conversation_history: Previous messages in conversation (Phase 2, optional)
            previous_agent_response_content: Content of previous agent response (Phase 2/3, optional)
            conversation_id: ID of current conversation (Phase 3, optional, required for routing)
            current_agent: ID of current agent (Phase 3, optional, required for routing)

        Returns:
            MessageProcessingResult with processing type, selected option,
            executable action details, optional intent classification, and
            optional routing decision/handoff ID

        Examples:
            >>> # Phase 1: User selects option 2
            >>> result = await processor.process_message("2", options)
            >>> assert result.processing_type == ProcessingType.OPTION_SELECTED
            >>> assert result.action_to_execute['type'] == 'tool_call'
            >>>
            >>> # Phase 2: User enters free text with intent classification
            >>> result = await processor.process_message(
            ...     "What about mornings?",
            ...     None,
            ...     conversation_history=history,
            ... )
            >>> assert result.processing_type == ProcessingType.INTENT_CLASSIFIED
            >>> assert result.intent_classification.intent_type == UserIntentType.EXTENSION
            >>>
            >>> # Phase 3: User selects routing option
            >>> result = await processor.process_message(
            ...     "1",
            ...     route_options,
            ...     conversation_id="conv_123",
            ...     current_agent="query_optimizer",
            ... )
            >>> assert result.processing_type == ProcessingType.ROUTING
            >>> assert result.handoff_id is not None
        """
        # Default conversation_history to empty tuple if None (Phase 2)
        if conversation_history is None:
            conversation_history = ()

        # If no options available, treat as free text
        if not available_options:
            logger.debug("no_options_available", user_input=user_input)

            # Phase 7: Check for clarification before processing as free text
            if self.enable_clarification and self.clarification_manager and target_tool:
                clarification = self.clarification_manager.request_clarification(
                    query=user_input,
                    target_tool=target_tool,
                    conversation_id=conversation_id or "unknown",
                    message_id=message_id or "unknown",
                )

                if clarification:
                    logger.debug(
                        "clarification_needed",
                        clarification_id=clarification.clarification_id,
                        target_tool=target_tool,
                        conversation_id=conversation_id,
                    )

                    return MessageProcessingResult(
                        processing_type=ProcessingType.CLARIFICATION_NEEDED,
                        original_input=user_input,
                        selected_option=None,
                        action_to_execute=None,
                        confidence=1.0,
                        intent_classification=None,
                        routing_decision=None,
                        handoff_id=None,
                        clarification_request=clarification,
                    )

            # Classify intent if enabled (Phase 2)
            intent_classification = None
            processing_type = ProcessingType.FREE_TEXT
            if self.classify_intent and self.intent_classifier:
                intent_classification = self.intent_classifier.classify(
                    user_message=user_input,
                    conversation_history=conversation_history,
                    previous_agent_response=previous_agent_response_content,  # type: ignore[arg-type]
                )
                processing_type = ProcessingType.INTENT_CLASSIFIED
                logger.debug(
                    "intent_classified",
                    intent_type=intent_classification.intent_type.value,
                    confidence=intent_classification.confidence,
                )

            return MessageProcessingResult(
                processing_type=processing_type,
                original_input=user_input,
                selected_option=None,
                action_to_execute=None,
                confidence=1.0,
                intent_classification=intent_classification,
            )

        # Use option selector to detect selection
        selection: OptionSelection = self.option_selector.process(
            user_input=user_input,
            available_options=available_options,
        )

        # If option selected, extract action and check for routing
        if selection.selection_type == "option":
            logger.debug(
                "option_selected",
                option_number=(
                    selection.selected_option.number
                    if selection.selected_option
                    else None
                ),
                confidence=selection.confidence,
            )

            action = (
                self._extract_action(selection.selected_option)
                if selection.selected_option
                else None
            )

            # Phase 3: Check if this is a routing action
            if (
                selection.selected_option
                and selection.selected_option.action_type == ActionType.ROUTE
                and self.routing_engine
                and self.handoff_manager
                and conversation_id
                and current_agent
            ):
                # Import here to avoid circular imports
                from starboard_server.services.messaging.routing_engine import (
                    RoutingDecision,
                )

                # Check for circular routing first
                is_circular = await self.handoff_manager.is_circular_routing(
                    conversation_id=conversation_id,
                    max_handoffs=3,
                )

                if is_circular:
                    logger.warning(
                        "circular_routing_prevented",
                        conversation_id=conversation_id,
                        current_agent=current_agent,
                        target_agent=selection.selected_option.target_agent,
                    )
                    return MessageProcessingResult(
                        processing_type=ProcessingType.ROUTING_REJECTED,
                        original_input=user_input,
                        selected_option=selection.selected_option,
                        action_to_execute=action,
                        confidence=selection.confidence,
                        intent_classification=None,
                        routing_decision=RoutingDecision(
                            should_route=False,
                            target_agent_id=None,
                            capability_id=None,
                            handoff_context={},
                            confidence=1.0,
                            reasoning="Maximum handoff limit reached for conversation (circular routing prevention)",
                        ),
                        handoff_id=None,
                    )

                # Get routing decision
                routing_decision = self.routing_engine.should_route(
                    selected_option=selection.selected_option,
                    current_agent=current_agent,
                    conversation_summary=previous_agent_response_content or "",
                )

                # If routing needed, initiate handoff
                if routing_decision.should_route:
                    handoff = await self.handoff_manager.initiate_handoff(
                        conversation_id=conversation_id,
                        source_agent_id=current_agent,
                        target_agent_id=routing_decision.target_agent_id,
                        capability_id=routing_decision.capability_id,
                        handoff_context=routing_decision.handoff_context,
                    )

                    logger.debug(
                        "routing_initiated",
                        conversation_id=conversation_id,
                        handoff_id=str(handoff.handoff_id),
                        source_agent=current_agent,
                        target_agent=routing_decision.target_agent_id,
                    )

                    return MessageProcessingResult(
                        processing_type=ProcessingType.ROUTING,
                        original_input=user_input,
                        selected_option=selection.selected_option,
                        action_to_execute=action,
                        confidence=selection.confidence,
                        routing_decision=routing_decision,
                        handoff_id=handoff.handoff_id,
                    )
                else:
                    logger.warning(
                        "routing_rejected",
                        conversation_id=conversation_id,
                        current_agent=current_agent,
                        target_agent=selection.selected_option.target_agent,
                        reason=routing_decision.reasoning,
                    )

                    return MessageProcessingResult(
                        processing_type=ProcessingType.ROUTING_REJECTED,
                        original_input=user_input,
                        selected_option=selection.selected_option,
                        action_to_execute=action,
                        confidence=selection.confidence,
                        routing_decision=routing_decision,
                    )

            return MessageProcessingResult(
                processing_type=ProcessingType.OPTION_SELECTED,
                original_input=user_input,
                selected_option=selection.selected_option,
                action_to_execute=action,
                confidence=selection.confidence,
            )

        # Otherwise, treat as free text
        logger.debug("free_text_detected", user_input=user_input)

        # Classify intent if enabled (Phase 2)
        intent_classification = None
        processing_type = ProcessingType.FREE_TEXT
        if self.classify_intent and self.intent_classifier:
            intent_classification = self.intent_classifier.classify(
                user_message=user_input,
                conversation_history=conversation_history,
                previous_agent_response=previous_agent_response_content,  # type: ignore[arg-type]
            )
            processing_type = ProcessingType.INTENT_CLASSIFIED
            logger.debug(
                "intent_classified",
                intent_type=intent_classification.intent_type.value,
                confidence=intent_classification.confidence,
            )

        return MessageProcessingResult(
            processing_type=processing_type,
            original_input=user_input,
            selected_option=None,
            action_to_execute=None,
            confidence=selection.confidence,
            intent_classification=intent_classification,
        )

    def _extract_action(self, option: NextStepOption) -> dict[str, Any]:
        """Extract executable action from a NextStepOption.

        Converts a NextStepOption into a dictionary containing the
        action type and required parameters for execution.

        Args:
            option: The selected NextStepOption

        Returns:
            Dictionary with action details:
            - type: 'tool_call', 'route', or 'continue'
            - tool_name: Tool to call (if type='tool_call')
            - target_agent: Agent to route to (if type='route')
            - parameters: Action parameters

        Examples:
            >>> action = processor._extract_action(tool_option)
            >>> assert action['type'] == 'tool_call'
            >>> assert action['tool_name'] == 'optimize_query'
            >>>
            >>> action = processor._extract_action(route_option)
            >>> assert action['type'] == 'route'
            >>> assert action['target_agent'] == 'cost_analyzer'
        """
        if option.action_type == ActionType.TOOL_CALL:
            return {
                "type": "tool_call",
                "tool_name": option.tool_name,
                "parameters": option.parameters or {},
            }
        elif option.action_type == ActionType.ROUTE:
            return {
                "type": "route",
                "target_agent": option.target_agent,
                "parameters": option.parameters or {},
            }
        elif option.action_type == ActionType.CONTINUE:
            return {
                "type": "continue",
                "parameters": option.parameters or {},
            }
        else:
            logger.warning(
                "unknown_action_type",
                action_type=option.action_type,
            )
            return {
                "type": "continue",
                "parameters": {},
            }

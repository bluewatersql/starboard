"""Intent classifier service for conversation extension pattern.

This service classifies user intent in multi-turn conversations to determine
whether the user is:
- EXTENSION: Adding constraints or scope to current topic
- REFINEMENT: Adjusting or correcting current analysis
- CLARIFICATION: Answering the agent's question
- NEW_QUERY: Starting a completely different topic
- FEEDBACK: Reacting to the agent's response

Part of Phase 2: Conversation Extension Pattern.
"""

from __future__ import annotations

import re
from typing import Any

from starboard_core.models.conversation import Message

from starboard_server.domain.models.conversation_patterns import (
    AgentResponse,
    IntentClassification,
    UserIntentType,
)


class IntentClassifierService:
    """Classifies user intent in multi-turn conversations.

    Uses heuristic-based pattern matching to determine if a user's message
    is extending an existing conversation, refining previous input, answering
    a clarifying question, starting a new topic, or providing feedback.

    Attributes:
        min_confidence: Minimum confidence threshold for classification (default: 0.5)
    """

    # Keywords indicating different intent types
    EXTENSION_KEYWORDS = [
        "also",
        "additionally",
        "what about",
        "how about",
        "and",
        "plus",
        "furthermore",
        "moreover",
        "in addition",
    ]

    REFINEMENT_KEYWORDS = [
        "actually",
        "correction",
        "i meant",
        "instead",
        "rather",
        "not",
        "no,",
        "wait,",
        "my mistake",
        "sorry,",
    ]

    CLARIFICATION_YES_NO = [
        "yes",
        "no",
        "yeah",
        "yep",
        "nope",
        "sure",
        "ok",
        "okay",
    ]

    FEEDBACK_KEYWORDS = [
        "thanks",
        "thank you",
        "helpful",
        "helps",
        "helped",
        "perfect",
        "great",
        "excellent",
        "good",
        "nice",
        "appreciate",
        "makes sense",
        "got it",
    ]

    # Temporal keywords for entity extraction
    TEMPORAL_PATTERNS = [
        r"\b(mornings?|afternoons?|evenings?|nights?|peak hours?|business hours?)\b",
        r"\b(\d{1,2}\s*am|\d{1,2}\s*pm)\b",
        r"\b(weekdays?|weekends?|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    ]

    def __init__(self, min_confidence: float = 0.5):
        """Initialize intent classifier.

        Args:
            min_confidence: Minimum confidence threshold (default: 0.5)

        Examples:
            >>> classifier = IntentClassifierService()
            >>> classifier.min_confidence
            0.5
            >>> classifier_strict = IntentClassifierService(min_confidence=0.75)
            >>> classifier_strict.min_confidence
            0.75
        """
        self.min_confidence = min_confidence

    def classify(
        self,
        user_message: str,
        conversation_history: tuple[Message, ...],
        previous_agent_response: AgentResponse | None,  # noqa: ARG002
    ) -> IntentClassification:
        """Classify user intent based on message and conversation context.

        Args:
            user_message: The user's current message
            conversation_history: Tuple of previous messages in conversation
            previous_agent_response: Optional previous agent response with metadata

        Returns:
            IntentClassification with detected intent, confidence, reasoning, and entities
        """
        user_message_lower = user_message.strip().lower()

        # Handle empty message
        if not user_message_lower:
            return IntentClassification(
                intent_type=UserIntentType.NEW_QUERY,
                confidence=0.5,
                reasoning="Empty message treated as new query",
                extracted_entities={},
            )

        # Strategy 1: First message → NEW_QUERY
        if not conversation_history:
            return IntentClassification(
                intent_type=UserIntentType.NEW_QUERY,
                confidence=0.95,
                reasoning="First message in conversation",
                extracted_entities=self._extract_entities(user_message),
            )

        # Strategy 2: CLARIFICATION (yes/no) - check first for direct yes/no responses
        # This takes precedence over feedback keywords like "thanks"
        if classification := self._check_yes_no_clarification(user_message_lower):
            return classification

        # Strategy 3: FEEDBACK (gratitude, sentiment)
        if classification := self._check_feedback(user_message_lower):
            return classification

        # Strategy 4: CLARIFICATION (short answers)
        if classification := self._check_short_clarification(user_message_lower):
            return classification

        # Strategy 5: REFINEMENT (corrections)
        if classification := self._check_refinement(user_message_lower, user_message):
            return classification

        # Strategy 6: EXTENSION (adding constraints/scope)
        if classification := self._check_extension(user_message_lower, user_message):
            return classification

        # Strategy 7: NEW_QUERY (topic switch - default fallback)
        return self._check_new_query(user_message, conversation_history)

    def _check_yes_no_clarification(
        self, user_message_lower: str
    ) -> IntentClassification | None:
        """Check if message is a yes/no CLARIFICATION.

        This is checked first to take precedence over feedback keywords like "thanks".

        Args:
            user_message_lower: Lowercased user message

        Returns:
            IntentClassification if yes/no clarification detected, None otherwise
        """
        # Check for yes/no (exact match)
        if user_message_lower in self.CLARIFICATION_YES_NO:
            return IntentClassification(
                intent_type=UserIntentType.CLARIFICATION,
                confidence=0.95,
                reasoning="Yes/no response to question",
                extracted_entities={"answer": user_message_lower},
            )

        # Check for yes/no with additional words (e.g., "yes, please" or "no, thanks")
        # This should take precedence over feedback keywords
        words = user_message_lower.split()
        if len(words) <= 3:  # Short messages with yes/no
            # Strip punctuation from words for matching
            words_clean = [word.strip(",.!?;:") for word in words]
            for keyword in self.CLARIFICATION_YES_NO:
                if keyword in words_clean:
                    return IntentClassification(
                        intent_type=UserIntentType.CLARIFICATION,
                        confidence=0.9,
                        reasoning=f"Response contains '{keyword}' in short message",
                        extracted_entities={"answer": keyword},
                    )

        return None

    def _check_short_clarification(
        self, user_message_lower: str
    ) -> IntentClassification | None:
        """Check if message is a short-answer CLARIFICATION.

        Args:
            user_message_lower: Lowercased user message

        Returns:
            IntentClassification if short clarification detected, None otherwise
        """
        words = user_message_lower.split()

        # Check for very short messages (likely direct answers) - but not single word feedback
        if len(words) <= 3 and len(user_message_lower) < 30:
            # Don't classify single-word feedback as clarification
            message_stripped = user_message_lower.strip(",.!?;:")
            if len(words) == 1 and message_stripped in [
                "thanks",
                "thank you",
                "perfect",
                "great",
                "excellent",
                "good",
                "nice",
            ]:
                return None

            return IntentClassification(
                intent_type=UserIntentType.CLARIFICATION,
                confidence=0.75,
                reasoning="Short direct answer",
                extracted_entities={"answer": user_message_lower},
            )

        return None

    def _check_feedback(self, user_message_lower: str) -> IntentClassification | None:
        """Check if message is FEEDBACK (gratitude, sentiment).

        Args:
            user_message_lower: Lowercased user message

        Returns:
            IntentClassification if feedback detected, None otherwise
        """
        for keyword in self.FEEDBACK_KEYWORDS:
            if keyword in user_message_lower:
                return IntentClassification(
                    intent_type=UserIntentType.FEEDBACK,
                    confidence=0.9,
                    reasoning=f"Feedback expression detected: '{keyword}'",
                    extracted_entities={"sentiment": "positive", "keyword": keyword},
                )

        return None

    def _check_refinement(
        self,
        user_message_lower: str,
        user_message: str,
    ) -> IntentClassification | None:
        """Check if message is a REFINEMENT (correction).

        Args:
            user_message_lower: Lowercased user message
            user_message: Original user message

        Returns:
            IntentClassification if refinement detected, None otherwise
        """
        for keyword in self.REFINEMENT_KEYWORDS:
            if keyword in user_message_lower:
                entities = self._extract_entities(user_message)
                entities["correction_keyword"] = keyword

                return IntentClassification(
                    intent_type=UserIntentType.REFINEMENT,
                    confidence=0.85,
                    reasoning=f"Correction indicated by '{keyword}'",
                    extracted_entities=entities,
                )

        return None

    def _check_extension(
        self,
        user_message_lower: str,
        user_message: str,
    ) -> IntentClassification | None:
        """Check if message is an EXTENSION (adding constraints/scope).

        Args:
            user_message_lower: Lowercased user message
            user_message: Original user message

        Returns:
            IntentClassification if extension detected, None otherwise
        """
        # Check for extension keywords
        for keyword in self.EXTENSION_KEYWORDS:
            if keyword in user_message_lower:
                entities = self._extract_entities(user_message)
                entities["extension_keyword"] = keyword

                return IntentClassification(
                    intent_type=UserIntentType.EXTENSION,
                    confidence=0.85,
                    reasoning=f"Extension indicated by '{keyword}'",
                    extracted_entities=entities,
                )

        # Check for temporal constraints (likely extension)
        temporal_match = self._extract_temporal(user_message_lower)
        if temporal_match:
            entities = self._extract_entities(user_message)

            return IntentClassification(
                intent_type=UserIntentType.EXTENSION,
                confidence=0.8,
                reasoning="Temporal constraint indicates scope extension",
                extracted_entities=entities,
            )

        return None

    def _check_new_query(
        self,
        user_message: str,
        conversation_history: tuple[Message, ...],  # noqa: ARG002
    ) -> IntentClassification:
        """Check if message is a NEW_QUERY (topic switch).

        This is the default fallback classification.

        Args:
            user_message: Original user message
            conversation_history: Conversation history

        Returns:
            IntentClassification for NEW_QUERY
        """
        # Simple heuristic: if message is long and doesn't match other patterns,
        # it's likely a new query
        confidence = 0.7 if len(user_message.split()) > 5 else 0.6

        return IntentClassification(
            intent_type=UserIntentType.NEW_QUERY,
            confidence=confidence,
            reasoning="Message does not match extension/refinement/feedback patterns",
            extracted_entities=self._extract_entities(user_message),
        )

    def _extract_entities(self, user_message: str) -> dict[str, Any]:
        """Extract entities from user message.

        Args:
            user_message: Original user message

        Returns:
            Dictionary of extracted entities
        """
        entities: dict[str, Any] = {}

        # Extract temporal information
        if temporal := self._extract_temporal(user_message):
            entities["timeframe"] = temporal

        # Extract warehouse names (common in Databricks context)
        warehouse_pattern = r"\b(\w+_dw|\w+_warehouse|\w+warehouse)\b"
        if match := re.search(warehouse_pattern, user_message, re.IGNORECASE):
            entities["warehouse"] = match.group(1)

        # Extract numeric values
        number_pattern = (
            r"\b(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?|ms|percent|%)\b"
        )
        numbers = re.findall(number_pattern, user_message, re.IGNORECASE)
        if numbers:
            entities["metrics"] = [f"{num} {unit}" for num, unit in numbers]

        return entities

    def _extract_temporal(self, user_message: str) -> str | None:
        """Extract temporal information from message.

        Args:
            user_message: User message (lowercased or original)

        Returns:
            Temporal string if found, None otherwise
        """
        for pattern in self.TEMPORAL_PATTERNS:
            if match := re.search(pattern, user_message, re.IGNORECASE):
                return match.group(1)
        return None

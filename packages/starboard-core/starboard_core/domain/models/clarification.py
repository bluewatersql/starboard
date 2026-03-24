"""Domain models for clarification requests (Phase 7).

This module defines models for the Clarification Request Pattern, which detects
ambiguity in user queries and requests clarification BEFORE agent execution.

Models follow these principles:
- Immutable (frozen dataclasses)
- Type-safe with full type hints
- Serializable (to_dict/from_dict)
- Well-documented with examples

Architecture:
- Service Layer: Ambiguity detection happens before agent routing
- Complements: Existing agent-level request_user_input tool
- Purpose: Catch obvious ambiguities early, prevent wasted LLM tokens
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ClarificationType(Enum):
    """Type of clarification needed.

    Indicates why the user's query requires clarification before
    the system can proceed with confidence.

    Examples:
        >>> ClarificationType.MISSING_PARAMETER.value
        'missing_parameter'
        >>> ClarificationType("ambiguous_entity")
        <ClarificationType.AMBIGUOUS_ENTITY: 'ambiguous_entity'>
    """

    MISSING_PARAMETER = "missing_parameter"  # Required param absent
    AMBIGUOUS_ENTITY = "ambiguous_entity"  # Entity reference unclear
    MULTIPLE_MATCHES = "multiple_matches"  # Several entities match
    INSUFFICIENT_CONTEXT = "insufficient_context"  # Too vague to proceed
    UNCLEAR_INTENT = "unclear_intent"  # Don't know what action to take
    VAGUE_REFERENCE = "vague_reference"  # Pronoun usage ("it", "that")


@dataclass(frozen=True)
class ClarificationOption:
    """One option in a clarification question.

    Represents a selectable choice presented to the user when multiple
    possibilities exist (e.g., multiple clusters, warehouses, etc.).

    Attributes:
        option_id: Unique identifier for this option (e.g., "1", "2", "opt_abc")
        display_text: Human-readable text to show user
        value: The actual value to use if selected (e.g., cluster_id)
        is_recommended: Whether this option is the recommended choice
        metadata: Additional info to display (e.g., status, last_used)

    Examples:
        >>> option = ClarificationOption(
        ...     option_id="1",
        ...     display_text="prod-analytics (10 nodes, running)",
        ...     value="cluster_123",
        ...     is_recommended=True,
        ...     metadata={"nodes": 10, "status": "running"},
        ... )
        >>> option.display_text
        'prod-analytics (10 nodes, running)'
    """

    option_id: str
    display_text: str
    value: Any
    is_recommended: bool = False
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage or API responses.

        Returns:
            Dictionary representation

        Examples:
            >>> option = ClarificationOption("1", "Option 1", "value_1")
            >>> data = option.to_dict()
            >>> data["option_id"]
            '1'
        """
        return {
            "option_id": self.option_id,
            "display_text": self.display_text,
            "value": self.value,
            "is_recommended": self.is_recommended,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClarificationOption:
        """Deserialize from dict.

        Args:
            data: Dictionary with option fields

        Returns:
            ClarificationOption instance

        Examples:
            >>> data = {"option_id": "1", "display_text": "Opt 1", "value": "v1"}
            >>> option = ClarificationOption.from_dict(data)
            >>> option.option_id
            '1'
        """
        return cls(
            option_id=data["option_id"],
            display_text=data["display_text"],
            value=data["value"],
            is_recommended=data.get("is_recommended", False),
            metadata=data.get("metadata"),
        )


@dataclass(frozen=True)
class ClarificationRequest:
    """Request for user to clarify ambiguous query.

    Created by the framework when a user's query lacks sufficient information
    to proceed confidently. The user must respond before the system continues.

    Attributes:
        clarification_id: Unique identifier for this clarification
        conversation_id: Associated conversation
        message_id: Original unclear message
        clarification_type: Why clarification is needed
        question: Human-readable question to ask user
        options: Available options (if applicable)
        allow_custom_response: Can user provide text answer?
        is_required: Must be answered to proceed?
        default_value: Suggested default (if any)
        created_at: When clarification was requested
        resolved_at: When user responded (None if pending)
        resolution: User's response data (None if pending)

    Examples:
        >>> request = ClarificationRequest(
        ...     clarification_id="clar_123",
        ...     conversation_id="conv_456",
        ...     message_id="msg_789",
        ...     clarification_type=ClarificationType.MISSING_PARAMETER,
        ...     question="What warehouse size?",
        ...     options=None,
        ...     allow_custom_response=True,
        ...     is_required=True,
        ...     default_value="Medium",
        ...     created_at=datetime.now(timezone.utc),
        ...     resolved_at=None,
        ...     resolution=None,
        ... )
        >>> request.question
        'What warehouse size?'
    """

    clarification_id: str
    conversation_id: str
    message_id: str

    # What's unclear
    clarification_type: ClarificationType
    question: str

    # Options (if applicable)
    options: tuple[ClarificationOption, ...] | None
    allow_custom_response: bool

    # Requirements
    is_required: bool
    default_value: Any | None

    # Metadata
    created_at: datetime
    resolved_at: datetime | None
    resolution: Any | None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage or API responses.

        Returns:
            Dictionary representation

        Examples:
            >>> request = ClarificationRequest(...)
            >>> data = request.to_dict()
            >>> data["clarification_type"]
            'missing_parameter'
        """
        return {
            "clarification_id": self.clarification_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "clarification_type": self.clarification_type.value,
            "question": self.question,
            "options": [opt.to_dict() for opt in self.options]
            if self.options
            else None,
            "allow_custom_response": self.allow_custom_response,
            "is_required": self.is_required,
            "default_value": self.default_value,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution": self.resolution,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClarificationRequest:
        """Deserialize from dict.

        Args:
            data: Dictionary with request fields

        Returns:
            ClarificationRequest instance

        Examples:
            >>> data = {"clarification_id": "clar_123", ...}
            >>> request = ClarificationRequest.from_dict(data)
            >>> request.clarification_id
            'clar_123'
        """
        options = None
        if data.get("options"):
            options = tuple(
                ClarificationOption.from_dict(opt) for opt in data["options"]
            )

        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        resolved_at = data.get("resolved_at")
        if resolved_at and isinstance(resolved_at, str):
            resolved_at = datetime.fromisoformat(resolved_at)

        return cls(
            clarification_id=data["clarification_id"],
            conversation_id=data["conversation_id"],
            message_id=data["message_id"],
            clarification_type=ClarificationType(data["clarification_type"]),
            question=data["question"],
            options=options,
            allow_custom_response=data["allow_custom_response"],
            is_required=data["is_required"],
            default_value=data.get("default_value"),
            created_at=created_at,
            resolved_at=resolved_at,
            resolution=data.get("resolution"),
        )


@dataclass(frozen=True)
class ClarificationResponse:
    """User's answer to a clarification question.

    Contains the user's response (either selected option or custom text)
    and the resolved information extracted from that response.

    Attributes:
        clarification_id: Which clarification this responds to
        selected_option_id: ID of option selected (if option-based)
        custom_response: User's text answer (if custom response)
        confidence: How confident we are in understanding (0.0-1.0)
        resolved_entities: What was determined from response
        timestamp: When user responded

    Examples:
        >>> # Option selection
        >>> response = ClarificationResponse(
        ...     clarification_id="clar_123",
        ...     selected_option_id="opt_2",
        ...     custom_response=None,
        ...     confidence=1.0,
        ...     resolved_entities={"warehouse_size": "Medium"},
        ...     timestamp=datetime.now(timezone.utc),
        ... )
        >>> response.confidence
        1.0

        >>> # Custom text response
        >>> response = ClarificationResponse(
        ...     clarification_id="clar_123",
        ...     selected_option_id=None,
        ...     custom_response="my-warehouse",
        ...     confidence=0.8,
        ...     resolved_entities={"warehouse_name": "my-warehouse"},
        ...     timestamp=datetime.now(timezone.utc),
        ... )
        >>> response.custom_response
        'my-warehouse'
    """

    clarification_id: str
    selected_option_id: str | None
    custom_response: str | None
    confidence: float
    resolved_entities: dict[str, Any]
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage or API responses.

        Returns:
            Dictionary representation

        Examples:
            >>> response = ClarificationResponse(...)
            >>> data = response.to_dict()
            >>> data["confidence"]
            1.0
        """
        return {
            "clarification_id": self.clarification_id,
            "selected_option_id": self.selected_option_id,
            "custom_response": self.custom_response,
            "confidence": self.confidence,
            "resolved_entities": self.resolved_entities,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClarificationResponse:
        """Deserialize from dict.

        Args:
            data: Dictionary with response fields

        Returns:
            ClarificationResponse instance

        Examples:
            >>> data = {"clarification_id": "clar_123", ...}
            >>> response = ClarificationResponse.from_dict(data)
            >>> response.clarification_id
            'clar_123'
        """
        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        return cls(
            clarification_id=data["clarification_id"],
            selected_option_id=data.get("selected_option_id"),
            custom_response=data.get("custom_response"),
            confidence=data["confidence"],
            resolved_entities=data["resolved_entities"],
            timestamp=timestamp,
        )


@dataclass(frozen=True)
class AmbiguityScore:
    """Assessment of query clarity.

    Provides a comprehensive evaluation of how clear or ambiguous a user's
    query is, with detailed scoring across multiple dimensions.

    Attributes:
        query: The user query being assessed
        overall_score: Overall clarity (0.0=very ambiguous, 1.0=crystal clear)
        entity_clarity: Are entity references clear? (0.0-1.0)
        parameter_completeness: Are required params present? (0.0-1.0)
        intent_clarity: Is user's intent clear? (0.0-1.0)
        reference_resolution: Are pronouns/refs clear? (0.0-1.0)
        ambiguous_entities: Which entities are unclear
        missing_parameters: Which required params are missing
        vague_references: Which references are vague ("it", "that")
        requires_clarification: Does this need clarification?

    Examples:
        >>> # Clear query
        >>> score = AmbiguityScore(
        ...     query="create warehouse my-wh size Medium",
        ...     overall_score=0.95,
        ...     entity_clarity=1.0,
        ...     parameter_completeness=1.0,
        ...     intent_clarity=0.9,
        ...     reference_resolution=1.0,
        ...     ambiguous_entities=(),
        ...     missing_parameters=(),
        ...     vague_references=(),
        ...     requires_clarification=False,
        ... )
        >>> score.requires_clarification
        False

        >>> # Ambiguous query
        >>> score = AmbiguityScore(
        ...     query="create warehouse",
        ...     overall_score=0.4,
        ...     entity_clarity=1.0,
        ...     parameter_completeness=0.3,
        ...     intent_clarity=0.8,
        ...     reference_resolution=1.0,
        ...     ambiguous_entities=(),
        ...     missing_parameters=("warehouse_name", "warehouse_size"),
        ...     vague_references=(),
        ...     requires_clarification=True,
        ... )
        >>> len(score.missing_parameters)
        2
    """

    query: str
    overall_score: float

    # Detailed scores
    entity_clarity: float
    parameter_completeness: float
    intent_clarity: float
    reference_resolution: float

    # Issues found
    ambiguous_entities: tuple[str, ...]
    missing_parameters: tuple[str, ...]
    vague_references: tuple[str, ...]

    requires_clarification: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage or API responses.

        Returns:
            Dictionary representation

        Examples:
            >>> score = AmbiguityScore(...)
            >>> data = score.to_dict()
            >>> data["overall_score"]
            0.95
        """
        return {
            "query": self.query,
            "overall_score": self.overall_score,
            "entity_clarity": self.entity_clarity,
            "parameter_completeness": self.parameter_completeness,
            "intent_clarity": self.intent_clarity,
            "reference_resolution": self.reference_resolution,
            "ambiguous_entities": list(self.ambiguous_entities),
            "missing_parameters": list(self.missing_parameters),
            "vague_references": list(self.vague_references),
            "requires_clarification": self.requires_clarification,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AmbiguityScore:
        """Deserialize from dict.

        Args:
            data: Dictionary with score fields

        Returns:
            AmbiguityScore instance

        Examples:
            >>> data = {"query": "test", "overall_score": 0.5, ...}
            >>> score = AmbiguityScore.from_dict(data)
            >>> score.query
            'test'
        """
        return cls(
            query=data["query"],
            overall_score=data["overall_score"],
            entity_clarity=data["entity_clarity"],
            parameter_completeness=data["parameter_completeness"],
            intent_clarity=data["intent_clarity"],
            reference_resolution=data["reference_resolution"],
            ambiguous_entities=tuple(data["ambiguous_entities"]),
            missing_parameters=tuple(data["missing_parameters"]),
            vague_references=tuple(data["vague_references"]),
            requires_clarification=data["requires_clarification"],
        )

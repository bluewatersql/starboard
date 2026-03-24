"""Pure domain models for intent resolution."""

from dataclasses import dataclass, field
from enum import Enum


class IntentType(str, Enum):
    """Primary optimization intent types."""

    UNKNOWN = "unknown"
    OPTIMIZE_JOB = "optimize_job"
    OPTIMIZE_QUERY = "optimize_query"
    OPTIMIZE_PIPELINE = "optimize_pipeline"
    GENERAL_INQUIRY = "general_inquiry"


class ContextKeyword(str, Enum):
    """Context keywords detected in user input."""

    JOB = "job"
    QUERY = "query"
    SQL = "sql"
    PIPELINE = "pipeline"
    TABLE = "table"
    WAREHOUSE = "warehouse"
    CLUSTER = "cluster"


@dataclass
class IntentResolutionInput:
    """Input for intent resolution."""

    user_input: str
    conversation_history: list[dict] | None = None


@dataclass
class IntentResolutionResult:
    """Structured result of intent classification.

    Attributes:
        intent: Classified intent type
        confidence: Confidence score (0.0 - 1.0)
        parameters: Extracted parameters (IDs, names, etc.)
        reasoning: Human-readable explanation
        suggested_friendly_name: Conversation title suggestion
        matched_keywords: Keywords detected in input
        extracted_tokens: ID-like tokens found in input
    """

    intent: IntentType
    confidence: float  # 0.0 - 1.0
    parameters: dict[str, str] = field(default_factory=dict)
    reasoning: str = ""
    suggested_friendly_name: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    extracted_tokens: list[str] = field(default_factory=list)

    def add_parameter(self, key: str, value: str) -> None:
        """Add an extracted parameter."""
        self.parameters[key] = value

    def add_keyword(self, keyword: ContextKeyword) -> None:
        """Add a detected keyword."""
        if keyword.value not in self.matched_keywords:
            self.matched_keywords.append(keyword.value)

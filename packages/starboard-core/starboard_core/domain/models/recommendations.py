"""Data models for optimization recommendations and actions."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionPriority(Enum):
    """Priority levels for recommended actions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionCategory(Enum):
    """Categories of recommended actions."""

    TABLE_OPTIMIZATION = "table_optimization"
    QUERY_REWRITE = "query_rewrite"
    COMPUTE_CONFIG = "compute_config"
    STATISTICS = "statistics"
    BENCHMARK = "benchmark"
    ANALYSIS = "analysis"


@dataclass
class ActionCommand:
    """Represents an executable command within an action.

    Attributes:
        type: SQL command type (e.g., ANALYZE, EXPLAIN, OPTIMIZE)
        target: Target resource (table name, query, etc.)
        command: Full command text to execute
    """

    type: str
    target: str
    command: str


@dataclass
class RecommendedAction:
    """Represents a recommended follow-up action.

    Attributes:
        action_id: Unique identifier for the action type
        title: User-friendly title for the action
        description: Detailed description of what the action does
        category: Category of the action
        priority: Priority level (low, medium, high)
        commands: Optional list of executable commands
        context: Additional context data needed for execution
        estimated_impact: Estimated performance impact if available
    """

    action_id: str
    title: str
    description: str
    category: ActionCategory = ActionCategory.ANALYSIS
    priority: ActionPriority = ActionPriority.MEDIUM
    commands: list[ActionCommand] | None = None
    context: dict[str, Any] = field(default_factory=dict)
    estimated_impact: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary with all action details
        """
        return {
            "action_id": self.action_id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "priority": self.priority.value,
            "commands": (
                [
                    {"type": cmd.type, "target": cmd.target, "command": cmd.command}
                    for cmd in self.commands
                ]
                if self.commands
                else None
            ),
            "context": self.context,
            "estimated_impact": self.estimated_impact,
        }


@dataclass
class ActionResult:
    """Result from executing a recommended action.

    Attributes:
        action_id: ID of the action that was executed
        status: Execution status (success, error, skipped)
        message: Human-readable result message
        data: Additional result data
        execution_time_ms: Execution time in milliseconds
        error: Error message if status is error
    """

    action_id: str
    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    execution_time_ms: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary with all result details
        """
        return {
            "action_id": self.action_id,
            "status": self.status,
            "message": self.message,
            "data": self.data,
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
        }


@dataclass
class ImpactMetrics:
    """Metrics for estimating the impact of a recommendation.

    Attributes:
        confidence: Confidence level (low, medium, high)
        data_read_pct: Estimated percentage impact on data read
        cost_pct: Estimated percentage impact on cost
        shuffle_pct: Estimated percentage impact on shuffle operations
        query_time_pct: Estimated percentage impact on query time
    """

    confidence: str = "medium"
    data_read_pct: float = 0.0
    cost_pct: float = 0.0
    shuffle_pct: float = 0.0
    query_time_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary with all metrics
        """
        return {
            "confidence": self.confidence,
            "data_read_pct": self.data_read_pct,
            "cost_pct": self.cost_pct,
            "shuffle_pct": self.shuffle_pct,
            "query_time_pct": self.query_time_pct,
        }

    def weighted_score(self) -> float:
        """Calculate weighted average score across all metrics.

        Returns:
            Average score across all percentage metrics
        """
        metrics = [
            self.data_read_pct,
            self.cost_pct,
            self.shuffle_pct,
            self.query_time_pct,
        ]
        return sum(metrics) / len(metrics)

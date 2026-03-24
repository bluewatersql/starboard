"""
API performance models.

Models for agent performance metrics:
- AgentPerformanceResponse: Agent performance metrics and analytics

Extracted from models.py for better organization.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class AgentPerformanceResponse(BaseModel):
    """
    Response containing agent performance metrics.

    Args:
        agent_name: Name of the agent
        period_days: Number of days covered by the report
        total_feedback: Total number of feedback submissions
        positive_count: Number of positive feedback submissions
        negative_count: Number of negative feedback submissions
        satisfaction_rate: Overall satisfaction rate (0.0 to 1.0)
        negative_categories: Breakdown of negative feedback categories
        generated_at: When the report was generated

    Examples:
        >>> response = AgentPerformanceResponse(
        ...     agent_name="query_agent",
        ...     period_days=7,
        ...     total_feedback=100,
        ...     positive_count=85,
        ...     negative_count=15,
        ...     satisfaction_rate=0.85,
        ...     negative_categories={"inaccurate": 5, "too_vague": 10},
        ...     generated_at=datetime.now()
        ... )
    """

    agent_name: str = Field(
        ...,
        description="Name of the agent",
    )
    period_days: int = Field(
        ...,
        ge=1,
        description="Number of days covered by the report",
    )
    total_feedback: int = Field(
        ...,
        ge=0,
        description="Total number of feedback submissions",
    )
    positive_count: int = Field(
        ...,
        ge=0,
        description="Number of positive feedbacks",
    )
    negative_count: int = Field(
        ...,
        ge=0,
        description="Number of negative feedbacks",
    )
    satisfaction_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall satisfaction rate (positive / total)",
    )
    negative_categories: dict[str, int] = Field(
        default_factory=dict,
        description="Breakdown of negative feedback categories",
    )
    generated_at: datetime = Field(
        ...,
        description="Report generation timestamp",
    )

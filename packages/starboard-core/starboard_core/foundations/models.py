# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Foundation data models for shared infrastructure.

This module defines immutable data classes used across the foundation layer:
- Reflexion learnings
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class ReflexionLearning:
    """A learning captured through reflexion.

    Reflexion is a self-improvement technique where agents:
    1. Evaluate their own responses
    2. Identify failures or suboptimal approaches
    3. Extract learnings for future use

    Attributes:
        id: Unique identifier
        problem: Description of the problem encountered
        solution: How it was solved or should be solved
        feedback: Agent's self-evaluation feedback
        success_score: Quality score (0.0 to 1.0)
        created_at: When the learning was captured
        tags: Categorization tags
        agent_domain: Which agent domain this applies to
        metadata: Additional context

    Example:
        >>> learning = ReflexionLearning(
        ...     id="learn_123",
        ...     problem="Query optimization for large tables",
        ...     solution="Use partitioning and limit scans",
        ...     feedback="Initial approach caused timeout",
        ...     success_score=0.85,
        ...     created_at=datetime.now(),
        ...     tags=["query", "optimization", "performance"],
        ...     agent_domain="query",
        ...     metadata={"table_size_gb": 1000}
        ... )
    """

    id: str
    problem: str
    solution: str
    feedback: str
    success_score: float
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = field(default_factory=list)
    agent_domain: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate reflexion learning."""
        if not 0.0 <= self.success_score <= 1.0:
            raise ValueError(
                f"success_score must be between 0 and 1, got {self.success_score}"
            )
        if not self.problem:
            raise ValueError("problem cannot be empty")
        if not self.solution:
            raise ValueError("solution cannot be empty")

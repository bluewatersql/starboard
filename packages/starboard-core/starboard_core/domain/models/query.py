"""Domain models for query operations.

Pure domain models for query resolution and analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class QuerySource(Enum):
    """Source of query resolution."""

    RAW_SQL = "raw_sql"
    QUERY_HISTORY = "query_history"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QueryResolutionInput:
    """
    Input for query resolution.

    Attributes:
        target: Raw input string (SQL, statement ID, or query description)
        classification: Optional LLM classification hints

    Example:
        >>> QueryResolutionInput(
        ...     target="SELECT * FROM table",
        ...     classification=None
        ... )
    """

    target: str
    classification: dict[str, Any] | None = None


@dataclass(frozen=True)
class QueryResolutionResult:
    """
    Result of query resolution.

    Attributes:
        source: How the query was resolved
        statement_id: Statement ID if resolved from query history
        sql_text: Resolved SQL text

    Example:
        >>> QueryResolutionResult(
        ...     source=QuerySource.RAW_SQL,
        ...     statement_id=None,
        ...     sql_text="SELECT * FROM table"
        ...     plan_text=[{"plan_text": "SELECT * FROM table"}],
        ...     metrics=[{"metrics": "SELECT * FROM table"}]
        ... )
    """

    source: QuerySource
    statement_id: str | None
    sql_text: str | None
    plan_text: list[dict[str, Any]] | None = None
    metrics: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExplainPlanInput:
    """
    Input for EXPLAIN plan generation.

    Attributes:
        sql_text: SQL query to analyze

    Example:
        >>> ExplainPlanInput(sql_text="SELECT * FROM table")
    """

    sql_text: str


@dataclass(frozen=True)
class ExplainPlanResult:
    """
    Result of EXPLAIN plan generation.

    Attributes:
        plan_text: Raw EXPLAIN plan output
        facts: Parsed facts from the plan (optional)

    Example:
        >>> ExplainPlanResult(
        ...     plan_text="== Physical Plan ==\\n...",
        ...     facts={"has_broadcast_join": True}
        ... )
    """

    plan_text: str
    facts: dict[str, Any] | None = None

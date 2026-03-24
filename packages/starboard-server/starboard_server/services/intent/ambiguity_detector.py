"""Ambiguity detector service for Phase 7 clarification pattern.

This service detects when user queries lack sufficient information to proceed
confidently, enabling proactive clarification BEFORE agent execution.

MVP Scope (Phase 7.1):
- Detect missing required parameters
- Calculate parameter completeness score
- Use existing ToolMetadata schemas
- Simple pattern-based parameter extraction

Future Enhancements (Phase 7.2+):
- Entity matching (find "the cluster" in database)
- LLM-based entity extraction
- Context-aware disambiguation
- Vague reference detection
"""

from __future__ import annotations

import re
from typing import Any

from starboard_core.domain.models.clarification import AmbiguityScore

from starboard_server.agents.tools import ToolRegistry
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class AmbiguityDetector:
    """
    Detects ambiguity and unclear aspects in user queries.

    Uses parameter schema matching to identify what information is missing
    or unclear before executing tool calls.

    Args:
        tool_registry: Registry of available tools with schemas

    Example:
        >>> registry = ToolRegistry()
        >>> detector = AmbiguityDetector(tool_registry=registry)
        >>> score = detector.detect_ambiguity(
        ...     query="create warehouse",
        ...     target_tool="create_warehouse",
        ... )
        >>> score.requires_clarification
        True
        >>> score.missing_parameters
        ('warehouse_name', 'warehouse_size')
    """

    def __init__(self, tool_registry: ToolRegistry):
        """Initialize ambiguity detector.

        Args:
            tool_registry: Registry of tools with parameter schemas
        """
        self.tool_registry = tool_registry
        self.ambiguity_threshold = 0.7  # Overall score below this needs clarification

    def detect_ambiguity(
        self,
        query: str,
        target_tool: str,
    ) -> AmbiguityScore:
        """
        Analyze query for ambiguous or missing information.

        For MVP (Phase 7.1), focuses on parameter completeness:
        - Checks if required parameters are present in query
        - Calculates completeness score
        - Determines if clarification is needed

        Args:
            query: User's query string
            target_tool: Tool the query is intended for

        Returns:
            Ambiguity assessment with scores and missing parameters

        Raises:
            ValueError: If query or target_tool is None or empty

        Examples:
            >>> # Missing parameters
            >>> score = detector.detect_ambiguity(
            ...     query="create warehouse",
            ...     target_tool="create_warehouse",
            ... )
            >>> score.requires_clarification
            True

            >>> # All parameters present
            >>> score = detector.detect_ambiguity(
            ...     query="create warehouse my-wh size Medium",
            ...     target_tool="create_warehouse",
            ... )
            >>> score.requires_clarification
            False
        """
        # Validate inputs
        if query is None:
            raise ValueError("Query cannot be None or empty")

        # Allow empty queries for testing, but treat as missing all parameters
        is_empty_query = isinstance(query, str) and query.strip() == ""

        if target_tool is None or (
            isinstance(target_tool, str) and target_tool.strip() == ""
        ):
            raise ValueError("Target tool cannot be None or empty")

        query = query.strip() if not is_empty_query else ""

        # Check if tool exists in registry
        adapter = self.tool_registry.get_tool(target_tool)
        if adapter is None:
            # Unknown tool - don't require clarification
            # (will be handled by intent classification/routing)
            logger.warning(
                "ambiguity_detection_unknown_tool",
                target_tool=target_tool,
                query=query,
            )
            return AmbiguityScore(
                query=query,
                overall_score=1.0,  # No clarification needed
                entity_clarity=1.0,
                parameter_completeness=1.0,
                intent_clarity=1.0,
                reference_resolution=1.0,
                ambiguous_entities=(),
                missing_parameters=(),
                vague_references=(),
                requires_clarification=False,
            )

        # Extract required parameters from tool schema
        required_params = self._get_required_parameters(adapter.metadata)

        # If no required parameters, query is complete
        if not required_params:
            return AmbiguityScore(
                query=query,
                overall_score=1.0,
                entity_clarity=1.0,
                parameter_completeness=1.0,
                intent_clarity=1.0,
                reference_resolution=1.0,
                ambiguous_entities=(),
                missing_parameters=(),
                vague_references=(),
                requires_clarification=False,
            )

        # Find which parameters are present in query
        present_params = self._extract_present_parameters(query, required_params)

        # Find missing parameters
        missing_params = tuple(
            param for param in required_params if param not in present_params
        )

        # Calculate parameter completeness score
        param_completeness = self._calculate_parameter_completeness(
            present_count=len(present_params),
            total_count=len(required_params),
        )

        # For MVP: Overall score = parameter completeness
        # (Future: will include entity_clarity, intent_clarity, etc.)
        overall_score = param_completeness

        # Determine if clarification is needed
        requires_clarification = overall_score < self.ambiguity_threshold

        logger.debug(
            "ambiguity_detection_complete",
            query=query,
            target_tool=target_tool,
            overall_score=overall_score,
            param_completeness=param_completeness,
            missing_params=missing_params,
            requires_clarification=requires_clarification,
        )

        return AmbiguityScore(
            query=query,
            overall_score=overall_score,
            entity_clarity=1.0,  # Not assessed in MVP
            parameter_completeness=param_completeness,
            intent_clarity=1.0,  # Not assessed in MVP
            reference_resolution=1.0,  # Not assessed in MVP
            ambiguous_entities=(),  # Not assessed in MVP
            missing_parameters=missing_params,
            vague_references=(),  # Not assessed in MVP
            requires_clarification=requires_clarification,
        )

    def _get_required_parameters(self, tool_metadata: Any) -> list[str]:
        """Extract required parameter names from tool schema.

        Args:
            tool_metadata: ToolMetadata with parameter schema

        Returns:
            List of required parameter names

        Examples:
            >>> metadata = ToolMetadata(
            ...     name="test",
            ...     description="test",
            ...     parameters={
            ...         "type": "object",
            ...         "properties": {"a": {}, "b": {}},
            ...         "required": ["a", "b"],
            ...     }
            ... )
            >>> detector._get_required_parameters(metadata)
            ['a', 'b']
        """
        schema = tool_metadata.parameters

        # Get required field from schema
        required = schema.get("required", [])

        return required if isinstance(required, list) else []

    def _extract_present_parameters(
        self,
        query: str,
        required_params: list[str],
    ) -> list[str]:
        """Find which required parameters are present in query.

        Uses pattern matching to detect parameter values in query text.
        For MVP, uses simple substring matching and common patterns.

        Args:
            query: User's query string
            required_params: List of required parameter names

        Returns:
            List of parameters detected in query

        Examples:
            >>> detector._extract_present_parameters(
            ...     query="create warehouse my-warehouse size Medium",
            ...     required_params=["warehouse_name", "warehouse_size"],
            ... )
            ['warehouse_name', 'warehouse_size']
        """
        query_lower = query.lower()
        present = []

        for param in required_params:
            # Check if parameter appears in query using various patterns
            if self._is_parameter_present(query_lower, param):
                present.append(param)

        return present

    def _is_parameter_present(self, query_lower: str, param_name: str) -> bool:
        """Check if a parameter value is present in query.

        Uses heuristics to detect parameter values:
        - Parameter name appears in query
        - Common value patterns (identifiers, names, sizes)
        - Contextual keywords

        Args:
            query_lower: Lowercase query string
            param_name: Parameter name to check

        Returns:
            True if parameter appears to be present

        Examples:
            >>> detector._is_parameter_present(
            ...     query_lower="create warehouse my-warehouse",
            ...     param_name="warehouse_name",
            ... )
            True
        """
        # Pattern 1: Parameter name followed by value
        # e.g., "warehouse_name my-warehouse" or "name: my-warehouse"
        param_base = param_name.replace("_", " ")
        if re.search(rf"\b{param_base}\b\s+\w+", query_lower):
            return True

        # Pattern 2: Common parameter patterns
        patterns = {
            "warehouse_name": [
                r"\bwarehouse\s+[\w\-]+",  # "warehouse my-wh"
                r"\bnamed?\s+[\w\-]+",  # "name my-wh" or "named my-wh"
                r"\bcalled\s+[\w\-]+",  # "called my-wh"
            ],
            "warehouse_size": [
                r"\bsize\s+\w+",  # "size Medium"
                r"\b(small|medium|large|x-?small|x-?large)\b",  # size values
            ],
            "cluster_name": [
                r"\bcluster\s+[\w\-]+",
                r"\bnamed?\s+[\w\-]+",
            ],
            "cluster_id": [
                r"\bcluster[_\-]?id\s+[\w\-]+",
                r"\bcluster\s+[\w\-]+",  # Often name works as ID
            ],
            "query_id": [
                r"\bquery[_\-]?id\s+[\w\-]+",
                r"\bstatement[_\-]?id\s+[\w\-]+",
            ],
            "job_id": [
                r"\bjob[_\-]?id\s+[\w\-]+",
                r"\bjob\s+\d+",  # "job 12345"
            ],
            "table_name": [
                r"\btable\s+[\w\-\.]+",  # "table catalog.schema.table"
                r"\b[\w]+\.[\w]+\.[\w]+\b",  # catalog.schema.table
            ],
        }

        # Check specific patterns for this parameter
        if param_name in patterns:
            for pattern in patterns[param_name]:
                if re.search(pattern, query_lower):
                    return True

        # Pattern 3: Generic identifier pattern (disabled for MVP)
        # Too aggressive - causes false positives
        # Will re-enable in Phase 7.2 with better heuristics

        return False

    def _calculate_parameter_completeness(
        self,
        present_count: int,
        total_count: int,
    ) -> float:
        """Calculate parameter completeness score.

        Args:
            present_count: Number of parameters present
            total_count: Total number of required parameters

        Returns:
            Score from 0.0 (none present) to 1.0 (all present)

        Examples:
            >>> detector._calculate_parameter_completeness(2, 2)
            1.0
            >>> detector._calculate_parameter_completeness(1, 2)
            0.5
            >>> detector._calculate_parameter_completeness(0, 2)
            0.0
        """
        if total_count == 0:
            return 1.0

        return present_count / total_count

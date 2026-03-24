"""Question generator service for Phase 7 clarification pattern.

This service generates user-friendly clarification questions with options
when user queries are ambiguous or missing required information.

MVP Scope (Phase 7.1):
- Generate questions for missing parameters
- Create options for parameters with known values
- Format questions clearly
- Support custom text responses

Future Enhancements (Phase 7.2+):
- Generate questions for entity disambiguation
- Context-aware question generation
- User preference learning
- Multi-language support
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from starboard_core.domain.models.clarification import (
    ClarificationOption,
    ClarificationRequest,
    ClarificationType,
)

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class QuestionGenerator:
    """
    Generate clear, helpful clarification questions.

    Creates well-formatted questions with appropriate options
    and guidance for users when their queries are ambiguous.

    Example:
        >>> generator = QuestionGenerator()
        >>> request = generator.generate_clarification_request(
        ...     conversation_id="conv_123",
        ...     message_id="msg_456",
        ...     missing_parameters=["warehouse_size"],
        ...     tool_name="create_warehouse",
        ... )
        >>> request.question
        'What warehouse size would you like?'
        >>> len(request.options)
        5
    """

    # Predefined options for known parameter types
    PARAMETER_OPTIONS = {
        "warehouse_size": [
            ("X-Small", "x-small", "X-Small (1 credit/hr) - Dev/testing", False),
            ("Small", "small", "Small (2 credits/hr) - Small teams", False),
            (
                "Medium",
                "medium",
                "Medium (4 credits/hr) - Production workloads",
                True,
            ),  # Recommended
            ("Large", "large", "Large (8 credits/hr) - Heavy analytics", False),
            ("X-Large", "x-large", "X-Large (16 credits/hr) - Enterprise scale", False),
        ],
        "cluster_size": [
            ("Small", "small", "Small - 2-4 workers", False),
            ("Medium", "medium", "Medium - 4-8 workers", True),  # Recommended
            ("Large", "large", "Large - 8+ workers", False),
        ],
    }

    def generate_clarification_request(
        self,
        conversation_id: str,
        message_id: str,
        missing_parameters: list[str],
        tool_name: str,
    ) -> ClarificationRequest:
        """
        Generate a complete clarification request for missing parameters.

        Args:
            conversation_id: ID of conversation
            message_id: ID of message that needs clarification
            missing_parameters: List of parameter names missing
            tool_name: Name of tool being called

        Returns:
            Complete ClarificationRequest with question and options

        Examples:
            >>> request = generator.generate_clarification_request(
            ...     conversation_id="conv_123",
            ...     message_id="msg_456",
            ...     missing_parameters=["warehouse_size"],
            ...     tool_name="create_warehouse",
            ... )
            >>> request.clarification_type
            <ClarificationType.MISSING_PARAMETER: 'missing_parameter'>
        """
        # Generate the question text
        question = self._generate_question_text(missing_parameters, tool_name)

        # Generate options if applicable (for first parameter)
        # For MVP, we only generate options for the first missing parameter
        options: tuple[ClarificationOption, ...] | None = None
        if missing_parameters:
            first_param = missing_parameters[0]
            param_options = self.generate_parameter_options(first_param, tool_name)
            if param_options:
                options = tuple(param_options)

        # Create the request
        clarification_id = f"clar_{uuid4().hex[:12]}"

        return ClarificationRequest(
            clarification_id=clarification_id,
            conversation_id=conversation_id,
            message_id=message_id,
            clarification_type=ClarificationType.MISSING_PARAMETER,
            question=question,
            options=options,
            allow_custom_response=True,  # Always allow custom text
            is_required=True,  # Must be answered to proceed
            default_value=None,
            created_at=datetime.now(UTC),
            resolved_at=None,
            resolution=None,
        )

    def generate_missing_parameter_question(
        self,
        conversation_id: str,
        message_id: str,
        missing_parameters: list[str],
        tool_name: str,
    ) -> ClarificationRequest:
        """
        Generate question for missing parameters.

        This is an alias for generate_clarification_request for backwards compatibility.

        Args:
            conversation_id: ID of conversation
            message_id: ID of message that needs clarification
            missing_parameters: List of parameter names missing
            tool_name: Name of tool being called

        Returns:
            ClarificationRequest with question
        """
        return self.generate_clarification_request(
            conversation_id=conversation_id,
            message_id=message_id,
            missing_parameters=missing_parameters,
            tool_name=tool_name,
        )

    def _generate_question_text(
        self,
        missing_parameters: list[str],
        tool_name: str,  # noqa: ARG002
    ) -> str:
        """
        Generate the question text for missing parameters.

        Args:
            missing_parameters: List of parameter names
            tool_name: Tool being called

        Returns:
            Question text

        Examples:
            >>> generator._generate_question_text(["warehouse_name"], "create_warehouse")
            'What warehouse name would you like?'
        """
        if not missing_parameters:
            return "Please provide the required information."

        # Single parameter
        if len(missing_parameters) == 1:
            param_name = missing_parameters[0]
            friendly_name = self.format_parameter_name(param_name)
            return f"What {friendly_name} would you like?"

        # Multiple parameters
        param_names = [self.format_parameter_name(p) for p in missing_parameters]
        if len(param_names) == 2:
            names_str = f"{param_names[0]} and {param_names[1]}"
        else:
            names_str = ", ".join(param_names[:-1]) + f", and {param_names[-1]}"

        return f"Please provide the {names_str}."

    def generate_parameter_options(
        self,
        parameter_name: str,
        tool_name: str,  # noqa: ARG002
    ) -> list[ClarificationOption]:
        """
        Generate options for a parameter if predefined options exist.

        Args:
            parameter_name: Name of parameter (e.g., "warehouse_size")
            tool_name: Tool name (for context)

        Returns:
            List of ClarificationOption objects (empty if no predefined options)

        Examples:
            >>> options = generator.generate_parameter_options(
            ...     "warehouse_size",
            ...     "create_warehouse",
            ... )
            >>> len(options)
            5
        """
        # Check if we have predefined options for this parameter
        if parameter_name not in self.PARAMETER_OPTIONS:
            return []

        # Generate options with sequential IDs
        options = []
        for idx, (label, value, display_text, is_recommended) in enumerate(
            self.PARAMETER_OPTIONS[parameter_name], 1
        ):
            option = ClarificationOption(
                option_id=str(idx),
                display_text=display_text,
                value=value,
                is_recommended=is_recommended,
                metadata={"label": label},
            )
            options.append(option)

        return options

    def format_options(self, options: list[ClarificationOption]) -> str:
        """
        Format options as numbered list for display.

        Args:
            options: List of ClarificationOption objects

        Returns:
            Formatted string with numbered options

        Examples:
            >>> formatted = generator.format_options(options)
            >>> print(formatted)
            1. Small (2 credits/hr) - Small teams
            2. Medium (4 credits/hr) - Production workloads ⭐ Recommended
            3. Large (8 credits/hr) - Heavy analytics
        """
        if not options:
            return ""

        lines = []
        for option in options:
            marker = " ⭐ Recommended" if option.is_recommended else ""
            lines.append(f"{option.option_id}. {option.display_text}{marker}")

        return "\n".join(lines)

    def format_parameter_name(self, parameter_name: str) -> str:
        """
        Convert parameter name to friendly display text.

        Args:
            parameter_name: Technical parameter name (e.g., "warehouse_size")

        Returns:
            Friendly name (e.g., "warehouse size")

        Examples:
            >>> generator.format_parameter_name("warehouse_size")
            'warehouse size'
            >>> generator.format_parameter_name("cluster_id")
            'cluster ID'
        """
        # Replace underscores with spaces
        friendly = parameter_name.replace("_", " ")

        # Special case for "id" -> "ID"
        friendly = friendly.replace(" id", " ID")

        return friendly

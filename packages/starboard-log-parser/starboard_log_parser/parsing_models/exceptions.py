from __future__ import annotations

import json
import logging

from starboard_log_parser.parsing_models.errors import (
    ParserErrorCodes,
    ParserErrorMessages,
    ParserErrorTypes,
)

logger = logging.getLogger("ParserExceptionLogger")


class SyncParserException(Exception):
    def __init__(
        self,
        error_type: str | None = None,
        error_message: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(error_message)

        self.error_type: str | None = error_type
        self.error_message: str | None = error_message
        self.status_code: int | None = status_code

        # 2022-03-25 RW:  Format the information in the way it is expected by the backend code
        self.error: dict[str, str | None] = {
            "error": error_type,
            "message": error_message,
        }

    def get_ui_return_value(self) -> dict[str, str | None]:
        """
        A possible rendering of one set of return information as dict
        """

        return {"error": self.error_type, "message": self.error_message}

    def get_ui_return_value_as_json(self) -> str:
        """
        A possible rendering of one set of return information as JSON
        """
        return json.dumps({"error": self.error_type, "message": self.error_message})


class ConfigurationException(SyncParserException):
    def __init__(self, config_recs: list[str]) -> None:
        error_message = ParserErrorMessages.SPARK_CONFIG_GENERIC_MESSAGE

        for idx, c in enumerate(config_recs):
            count = idx + 1
            error_message += f"  ({count}) {c}"

        error_message += f". {ParserErrorMessages.SUPPORT_MESSAGE}"

        super().__init__(
            error_type=ParserErrorTypes.SPARK_CONFIG_ERROR,
            error_message=error_message,
            status_code=ParserErrorCodes.SPARK_CONFIG_ERROR,
        )


class LazyEventValidationException(SyncParserException):
    """
    This Exception is for missing event data that doesn't immediately kill the parser.
    All of the related missing events can be gathered and identified in the error message.
    """

    def __init__(self, error_message: str):
        error_message += (
            f"{ParserErrorMessages.MISSING_EVENT_EXPLANATION} "
            + f"{ParserErrorMessages.SUPPORT_MESSAGE}"
        )

        super().__init__(
            error_type=ParserErrorTypes.MISSING_EVENT_ERROR,
            error_message=error_message,
            status_code=ParserErrorCodes.SPARK_EVENT_ERROR,
        )


class UrgentEventValidationException(SyncParserException):
    """
    This Exception is for missing event data that stops the parser dead in its tracks.

    Attributes:
        missing_event: Description of the missing or invalid event
        context: Additional context about the error (e.g., line number, event details)
        line_number: Specific line number where the error occurred
    """

    def __init__(
        self,
        missing_event: str = "",
        context: str = "",
        line_number: int | None = None,
    ) -> None:
        error_message = (
            f"{ParserErrorMessages.MISSING_EVENT_GENERIC_MESSAGE} '{missing_event}'. "
            + f"{ParserErrorMessages.MISSING_EVENT_EXPLANATION} "
            + f"{ParserErrorMessages.SUPPORT_MESSAGE}"
        )

        # Add context if provided
        if context:
            error_message = f"{error_message}\nContext: {context}"

        # Add line number if provided
        if line_number is not None:
            error_message = f"{error_message}\nLine: {line_number}"

        super().__init__(
            error_type=ParserErrorTypes.MISSING_EVENT_ERROR,
            error_message=error_message,
            status_code=ParserErrorCodes.SPARK_EVENT_ERROR,
        )

        self.line_number = line_number


class LogSubmissionException(SyncParserException, ValueError):
    """
    This Exception is for malformed log submission
    """

    def __init__(self, error_message: str) -> None:
        super().__init__(
            error_type=ParserErrorTypes.LOG_SUBMISSION_ERROR,
            error_message=error_message,
            status_code=ParserErrorCodes.LOG_SUBMISSION_ERROR,
        )

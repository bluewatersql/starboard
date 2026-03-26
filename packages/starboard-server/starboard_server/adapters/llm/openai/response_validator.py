"""Response validation and JSON parsing for LLM responses.

Handles JSON extraction from LLM output with fallback strategies
(markdown code fences, regex extraction) and Pydantic validation.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from starboard_server.infra.observability.logging import get_logger, get_request_id
from starboard_server.infra.serialization import json_loads

logger = get_logger(__name__)


def parse_json_content(content: str, trace_id: str) -> dict[str, Any]:
    """Parse JSON content from LLM response with fallback extraction.

    Args:
        content: Raw content string from LLM
        trace_id: Request correlation ID for logging

    Returns:
        Parsed JSON dictionary or error dict if parsing fails
    """
    if not content:
        logger.error(
            "json_parse_failed_empty_content",
            trace_id=trace_id,
        )
        return {"error": "llm_parse_failed", "raw": ""}

    try:
        return json_loads(content)
    except json.JSONDecodeError as e:
        # Try to extract from markdown code fences: ```json\n{...}\n```
        fence_match = re.search(r"```(?:json)?\s*\n(\{[\s\S]*?\})\s*\n```", content)
        if fence_match:
            try:
                return json_loads(fence_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find any JSON object in the content
        match = re.search(r"\{[\s\S]*?\}", content)
        if match:
            try:
                return json_loads(match.group(0))
            except json.JSONDecodeError:
                logger.error(
                    "json_parse_failed_after_extraction",
                    trace_id=trace_id,
                    content_preview=content[:500] if content else None,
                    content_length=len(content),
                    parse_error=str(e),
                )
                return {"error": "llm_parse_failed", "raw": content}

        logger.error(
            "json_parse_failed_no_json_found",
            trace_id=trace_id,
            content_preview=content[:500] if content else None,
            content_length=len(content),
            parse_error=str(e),
        )
        return {"error": "llm_parse_failed", "raw": content}


def validate_with_pydantic(
    data: dict[str, Any], model_class: type[BaseModel]
) -> dict[str, Any]:
    """Validate LLM response with Pydantic model.

    Args:
        data: Raw dictionary from LLM
        model_class: Pydantic model class for validation

    Returns:
        Validated and cleaned dictionary

    Raises:
        ValidationError: If validation fails
    """
    try:
        validated = model_class.model_validate(data)
        return validated.model_dump()
    except ValidationError as e:
        logger.error(
            "pydantic_validation_failed",
            trace_id=get_request_id(),
            model=model_class.__name__,
            errors=str(e),
        )
        raise

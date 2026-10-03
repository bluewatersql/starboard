# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Response validation and JSON parsing for LLM responses.

Handles JSON extraction from LLM output with fallback strategies
(markdown code fences, regex extraction) and Pydantic validation.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from starboard.infra.observability.logging import get_logger, get_request_id
from starboard.infra.serialization import json_loads

logger = get_logger(__name__)


def coerce_message_text(content: Any) -> str:
    """Flatten an LLM message ``content`` into plain text.

    Some serving endpoints (notably Anthropic Claude via Databricks) return the
    assistant message ``content`` as a **list of content blocks**
    (``[{"type": "text", "text": "..."}, ...]``) rather than a bare string.
    Downstream JSON/regex extraction expects text, so concatenate the textual
    parts. A bare string is returned unchanged; other scalars are stringified.

    Args:
        content: Raw ``message.content`` (str, list of blocks, or None).

    Returns:
        The textual content (possibly empty).
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


def parse_json_content(content: Any, trace_id: str) -> dict[str, Any]:
    """Parse JSON content from LLM response with fallback extraction.

    Args:
        content: Raw content from the LLM (a string, or a list of content
            blocks as some Claude serving endpoints return).
        trace_id: Request correlation ID for logging

    Returns:
        Parsed JSON dictionary or error dict if parsing fails
    """
    content = coerce_message_text(content)
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

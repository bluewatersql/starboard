# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Typed accessors for OpenAI SDK streaming objects.

Centralizes hasattr/getattr checks into a single module so that if the SDK
changes its internal structure, only this file needs updating.
"""

from __future__ import annotations

from typing import Any


def _text_from_content_block(block: Any) -> str:
    """Extract streamable text from a single structured content block.

    Handles the reasoning-model shape emitted by Claude models served over the
    OpenAI-compatible endpoint, where a block is a dict/object such as
    ``{"type": "text", "text": "..."}`` or
    ``{"type": "reasoning", "summary": [{"type": "summary_text", "text": "..."}]}``.
    Signatures and non-text fields are ignored.
    """

    def _get(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    text = _get(block, "text")
    if isinstance(text, str) and text:
        return text

    # Reasoning blocks carry their text under a nested "summary" list.
    summary = _get(block, "summary")
    if isinstance(summary, list):
        return "".join(_text_from_content_block(item) for item in summary)

    return ""


def get_delta_content(delta: Any) -> str | None:
    """Extract content text from a streaming delta, or None.

    Most models set ``delta.content`` to a plain string. Reasoning models
    (e.g. Claude served over the OpenAI-compatible endpoint) instead set it to
    a list of structured content blocks; those are flattened to their text so
    the caller always receives a string per the streaming contract.
    """
    content = getattr(delta, "content", None)
    if content is None:
        return None
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        text = "".join(_text_from_content_block(block) for block in content)
        return text or None
    return None


def get_chunk_usage(chunk: Any) -> Any | None:
    """Extract usage from a chunk, or None."""
    return getattr(chunk, "usage", None) or None

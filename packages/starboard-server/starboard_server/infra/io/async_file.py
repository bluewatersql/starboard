"""Async file I/O utilities.

Thin wrappers around aiofiles for common file operations.
All file I/O in starboard-server MUST use these helpers
instead of built-in open() when called from async context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiofiles  # type: ignore[import-untyped]
import yaml


async def read_json(path: Path | str) -> Any:
    """Read and parse a JSON file asynchronously.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON data.
    """
    async with aiofiles.open(path, encoding="utf-8") as f:
        content = await f.read()
    return json.loads(content)


async def write_json(
    path: Path | str,
    data: Any,
    *,
    indent: int = 2,
    default: Any = str,
) -> None:
    """Write data as JSON to a file asynchronously.

    Args:
        path: Path to the output file.
        data: Data to serialize as JSON.
        indent: JSON indentation level.
        default: Default serializer for non-JSON types.
    """
    content = json.dumps(data, indent=indent, default=default)
    async with aiofiles.open(path, mode="w", encoding="utf-8") as f:
        await f.write(content)


async def read_yaml(path: Path | str) -> Any:
    """Read and parse a YAML file asynchronously.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed YAML data.
    """
    async with aiofiles.open(path, encoding="utf-8") as f:
        content = await f.read()
    return yaml.safe_load(content)


async def read_text(path: Path | str, encoding: str = "utf-8") -> str:
    """Read a text file asynchronously.

    Args:
        path: Path to the text file.
        encoding: File encoding.

    Returns:
        File contents as string.
    """
    async with aiofiles.open(path, encoding=encoding) as f:
        return await f.read()


async def write_text(
    path: Path | str,
    content: str,
    encoding: str = "utf-8",
) -> None:
    """Write text to a file asynchronously.

    Args:
        path: Path to the output file.
        content: Text content to write.
        encoding: File encoding.
    """
    async with aiofiles.open(path, mode="w", encoding=encoding) as f:
        await f.write(content)

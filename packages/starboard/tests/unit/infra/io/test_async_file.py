# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for async file I/O utilities."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from starboard.infra.io.async_file import (
    read_json,
    read_text,
    read_yaml,
    write_json,
    write_text,
)


async def test_read_write_json(tmp_path: Path) -> None:
    """Test round-trip JSON read/write."""
    path = tmp_path / "test.json"
    data = {"key": "value", "nested": {"a": 1}}
    await write_json(path, data)
    result = await read_json(path)
    assert result == data


async def test_read_yaml(tmp_path: Path) -> None:
    """Test YAML file reading."""
    path = tmp_path / "test.yaml"
    path.write_text("key: value\nlist:\n  - a\n  - b\n")
    result = await read_yaml(path)
    assert result == {"key": "value", "list": ["a", "b"]}


async def test_read_write_text(tmp_path: Path) -> None:
    """Test round-trip text read/write."""
    path = tmp_path / "test.txt"
    await write_text(path, "hello world")
    result = await read_text(path)
    assert result == "hello world"


async def test_write_json_default_serializer(tmp_path: Path) -> None:
    """Test JSON write with default serializer for non-JSON types."""
    path = tmp_path / "test.json"
    data = {"ts": datetime(2024, 1, 1)}
    await write_json(path, data)
    result = await read_json(path)
    assert result["ts"] == "2024-01-01 00:00:00"


async def test_read_json_file_not_found(tmp_path: Path) -> None:
    """Test read_json raises on missing file."""
    path = tmp_path / "nonexistent.json"
    with pytest.raises(FileNotFoundError):
        await read_json(path)


async def test_read_text_custom_encoding(tmp_path: Path) -> None:
    """Test text read/write with custom encoding."""
    path = tmp_path / "test.txt"
    await write_text(path, "hello", encoding="ascii")
    result = await read_text(path, encoding="ascii")
    assert result == "hello"


async def test_write_json_custom_indent(tmp_path: Path) -> None:
    """Test JSON write with custom indentation."""
    path = tmp_path / "test.json"
    await write_json(path, {"a": 1}, indent=4)
    raw = await read_text(path)
    assert "    " in raw  # 4-space indent

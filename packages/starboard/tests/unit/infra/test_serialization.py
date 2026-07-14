# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for orjson-based serialization wrapper."""

from datetime import UTC, datetime
from enum import Enum

import pytest
from starboard.infra.serialization import (
    json_dumps,
    json_dumps_bytes,
    json_loads,
)


class Color(Enum):
    RED = "red"
    GREEN = "green"


class TestJsonDumps:
    """json_dumps returns a UTF-8 string."""

    def test_simple_dict(self):
        assert json_dumps({"key": "value"}) == '{"key":"value"}'

    def test_nested_structure(self):
        data = {"a": [1, 2, {"b": True}]}
        result = json_dumps(data)
        assert json_loads(result) == data

    def test_returns_str(self):
        assert isinstance(json_dumps({}), str)

    def test_none_value(self):
        assert json_dumps(None) == "null"

    def test_list(self):
        assert json_dumps([1, 2, 3]) == "[1,2,3]"

    def test_datetime_serialized(self):
        """orjson natively handles datetime objects."""
        dt = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = json_dumps({"ts": dt})
        assert "2025-01-15" in result

    def test_unicode(self):
        result = json_dumps({"emoji": "\U0001f680"})
        parsed = json_loads(result)
        assert parsed["emoji"] == "\U0001f680"


class TestJsonDumpsBytes:
    """json_dumps_bytes returns raw bytes for zero-copy SSE."""

    def test_returns_bytes(self):
        result = json_dumps_bytes({"key": "value"})
        assert isinstance(result, bytes)

    def test_decodable_to_str(self):
        result = json_dumps_bytes({"key": "value"})
        assert result.decode("utf-8") == '{"key":"value"}'


class TestJsonLoads:
    """json_loads parses both str and bytes."""

    def test_loads_str(self):
        assert json_loads('{"a":1}') == {"a": 1}

    def test_loads_bytes(self):
        assert json_loads(b'{"a":1}') == {"a": 1}

    def test_roundtrip(self):
        data = {"nested": {"list": [1, "two", None, True]}}
        assert json_loads(json_dumps(data)) == data

    def test_roundtrip_bytes(self):
        data = {"key": "value"}
        assert json_loads(json_dumps_bytes(data)) == data

    def test_empty_object(self):
        assert json_loads("{}") == {}

    def test_empty_array(self):
        assert json_loads("[]") == []

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            json_loads("not json")

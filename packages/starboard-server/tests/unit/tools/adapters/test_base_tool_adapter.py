"""Unit tests for BaseToolAdapter, OutputFormat, and tool_schema.

Tests cover:
- BaseToolAdapter shared init and from_provider factory
- _log_obs_context standardized logging
- OutputFormat enum values
- tool_schema decorator auto-generating JSON schema from signature/docstring
- collect_tool_schemas helper
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from starboard_server.tools.adapters.base import (
    BaseToolAdapter,
    OutputFormat,
    _extract_param_doc,
    collect_tool_schemas,
    tool_schema,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_provider():
    """Return a minimal mock SharedContextProvider."""
    return MagicMock()


def make_events():
    """Return a minimal mock EventEmitter."""
    return MagicMock()


# ---------------------------------------------------------------------------
# BaseToolAdapter
# ---------------------------------------------------------------------------


class TestBaseToolAdapter:
    def test_init_stores_provider_and_events(self):
        provider = make_provider()
        events = make_events()
        adapter = BaseToolAdapter(provider=provider, events=events)
        assert adapter.provider is provider
        assert adapter.events is events

    def test_init_creates_default_emitter_when_no_events(self):
        from starboard_server.infra.observability.events import EventEmitter

        provider = make_provider()
        adapter = BaseToolAdapter(provider=provider)
        assert isinstance(adapter.events, EventEmitter)

    def test_from_provider_returns_instance(self):
        provider = make_provider()
        adapter = BaseToolAdapter.from_provider(provider)
        assert isinstance(adapter, BaseToolAdapter)
        assert adapter.provider is provider

    def test_from_provider_accepts_events(self):
        provider = make_provider()
        events = make_events()
        adapter = BaseToolAdapter.from_provider(provider, events=events)
        assert adapter.events is events

    def test_log_obs_context_calls_logger_debug(self):
        provider = make_provider()
        adapter = BaseToolAdapter(provider=provider)
        with patch(
            "starboard_server.tools.adapters.base.logger"
        ) as mock_logger:
            adapter._log_obs_context("test_operation", {"key": "value"})
            mock_logger.debug.assert_called_once_with(
                "test_operation",
                extra={"operation": "test_operation", "key": "value"},
            )

    def test_log_obs_context_without_extra(self):
        provider = make_provider()
        adapter = BaseToolAdapter(provider=provider)
        with patch(
            "starboard_server.tools.adapters.base.logger"
        ) as mock_logger:
            adapter._log_obs_context("list_clusters")
            mock_logger.debug.assert_called_once_with(
                "list_clusters",
                extra={"operation": "list_clusters"},
            )

    def test_subclass_inherits_provider_and_events(self):
        class MyTools(BaseToolAdapter):
            pass

        provider = make_provider()
        tools = MyTools.from_provider(provider)
        assert isinstance(tools, MyTools)
        assert tools.provider is provider


# ---------------------------------------------------------------------------
# OutputFormat
# ---------------------------------------------------------------------------


class TestOutputFormat:
    def test_raw_value(self):
        assert OutputFormat.RAW == "raw"

    def test_formatted_value(self):
        assert OutputFormat.FORMATTED == "formatted"

    def test_is_str_enum(self):
        assert isinstance(OutputFormat.RAW, str)
        assert isinstance(OutputFormat.FORMATTED, str)

    def test_comparison_with_string(self):
        assert OutputFormat.RAW == "raw"
        assert OutputFormat.FORMATTED == "formatted"

    def test_default_is_formatted(self):
        # The cluster_tools default should be FORMATTED
        assert OutputFormat.FORMATTED.value == "formatted"


# ---------------------------------------------------------------------------
# tool_schema decorator
# ---------------------------------------------------------------------------


class TestToolSchemaDecorator:
    def test_attaches_tool_schema_attribute(self):
        @tool_schema()
        def my_func(self, warehouse_id: str, window_days: int = 7) -> dict:
            """Get warehouse details.

            Args:
                warehouse_id: The warehouse identifier.
                window_days: Analysis window in days.
            """

        assert hasattr(my_func, "__tool_schema__")

    def test_schema_has_correct_name(self):
        @tool_schema()
        def get_warehouse_portfolio(self, window_days: int = 7) -> dict:
            """Get portfolio."""

        schema = get_warehouse_portfolio.__tool_schema__
        assert schema["function"]["name"] == "get_warehouse_portfolio"

    def test_schema_uses_docstring_description(self):
        @tool_schema()
        def my_tool(self, x: str) -> dict:
            """Fetch important data from the service."""

        schema = my_tool.__tool_schema__
        assert schema["function"]["description"] == "Fetch important data from the service."

    def test_schema_uses_explicit_description(self):
        @tool_schema(description="Custom description override")
        def my_tool(self, x: str) -> dict:
            """Docstring description."""

        schema = my_tool.__tool_schema__
        assert schema["function"]["description"] == "Custom description override"

    def test_schema_infers_required_params(self):
        @tool_schema()
        def my_tool(self, required_param: str, optional_param: int = 5) -> dict:
            """A tool."""

        schema = my_tool.__tool_schema__
        params = schema["function"]["parameters"]
        assert "required_param" in params["required"]
        assert "optional_param" not in params["required"]

    def test_schema_explicit_required_overrides_inferred(self):
        @tool_schema(required=["optional_param"])
        def my_tool(self, required_param: str, optional_param: int = 5) -> dict:
            """A tool."""

        schema = my_tool.__tool_schema__
        assert schema["function"]["parameters"]["required"] == ["optional_param"]

    def test_schema_excludes_self_from_properties(self):
        @tool_schema()
        def my_tool(self, x: str) -> dict:
            """A tool."""

        schema = my_tool.__tool_schema__
        properties = schema["function"]["parameters"]["properties"]
        assert "self" not in properties
        assert "x" in properties

    def test_schema_applies_properties_override(self):
        @tool_schema(properties_override={"window_days": {"enum": [7, 30, 90]}})
        def my_tool(self, window_days: int = 7) -> dict:
            """A tool."""

        schema = my_tool.__tool_schema__
        assert schema["function"]["parameters"]["properties"]["window_days"]["enum"] == [
            7,
            30,
            90,
        ]

    def test_schema_type_mapping_str(self):
        @tool_schema()
        def my_tool(self, name: str) -> dict:
            """A tool."""

        schema = my_tool.__tool_schema__
        assert schema["function"]["parameters"]["properties"]["name"]["type"] == "string"

    def test_schema_type_mapping_int(self):
        @tool_schema()
        def my_tool(self, count: int = 0) -> dict:
            """A tool."""

        schema = my_tool.__tool_schema__
        assert schema["function"]["parameters"]["properties"]["count"]["type"] == "integer"

    def test_schema_type_mapping_bool(self):
        @tool_schema()
        def my_tool(self, flag: bool = False) -> dict:
            """A tool."""

        schema = my_tool.__tool_schema__
        assert schema["function"]["parameters"]["properties"]["flag"]["type"] == "boolean"

    def test_schema_default_value_included(self):
        @tool_schema()
        def my_tool(self, window_days: int = 7) -> dict:
            """A tool."""

        schema = my_tool.__tool_schema__
        assert schema["function"]["parameters"]["properties"]["window_days"]["default"] == 7

    def test_schema_structure_matches_openai_function_format(self):
        @tool_schema()
        def get_portfolio(self, window_days: int = 7) -> dict:
            """Get portfolio view."""

        schema = get_portfolio.__tool_schema__
        assert schema["type"] == "function"
        assert "function" in schema
        assert "name" in schema["function"]
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]
        assert schema["function"]["parameters"]["type"] == "object"
        assert "properties" in schema["function"]["parameters"]
        assert "required" in schema["function"]["parameters"]

    def test_decorated_function_still_callable(self):
        @tool_schema()
        def my_tool(self, x: str) -> dict:
            """A tool."""
            return {"x": x}

        # The original function must remain callable
        result = my_tool(None, x="hello")
        assert result == {"x": "hello"}


# ---------------------------------------------------------------------------
# _extract_param_doc helper
# ---------------------------------------------------------------------------


class TestExtractParamDoc:
    def test_extracts_param_description(self):
        docstring = """Summary line.

        Args:
            warehouse_id: The warehouse identifier.
            window_days: Analysis window in days.
        """
        result = _extract_param_doc(docstring, "warehouse_id")
        assert result == "The warehouse identifier."

    def test_returns_none_for_missing_param(self):
        docstring = """Summary.

        Args:
            x: Some param.
        """
        result = _extract_param_doc(docstring, "missing_param")
        assert result is None

    def test_returns_none_for_empty_docstring(self):
        result = _extract_param_doc("", "x")
        assert result is None


# ---------------------------------------------------------------------------
# collect_tool_schemas helper
# ---------------------------------------------------------------------------


class TestCollectToolSchemas:
    def test_collects_decorated_methods(self):
        class MyAdapter:
            @tool_schema(description="Method A")
            def method_a(self, x: str) -> dict:
                """Method A."""

            @tool_schema(description="Method B")
            def method_b(self, y: int = 0) -> dict:
                """Method B."""

            def undecorated(self) -> dict:
                return {}

        instance = MyAdapter()
        schemas = collect_tool_schemas(instance)
        names = [s["function"]["name"] for s in schemas]
        assert "method_a" in names
        assert "method_b" in names
        assert "undecorated" not in names

    def test_returns_empty_list_for_no_decorated_methods(self):
        class NoSchemas:
            def plain_method(self) -> dict:
                return {}

        instance = NoSchemas()
        schemas = collect_tool_schemas(instance)
        assert schemas == []

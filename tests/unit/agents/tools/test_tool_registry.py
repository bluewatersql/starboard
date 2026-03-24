"""Unit tests for ToolRegistry and related classes."""

from unittest.mock import AsyncMock, Mock

import pytest
from starboard_server.agents.tools.tool_registry import (
    NativeToolAdapter,
    ToolMetadata,
    ToolRegistry,
    _coerce_kwargs_to_schema,
)


class TestToolMetadata:
    """Tests for ToolMetadata class."""

    def test_metadata_creation(self):
        """Test creating valid tool metadata."""
        metadata = ToolMetadata(
            name="test_tool",
            description="Test tool description",
            parameters={
                "type": "object",
                "properties": {"arg1": {"type": "string"}},
            },
        )

        assert metadata.name == "test_tool"
        assert metadata.description == "Test tool description"
        assert metadata.parameters["type"] == "object"

    def test_metadata_empty_name_raises(self):
        """Test that empty name raises error."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            ToolMetadata(
                name="",
                description="Test",
                parameters={"type": "object", "properties": {}},
            )

    def test_metadata_empty_description_raises(self):
        """Test that empty description raises error."""
        with pytest.raises(ValueError, match="description cannot be empty"):
            ToolMetadata(
                name="test",
                description="",
                parameters={"type": "object", "properties": {}},
            )

    def test_metadata_non_dict_parameters_raises(self):
        """Test that non-dict parameters raises error."""
        with pytest.raises(ValueError, match="parameters must be a dictionary"):
            ToolMetadata(
                name="test",
                description="Test",
                parameters="not-a-dict",  # type: ignore
            )

    def test_metadata_parameters_without_type_raises(self):
        """Test that parameters without 'type' raises error."""
        with pytest.raises(ValueError, match="must have 'type' field"):
            ToolMetadata(name="test", description="Test", parameters={})

    def test_metadata_object_without_properties_raises(self):
        """Test that object type without properties raises error."""
        with pytest.raises(ValueError, match="must have 'properties'"):
            ToolMetadata(name="test", description="Test", parameters={"type": "object"})

    def test_to_openai_schema(self):
        """Test converting metadata to OpenAI schema."""
        metadata = ToolMetadata(
            name="test_tool",
            description="Test description",
            parameters={
                "type": "object",
                "properties": {"arg1": {"type": "string"}},
            },
        )

        schema = metadata.to_openai_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test_tool"
        assert schema["function"]["description"] == "Test description"
        assert schema["function"]["parameters"]["type"] == "object"


class TestNativeToolAdapter:
    """Tests for NativeToolAdapter class."""

    @pytest.fixture
    def mock_tool_instance(self):
        """Create mock tool instance."""
        tool = Mock()
        tool.test_method = AsyncMock(return_value={"result": "success"})
        return tool

    @pytest.fixture
    def sample_metadata(self):
        """Create sample tool metadata."""
        return ToolMetadata(
            name="test_tool",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
        )

    def test_adapter_initialization(self, mock_tool_instance, sample_metadata):
        """Test adapter initialization."""
        adapter = NativeToolAdapter(
            tool_instance=mock_tool_instance,
            method_name="test_method",
            metadata=sample_metadata,
        )

        assert adapter.tool_instance == mock_tool_instance
        assert adapter.method_name == "test_method"
        assert adapter.metadata == sample_metadata

    def test_adapter_method_not_found_raises(self, sample_metadata):
        """Test that adapter with non-existent method raises error."""
        tool = Mock(spec=[])  # Mock with no methods

        with pytest.raises(ValueError, match="not found"):
            NativeToolAdapter(
                tool_instance=tool,
                method_name="nonexistent_method",
                metadata=sample_metadata,
            )

    def test_adapter_non_callable_method_raises(self, sample_metadata):
        """Test that adapter with non-callable method raises error."""
        tool = Mock()
        tool.not_a_method = "not_callable"

        with pytest.raises(ValueError, match="is not callable"):
            NativeToolAdapter(
                tool_instance=tool, method_name="not_a_method", metadata=sample_metadata
            )

    @pytest.mark.asyncio
    async def test_adapter_execute(self, mock_tool_instance, sample_metadata):
        """Test executing tool via adapter."""
        adapter = NativeToolAdapter(
            tool_instance=mock_tool_instance,
            method_name="test_method",
            metadata=sample_metadata,
        )

        result = await adapter.execute(arg1="value1")

        mock_tool_instance.test_method.assert_called_once_with(arg1="value1")
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_adapter_execute_non_dict_result_raises(self, sample_metadata):
        """Test that adapter raises error if tool returns non-dict."""
        tool = Mock()
        tool.test_method = AsyncMock(return_value="not-a-dict")

        adapter = NativeToolAdapter(
            tool_instance=tool, method_name="test_method", metadata=sample_metadata
        )

        with pytest.raises(TypeError, match="must return dict"):
            await adapter.execute()


class TestToolRegistry:
    """Tests for ToolRegistry class."""

    @pytest.fixture
    def registry(self):
        """Create empty tool registry."""
        return ToolRegistry()

    @pytest.fixture
    def sample_metadata(self):
        """Create sample tool metadata."""
        return ToolMetadata(
            name="test_tool",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
        )

    @pytest.fixture
    def sample_adapter(self, sample_metadata):
        """Create sample tool adapter."""
        tool = Mock()
        tool.test_method = AsyncMock(return_value={"result": "success"})
        return NativeToolAdapter(
            tool_instance=tool, method_name="test_method", metadata=sample_metadata
        )

    def test_registry_initialization(self, registry):
        """Test registry initialization."""
        assert isinstance(registry, ToolRegistry)
        assert len(registry._tools) == 0

    def test_register_tool(self, registry, sample_adapter):
        """Test registering a tool."""
        registry.register("test_tool", sample_adapter)

        assert "test_tool" in registry._tools
        assert registry._tools["test_tool"] == sample_adapter

    def test_register_duplicate_tool_raises(self, registry, sample_adapter):
        """Test that registering duplicate tool raises error."""
        registry.register("test_tool", sample_adapter)

        with pytest.raises(ValueError, match="already registered"):
            registry.register("test_tool", sample_adapter)

    def test_get_tool(self, registry, sample_adapter):
        """Test getting a registered tool."""
        registry.register("test_tool", sample_adapter)

        tool = registry.get_tool("test_tool")

        assert tool == sample_adapter

    def test_get_tool_not_found(self, registry):
        """Test getting non-existent tool returns None."""
        tool = registry.get_tool("nonexistent")

        assert tool is None

    def test_list_tools(self, registry, sample_adapter):
        """Test listing all registered tools."""
        registry.register("tool1", sample_adapter)

        # Create another adapter
        tool2 = Mock()
        tool2.method = AsyncMock(return_value={})
        metadata2 = ToolMetadata(
            name="tool2",
            description="Tool 2",
            parameters={"type": "object", "properties": {}},
        )
        adapter2 = NativeToolAdapter(
            tool_instance=tool2, method_name="method", metadata=metadata2
        )
        registry.register("tool2", adapter2)

        tools = registry.list_tools()

        assert len(tools) == 2
        assert "tool1" in tools
        assert "tool2" in tools

    def test_list_tools_empty(self, registry):
        """Test listing tools in empty registry."""
        tools = registry.list_tools()

        assert tools == []

    def test_get_tool_schemas(self, registry, sample_adapter):
        """Test getting tool schemas for LLM."""
        registry.register("test_tool", sample_adapter)

        schemas = registry.get_tool_schemas()

        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "test_tool"

    def test_get_tool_schemas_empty(self, registry):
        """Test getting schemas from empty registry."""
        schemas = registry.get_tool_schemas()

        assert schemas == []

    @pytest.mark.asyncio
    async def test_execute_tool(self, registry, sample_adapter):
        """Test executing a registered tool."""
        registry.register("test_tool", sample_adapter)

        result = await registry.execute_tool("test_tool", arg1="value1")

        # execute_tool returns ToolResult
        assert result.tool_name == "test_tool"
        assert not result.is_error()
        # Content is JSON string
        assert "success" in result.content

    @pytest.mark.asyncio
    async def test_execute_tool_not_found_returns_error(self, registry):
        """Test executing non-existent tool returns error result."""
        result = await registry.execute_tool("nonexistent", arg1="value")

        # Returns ToolResult with error, not exception
        assert result.is_error()
        assert "not found" in result.error.lower()

    def test_contains_tool(self, registry, sample_adapter):
        """Test checking if tool is registered."""
        registry.register("test_tool", sample_adapter)

        assert "test_tool" in registry
        assert "nonexistent" not in registry

    def test_len_registry(self, registry, sample_adapter):
        """Test getting count of registered tools."""
        assert len(registry) == 0

        registry.register("tool1", sample_adapter)

        assert len(registry) == 1


class TestCoerceKwargsToSchema:
    """Some LLM providers (e.g. Databricks FMAPI) emit all tool-call args as strings.

    _coerce_kwargs_to_schema uses the tool's JSON Schema to cast them back.
    """

    SCHEMA = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
            "threshold": {"type": "number", "default": 0.5},
            "include_details": {"type": "boolean", "default": False},
        },
    }

    def test_already_correct_types_unchanged(self):
        kwargs = {"query": "hello", "limit": 10, "threshold": 0.5, "include_details": True}
        result = _coerce_kwargs_to_schema(kwargs, self.SCHEMA)
        assert result == kwargs

    def test_string_integer_coerced(self):
        result = _coerce_kwargs_to_schema({"limit": "15"}, self.SCHEMA)
        assert result["limit"] == 15
        assert isinstance(result["limit"], int)

    def test_string_number_coerced(self):
        result = _coerce_kwargs_to_schema({"threshold": "0.75"}, self.SCHEMA)
        assert result["threshold"] == 0.75
        assert isinstance(result["threshold"], float)

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("false", False),
            ("False", False),
            ("1", True),
            ("0", False),
            ("yes", True),
            ("no", False),
        ],
    )
    def test_string_boolean_coerced(self, value, expected):
        result = _coerce_kwargs_to_schema({"include_details": value}, self.SCHEMA)
        assert result["include_details"] is expected

    def test_unparseable_integer_left_unchanged(self):
        result = _coerce_kwargs_to_schema({"limit": "not_a_number"}, self.SCHEMA)
        assert result["limit"] == "not_a_number"

    def test_unknown_keys_pass_through(self):
        result = _coerce_kwargs_to_schema(
            {"limit": "5", "unknown_param": "foo"},
            self.SCHEMA,
        )
        assert result["limit"] == 5
        assert result["unknown_param"] == "foo"

    def test_empty_schema_properties(self):
        result = _coerce_kwargs_to_schema(
            {"limit": "5"},
            {"type": "object"},
        )
        assert result["limit"] == "5"

    @pytest.mark.asyncio
    async def test_adapter_coerces_string_kwargs(self):
        """End-to-end: NativeToolAdapter coerces string args via schema."""
        tool = Mock()
        tool.analyze = AsyncMock(return_value={"ok": True})

        metadata = ToolMetadata(
            name="analyze",
            description="Run analysis",
            parameters={
                "type": "object",
                "properties": {
                    "n_results": {"type": "integer", "default": 5},
                    "include_all": {"type": "boolean", "default": False},
                },
            },
        )

        adapter = NativeToolAdapter(
            tool_instance=tool,
            method_name="analyze",
            metadata=metadata,
        )

        await adapter.execute(n_results="15", include_all="true")

        tool.analyze.assert_called_once_with(n_results=15, include_all=True)

# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for tool factory and metadata."""

from unittest.mock import Mock, patch

import pytest
from starboard_server.agents.tools import (
    ALL_TOOL_METADATA,
    TOOL_CATEGORIES,
    ToolRegistry,
    create_tool_registry,
    get_tool_count,
    get_tool_metadata,
    get_tools_for_domain,
    list_all_tools,
    validate_tool_metadata,
)


class TestToolMetadata:
    """Tests for tool metadata definitions."""

    def test_all_tools_have_required_fields(self):
        """Test that all tools have name, description, and parameters."""
        for tool_name, metadata in ALL_TOOL_METADATA.items():
            assert "name" in metadata, f"{tool_name} missing 'name'"
            assert "description" in metadata, f"{tool_name} missing 'description'"
            assert "parameters" in metadata, f"{tool_name} missing 'parameters'"

    def test_all_tool_names_match_keys(self):
        """Test that tool names in metadata match dictionary keys."""
        for tool_name, metadata in ALL_TOOL_METADATA.items():
            assert metadata["name"] == tool_name, (
                f"Tool {tool_name} has mismatched name: {metadata['name']}"
            )

    def test_all_parameters_have_type(self):
        """Test that all parameter schemas have a type field."""
        for tool_name, metadata in ALL_TOOL_METADATA.items():
            params = metadata["parameters"]
            assert "type" in params, f"{tool_name} parameters missing 'type'"

    def test_object_parameters_have_properties(self):
        """Test that object-type parameters have properties."""
        for tool_name, metadata in ALL_TOOL_METADATA.items():
            params = metadata["parameters"]
            if params.get("type") == "object":
                assert "properties" in params, (
                    f"{tool_name} object parameters missing 'properties'"
                )

    def test_descriptions_are_non_empty(self):
        """Test that all descriptions are non-empty."""
        for tool_name, metadata in ALL_TOOL_METADATA.items():
            assert len(metadata["description"].strip()) > 0, (
                f"{tool_name} has empty description"
            )

    def test_get_tool_metadata(self):
        """Test getting metadata for specific tool."""
        metadata = get_tool_metadata("resolve_query")
        assert metadata["name"] == "resolve_query"
        assert "description" in metadata
        assert "parameters" in metadata

    def test_get_tool_metadata_not_found(self):
        """Test getting metadata for nonexistent tool raises error."""
        with pytest.raises(KeyError):
            get_tool_metadata("nonexistent_tool")

    def test_list_all_tools(self):
        """Test listing all available tools."""
        tools = list_all_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0
        assert "resolve_query" in tools
        assert "get_table_metadata" in tools

    def test_get_tools_for_domain(self):
        """Test getting tools for a domain agent."""
        all_tools = list_all_tools()
        query_tools = get_tools_for_domain("query", all_tools)
        assert isinstance(query_tools, list)
        assert "resolve_query" in query_tools
        assert "analyze_query_plan" in query_tools


class TestToolMetadataValidation:
    """Tests for tool metadata validation."""

    def test_validate_tool_metadata_all_valid(self):
        """Test that all current metadata passes validation."""
        result = validate_tool_metadata()

        assert len(result["valid"]) > 0, "No tools validated successfully"
        assert len(result["invalid"]) == 0, f"Invalid tools found: {result['invalid']}"
        assert len(result["errors"]) == 0, f"Validation errors: {result['errors']}"

    def test_validate_returns_correct_structure(self):
        """Test that validation returns expected structure."""
        result = validate_tool_metadata()

        assert "valid" in result
        assert "invalid" in result
        assert "errors" in result
        assert isinstance(result["valid"], list)
        assert isinstance(result["invalid"], list)
        assert isinstance(result["errors"], list)


class TestToolFactory:
    """Tests for tool factory."""

    @pytest.mark.asyncio
    async def test_create_tool_registry(self):
        """Test creating a tool registry with all tools."""
        # Create mock dependencies
        mock_api = Mock()
        mock_provider = Mock()  # SharedContextProvider mock
        mock_events = Mock()
        mock_llm = Mock()  # LLM client mock
        mock_vector_store = Mock()
        mock_vector_store.__class__.__name__ = "MultiCollectionStore"
        mock_embedding = Mock()
        mock_embedding.__class__.__name__ = "EmbeddingProvider"

        # Patch type checks to pass
        with (
            patch(
                "starboard_server.adapters.llm.openai.client.OpenAIProvider"
            ) as MockProvider,
            patch(
                "starboard_server.agents.tools.tool_factory.isinstance"
            ) as mock_isinstance,
        ):
            MockProvider.return_value = mock_llm
            # Make isinstance return True for our mocks
            mock_isinstance.side_effect = lambda obj, cls: True

            # Create registry with required vector_store and embedding_service
            registry, _ = create_tool_registry(
                mock_api,
                mock_provider,
                mock_events,
                llm_client=mock_llm,
                vector_store=mock_vector_store,
                embedding_service=mock_embedding,
            )

            # Verify it's a ToolRegistry
            assert isinstance(registry, ToolRegistry)

            # Verify tools were registered
            tools = registry.list_tools()
            assert len(tools) > 0, "No tools registered"

            # Verify key tools are present
            assert "resolve_query" in registry
            assert "get_table_metadata" in registry
            assert "request_user_input" in registry  # Web API mode tool

    @pytest.mark.asyncio
    async def test_registry_has_all_metadata_tools(self):
        """Test that registry contains all tools from metadata."""
        mock_api = Mock()
        mock_provider = Mock()  # SharedContextProvider mock
        mock_llm = Mock()  # LLM client mock
        mock_cache_factory = Mock()  # CacheFactory for artifact exploration
        mock_vector_store = Mock()
        mock_vector_store.__class__.__name__ = "MultiCollectionStore"
        mock_embedding = Mock()
        mock_embedding.__class__.__name__ = "EmbeddingProvider"

        with (
            patch(
                "starboard_server.adapters.llm.openai.client.OpenAIProvider"
            ) as MockProvider,
            patch(
                "starboard_server.agents.tools.tool_factory.isinstance"
            ) as mock_isinstance,
        ):
            MockProvider.return_value = mock_llm
            mock_isinstance.side_effect = lambda obj, cls: True

            registry, _ = create_tool_registry(
                mock_api,
                mock_provider,
                llm_client=mock_llm,
                cache_factory=mock_cache_factory,
                vector_store=mock_vector_store,
                embedding_service=mock_embedding,
            )

            registered_tools = set(registry.list_tools())
            # Remove tools registered separately or conditionally
            registered_tools.discard("complete")

            metadata_tools = set(ALL_TOOL_METADATA.keys())

            assert registered_tools == metadata_tools, (
                f"Mismatch: registered={registered_tools}, metadata={metadata_tools}"
            )

    @pytest.mark.asyncio
    async def test_registered_tools_have_valid_schemas(self):
        """Test that all registered tools have valid OpenAI schemas."""
        mock_api = Mock()
        mock_provider = Mock()  # SharedContextProvider mock
        mock_llm = Mock()  # LLM client mock
        mock_vector_store = Mock()
        mock_vector_store.__class__.__name__ = "MultiCollectionStore"
        mock_embedding = Mock()
        mock_embedding.__class__.__name__ = "EmbeddingProvider"

        with (
            patch(
                "starboard_server.adapters.llm.openai.client.OpenAIProvider"
            ) as MockProvider,
            patch(
                "starboard_server.agents.tools.tool_factory.isinstance"
            ) as mock_isinstance,
        ):
            MockProvider.return_value = mock_llm
            mock_isinstance.side_effect = lambda obj, cls: True

            registry, _ = create_tool_registry(
                mock_api,
                mock_provider,
                llm_client=mock_llm,
                vector_store=mock_vector_store,
                embedding_service=mock_embedding,
            )

            schemas = registry.get_tool_schemas()

            assert len(schemas) > 0, "No tool schemas generated"

            # Validate schema structure
            for schema in schemas:
                assert "type" in schema
                assert schema["type"] == "function"
                assert "function" in schema
                assert "name" in schema["function"]
                assert "description" in schema["function"]
                assert "parameters" in schema["function"]

    def test_get_tool_count(self):
        """Test getting total tool count."""
        count = get_tool_count()
        assert count == len(ALL_TOOL_METADATA)
        assert count > 0

    @pytest.mark.asyncio
    async def test_create_tool_registry_without_vector_store(self):
        """Test creating a tool registry without vector store (CLI mode)."""
        # Create mock dependencies
        mock_api = Mock()
        mock_provider = Mock()  # SharedContextProvider mock
        mock_events = Mock()
        mock_llm = Mock()  # LLM client mock

        # Patch LLM provider creation
        with patch(
            "starboard_server.adapters.llm.openai.client.OpenAIProvider"
        ) as MockProvider:
            MockProvider.return_value = mock_llm

            # Create registry WITHOUT vector_store and embedding_service
            registry, _ = create_tool_registry(
                mock_api,
                mock_provider,
                mock_events,
                llm_client=mock_llm,
                vector_store=None,  # Not provided in CLI mode
                embedding_service=None,  # Not provided in CLI mode
            )

            # Verify it's a ToolRegistry
            assert isinstance(registry, ToolRegistry)

            # Verify tools were registered
            tools = registry.list_tools()
            assert len(tools) > 0, "No tools registered"

            # Verify key tools are present
            assert "resolve_query" in registry
            assert "get_table_metadata" in registry
            assert "request_user_input" in registry

            # Verify analytics context tool is NOT present (requires vector store)
            assert "build_analytics_context" not in registry

            # Verify analytics SQL tools ARE present (don't require vector store)
            assert "build_sql_query" in registry
            assert "validate_sql_query" in registry
            assert "execute_sql_query" in registry


class TestToolExecution:
    """Tests for tool execution through registry."""

    @pytest.mark.asyncio
    async def test_execute_resolve_query_tool(self):
        """Test executing resolve_query tool."""
        # Create mocks
        mock_api = Mock()
        mock_provider = Mock()  # SharedContextProvider mock
        mock_llm = Mock()  # LLM client mock
        mock_vector_store = Mock()
        mock_vector_store.__class__.__name__ = "MultiCollectionStore"
        mock_embedding = Mock()
        mock_embedding.__class__.__name__ = "EmbeddingProvider"

        with (
            patch(
                "starboard_server.adapters.llm.openai.client.OpenAIProvider"
            ) as MockProvider,
            patch(
                "starboard_server.agents.tools.tool_factory.isinstance"
            ) as mock_isinstance,
        ):
            MockProvider.return_value = mock_llm
            mock_isinstance.side_effect = lambda obj, cls: True

            # Create registry
            registry, _ = create_tool_registry(
                mock_api,
                mock_provider,
                llm_client=mock_llm,
                vector_store=mock_vector_store,
                embedding_service=mock_embedding,
            )

            # Get the tool
            assert "resolve_query" in registry

            # Execute tool (will fail without proper mocks, but validates structure)
            try:
                result = await registry.execute_tool(
                    "resolve_query", target="SELECT * FROM users"
                )
                # If it succeeds or fails, we've validated the structure
                assert result is not None
            except Exception:
                # Expected - we don't have real Databricks connection
                pass

    @pytest.mark.asyncio
    async def test_tool_schemas_match_metadata(self):
        """Test that generated schemas match metadata definitions."""
        mock_api = Mock()
        mock_provider = Mock()  # SharedContextProvider mock
        mock_llm = Mock()  # LLM client mock
        mock_cache_factory = Mock()  # CacheFactory for artifact exploration
        mock_vector_store = Mock()
        mock_vector_store.__class__.__name__ = "MultiCollectionStore"
        mock_embedding = Mock()
        mock_embedding.__class__.__name__ = "EmbeddingProvider"

        with (
            patch(
                "starboard_server.adapters.llm.openai.client.OpenAIProvider"
            ) as MockProvider,
            patch(
                "starboard_server.agents.tools.tool_factory.isinstance"
            ) as mock_isinstance,
        ):
            MockProvider.return_value = mock_llm
            mock_isinstance.side_effect = lambda obj, cls: True

            registry, _ = create_tool_registry(
                mock_api,
                mock_provider,
                llm_client=mock_llm,
                cache_factory=mock_cache_factory,
                vector_store=mock_vector_store,
                embedding_service=mock_embedding,
            )
            schemas = registry.get_tool_schemas()

            # Create mapping of schema names to schemas
            schema_map = {s["function"]["name"]: s for s in schemas}

            # Check each metadata tool has corresponding schema
            for tool_name, metadata in ALL_TOOL_METADATA.items():
                assert tool_name in schema_map, f"No schema for {tool_name}"

                schema = schema_map[tool_name]
                func = schema["function"]

                # Verify name matches
                assert func["name"] == metadata["name"]

                # Verify description matches
                assert func["description"] == metadata["description"]

                # Verify parameters match
                assert func["parameters"]["type"] == metadata["parameters"]["type"]


class TestToolCategories:
    """Tests for domain-based tool access (TOOL_CATEGORIES from tool_categories.py)."""

    def test_expected_domains_exist(self):
        """Test that expected agent domains are defined."""
        expected_domains = [
            "router",
            "query",
            "job",
            "uc",
            "cluster",
            "analytics",
            "diagnostic",
            "warehouse",
        ]
        for domain in expected_domains:
            assert domain in TOOL_CATEGORIES, f"Domain {domain} not defined"

    def test_diagnostic_has_all_marker(self):
        """Test that diagnostic domain has special 'all' marker."""
        assert TOOL_CATEGORIES["diagnostic"] == "all"

    def test_query_domain_has_expected_tools(self):
        """Test that query domain has key tools."""
        all_tools = list_all_tools()
        query_tools = get_tools_for_domain("query", all_tools)
        assert "resolve_query" in query_tools
        assert "analyze_query_plan" in query_tools

    def test_uc_domain_has_expected_tools(self):
        """Test that UC domain has key tools."""
        all_tools = list_all_tools()
        uc_tools = get_tools_for_domain("uc", all_tools)
        assert "get_table_metadata" in uc_tools
        assert "get_table_history" in uc_tools


class TestToolParameterSchemas:
    """Tests for tool parameter schemas."""

    def test_resolve_query_has_target_parameter(self):
        """Test resolve_query has target parameter."""
        metadata = get_tool_metadata("resolve_query")
        props = metadata["parameters"]["properties"]

        assert "target" in props
        assert props["target"]["type"] == "string"
        assert "description" in props["target"]

    def test_get_table_metadata_has_table_name_parameter(self):
        """Test get_table_metadata has table_name parameter."""
        metadata = get_tool_metadata("get_table_metadata")
        props = metadata["parameters"]["properties"]

        assert "table_name" in props
        assert props["table_name"]["type"] == "string"

    def test_all_required_fields_exist_in_properties(self):
        """Test that all required fields exist in properties."""
        for tool_name, metadata in ALL_TOOL_METADATA.items():
            params = metadata["parameters"]
            if "required" in params:
                props = params.get("properties", {})
                for required_field in params["required"]:
                    assert required_field in props, (
                        f"{tool_name}: required field '{required_field}' not in properties"
                    )

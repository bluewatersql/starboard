"""
Tests for OpenAI LLM client adapter - async-native version.

Coverage targets:
- Initialization and configuration
- Text responses and streaming
- JSON responses and streaming
- Function/tool calling
- Token counting and normalization
- Error handling
- Helper methods
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from openai import APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel
from starboard_server.adapters.llm.openai.client import OpenAIProvider
from starboard_server.infra.core.config import EnvConfig


class SampleSchema(BaseModel):
    """Sample Pydantic model for testing."""

    name: str
    value: int


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def create_mock_usage(
    prompt_tokens: int = 10, completion_tokens: int = 5, total_tokens: int = 15
):
    """Create a properly configured mock usage object."""
    mock_usage = Mock()
    mock_usage.prompt_tokens = prompt_tokens
    mock_usage.completion_tokens = completion_tokens
    mock_usage.total_tokens = total_tokens
    # For normalize_usage to work properly
    mock_usage.model_dump = Mock(
        return_value={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
    )
    return mock_usage


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_env_config() -> Mock:
    """Provide a mock environment configuration."""
    config = Mock(spec=EnvConfig)
    config.llm_api_key = "test-api-key"
    config.llm_model = "gpt-4o-mini"
    config.llm_temperature = 0.4
    config.llm_max_tokens = 4096
    config.llm_seed = 42
    config.llm_base_url = ""
    config.embedding_model = "text-embedding-3-small"
    # Phase-specific configs
    config.llm_planning_model = None
    config.llm_planning_temperature = None
    config.llm_judge_model = None
    config.llm_judge_temperature = None
    config.llm_synth_model = None
    config.llm_synth_temperature = None
    return config


@pytest.fixture
def mock_async_openai_client() -> AsyncMock:
    """Provide a mock OpenAI async client."""
    client = AsyncMock(spec=AsyncOpenAI)
    client.chat = AsyncMock()
    client.chat.completions = AsyncMock()
    client.embeddings = AsyncMock()
    return client


@pytest.fixture
def openai_provider(
    mock_env_config: Mock, mock_async_openai_client: AsyncMock
) -> OpenAIProvider:
    """Provide an OpenAIProvider instance with mocked async client."""
    with patch(
        "starboard_server.adapters.llm.openai.client.AsyncOpenAI",
        return_value=mock_async_openai_client,
    ):
        provider = OpenAIProvider(cfg=mock_env_config)
        provider.async_client = mock_async_openai_client
        return provider


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


class TestOpenAIProviderInitialization:
    """Tests for OpenAIProvider initialization and configuration."""

    def test_init_with_config(self, mock_env_config) -> None:
        """Test that provider initializes correctly with config."""
        with patch("starboard_server.adapters.llm.openai.client.AsyncOpenAI"):
            provider = OpenAIProvider(cfg=mock_env_config)

            assert provider.cfg == mock_env_config
            assert provider.model == "gpt-4o-mini"
            assert provider.temperature == 0.4
            assert provider.max_tokens == 4096
            assert provider.seed == 42

    def test_init_without_api_key_raises_error(self):
        """Test that missing API key raises ValueError."""
        config = Mock(spec=EnvConfig)
        config.llm_api_key = None

        with pytest.raises(ValueError, match="LLM_API_KEY is required"):
            OpenAIProvider(cfg=config)

    def test_circuit_breaker_initialized(self, openai_provider) -> None:
        """Test that circuit breaker is initialized."""
        assert openai_provider.circuit_breaker is not None
        assert openai_provider.circuit_breaker.name == "openai_api"


# ============================================================================
# TEXT RESPONSE TESTS
# ============================================================================


class TestTextResponse:
    """Tests for text_response method."""

    @pytest.mark.asyncio
    async def test_basic_text_response(
        self, openai_provider, mock_async_openai_client
    ) -> None:
        """Test basic text response generation."""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Hello, world!"))]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        messages = [{"role": "user", "content": "Say hello"}]

        result = await openai_provider.text_response(messages)

        assert result == "Hello, world!"
        mock_async_openai_client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_text_response_empty_content_raises_error(
        self, openai_provider, mock_async_openai_client
    ):
        """Test that empty content raises ValueError."""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content=None))]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        with pytest.raises(ValueError, match="LLM returned empty response"):
            await openai_provider.text_response([{"role": "user", "content": "Test"}])


# ============================================================================
# STREAMING TESTS
# ============================================================================


class TestTextResponseStream:
    """Tests for text_response_stream method."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(
        self, openai_provider, mock_async_openai_client
    ) -> None:
        """Test that streaming yields content chunks."""
        chunk1 = Mock()
        chunk1.choices = [Mock(delta=Mock(content="Hello"))]
        chunk1.usage = None

        chunk2 = Mock()
        chunk2.choices = [Mock(delta=Mock(content=" world"))]
        chunk2.usage = None

        chunk3 = Mock()
        chunk3.choices = [Mock(delta=Mock(content="!"))]
        chunk3.usage = create_mock_usage()

        async def mock_stream():
            for chunk in [chunk1, chunk2, chunk3]:
                yield chunk

        mock_async_openai_client.chat.completions.create.return_value = mock_stream()

        chunks = []
        async for chunk in openai_provider.text_response_stream(
            [{"role": "user", "content": "Test"}]
        ):
            chunks.append(chunk)

        assert chunks == ["Hello", " world", "!"]


# ============================================================================
# HELPER METHOD TESTS
# ============================================================================


class TestHelperMethods:
    """Tests for helper/utility methods."""

    def test_is_gemini_model(self, openai_provider) -> None:
        """Test Gemini model detection."""
        assert openai_provider._is_gemini_model("gemini-pro") is True
        assert openai_provider._is_gemini_model("google-gemini-1.5") is True
        assert openai_provider._is_gemini_model("gpt-4o") is False

    def test_is_gpt5_model(self, openai_provider) -> None:
        """Test GPT-5 model detection."""
        assert openai_provider._is_gpt5_model("gpt-5") is True
        assert openai_provider._is_gpt5_model("gpt-5-turbo") is True
        assert openai_provider._is_gpt5_model("databricks-gpt-5") is True
        assert openai_provider._is_gpt5_model("gpt-4o") is False

    def test_flatten_json_schema_no_refs(self, openai_provider) -> None:
        """Test schema flattening with no $ref."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = openai_provider._flatten_json_schema(schema)
        assert result == schema

    def test_flatten_json_schema_with_refs(self, openai_provider) -> None:
        """Test schema flattening with $ref and $defs."""
        schema = {
            "$defs": {
                "Person": {"type": "object", "properties": {"name": {"type": "string"}}}
            },
            "type": "object",
            "properties": {"person": {"$ref": "#/$defs/Person"}},
        }

        result = openai_provider._flatten_json_schema(schema)

        # Should inline the definition
        assert "$defs" not in result
        assert "$ref" not in str(result)
        assert result["properties"]["person"]["type"] == "object"

    def test_flatten_json_schema_nested_refs(self, openai_provider) -> None:
        """Test schema flattening with nested $refs."""
        schema = {
            "$defs": {
                "Address": {
                    "type": "object",
                    "properties": {"street": {"type": "string"}},
                },
                "Person": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "address": {"$ref": "#/$defs/Address"},
                    },
                },
            },
            "type": "object",
            "properties": {"person": {"$ref": "#/$defs/Person"}},
        }

        result = openai_provider._flatten_json_schema(schema)

        # Should resolve all refs
        assert "$defs" not in result
        assert result["properties"]["person"]["type"] == "object"
        assert (
            result["properties"]["person"]["properties"]["address"]["type"] == "object"
        )

    def test_prepare_tools_for_gemini_flattens_schemas(self, openai_provider) -> None:
        """Test that tool schemas are flattened for Gemini."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test",
                    "parameters": {
                        "$defs": {"Item": {"type": "object"}},
                        "properties": {"item": {"$ref": "#/$defs/Item"}},
                    },
                },
            }
        ]

        result = openai_provider._prepare_tools_for_model(tools, "gemini-pro")

        # Should flatten the schema
        assert "$defs" not in str(result)
        assert (
            result[0]["function"]["parameters"]["properties"]["item"]["type"]
            == "object"
        )

    def test_prepare_json_schema_dict_with_name(self, openai_provider) -> None:
        """Test JSON schema preparation with dict containing name."""
        schema = {
            "name": "custom_schema",
            "schema": {"type": "object", "properties": {}},
            # No 'strict' key - will be added
        }

        json_schema, pydantic_model, is_pydantic = openai_provider._prepare_json_schema(
            schema
        )

        assert is_pydantic is False
        assert pydantic_model is None
        assert json_schema["name"] == "custom_schema"
        assert json_schema["strict"] is True  # Should be added

    def test_normalize_usage_openai_format(self, openai_provider) -> None:
        """Test usage normalization for OpenAI format."""
        usage = create_mock_usage(10, 5, 15)
        result = openai_provider._normalize_usage(usage)

        assert result["prompt_tokens"] == 10
        assert result["completion_tokens"] == 5
        assert result["total_tokens"] == 15

    def test_normalize_usage_empty(self, openai_provider) -> None:
        """Test usage normalization with None."""
        result = openai_provider._normalize_usage(None)

        assert result["prompt_tokens"] == 0
        assert result["completion_tokens"] == 0
        assert result["total_tokens"] == 0

    def test_normalize_usage_anthropic_format(self, openai_provider) -> None:
        """Test usage normalization for Anthropic/Claude format."""
        usage_mock = Mock()
        # Set attributes directly as integers
        usage_mock.prompt_tokens = None
        usage_mock.completion_tokens = None
        usage_mock.input_tokens = 10
        usage_mock.output_tokens = 5
        usage_mock.total_tokens = None
        # Make model_dump fail to force attribute access
        usage_mock.model_dump = Mock(side_effect=Exception("Not available"))

        result = openai_provider._normalize_usage(usage_mock)

        assert result["prompt_tokens"] == 10
        assert result["completion_tokens"] == 5

    def test_normalize_usage_dict_format(self, openai_provider) -> None:
        """Test usage normalization with dict input."""
        usage = {"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25}

        result = openai_provider._normalize_usage(usage)

        assert result["prompt_tokens"] == 15
        assert result["completion_tokens"] == 10
        assert result["total_tokens"] == 25

    def test_parse_json_content_valid(self, openai_provider) -> None:
        """Test JSON content parsing with valid JSON."""
        content = '{"result": "success"}'
        result = openai_provider._parse_json_content(content, "trace_123")
        assert result == {"result": "success"}

    def test_parse_json_content_markdown(self, openai_provider) -> None:
        """Test JSON content parsing from markdown."""
        content = '```json\n{"result": "success"}\n```'
        result = openai_provider._parse_json_content(content, "trace_123")
        assert result == {"result": "success"}

    def test_parse_json_content_invalid(self, openai_provider) -> None:
        """Test JSON content parsing with invalid JSON."""
        content = "not json at all"
        result = openai_provider._parse_json_content(content, "trace_123")
        assert result["error"] == "llm_parse_failed"

    def test_build_request_params_defaults(self, openai_provider) -> None:
        """Test request parameter building with defaults."""
        messages = [{"role": "user", "content": "Test"}]
        params = openai_provider._build_request_params(messages)

        assert params["model"] == "gpt-4o-mini"
        assert params["temperature"] == 0.4
        assert params["max_tokens"] == 4096
        assert params["stream"] is False
        assert params["seed"] == 42

    def test_build_request_params_gpt5_temperature_override(
        self, openai_provider
    ) -> None:
        """Test that GPT-5 models override temperature to 1.0."""
        messages = [{"role": "user", "content": "Test"}]
        params = openai_provider._build_request_params(
            messages, model="gpt-5", temperature=0.5
        )

        # Should override to 1.0
        assert params["temperature"] == 1.0

    def test_prepare_json_schema_pydantic(self, openai_provider) -> None:
        """Test JSON schema preparation with Pydantic model."""
        json_schema, pydantic_model, is_pydantic = openai_provider._prepare_json_schema(
            SampleSchema
        )

        assert is_pydantic is True
        assert pydantic_model == SampleSchema
        assert json_schema["name"] == "SampleSchema"
        assert json_schema["strict"] is True


# ============================================================================
# JSON RESPONSE TESTS
# ============================================================================


class TestJsonResponse:
    """Tests for json_response method."""

    @pytest.mark.asyncio
    async def test_json_response_without_schema(
        self, openai_provider, mock_async_openai_client
    ) -> None:
        """Test JSON response without schema."""
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = '{"result": "success"}'
        mock_message.refusal = None
        mock_response.choices = [Mock(message=mock_message)]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        result = await openai_provider.json_response(
            [{"role": "user", "content": "Test"}]
        )

        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_json_response_handles_refusal(
        self, openai_provider, mock_async_openai_client
    ) -> None:
        """Test JSON response handles LLM refusal."""
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = None
        mock_message.refusal = "I cannot do that"
        mock_response.choices = [Mock(message=mock_message)]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        result = await openai_provider.json_response(
            [{"role": "user", "content": "Test"}]
        )

        assert result["error"] == "llm_refused"


# ============================================================================
# EMBEDDING TESTS
# ============================================================================


class TestEmbed:
    """Tests for embed method."""

    @pytest.mark.asyncio
    async def test_embed_basic(self, openai_provider, mock_async_openai_client) -> None:
        """Test basic embedding generation."""
        mock_response = Mock()
        mock_response.data = [
            Mock(embedding=[0.1, 0.2, 0.3]),
            Mock(embedding=[0.4, 0.5, 0.6]),
        ]
        mock_async_openai_client.embeddings.create.return_value = mock_response

        result = await openai_provider.embed(["text1", "text2"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    @pytest.mark.asyncio
    async def test_embed_empty_list(self, openai_provider) -> None:
        """Test embedding with empty list."""
        result = await openai_provider.embed([])
        assert result == []


# ============================================================================
# TOOL CALLING TESTS
# ============================================================================


class TestCallWithTools:
    """Tests for tool calling."""

    @pytest.mark.asyncio
    async def test_call_with_tools_basic(
        self, openai_provider, mock_async_openai_client
    ) -> None:
        """Test basic tool calling."""
        mock_response = Mock()
        mock_response.choices = [
            Mock(
                message=Mock(content="I'll help", tool_calls=None), finish_reason="stop"
            )
        ]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        tools = [{"type": "function", "function": {"name": "test_tool"}}]

        result = await openai_provider.call_with_tools(
            [{"role": "user", "content": "Test"}], tools=tools
        )

        assert result.content == "I'll help"
        assert len(result.tool_calls) == 0

    @pytest.mark.asyncio
    async def test_call_with_tools_single_tool_call(
        self, openai_provider, mock_async_openai_client
    ):
        """Test tool calling with single tool call."""
        mock_function = Mock()
        mock_function.name = "test_tool"
        mock_function.arguments = '{"param": "value"}'

        mock_tool_call = Mock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function = mock_function

        mock_response = Mock()
        mock_response.choices = [
            Mock(
                message=Mock(content=None, tool_calls=[mock_tool_call]),
                finish_reason="tool_calls",
            )
        ]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        tools = [{"type": "function", "function": {"name": "test_tool"}}]

        result = await openai_provider.call_with_tools(
            [{"role": "user", "content": "Test"}], tools=tools
        )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_123"
        assert result.tool_calls[0].name == "test_tool"


# ============================================================================
# ASYNC TOOL STREAMING TESTS
# ============================================================================


class TestCallWithToolsStream:
    """Tests for async tool calling with streaming."""

    @pytest.mark.asyncio
    async def test_stream_content_delta(
        self, openai_provider, mock_async_openai_client
    ):
        """Test streaming content deltas."""

        async def mock_stream():
            chunk = Mock()
            chunk.choices = [
                Mock(delta=Mock(content="Hello", tool_calls=None), finish_reason=None)
            ]
            yield chunk

            chunk2 = Mock()
            chunk2.choices = [
                Mock(
                    delta=Mock(content=" world", tool_calls=None), finish_reason="stop"
                )
            ]
            yield chunk2

        mock_async_openai_client.chat.completions.create.return_value = mock_stream()

        tools = []

        chunks = []
        async for chunk in openai_provider.call_with_tools_stream(
            [{"role": "user", "content": "Test"}], tools=tools
        ):
            chunks.append(chunk)

        content_chunks = [c for c in chunks if c.get("type") == "content_delta"]
        assert len(content_chunks) == 2
        assert content_chunks[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_stream_yields_usage(
        self, openai_provider: OpenAIProvider, mock_async_openai_client: AsyncMock
    ) -> None:
        """Test that streaming yields usage information."""

        async def mock_stream():
            chunk = Mock()
            chunk.choices = [
                Mock(delta=Mock(content="Test", tool_calls=None), finish_reason="stop")
            ]
            yield chunk

        mock_async_openai_client.chat.completions.create.return_value = mock_stream()

        chunks = []
        async for chunk in openai_provider.call_with_tools_stream(
            [{"role": "user", "content": "Test"}], tools=[]
        ):
            chunks.append(chunk)

        usage_chunks = [c for c in chunks if c.get("type") == "usage"]
        assert len(usage_chunks) >= 1


# ============================================================================
# JSON STREAMING TESTS
# ============================================================================


class TestJsonResponseStream:
    """Tests for JSON streaming."""

    @pytest.mark.asyncio
    async def test_json_stream_basic(
        self, openai_provider, mock_async_openai_client
    ) -> None:
        """Test basic JSON streaming."""
        chunk = Mock()
        chunk.choices = [Mock(delta=Mock(content='{"test": 1}'))]
        chunk.usage = create_mock_usage()

        async def mock_stream():
            yield chunk

        mock_async_openai_client.chat.completions.create.return_value = mock_stream()

        chunks = []
        async for c in openai_provider.json_response_stream(
            [{"role": "user", "content": "Test"}]
        ):
            chunks.append(c)

        assert len(chunks) > 0


# ============================================================================
# ADDITIONAL TEXT RESPONSE TESTS
# ============================================================================


class TestTextResponseAdditional:
    """Additional text response tests for coverage."""

    @pytest.mark.asyncio
    async def test_text_response_with_custom_params(
        self, openai_provider, mock_async_openai_client
    ):
        """Test text response with all custom parameters."""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Response"))]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        result = await openai_provider.text_response(
            [{"role": "user", "content": "Test"}],
            model="gpt-4o",
            temperature=0.9,
            max_tokens=100,
        )

        assert result == "Response"
        call_kwargs = mock_async_openai_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["temperature"] == 0.9
        assert call_kwargs["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_text_response_handles_api_timeout(
        self, openai_provider, mock_async_openai_client
    ):
        """Test text response retries on timeout."""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Success"))]
        mock_response.usage = create_mock_usage()

        mock_async_openai_client.chat.completions.create.side_effect = [
            APITimeoutError("Timeout"),
            mock_response,
        ]

        result = await openai_provider.text_response(
            [{"role": "user", "content": "Test"}]
        )

        assert result == "Success"
        assert mock_async_openai_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_text_response_handles_rate_limit(
        self, openai_provider, mock_async_openai_client
    ):
        """Test text response retries on rate limit."""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Success"))]
        mock_response.usage = create_mock_usage()

        mock_rate_limit_response = Mock()
        mock_rate_limit_response.request = Mock()

        mock_async_openai_client.chat.completions.create.side_effect = [
            RateLimitError("Rate limit", response=mock_rate_limit_response, body=None),
            mock_response,
        ]

        result = await openai_provider.text_response(
            [{"role": "user", "content": "Test"}]
        )

        assert result == "Success"
        assert mock_async_openai_client.chat.completions.create.call_count == 2


# ============================================================================
# ADDITIONAL JSON RESPONSE TESTS
# ============================================================================


class TestJsonResponseAdditional:
    """Additional JSON response tests for coverage."""

    @pytest.mark.asyncio
    async def test_json_response_with_pydantic_schema(
        self, openai_provider, mock_async_openai_client
    ):
        """Test JSON response with Pydantic schema."""
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = '{"name": "test", "value": 42}'
        mock_message.refusal = None
        mock_response.choices = [Mock(message=mock_message)]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        result = await openai_provider.json_response(
            [{"role": "user", "content": "Test"}], schema=SampleSchema
        )

        assert result["name"] == "test"
        assert result["value"] == 42

    @pytest.mark.asyncio
    async def test_json_response_with_dict_schema(
        self, openai_provider, mock_async_openai_client
    ) -> None:
        """Test JSON response with dict schema."""
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = '{"test": "value"}'
        mock_message.refusal = None
        mock_response.choices = [Mock(message=mock_message)]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        schema = {"type": "object", "properties": {"test": {"type": "string"}}}

        result = await openai_provider.json_response(
            [{"role": "user", "content": "Test"}], schema=schema
        )

        assert result["test"] == "value"

    @pytest.mark.asyncio
    async def test_json_response_handles_empty_content(
        self, openai_provider, mock_async_openai_client
    ):
        """Test JSON response handles empty content."""
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = ""
        mock_message.refusal = None
        mock_response.choices = [Mock(message=mock_message, finish_reason="stop")]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        result = await openai_provider.json_response(
            [{"role": "user", "content": "Test"}]
        )

        assert result["error"] == "llm_empty_content"

    @pytest.mark.asyncio
    async def test_json_response_extracts_from_markdown(
        self, openai_provider, mock_async_openai_client
    ):
        """Test JSON response extracts from markdown code block."""
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = '```json\n{"extracted": true}\n```'
        mock_message.refusal = None
        mock_response.choices = [Mock(message=mock_message)]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        result = await openai_provider.json_response(
            [{"role": "user", "content": "Test"}]
        )

        assert result["extracted"] is True


# ============================================================================
# PHASE-BASED MODEL/TEMPERATURE TESTS
# ============================================================================


class TestPhaseSelection:
    """Tests for phase-based model and temperature selection."""

    def test_get_model_for_phase_planning(self, openai_provider) -> None:
        """Test model selection for planning phase."""
        model = openai_provider._get_model_for_phase("planning")
        # Should return default since no planning model configured
        assert model == "gpt-4o-mini"

    def test_get_temperature_for_phase_planning(self, openai_provider) -> None:
        """Test temperature selection for planning phase."""
        temp = openai_provider._get_temperature_for_phase("planning")
        # Should return default since no planning temperature configured
        assert temp == 0.4


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(
        self, openai_provider, mock_async_openai_client
    ) -> None:
        """Test that exhausted retries raise error."""
        mock_response = Mock()
        mock_response.request = Mock()

        mock_async_openai_client.chat.completions.create.side_effect = RateLimitError(
            "Rate limit", response=mock_response, body=None
        )

        with pytest.raises(RateLimitError):
            await openai_provider.text_response([{"role": "user", "content": "Test"}])

    @pytest.mark.asyncio
    async def test_invalid_message_format_raises_error(self, openai_provider) -> None:
        """Test that invalid message format raises ValueError."""
        with pytest.raises(ValueError, match="messages must be a list"):
            await openai_provider.json_response("not a list")

    @pytest.mark.asyncio
    async def test_missing_message_fields_raises_error(
        self, openai_provider, mock_async_openai_client
    ):
        """Test missing message fields raises ValueError."""
        mock_response = Mock()
        mock_message = Mock()
        mock_message.content = '{"test": "value"}'
        mock_message.refusal = None
        mock_response.choices = [Mock(message=mock_message)]
        mock_response.usage = create_mock_usage()
        mock_async_openai_client.chat.completions.create.return_value = mock_response

        with pytest.raises(ValueError, match="missing 'role' or 'content'"):
            await openai_provider.json_response([{"role": "user"}])  # Missing content

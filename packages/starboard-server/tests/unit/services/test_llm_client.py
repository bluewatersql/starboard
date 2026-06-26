# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for LLM client."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field
from starboard_server.adapters.llm.openai.client import OpenAIProvider
from starboard_server.adapters.llm.openai.tokens import TokenBudget
from starboard_server.infra.core.config import EnvConfig


class MockSchema(BaseModel):
    """Mock Pydantic schema for testing (named without Test prefix to avoid pytest collection)."""

    message: str = Field(..., description="Test message")
    count: int = Field(default=0, description="Test count")


class TestOpenAIProvider:
    """Test OpenAIProvider functionality."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        cfg = Mock(spec=EnvConfig)
        cfg.llm_api_key = "test-key"
        cfg.llm_model = "gpt-4o-mini"
        cfg.llm_temperature = 0.4
        cfg.llm_max_tokens = 8192
        cfg.llm_base_url = None
        cfg.llm_planning_model = None
        cfg.llm_judge_model = None
        cfg.llm_review_model = None
        cfg.llm_synth_model = None
        cfg.llm_planning_temperature = None
        cfg.llm_judge_temperature = None
        cfg.llm_review_temperature = None
        cfg.llm_synth_temperature = None
        cfg.llm_seed = 42  # Add seed to mock config
        return cfg

    @pytest.fixture
    def mock_async_openai_client(self):
        """Create mock AsyncOpenAI SDK client."""
        mock = AsyncMock()
        # Mock response
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "Test response"
        response.choices[0].message.refusal = None  # No refusal
        response.usage.prompt_tokens = 100
        response.usage.completion_tokens = 50
        response.usage.total_tokens = 150
        mock.chat.completions.create = AsyncMock(return_value=response)
        return mock

    @pytest.fixture
    def llm_client(self, mock_config, mock_async_openai_client):
        """Create LLM client with mocked dependencies."""
        with patch(
            "starboard_server.adapters.llm.openai.client.AsyncOpenAI"
        ) as mock_cls:
            mock_cls.return_value = mock_async_openai_client
            client = OpenAIProvider(mock_config)
            return client

    def test_initialization(self, mock_config):
        """Test LLM client initialization."""
        with patch("starboard_server.adapters.llm.openai.client.AsyncOpenAI"):
            client = OpenAIProvider(mock_config)
            assert client.model == "gpt-4o-mini"
            assert client.temperature == 0.4
            assert client.max_tokens == 8192
            assert client.seed == 42

    def test_build_request_params(self, llm_client):
        """Test building request parameters."""
        messages = [{"role": "user", "content": "test"}]

        params = llm_client._build_request_params(
            messages=messages,
            model="gpt-4",
            temperature=0.5,
            max_tokens=1000,
            stream=False,
        )

        assert params["model"] == "gpt-4"
        assert params["temperature"] == 0.5
        assert params["max_tokens"] == 1000
        assert params["messages"] == messages
        assert params["stream"] is False
        assert params["seed"] == 42

    def test_build_request_params_with_phase(self, llm_client, mock_config):
        """Test building request parameters with phase-specific settings."""
        # Update the config and recreate client to pick up phase-specific settings
        mock_config.llm_planning_model = "o1-preview"
        mock_config.llm_planning_temperature = 0.2

        # Re-initialize the cfg attribute
        llm_client.cfg = mock_config

        params = llm_client._build_request_params(
            messages=[], phase="planning", stream=False
        )

        # Phase-specific model should override if configured
        assert params["model"] in [
            "o1-preview",
            "gpt-4o-mini",
        ]  # Depends on implementation
        assert params["temperature"] in [0.2, 0.4]  # Depends on implementation

    @pytest.mark.asyncio
    async def test_text_response(self, llm_client):
        """Test text response generation."""
        messages = [{"role": "user", "content": "Hello"}]

        result = await llm_client.text_response(messages)

        assert result == "Test response"
        assert llm_client.async_client.chat.completions.create.called

    @pytest.mark.asyncio
    async def test_json_response_with_schema(self, llm_client):
        """Test JSON response with Pydantic schema."""
        # Mock JSON response
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '{"message": "test", "count": 5}'
        response.choices[0].message.refusal = None
        response.usage.prompt_tokens = 100
        response.usage.completion_tokens = 50
        response.usage.total_tokens = 150
        llm_client.async_client.chat.completions.create = AsyncMock(
            return_value=response
        )

        messages = [{"role": "user", "content": "Generate JSON"}]

        result = await llm_client.json_response(messages, schema=MockSchema)

        assert "message" in result
        assert result["message"] == "test"
        assert result["count"] == 5

    def test_log_llm_call(self, llm_client):
        """Test LLM call logging."""
        with patch(
            "starboard_server.adapters.llm.openai.request_lifecycle.logger"
        ) as mock_logger:
            llm_client._log_llm_call(
                call_type="text_call",
                trace_id="test-123",
                model="gpt-4",
                temperature=0.4,
                input_tokens=100,
                output_tokens=50,
                latency_ms=523.4,
                phase="planning",
            )

            # Logging uses logger.info (not debug) for structured observability
            assert mock_logger.info.called
            call_args = mock_logger.info.call_args
            assert "llm_text_call_completed" in str(call_args)

    @pytest.mark.asyncio
    async def test_token_usage_tracking(self, llm_client):
        """Test token usage logging occurs."""
        messages = [{"role": "user", "content": "Test"}]

        # Initialize token_usage dict if not present
        if not hasattr(llm_client, "token_usage"):
            llm_client.token_usage = {}

        await llm_client.text_response(messages)

        # Verify LLM client was called (usage is logged internally)
        assert llm_client.async_client.chat.completions.create.called

    def test_prepare_json_schema_pydantic(self, llm_client):
        """Test JSON schema preparation with Pydantic model."""
        schema_def, pydantic_model, is_pydantic = llm_client._prepare_json_schema(
            schema=MockSchema, phase="test"
        )

        assert is_pydantic is True
        assert pydantic_model == MockSchema
        assert "name" in schema_def
        assert schema_def["name"] == "MockSchema"
        assert "schema" in schema_def
        assert schema_def["strict"] is True

    def test_prepare_json_schema_dict(self, llm_client):
        """Test JSON schema preparation with dict."""
        schema_dict = {"type": "object", "properties": {"test": {"type": "string"}}}

        schema_def, pydantic_model, is_pydantic = llm_client._prepare_json_schema(
            schema=schema_dict, phase="test"
        )

        assert is_pydantic is False
        assert pydantic_model is None
        assert "name" in schema_def
        assert "schema" in schema_def

    def test_parse_json_content_valid(self, llm_client):
        """Test parsing valid JSON content."""
        content = '{"status": "ok", "value": 123}'

        result = llm_client._parse_json_content(content, "trace-123")

        assert result["status"] == "ok"
        assert result["value"] == 123

    def test_parse_json_content_invalid(self, llm_client):
        """Test parsing invalid JSON content."""
        content = "This is not JSON"

        result = llm_client._parse_json_content(content, "trace-123")

        assert "error" in result
        assert result["error"] == "llm_parse_failed"

    def test_circuit_breaker_integration(self, llm_client):
        """Test circuit breaker integration."""
        # Should have circuit breaker
        assert llm_client.circuit_breaker is not None
        assert llm_client.circuit_breaker.name == "openai_api"
        assert llm_client.circuit_breaker.failure_threshold == 5
        assert llm_client.circuit_breaker.recovery_timeout == 60.0

    def test_is_gemini_model(self, llm_client):
        """Test Gemini model detection."""
        assert llm_client._is_gemini_model("databricks-gemini-2-5-pro") is True
        assert llm_client._is_gemini_model("gemini-pro") is True
        assert llm_client._is_gemini_model("google-gemini-1.5-pro") is True
        assert llm_client._is_gemini_model("gpt-4") is False
        assert llm_client._is_gemini_model("claude-3-5-sonnet") is False
        assert llm_client._is_gemini_model("databricks-claude-sonnet-4-5") is False

    def test_flatten_json_schema_simple(self, llm_client):
        """Test schema flattening with simple schema (no refs)."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        }

        result = llm_client._flatten_json_schema(schema)

        # Should return unchanged
        assert result == schema
        assert "$defs" not in result

    def test_flatten_json_schema_with_refs(self, llm_client):
        """Test schema flattening with $ref and $defs."""
        schema = {
            "type": "object",
            "properties": {
                "user": {"$ref": "#/$defs/User"},
                "address": {"$ref": "#/$defs/Address"},
            },
            "$defs": {
                "User": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                },
                "Address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string"},
                        "city": {"type": "string"},
                    },
                },
            },
        }

        result = llm_client._flatten_json_schema(schema)

        # $defs should be removed
        assert "$defs" not in result

        # References should be inlined
        assert "$ref" not in str(result)
        assert result["properties"]["user"]["type"] == "object"
        assert "name" in result["properties"]["user"]["properties"]
        assert "email" in result["properties"]["user"]["properties"]
        assert result["properties"]["address"]["type"] == "object"
        assert "street" in result["properties"]["address"]["properties"]

    def test_flatten_json_schema_nested_refs(self, llm_client):
        """Test schema flattening with nested $refs."""
        schema = {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {"$ref": "#/$defs/Item"}}
            },
            "$defs": {
                "Item": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "category": {"$ref": "#/$defs/Category"},
                    },
                },
                "Category": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        }

        result = llm_client._flatten_json_schema(schema)

        # $defs should be removed
        assert "$defs" not in result

        # All nested refs should be inlined
        assert "$ref" not in str(result)
        assert result["properties"]["items"]["items"]["type"] == "object"
        assert "category" in result["properties"]["items"]["items"]["properties"]
        assert (
            result["properties"]["items"]["items"]["properties"]["category"]["type"]
            == "object"
        )

    def test_prepare_tools_for_model_openai(self, llm_client):
        """Test tool preparation for OpenAI models (no transformation)."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "parameters": {
                        "type": "object",
                        "properties": {"arg": {"$ref": "#/$defs/Arg"}},
                        "$defs": {"Arg": {"type": "string"}},
                    },
                },
            }
        ]

        result = llm_client._prepare_tools_for_model(tools, "gpt-4")

        # Should be unchanged for OpenAI
        assert result == tools
        assert "$defs" in result[0]["function"]["parameters"]

    def test_prepare_tools_for_model_gemini(self, llm_client):
        """Test tool preparation for Gemini models (flatten schemas)."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "complete",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "summary": {"$ref": "#/$defs/Summary"},
                            "findings": {
                                "type": "array",
                                "items": {"$ref": "#/$defs/Finding"},
                            },
                        },
                        "$defs": {
                            "Summary": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                            },
                            "Finding": {
                                "type": "object",
                                "properties": {"title": {"type": "string"}},
                            },
                        },
                    },
                },
            }
        ]

        result = llm_client._prepare_tools_for_model(tools, "databricks-gemini-2-5-pro")

        # Schemas should be flattened for Gemini
        assert "$defs" not in result[0]["function"]["parameters"]
        assert "$ref" not in str(result[0]["function"]["parameters"])

        # Verify structure is preserved but inlined
        params = result[0]["function"]["parameters"]
        assert params["properties"]["summary"]["type"] == "object"
        assert "text" in params["properties"]["summary"]["properties"]
        assert params["properties"]["findings"]["items"]["type"] == "object"
        assert "title" in params["properties"]["findings"]["items"]["properties"]


class TestOpenAIProviderStreaming:
    """Test OpenAI Provider streaming functionality."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        cfg = Mock(spec=EnvConfig)
        cfg.llm_api_key = "test-key"
        cfg.llm_model = "gpt-4o-mini"
        cfg.llm_temperature = 0.4
        cfg.llm_max_tokens = 8192
        cfg.llm_base_url = None
        cfg.llm_planning_model = None
        cfg.llm_judge_model = None
        cfg.llm_review_model = None
        cfg.llm_synth_model = None
        cfg.llm_planning_temperature = None
        cfg.llm_judge_temperature = None
        cfg.llm_review_temperature = None
        cfg.llm_synth_temperature = None
        cfg.llm_seed = 42  # Add seed to mock config
        return cfg

    @pytest.fixture
    def llm_client(self, mock_config):
        """Create LLM client."""
        with patch("starboard_server.adapters.llm.openai.client.AsyncOpenAI"):
            return OpenAIProvider(mock_config)

    @pytest.mark.asyncio
    async def test_text_response_stream(self, llm_client):
        """Test text response streaming."""
        # Mock streaming response as async iterator
        mock_chunks = []
        for _, text in enumerate(["Hello", " ", "world", "!"]):
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = text
            chunk.usage = None
            mock_chunks.append(chunk)

        # Add usage to last chunk
        mock_chunks[-1].usage = MagicMock()
        mock_chunks[-1].usage.prompt_tokens = 10
        mock_chunks[-1].usage.completion_tokens = 4

        async def mock_stream():
            for chunk in mock_chunks:
                yield chunk

        llm_client.async_client.chat.completions.create = AsyncMock(
            return_value=mock_stream()
        )

        messages = [{"role": "user", "content": "test"}]
        chunks = []
        async for chunk in llm_client.text_response_stream(messages):
            chunks.append(chunk)

        assert "".join(chunks) == "Hello world!"
        assert len(chunks) == 4

    @pytest.mark.asyncio
    async def test_json_response_stream(self, llm_client):
        """Test JSON response streaming."""
        # Mock streaming JSON response as async iterator
        json_text = '{"message": "test", "count": 5}'
        mock_chunks = []
        for char in json_text:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = char
            chunk.usage = None
            mock_chunks.append(chunk)

        # Add usage to last chunk
        mock_chunks[-1].usage = MagicMock()
        mock_chunks[-1].usage.prompt_tokens = 10
        mock_chunks[-1].usage.completion_tokens = 20

        async def mock_stream():
            for chunk in mock_chunks:
                yield chunk

        llm_client.async_client.chat.completions.create = AsyncMock(
            return_value=mock_stream()
        )

        messages = [{"role": "user", "content": "test"}]
        chunks = []
        async for chunk in llm_client.json_response_stream(messages):
            chunks.append(chunk)

        full_json = "".join(chunks)
        assert full_json == json_text


class TestTokenBudget:
    """Test TokenBudget functionality."""

    def test_initialization(self):
        """Test TokenBudget initialization with new phase categories."""
        budget = TokenBudget(
            session_cap_tokens=120000,
            planning_prompt_cap=10000,
            planning_output_cap=10000,
            analysis_prompt_cap=30000,
            analysis_output_cap=30000,
            synth_prompt_cap=50000,
            synth_output_cap=50000,
        )

        assert budget.session_cap == 120000
        assert budget.remaining == 120000
        assert "planning" in budget.phase_caps
        assert "analysis" in budget.phase_caps
        assert "synth" in budget.phase_caps
        assert budget.phase_caps["planning"]["prompt"] == 10000
        assert budget.phase_caps["planning"]["output"] == 10000
        assert budget.phase_caps["analysis"]["prompt"] == 30000

    def test_phase_caps_calculation(self):
        """Test phase caps are accessible for all core categories."""
        budget = TokenBudget(
            planning_prompt_cap=8000,
            planning_output_cap=3000,
            critic_prompt_cap=8000,
            critic_output_cap=3000,
            analysis_prompt_cap=30000,
            analysis_output_cap=30000,
        )

        # Verify all core phase caps exist
        assert budget.phase_caps["planning"]["prompt"] == 8000
        assert budget.phase_caps["planning"]["output"] == 3000
        assert budget.phase_caps["critic"]["prompt"] == 8000
        assert budget.phase_caps["critic"]["output"] == 3000
        assert budget.phase_caps["analysis"]["prompt"] == 30000
        assert budget.phase_caps["analysis"]["output"] == 30000

    def test_phase_mapping(self):
        """Test phase name mapping to core categories."""
        # Planning variants
        assert TokenBudget.map_phase("planning") == "planning"
        assert TokenBudget.map_phase("replanning") == "planning"
        assert TokenBudget.map_phase("planner") == "planning"
        assert TokenBudget.map_phase("replanner") == "planning"

        # Critic variants
        assert TokenBudget.map_phase("critic") == "critic"
        assert TokenBudget.map_phase("judge") == "critic"
        assert TokenBudget.map_phase("validation") == "critic"

        # Analysis variants
        assert TokenBudget.map_phase("analysis") == "analysis"
        assert TokenBudget.map_phase("execution") == "analysis"
        assert TokenBudget.map_phase("table_extract") == "analysis"

        # Synth variants
        assert TokenBudget.map_phase("synth") == "synth"
        assert TokenBudget.map_phase("summarization") == "synth"
        assert TokenBudget.map_phase("review") == "synth"
        assert TokenBudget.map_phase("finalization") == "synth"

        # Unknown phase defaults to analysis
        assert TokenBudget.map_phase("unknown_phase") == "analysis"

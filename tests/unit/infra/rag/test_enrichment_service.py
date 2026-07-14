# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for EnrichmentService.

Tests LLM-based metadata enrichment with mocked LLM client.
"""

import json

import pytest
from starboard_core.rag.models import ColumnMetadata, TableMetadata
from starboard.infra.rag.services.enrichment_service import EnrichmentService


class MockLLMClient:
    """Mock LLM client for testing that matches OpenAIProvider API."""

    def __init__(self):
        """Initialize with empty responses."""
        self.calls = []
        self.responses = []
        self.should_fail = False
        self.model = "gpt-4o-mini"
        self.temperature = 0.3
        self.max_tokens = 2000
        # Create mock async_client that matches OpenAIProvider structure
        self.async_client = MockAsyncOpenAIClient(self)

    def add_response(self, response: dict | str):
        """Add mock response."""
        if isinstance(response, dict):
            self.responses.append(json.dumps(response))
        else:
            self.responses.append(response)


class MockAsyncOpenAIClient:
    """Mock AsyncOpenAI client for testing."""

    def __init__(self, parent: MockLLMClient):
        """Initialize with reference to parent mock."""
        self.parent = parent
        self.chat = MockChat(self.parent)


class MockChat:
    """Mock chat namespace (async_client.chat)."""

    def __init__(self, parent: MockLLMClient):
        """Initialize with reference to parent mock."""
        self.completions = MockChatCompletions(parent)


class MockChatCompletions:
    """Mock chat.completions API (async_client.chat.completions)."""

    def __init__(self, parent: MockLLMClient):
        """Initialize with reference to parent mock."""
        self.parent = parent

    async def create(self, **kwargs):
        """Mock create method."""
        # Track call
        self.parent.calls.append(kwargs)

        if self.parent.should_fail:
            raise Exception("LLM call failed")

        if not self.parent.responses:
            raise ValueError("No mock responses configured")

        response_text = self.parent.responses.pop(0)

        # Return mock response object that matches OpenAI API structure
        return MockChatCompletionResponse(response_text)


class MockChatCompletionResponse:
    """Mock OpenAI chat completion response."""

    def __init__(self, content: str):
        """Initialize with response content."""
        self.choices = [MockChoice(content)]


class MockChoice:
    """Mock choice in completion response."""

    def __init__(self, content: str):
        """Initialize with message content."""
        self.message = MockMessage(content)


class MockMessage:
    """Mock message in choice."""

    def __init__(self, content: str):
        """Initialize with content."""
        self.content = content


class TestEnrichmentService:
    """Test EnrichmentService initialization."""

    def test_init(self):
        """Should initialize with client and max_concurrent."""
        client = MockLLMClient()
        service = EnrichmentService(client, max_concurrent=5)

        assert service.llm_client is client
        assert service.max_concurrent == 5

    def test_init_default_max_concurrent(self):
        """Should use default max_concurrent if not specified."""
        client = MockLLMClient()
        service = EnrichmentService(client)

        assert service.max_concurrent == 10


class TestEnrichTable:
    """Test enrich_table method."""

    @pytest.mark.asyncio
    async def test_enrich_table_basic(self):
        """Should enrich table with LLM response."""
        client = MockLLMClient()
        client.add_response(
            {
                "business_context": "Tracks billing usage",
                "grain": "One row per SKU per day",
                "common_use_cases": [
                    "Daily cost analysis",
                    "SKU utilization trends",
                ],
                "columns": [
                    {
                        "name": "usage_date",
                        "business_meaning": "Date of usage",
                        "cardinality_estimate": "high",
                    },
                    {
                        "name": "sku_name",
                        "business_meaning": None,
                        "cardinality_estimate": "low",
                    },
                ],
            }
        )

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="usage_date",
                    data_type="DATE",
                ),
                ColumnMetadata(
                    table_name="system.billing.usage",
                    column_name="sku_name",
                    data_type="STRING",
                ),
            ],
        )

        service = EnrichmentService(client)
        enriched = await service.enrich_table(table)

        # Verify enrichment
        assert enriched.business_context == "Tracks billing usage"
        assert enriched.grain == "One row per SKU per day"
        assert len(enriched.common_use_cases) == 2
        assert "Daily cost analysis" in enriched.common_use_cases

        # Verify columns
        assert enriched.columns[0].business_meaning == "Date of usage"
        assert enriched.columns[0].cardinality_estimate == "high"
        assert enriched.columns[1].business_meaning is None
        assert enriched.columns[1].cardinality_estimate == "low"

    @pytest.mark.asyncio
    async def test_enrich_table_with_markdown_wrapper(self):
        """Should handle JSON wrapped in markdown code blocks."""
        client = MockLLMClient()
        response = {
            "business_context": "Test context",
            "grain": "Test grain",
            "common_use_cases": ["Use case 1"],
            "columns": [],
        }
        client.add_response(f"```json\n{json.dumps(response)}\n```")

        table = TableMetadata(
            table_catalog="system",
            table_schema="test",
            table_name="test_table",
            table_type="TABLE",
        )

        service = EnrichmentService(client)
        enriched = await service.enrich_table(table)

        assert enriched.business_context == "Test context"

    @pytest.mark.asyncio
    async def test_enrich_table_with_code_block(self):
        """Should handle JSON wrapped in generic code blocks."""
        client = MockLLMClient()
        response = {
            "business_context": "Test context",
            "grain": "Test grain",
            "common_use_cases": [],
            "columns": [],
        }
        client.add_response(f"```\n{json.dumps(response)}\n```")

        table = TableMetadata(
            table_catalog="system",
            table_schema="test",
            table_name="test_table",
            table_type="TABLE",
        )

        service = EnrichmentService(client)
        enriched = await service.enrich_table(table)

        assert enriched.grain == "Test grain"

    @pytest.mark.asyncio
    async def test_enrich_table_with_prose(self):
        """Should extract JSON embedded in prose."""
        client = MockLLMClient()
        response_json = {
            "business_context": "Test",
            "grain": "Test",
            "common_use_cases": [],
            "columns": [],
        }
        client.add_response(
            f"Here is the analysis:\n{json.dumps(response_json)}\nHope this helps!"
        )

        table = TableMetadata(
            table_catalog="system",
            table_schema="test",
            table_name="test_table",
            table_type="TABLE",
        )

        service = EnrichmentService(client)
        enriched = await service.enrich_table(table)

        assert enriched.business_context == "Test"

    @pytest.mark.asyncio
    async def test_enrich_table_column_count_mismatch(self):
        """Should handle column count mismatch gracefully."""
        client = MockLLMClient()
        client.add_response(
            {
                "business_context": "Test",
                "grain": "Test",
                "common_use_cases": [],
                "columns": [
                    {
                        "name": "col1",
                        "business_meaning": "Test",
                        "cardinality_estimate": "high",
                    }
                ],
            }
        )

        table = TableMetadata(
            table_catalog="system",
            table_schema="test",
            table_name="test_table",
            table_type="TABLE",
            columns=[
                ColumnMetadata(
                    table_name="test.test_table",
                    column_name="col1",
                    data_type="STRING",
                ),
                ColumnMetadata(
                    table_name="test.test_table",
                    column_name="col2",
                    data_type="STRING",
                ),
            ],
        )

        service = EnrichmentService(client)
        # Should not raise, just log warning
        enriched = await service.enrich_table(table)

        # First column should be enriched
        assert enriched.columns[0].business_meaning == "Test"
        # Second column should remain unenriched
        assert enriched.columns[1].business_meaning is None

    @pytest.mark.asyncio
    async def test_enrich_table_invalid_json(self):
        """Should raise on invalid JSON response."""
        client = MockLLMClient()
        client.add_response("This is not valid JSON")

        table = TableMetadata(
            table_catalog="system",
            table_schema="test",
            table_name="test_table",
            table_type="TABLE",
        )

        service = EnrichmentService(client)

        with pytest.raises(json.JSONDecodeError):
            await service.enrich_table(table)

    @pytest.mark.asyncio
    async def test_enrich_table_llm_failure(self):
        """Should raise on LLM call failure."""
        client = MockLLMClient()
        client.should_fail = True

        table = TableMetadata(
            table_catalog="system",
            table_schema="test",
            table_name="test_table",
            table_type="TABLE",
        )

        service = EnrichmentService(client)

        with pytest.raises(Exception, match="LLM call failed"):
            await service.enrich_table(table)

    @pytest.mark.asyncio
    async def test_enrich_table_with_comment(self):
        """Should include table and column comments in prompt."""
        client = MockLLMClient()
        client.add_response(
            {
                "business_context": "Test",
                "grain": "Test",
                "common_use_cases": [],
                "columns": [],
            }
        )

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            comment="Billing usage table",
        )

        service = EnrichmentService(client)
        await service.enrich_table(table)

        # Verify comment was included in prompt
        assert len(client.calls) == 1
        # Check messages array (OpenAI API format)
        messages = client.calls[0]["messages"]
        user_message = next((m for m in messages if m["role"] == "user"), None)
        assert user_message is not None
        assert "Billing usage table" in user_message["content"]


class TestEnrichAllTables:
    """Test enrich_all_tables method."""

    @pytest.mark.asyncio
    async def test_enrich_all_tables_empty(self):
        """Should return empty list for empty input."""
        client = MockLLMClient()
        service = EnrichmentService(client)

        result = await service.enrich_all_tables([])

        assert result == []
        assert len(client.calls) == 0

    @pytest.mark.asyncio
    async def test_enrich_all_tables_single(self):
        """Should enrich single table."""
        client = MockLLMClient()
        client.add_response(
            {
                "business_context": "Test",
                "grain": "Test",
                "common_use_cases": [],
                "columns": [],
            }
        )

        tables = [
            TableMetadata(
                table_catalog="system",
                table_schema="test",
                table_name="table1",
                table_type="TABLE",
            )
        ]

        service = EnrichmentService(client)
        enriched = await service.enrich_all_tables(tables)

        assert len(enriched) == 1
        assert enriched[0].business_context == "Test"

    @pytest.mark.asyncio
    async def test_enrich_all_tables_multiple(self):
        """Should enrich multiple tables concurrently."""
        client = MockLLMClient()

        # Add responses for 3 tables
        for i in range(3):
            client.add_response(
                {
                    "business_context": f"Context {i}",
                    "grain": f"Grain {i}",
                    "common_use_cases": [],
                    "columns": [],
                }
            )

        tables = [
            TableMetadata(
                table_catalog="system",
                table_schema="test",
                table_name=f"table{i}",
                table_type="TABLE",
            )
            for i in range(3)
        ]

        service = EnrichmentService(client, max_concurrent=2)
        enriched = await service.enrich_all_tables(tables)

        assert len(enriched) == 3
        assert enriched[0].business_context == "Context 0"
        assert enriched[1].business_context == "Context 1"
        assert enriched[2].business_context == "Context 2"

    @pytest.mark.asyncio
    async def test_enrich_all_tables_partial_failure(self):
        """Should continue on failures and return partial results."""
        client = MockLLMClient()

        # First table succeeds
        client.add_response(
            {
                "business_context": "Success",
                "grain": "Test",
                "common_use_cases": [],
                "columns": [],
            }
        )

        # Second table fails (invalid JSON)
        client.add_response("Invalid JSON")

        # Third table succeeds
        client.add_response(
            {
                "business_context": "Success 2",
                "grain": "Test",
                "common_use_cases": [],
                "columns": [],
            }
        )

        tables = [
            TableMetadata(
                table_catalog="system",
                table_schema="test",
                table_name=f"table{i}",
                table_type="TABLE",
            )
            for i in range(3)
        ]

        service = EnrichmentService(client)
        enriched = await service.enrich_all_tables(tables, fail_fast=False)

        # Should return all 3 tables
        assert len(enriched) == 3

        # First and third should be enriched
        assert enriched[0].business_context == "Success"
        assert enriched[2].business_context == "Success 2"

        # Second should be unchanged (failed)
        assert enriched[1].business_context is None

    @pytest.mark.asyncio
    async def test_enrich_all_tables_fail_fast(self):
        """Should raise on first failure when fail_fast=True."""
        client = MockLLMClient()

        # First table succeeds
        client.add_response(
            {
                "business_context": "Success",
                "grain": "Test",
                "common_use_cases": [],
                "columns": [],
            }
        )

        # Second table fails
        client.add_response("Invalid JSON")

        tables = [
            TableMetadata(
                table_catalog="system",
                table_schema="test",
                table_name=f"table{i}",
                table_type="TABLE",
            )
            for i in range(2)
        ]

        service = EnrichmentService(client)

        # asyncio.TaskGroup wraps exceptions in ExceptionGroup; unwrap to check
        # the inner exception type.
        with pytest.raises(ExceptionGroup) as exc_info:
            await service.enrich_all_tables(tables, fail_fast=True)

        inner_exceptions = exc_info.value.exceptions
        assert len(inner_exceptions) == 1
        assert isinstance(inner_exceptions[0], json.JSONDecodeError)


class TestExtractJSON:
    """Test _extract_json helper method."""

    def test_extract_json_plain(self):
        """Should handle plain JSON."""
        client = MockLLMClient()
        service = EnrichmentService(client)

        json_str = '{"key": "value"}'
        result = service._extract_json(json_str)

        assert result == json_str

    def test_extract_json_markdown_json(self):
        """Should remove ```json wrappers."""
        client = MockLLMClient()
        service = EnrichmentService(client)

        json_str = '{"key": "value"}'
        wrapped = f"```json\n{json_str}\n```"
        result = service._extract_json(wrapped)

        assert result == json_str

    def test_extract_json_markdown_generic(self):
        """Should remove ``` wrappers."""
        client = MockLLMClient()
        service = EnrichmentService(client)

        json_str = '{"key": "value"}'
        wrapped = f"```\n{json_str}\n```"
        result = service._extract_json(wrapped)

        assert result == json_str

    def test_extract_json_embedded(self):
        """Should extract JSON from prose."""
        client = MockLLMClient()
        service = EnrichmentService(client)

        response = 'Here is the data: {"key": "value"} Hope this helps!'
        result = service._extract_json(response)

        assert result == '{"key": "value"}'

    def test_extract_json_empty(self):
        """Should raise on empty response."""
        client = MockLLMClient()
        service = EnrichmentService(client)

        with pytest.raises(ValueError, match="No JSON content found"):
            service._extract_json("")

    def test_extract_json_no_json(self):
        """Should return original content if no JSON braces found."""
        client = MockLLMClient()
        service = EnrichmentService(client)

        # If no JSON braces found, returns original content
        result = service._extract_json("This has no JSON at all")
        assert result == "This has no JSON at all"

        # Parsing this would fail later in enrich_table
        with pytest.raises(json.JSONDecodeError):
            json.loads(result)

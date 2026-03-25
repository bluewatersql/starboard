"""Abstract base class for LLM clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_server.adapters.llm.openai.tokens import TokenBudget

logger = get_logger(__name__)

class BaseLLMClient(ABC):
    """Abstract base class for LLM client implementations."""

    def __init__(self) -> None:
        """Initialize base LLM client."""
        self.token_usage: dict[str, int] = {}

    @abstractmethod
    async def text_response(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """
        Get a text response from the LLM.

        Args:
            messages: List of message dictionaries with role and content
            max_tokens: Optional maximum tokens for the response
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Returns:
            Response text from the LLM

        Raises:
            ValueError: If LLM returns empty response
        """
        pass

    @abstractmethod
    async def text_response_stream(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """
        Get a streaming text response from the LLM.

        Args:
            messages: List of message dictionaries with role and content
            max_tokens: Optional maximum tokens for the response
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Yields:
            Text chunks as they arrive from the LLM

        Raises:
            ValueError: If LLM returns empty response
        """
        # This yield is needed to make this an async generator for type checking
        yield  # type: ignore[misc]
        pass

    @abstractmethod
    async def json_response(
        self,
        messages: list[dict[str, Any]],
        phase: str | None = None,
        schema: dict[str, Any] | type[BaseModel] | None = None,
        budget: TokenBudget | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """
        Get a JSON response from the LLM.

        Args:
            messages: List of message dictionaries with role and content
            phase: Optional phase name for budget tracking
            schema: Optional JSON schema or Pydantic model for structured output
            budget: Optional token budget manager
            max_tokens: Optional maximum tokens for the response
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Returns:
            Parsed JSON response dictionary
        """
        pass

    @abstractmethod
    async def json_response_stream(
        self,
        messages: list[dict[str, Any]],
        phase: str | None = None,
        schema: dict[str, Any] | None = None,
        budget: TokenBudget | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """
        Get a streaming JSON response from the LLM.

        Args:
            messages: List of message dictionaries with role and content
            phase: Optional phase name for budget tracking
            schema: Optional JSON schema for structured output
            budget: Optional token budget manager
            max_tokens: Optional maximum tokens for the response
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Yields:
            JSON content chunks as they arrive from the LLM

        Note:
            The yielded chunks are raw text. The full JSON can be parsed
            after all chunks are received. For real-time JSON parsing,
            consider using a streaming JSON parser.
        """
        # This yield is needed to make this an async generator for type checking
        yield  # type: ignore[misc]
        pass

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        pass

    @abstractmethod
    async def call_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> Any:  # Returns LLMResponse (avoiding circular import)
        """
        Call LLM with tool/function calling support.

        This method enables the LLM to request tool executions as part of
        its response. The LLM can either return text content, request one
        or more tool calls, or both.

        Args:
            messages: List of message dictionaries with role and content
            tools: List of tool definitions in OpenAI format:
                [{
                    "type": "function",
                    "function": {
                        "name": "tool_name",
                        "description": "...",
                        "parameters": {"type": "object", "properties": {...}}
                    }
                }]
            max_tokens: Optional maximum tokens for the response
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Returns:
            LLMResponse object containing:
                - content: Optional text response
                - tool_calls: Tuple of ToolCall objects (empty if none)
                - usage: TokenUsage with prompt/completion/total tokens
                - finish_reason: Why the LLM stopped ("stop", "tool_calls", etc.)
                - model: Model that generated the response

        Example:
            >>> tools = [{
            ...     "type": "function",
            ...     "function": {
            ...         "name": "resolve_query",
            ...         "description": "Resolve a query from statement_id",
            ...         "parameters": {
            ...             "type": "object",
            ...             "properties": {
            ...                 "statement_id": {"type": "string"}
            ...             },
            ...             "required": ["statement_id"]
            ...         }
            ...     }
            ... }]
            >>> response = await client.call_with_tools(messages, tools)
            >>> if response.has_tool_calls():
            ...     for tool_call in response.tool_calls:
            ...         print(f"Call {tool_call.name} with {tool_call.arguments}")

        Note:
            This is a v2-only method. V1 code does not use tool calling and
            should continue using json_response() for structured outputs.
        """
        pass

    @abstractmethod
    async def call_with_tools_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:  # Yields streaming event data
        """
        Call LLM with tool/function calling support (streaming mode).

        This method enables real-time streaming of LLM responses with tool calling.
        It yields tokens as they arrive, allowing for real-time display of the
        LLM's thinking process. Tool calls are buffered until complete.

        Streaming Strategy (Smart Buffering):
        - Text tokens: Yielded immediately as they arrive (token-by-token)
        - Tool calls: Buffered until complete, then yielded as full calls
        - This provides the best user experience: real-time thinking, complete tool calls

        Args:
            messages: List of message dictionaries with role and content
            tools: List of tool definitions in OpenAI format (same as call_with_tools)
            max_tokens: Optional maximum tokens for the response
            model: Optional model override (uses config default if not set)
            temperature: Optional temperature override (uses config default if not set)

        Yields:
            Dict with one of these structures:

            1. Text delta (thinking/reasoning):
            {
                "type": "content_delta",
                "content": str,  # Text token(s)
                "finish_reason": None | str  # None during streaming, set when done
            }

            2. Tool call delta (buffered, yielded when complete):
            {
                "type": "tool_calls_delta",
                "tool_calls": [
                    {
                        "id": str,
                        "name": str,
                        "arguments": str  # Complete JSON string
                    }
                ]
            }

            3. Usage info (final event):
            {
                "type": "usage",
                "usage": {
                    "prompt_tokens": int,
                    "completion_tokens": int,
                    "total_tokens": int
                }
            }

        Example:
            >>> async for chunk in client.call_with_tools_stream(messages, tools):
            ...     if chunk["type"] == "content_delta":
            ...         print(chunk["content"], end="", flush=True)
            ...     elif chunk["type"] == "tool_calls_delta":
            ...         for call in chunk["tool_calls"]:
            ...             print(f"\\nCalling {call['name']}...")

        Note:
            - This is a v2-only streaming method
            - Use call_with_tools() for non-streaming (simpler, recommended for most cases)
            - Streaming is best for long-running LLM calls where real-time feedback is valuable
            - Tool calls are fully buffered before yielding to ensure completeness
        """
        # This yield is needed to make this an async generator for type checking
        yield  # type: ignore[misc]
        pass

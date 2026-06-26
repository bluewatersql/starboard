# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tool registry for multi-agent reasoning framework.

This module provides a registry for managing tools that can be called by the
LLM during reasoning. All tools now use the native adapter pattern.

Tool Adapter:
    - NativeToolAdapter: Wraps native tools that use **kwargs and return dicts
    - All tools implement the ToolAdapter protocol

Execution:
    All tool adapters implement async execute(), so calls are awaited directly
    on the running event loop. All registered tools are async-native; no thread
    pool is required.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from starboard_server.agents.output.llm_responses import ToolResult
from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_server.agents.tool_categories import AgentDomain

logger = get_logger(__name__)


def _json_serializer(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default.

    Args:
        obj: Object to serialize

    Returns:
        Serializable representation of obj

    Raises:
        TypeError: If object type is not serializable
    """
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def _coerce_kwargs_to_schema(
    kwargs: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Coerce kwargs values to match JSON Schema types.

    Some LLM providers (notably Databricks Foundation Model API) serialize all
    tool-call arguments as strings even when the schema specifies integer or
    boolean.  This function inspects the tool's JSON Schema and casts values
    to their declared types so downstream Python code receives proper types.

    Only handles the leaf types that are commonly mis-serialized: integer,
    number, and boolean.  Unknown or already-correct types pass through
    unchanged.
    """
    properties = schema.get("properties", {})
    if not properties:
        return kwargs

    coerced = dict(kwargs)
    for key, value in coerced.items():
        prop_schema = properties.get(key)
        if prop_schema is None:
            continue

        declared_type = prop_schema.get("type")

        if declared_type == "integer" and not isinstance(value, int):
            with contextlib.suppress(ValueError, TypeError):
                coerced[key] = int(value)  # leave as-is on failure; tool will raise
        elif declared_type == "number" and not isinstance(value, (int, float)):
            with contextlib.suppress(ValueError, TypeError):
                coerced[key] = float(value)
        elif declared_type == "boolean" and not isinstance(value, bool):
            if isinstance(value, str):
                coerced[key] = value.strip().lower() in ("true", "1", "yes")
            else:
                coerced[key] = bool(value)

    return coerced


@dataclass(frozen=True)
class ToolMetadata:
    """
    Metadata describing a tool for LLM function calling.

    This structure maps directly to OpenAI's function calling schema format,
    making it easy to generate tool definitions for the LLM.

    Attributes:
        name: Unique tool identifier (e.g., "resolve_query")
        description: Clear description of what the tool does
        parameters: JSON schema describing tool parameters

    Example:
        >>> metadata = ToolMetadata(
        ...     name="resolve_query",
        ...     description="Resolve a SQL query from statement_id or raw SQL",
        ...     parameters={
        ...         "type": "object",
        ...         "properties": {
        ...             "target": {
        ...                 "type": "string",
        ...                 "description": "Statement ID or raw SQL query"
        ...             }
        ...         },
        ...         "required": ["target"]
        ...     }
        ... )
    """

    name: str
    description: str
    parameters: dict[str, Any]

    def __post_init__(self) -> None:
        """Validate metadata."""
        if not self.name:
            raise ValueError("Tool name cannot be empty")

        if not self.description:
            raise ValueError("Tool description cannot be empty")

        if not isinstance(self.parameters, dict):
            raise ValueError("Tool parameters must be a dictionary")

        # Validate parameters has required fields
        if "type" not in self.parameters:
            raise ValueError("Tool parameters must have 'type' field")

        if (
            self.parameters.get("type") == "object"
            and "properties" not in self.parameters
        ):
            raise ValueError(
                "Tool parameters with type 'object' must have 'properties'"
            )

    def to_openai_schema(self) -> dict[str, Any]:
        """
        Convert metadata to OpenAI function calling schema.

        Returns:
            Dictionary in OpenAI tool schema format

        Example:
            >>> metadata = ToolMetadata(...)
            >>> schema = metadata.to_openai_schema()
            >>> # Returns:
            >>> {
            ...     "type": "function",
            ...     "function": {
            ...         "name": "resolve_query",
            ...         "description": "...",
            ...         "parameters": {...}
            ...     }
            ... }
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class NativeToolAdapter:
    """
    Adapter for native tools that return dicts directly.

    Native tools use the clean signature: async def tool(**kwargs) -> dict[str, Any]
    This adapter simply forwards arguments and validates the return type.

    Attributes:
        tool_instance: Instance of tool class (e.g., QueryTools)
        method_name: Name of method to call (e.g., "resolve_query")
        metadata: Tool metadata for LLM

    Example:
        >>> query_tools = QueryTools(api, context, events)
        >>> adapter = NativeToolAdapter(
        ...     tool_instance=query_tools,
        ...     method_name="resolve_query",
        ...     metadata=ToolMetadata(...)
        ... )
        >>> result = await adapter.execute(target="SELECT * FROM table")
        >>> # Returns: {"source": "raw_sql", "statement_id": None, ...}
    """

    def __init__(
        self,
        tool_instance: Any,
        method_name: str,
        metadata: ToolMetadata,
    ):
        """
        Initialize native tool adapter.

        Args:
            tool_instance: Instance of tool class
            method_name: Name of method to call on the instance
            metadata: Tool metadata

        Raises:
            ValueError: If method doesn't exist or isn't callable
        """
        self.tool_instance = tool_instance
        self.method_name = method_name
        self.metadata = metadata

        # Verify method exists and is callable in a single lookup
        method = getattr(tool_instance, method_name, None)
        if method is None:
            raise ValueError(
                f"Method '{method_name}' not found on {type(tool_instance).__name__}"
            )
        if not callable(method):
            raise ValueError(
                f"'{method_name}' on {type(tool_instance).__name__} is not callable"
            )

        self.method = method

    async def execute(self, **kwargs) -> dict[str, Any]:
        """
        Execute the native tool with provided arguments.

        Args:
            **kwargs: Tool arguments (e.g., target="abc123")

        Returns:
            Dict containing the tool result

        Raises:
            TypeError: If tool returns non-dict
            Exception: If tool execution fails (propagated to caller)

        Example:
            >>> result = await adapter.execute(sql_text="SELECT 1")
            >>> # Returns: {"plan_text": "...", "facts": {...}}
        """
        # Coerce string-typed values to match the declared JSON Schema types.
        # Some LLM providers emit all tool-call args as strings.
        kwargs = _coerce_kwargs_to_schema(kwargs, self.metadata.parameters)

        # Strip unknown kwargs that aren't in the tool's JSON Schema.
        # MCP clients sometimes inject extra parameters (e.g. wrapping
        # arguments under a "kwargs" key) that the tool method doesn't accept.
        known_keys = set(self.metadata.parameters.get("properties", {}).keys())
        if known_keys:
            kwargs = {k: v for k, v in kwargs.items() if k in known_keys}

        logger.debug(
            f"Executing native tool: {self.method_name}",
            extra={"kwargs": kwargs},
        )

        # Execute native tool (let exceptions propagate)
        result = await self.method(**kwargs)

        # Validate return type
        if not isinstance(result, dict):
            raise TypeError(
                f"Tool {self.method_name} must return dict, got {type(result).__name__}"
            )

        return result


class ToolAdapter(Protocol):
    """
    Protocol defining the interface for tool adapters.

    All tool adapters (NativeToolAdapter) must implement this protocol
    to be registered in the ToolRegistry.

    Attributes:
        metadata: Tool metadata for LLM function calling

    Methods:
        execute: Execute the tool with provided arguments
    """

    metadata: ToolMetadata

    async def execute(self, **kwargs) -> dict[str, Any]:
        """
        Execute the tool with provided arguments.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            Dict containing tool results

        Raises:
            Exception: If tool execution fails
        """
        ...


class ToolRegistry:
    """
    Registry for managing tools available to the reasoning agent.

    The registry stores tool metadata and callable adapters, making them
    available for the LLM to discover and execute during reasoning.

    Execution:
        All tool adapters implement async execute(), so calls are awaited
        directly on the running event loop. No thread pool is required because
        all registered tools are async-native.

    Example:
        >>> # Create registry
        >>> registry = ToolRegistry()
        >>>
        >>> # Register tools
        >>> query_tools = QueryTools(api, context, events)
        >>> adapter = NativeToolAdapter(query_tools, "resolve_query", metadata)
        >>> registry.register("resolve_query", adapter)
        >>>
        >>> # Get tool schemas for LLM
        >>> schemas = registry.get_tool_schemas()
        >>>
        >>> # Execute tool
        >>> result = await registry.execute_tool("resolve_query", target="abc123")
    """

    def __init__(self):
        """Initialize empty tool registry."""
        self._tools: dict[str, ToolAdapter] = {}
        logger.debug("ToolRegistry initialized")

    def register(
        self,
        tool_name: str,
        adapter: ToolAdapter,
    ) -> None:
        """
        Register a tool with the registry.

        Args:
            tool_name: Unique tool identifier
            adapter: Tool adapter (NativeToolAdapter implementing ToolAdapter protocol)

        Raises:
            ValueError: If tool already registered

        Example:
            >>> adapter = NativeToolAdapter(query_tools, "resolve_query", metadata)
            >>> registry.register("resolve_query", adapter)
        """
        if tool_name in self._tools:
            raise ValueError(f"Tool '{tool_name}' is already registered")

        self._tools[tool_name] = adapter
        logger.debug(
            f"Registered tool: {tool_name}",
            extra={"description": adapter.metadata.description},
        )

    def get_tool(self, tool_name: str) -> ToolAdapter | None:
        """
        Get a registered tool adapter.

        Args:
            tool_name: Tool identifier

        Returns:
            Tool adapter or None if not found

        Example:
            >>> adapter = registry.get_tool("resolve_query")
            >>> if adapter:
            ...     result = await adapter.execute(target="abc")
        """
        return self._tools.get(tool_name)

    def list_tools(self) -> list[str]:
        """
        List all registered tool names.

        Returns:
            List of tool names

        Example:
            >>> tools = registry.list_tools()
            >>> print(tools)
            ['resolve_query', 'analyze_query_plan', 'get_table_metadata']
        """
        return list(self._tools.keys())

    def filter_by_domain(
        self,
        domain: str | AgentDomain,
        offline_mode: bool = False,
    ) -> ToolRegistry:
        """Create a new registry with tools filtered by domain.

        Implements tool filtering for the multi-agent system, ensuring each
        domain agent only has access to its relevant tools. Returns a new
        registry without modifying the original (immutable pattern).

        Args:
            domain: Agent domain (router, query, job, table, compute, diagnostic)
            offline_mode: If True, filter out tools requiring Databricks API calls

        Returns:
            New ToolRegistry containing only tools allowed for the domain

        Raises:
            ValueError: If domain is not recognized
        """
        from starboard_server.agents.tool_categories import (
            AgentDomain,
            get_tools_for_domain,
        )

        # Create new empty registry
        filtered_registry = ToolRegistry()

        # Get allowed tools for this domain (with offline filtering if enabled)
        all_tool_names = self.list_tools()
        allowed_tools = get_tools_for_domain(
            cast(AgentDomain, domain), all_tool_names, offline_mode=offline_mode
        )

        # Copy only allowed tools to new registry
        for tool_name in allowed_tools:
            if tool_name in self._tools:
                filtered_registry._tools[tool_name] = self._tools[tool_name]

        logger.debug(
            f"Filtered registry for domain '{domain}'",
            extra={
                "domain": domain,
                "offline_mode": offline_mode,
                "filtered_count": len(filtered_registry._tools),
                "original_count": len(self._tools),
                "filtered_tools": list(filtered_registry._tools.keys()),
            },
        )

        return filtered_registry

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """
        Get OpenAI-compatible schemas for all registered tools.

        Returns:
            List of tool schema dictionaries

        Example:
            >>> schemas = registry.get_tool_schemas()
            >>> # Pass to LLM: client.call_with_tools(messages, schemas)
        """
        return [adapter.metadata.to_openai_schema() for adapter in self._tools.values()]

    async def execute_tool(
        self,
        tool_name: str,
        agent_context: dict[str, Any] | None = None,  # noqa: ARG002
        **kwargs,  # noqa: ARG002
    ) -> ToolResult:
        """Execute a registered tool and return structured result.

        All tool adapters implement async execute(), so calls are awaited
        directly on the running event loop.

        Args:
            tool_name: Tool to execute
            agent_context: Optional agent context (unused)
            **kwargs: Tool arguments

        Returns:
            ToolResult with content or error
        """
        adapter = self.get_tool(tool_name)

        if not adapter:
            error_msg = f"Tool '{tool_name}' not found in registry"
            logger.error(error_msg, extra={"available_tools": self.list_tools()})
            return ToolResult(
                tool_call_id="",  # Will be set by caller
                tool_name=tool_name,
                content="",
                error=error_msg,
            )

        try:
            # All tool adapters are async — await directly
            logger.debug("tool_execution_starting", tool_name=tool_name)
            result_dict = await adapter.execute(**kwargs)
            logger.debug("tool_execution_completed", tool_name=tool_name)

            # Convert dict to JSON string for LLM
            content = json.dumps(result_dict, indent=2, default=_json_serializer)

            # Log what's being sent to LLM (for debugging)
            logger.debug(
                "tool_result_for_llm",
                extra={
                    "tool_name": tool_name,
                    "result_size_bytes": len(content),
                    "result_size_kb": round(len(content) / 1024, 2),
                    "result_preview": (
                        content[:500] + "..." if len(content) > 500 else content
                    ),
                    "result_keys": (
                        list(result_dict.keys())
                        if isinstance(result_dict, dict)
                        else None
                    ),
                    # For analytics queries, extract key metrics
                    **self._extract_analytics_metrics(result_dict),
                },
            )

            # Truncate large results to prevent LLM errors
            MAX_CONTENT_SIZE = 100_000
            if len(content) > MAX_CONTENT_SIZE:
                truncated_content = content[:MAX_CONTENT_SIZE]
                last_newline = truncated_content.rfind("\n")
                if last_newline > 0:
                    truncated_content = truncated_content[:last_newline]

                content = (
                    truncated_content
                    + f"\n\n... [TRUNCATED: Result too large ({len(content):,} chars). "
                    f"Showing first {len(truncated_content):,} chars.]"
                )

                logger.warning(
                    "tool_result_truncated",
                    tool_name=tool_name,
                    original_size=len(json.dumps(result_dict, indent=2)),
                    truncated_size=len(content),
                )

            # For complete tool, preserve raw result dict for final output extraction
            # (truncated content may not be valid JSON)
            raw_result = result_dict if tool_name == "complete" else None

            return ToolResult(
                tool_call_id="",  # Will be set by caller
                tool_name=tool_name,
                content=content,
                raw_result=raw_result,
            )

        except (ImportError, AttributeError, TypeError) as e:
            logger.error(
                f"Tool execution failed: {tool_name}",
                extra={"error": str(e), "kwargs": kwargs},
                exc_info=True,
            )
            error_msg = f"Tool execution failed: {str(e)}"
            return ToolResult(
                tool_call_id="",  # Will be set by caller
                tool_name=tool_name,
                content="",  # Empty content is OK when error is present
                error=error_msg,
            )

    def _extract_analytics_metrics(self, result_dict: dict[str, Any]) -> dict[str, Any]:
        """Extract key metrics from analytics query results for logging.

        Args:
            result_dict: Tool result dictionary

        Returns:
            Dictionary with extracted metrics for logging
        """
        if not isinstance(result_dict, dict):
            return {}

        metrics = {}

        # Extract row count metrics
        for key in ("row_count", "showing_rows", "truncated"):
            if key in result_dict:
                metrics[f"analytics_{key}"] = result_dict[key]

        # Extract cost/spend summaries
        if isinstance(result_dict.get("summary"), dict):
            for key, value in result_dict["summary"].items():
                if any(term in key.lower() for term in ("cost", "price", "spend")):
                    metrics[f"analytics_summary_{key}"] = value

        # Extract results array metrics
        results = result_dict.get("results")
        if isinstance(results, list) and results:
            metrics["analytics_results_count"] = len(results)
            if isinstance(results[0], dict):
                metrics["analytics_first_result_keys"] = list(results[0].keys())
                for key, value in results[0].items():
                    if "cost" in key.lower() and isinstance(value, (int, float)):
                        metrics[f"analytics_first_{key}"] = value

        return metrics

    def __len__(self) -> int:
        """Return number of registered tools."""
        return len(self._tools)

    def __contains__(self, tool_name: str) -> bool:
        """Check if tool is registered."""
        return tool_name in self._tools

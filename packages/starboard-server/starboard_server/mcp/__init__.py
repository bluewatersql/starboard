# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Starboard MCP Server — Model Context Protocol integration.

Exposes Starboard's tools, agents, resources, and prompts over the
MCP protocol with stdio and Streamable HTTP transports.
"""

from starboard_server.mcp.agent_bridge import (
    MCPAgentExecutor,
    MCPProgressBridge,
    generate_conversation_id,
)
from starboard_server.mcp.config import (
    CostAttribution,
    MCPServerConfig,
    WorkspaceProfile,
)
from starboard_server.mcp.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ExecutionError,
    RateLimitError,
)
from starboard_server.mcp.models import (
    MCPAgentResponse,
    MCPError,
    MCPResponseMetadata,
    MCPToolResponse,
)
from starboard_server.mcp.observability import MCPCostTag, MCPSpan, TokenBudgetTracker
from starboard_server.mcp.prompt_bridge import PROMPT_METADATA, build_prompt_messages
from starboard_server.mcp.result_formatter import format_tool_result
from starboard_server.mcp.server import StarboardMCPServer
from starboard_server.mcp.tool_bridge import PHASE_A_TOOLS, get_mcp_tools

__all__ = [
    "AuthenticationError",
    "ConfigurationError",
    "CostAttribution",
    "ExecutionError",
    "MCPAgentExecutor",
    "MCPAgentResponse",
    "MCPCostTag",
    "MCPError",
    "MCPProgressBridge",
    "MCPResponseMetadata",
    "MCPServerConfig",
    "MCPSpan",
    "MCPToolResponse",
    "PHASE_A_TOOLS",
    "PROMPT_METADATA",
    "RateLimitError",
    "StarboardMCPServer",
    "TokenBudgetTracker",
    "WorkspaceProfile",
    "build_prompt_messages",
    "format_tool_result",
    "generate_conversation_id",
    "get_mcp_tools",
]

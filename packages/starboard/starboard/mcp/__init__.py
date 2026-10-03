# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Starboard MCP Server — Model Context Protocol integration.

Exposes Starboard's tools, agents, resources, and prompts over the
MCP protocol with stdio and Streamable HTTP transports.
"""

from starboard.mcp.agent_bridge import (
    MCPAgentExecutor,
    MCPProgressBridge,
    generate_conversation_id,
)
from starboard.mcp.config import (
    CostAttribution,
    MCPServerConfig,
    WorkspaceProfile,
)
from starboard.mcp.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ExecutionError,
    RateLimitError,
)
from starboard.mcp.models import (
    MCPAgentResponse,
    MCPError,
    MCPResponseMetadata,
    MCPToolResponse,
)
from starboard.mcp.observability import MCPCostTag, MCPSpan, TokenBudgetTracker
from starboard.mcp.prompt_bridge import PROMPT_METADATA, build_prompt_messages
from starboard.mcp.result_formatter import format_tool_result
from starboard.mcp.server import StarboardMCPServer
from starboard.mcp.tool_bridge import PHASE_A_TOOLS, get_mcp_tools

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

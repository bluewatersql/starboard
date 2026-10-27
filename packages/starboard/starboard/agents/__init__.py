# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Multi-Agent System implementation.

This package contains the multi-agent architecture with domain-specialized
agents using dynamic tool selection and step-by-step reasoning.

Key Components:
    - MultiAgentConversationManager: Main orchestrator coordinating agents
    - DomainAgent: Base agent with dynamic reasoning and tool selection
    - IntentRouter: Routes requests to appropriate domain specialist
    - AgentFactory: Creates configured domain agents (Query/Job/Table/Diagnostic)
    - ToolRegistry: Maps LLM tool calls to task implementations
    - SharedAgentContext: Context shared across agent transitions
    - AgentConfig: Configuration for agent behavior

Domain Agents:
    - QueryAgent: SQL query optimization and analysis
    - JobAgent: Databricks job performance analysis
    - TableAgent: Schema and data lineage operations
    - DiagnosticAgent: Troubleshooting and debugging

Architecture:
    - domain/ package: Domain agent components
    - conversation/ package: Multi-agent conversation management

Example:
    >>> from starboard.agents.domain import DomainAgent
    >>> from starboard.agents import AgentConfig
    >>> from starboard.adapters.llm.openai.client import OpenAIClient
    >>>
    >>> config = AgentConfig(model="gpt-4o-mini", max_tokens=80_000)
    >>> llm_client = OpenAIClient(...)
    >>> tool_registry = ToolRegistry(...)
    >>>
    >>> agent = DomainAgent(
    ...     llm_client=llm_client,
    ...     tool_registry=tool_registry,
    ...     config=config,
    ... )
    >>>
    >>> async for event in agent.run_stream(
    ...     user_input="statement_id:abc123",
    ...     mode=OptimizationMode.ONLINE,
    ... ):
    ...     print(event.type)
"""

from starboard.agents.clarification.clarification_handler import (
    ClarificationHandler,
    DomainOption,
)
from starboard.agents.clarification.clarification_response_parser import (
    ClarificationResponseParser,
)
from starboard.agents.config.agent_config import AgentConfig
from starboard.agents.config.model_generator import (
    DomainModelConfigGenerator,
)
from starboard.agents.conversation import MultiAgentConversationManager
from starboard.agents.domain import DomainAgent
from starboard.agents.events import (
    ErrorEvent,
    EventType,
    StepCompleteEvent,
    StreamEvent,
    StreamingEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolProgressEvent,
    ToolStartEvent,
    create_error_event,
    create_step_complete_event,
    create_thinking_event,
    create_tool_end_event,
    create_tool_start_event,
)
from starboard.agents.observability.metrics import (
    AgentMetrics,
    MultiAgentMetrics,
    RoutingMetrics,
    SpecialistMetrics,
    StepMetrics,
    ToolMetrics,
    TransitionMetrics,
    get_metrics,
)
from starboard.agents.observability.sse_broadcaster import SSEBroadcaster
from starboard.agents.output.history_formatter import HistoryFormatter
from starboard.agents.output.llm_responses import (
    LLMResponse,
    TokenUsage,
    ToolCall,
    ToolResult,
)
from starboard.agents.routing.specialist_context_builder import (
    SpecialistContextBuilder,
)
from starboard.agents.state.agent_state import (
    AgentOutput,
    AgentState,
    Message,
    WorkingMemory,
)
from starboard.agents.state.context_manager import ContextManager
from starboard.agents.state.event_context_updater import EventContextUpdater
from starboard.agents.tools import (
    ToolMetadata,
    ToolRegistry,
    create_tool_registry,
)

__all__ = [
    "AgentConfig",
    # Metrics
    "AgentMetrics",
    "MultiAgentMetrics",
    "RoutingMetrics",
    "SpecialistMetrics",
    "StepMetrics",
    "ToolMetrics",
    "TransitionMetrics",
    "get_metrics",
    # Agents
    "DomainAgent",
    "MultiAgentConversationManager",
    "AgentState",
    "AgentOutput",
    "Message",
    "WorkingMemory",
    "LLMResponse",
    "ToolCall",
    "ToolResult",
    "TokenUsage",
    "ToolMetadata",
    "ToolRegistry",
    "create_tool_registry",
    # Streaming events
    "EventType",
    "StreamingEvent",
    "ThinkingEvent",
    "ToolStartEvent",
    "ToolProgressEvent",
    "ToolEndEvent",
    "StepCompleteEvent",
    "ErrorEvent",
    "StreamEvent",
    "create_thinking_event",
    "create_tool_start_event",
    "create_tool_end_event",
    "create_step_complete_event",
    "create_error_event",
    # Clarification
    "ClarificationHandler",
    "ClarificationResponseParser",
    "DomainOption",
    # Context Management
    "ContextManager",
    "EventContextUpdater",
    # Formatting & Config Generation
    "HistoryFormatter",
    "DomainModelConfigGenerator",
    # SSE Broadcasting
    "SSEBroadcaster",
    # Routing Support
    "SpecialistContextBuilder",
]

__version__ = "2.0.0"

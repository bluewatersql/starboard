---
title: "Package: starboard"
description: Documentation for the starboard package.
last_reviewed: 2026-07-12
status: current
---

# starboard

> **Docs** > **Packages** > **starboard**

The primary backend package providing the multi-agent system, MCP server, CLI, and tool implementations.

---

## Overview

`starboard` is the heart of the Starboard AI Agent. It contains:

- **Multi-Agent System**: 8 domain agents + Intent Router with continuous reasoning
- **MCP Server**: stdio + streamable-HTTP transports (`starboard-mcp` entry point)
- **CLI**: flag-based runner + subcommands `review`, `genie ask`, `auth` (`starboard`)
- **Workload Review**: `WorkloadReviewService` + validator council over public `system.*`
- **Public API facade**: `starboard/__init__.py` lazily re-exports the curated API the CLI composes
- **Tool System**: three-layer tools (Domain, Service, Adapter) + `starboard.mcp_tools` plugin seam
- **Ports + internal-data gate**: public port adapters + `starboard.port_adapters` contract
- **State Management**: default `memory`; opt-in `sqlite`/`postgres`/`lakebase`/`uc`
- **LLM Adapters**: Multi-provider support (OpenAI, Azure, Databricks Model Serving)

## Install

```bash
pip install starboard
```

The default install pulls **no** store/vector drivers; add them via extras
(`starboard[sqlite]`, `[postgres]`, `[redis]`, `[vectorsearch]`, …).

## Entry Points

| Command | Description |
|---------|-------------|
| `starboard` | CLI — flag-based goal runner + `review` / `genie ask` / `auth` |
| `starboard-mcp` | MCP server — stdio transport for Claude Code / Cursor / Codex |
| `starboard-server` | Minimal FastAPI process — health probes + optional `/mcp` mount |

## Public API facade

```python
from starboard import (
    get_logger, describe_auth, resolve_workspace_client, create_llm_client,
    AnalyticsSqlAdapter, LLMSQLGenerator, CouncilConfig, build_council,
    WorkloadReviewService,
)
```

`import starboard` performs no heavy work — symbols resolve lazily (PEP 562), so
`openai` / `databricks.sdk` / `fastapi` are not imported until first use. The CLI must
compose through this facade, not `starboard.infra`/`adapters`/`tools` (enforced by
`tests/architecture/test_package_boundaries.py`).

## Key Components

### Domain Agents

| Agent | Domain | Purpose | Tools |
|-------|--------|---------|-------|
| **Query** | `query` | SQL optimization, execution plan analysis | 8 |
| **Job** | `job` | Job performance, Spark tuning, code quality | 14 |
| **UC** | `uc` | Unity Catalog governance, lineage, schema drift | 18 |
| **Cluster** | `cluster` | Cluster configuration, health, utilization | 8 |
| **Analytics** | `analytics` | FinOps cost analysis via agentic RAG | 6 |
| **Warehouse** | `warehouse` | SQL warehouse portfolio optimization, SLO | 11 |
| **Discovery** | `discovery` | Workspace-wide health assessment | 6 |
| **Diagnostic** | `diagnostic` | Cross-domain troubleshooting | ALL |
| **Intent Router** | `router` | Request classification and routing | 3 |

### Architecture

```
starboard/
    __init__.py          # Public API facade (PEP 562 lazy re-exports)
    main.py              # Minimal FastAPI app (health + optional /mcp)
    mcp/                 # MCP server (stdio + streamable-http)
    cli/                 # CLI entry point + subcommands (review, genie, auth)
    agents/              # Multi-agent system
        conversation/    # Conversation manager (orchestrator)
        domain/          # Base domain agent
        routing/         # Intent router and routing models
        tools/           # Tool registry (thread-isolated execution)
        tool_categories.py  # Domain-to-tool mappings
    tools/               # Tool implementations (3-layer)
        domain/          # Pure business logic (no I/O)
        services/        # Orchestration + WorkloadReviewService, validator_council
        adapters/        # I/O adapters (Databricks API)
        plugins.py       # ToolPlugin contract (starboard.mcp_tools seam)
    ports/               # Port registry + entry-point discovery (the gate)
    discovery/           # Query-pack executor + registry
    prompts/             # Domain-specific system prompts
    infra/               # Config, logging, DI, observability, auth
    adapters/            # External adapters (LLM, Databricks, ports, state)
```

### Technology Stack

- **MCP**: stdio + streamable-HTTP transports (Model Context Protocol)
- **CLI**: argparse + rich output
- **Agents**: LLM-driven continuous reasoning loops
- **LLM**: Multi-provider (OpenAI, Azure, Databricks Model Serving)
- **Events**: typed in-process event stream (not an HTTP SSE endpoint)
- **State**: memory (default) / SQLite / PostgreSQL / Lakebase / UC-native (opt-in)
- **Observability**: Structured logging, distributed tracing

## Design Principles

1. **Async-first**: All I/O is non-blocking
2. **Agent-centric**: Domain specialists, not monolith
3. **Observable**: Comprehensive logging and tracing
4. **Resilient**: Circuit breakers, retries, graceful degradation

## Scale

- **Source Files**: 400+
- **Test Files**: 100+
- **Lines of Code**: ~50,000
- **Tools**: 57 across 9 categories

## Quick Links

- [Package README](https://github.com/starboard-ai/job-agent/blob/main/packages/starboard/README.md) -- Installation and quick start
- [System Architecture](../../architecture/SYSTEM_ARCHITECTURE.md) -- Full system design
- [Agent Documentation](../../agents/README.md) -- All 8 domain agents
- [Tool Catalog](../../tools/TOOL_CATALOG.md) -- Complete tool reference
- [Configuration Guide](../../CONFIGURATION.md) -- Environment variables

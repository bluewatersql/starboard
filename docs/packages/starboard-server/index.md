---
title: "Package: starboard-server"
description: Documentation for the starboard-server package.
last_reviewed: 2026-03-24
status: current
---

# starboard-server

> **Docs** > **Packages** > **starboard-server**

The core backend package providing the multi-agent system, FastAPI API, and tool implementations.

---

## Overview

`starboard-server` is the heart of the Starboard AI Agent. It contains:

- **Multi-Agent System**: 8 domain agents + Intent Router with continuous reasoning
- **FastAPI Backend**: REST API with SSE streaming (22 endpoints)
- **Tool System**: 45+ tools in three-layer architecture (Domain, Service, Adapter)
- **State Management**: Pluggable backends (SQLite, Postgres, Lakebase, Redis, InMemory)
- **LLM Adapters**: Multi-provider support (OpenAI, Azure, Databricks Model Serving)

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
starboard_server/
    api/                 # FastAPI routes and SSE streaming
    agents/              # Multi-agent system
        conversation/    # Conversation manager (orchestrator)
        domain/          # Base domain agent
        routing/         # Intent router and routing models
        tools/           # Tool registry and filtering
        tool_categories.py  # Domain-to-tool mappings
    tools/               # Tool implementations (3-layer)
        domain/          # Pure business logic (no I/O)
        services/        # Orchestration layer
        adapters/        # I/O adapters (Databricks API)
    prompts/             # Domain-specific system prompts
    infra/               # Config, logging, DI, observability
    adapters/            # External service adapters (LLM, Databricks)
    services/            # Business services
```

### Technology Stack

- **Framework**: FastAPI (async-first)
- **Agents**: LLM-driven continuous reasoning loops
- **LLM**: Multi-provider (OpenAI, Azure, Databricks Model Serving)
- **Streaming**: Server-Sent Events (SSE)
- **State**: SQLite / PostgreSQL / Databricks Lakebase / Redis
- **Observability**: Structured logging, distributed tracing

## Design Principles

1. **Async-first**: All I/O is non-blocking
2. **Event-driven**: SSE streaming for real-time UX
3. **Agent-centric**: Domain specialists, not monolith
4. **Observable**: Comprehensive logging and tracing
5. **Resilient**: Circuit breakers, retries, graceful degradation

## Scale

- **Source Files**: 400+
- **Test Files**: 100+
- **Lines of Code**: ~50,000
- **Tools**: 45+ across 9 categories

## Quick Links

- [Package README](../../../packages/starboard-server/README.md) -- Installation and quick start
- [System Architecture](../../architecture/SYSTEM_ARCHITECTURE.md) -- Full system design
- [Agent Documentation](../../agents/README.md) -- All 8 domain agents
- [Tool Catalog](../../tools/TOOL_CATALOG.md) -- Complete tool reference
- [API Reference](../../api/API_REFERENCE.md) -- REST API specification
- [Configuration Guide](../../CONFIGURATION.md) -- Environment variables

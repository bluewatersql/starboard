# Starboard AI Agent Documentation

Welcome to the Starboard AI Agent documentation — an AI-powered analysis and optimization platform for Databricks workloads.

## Overview

Starboard uses **8 domain-specialized AI agents** that reason step-by-step, dynamically select from **45+ tools**, and stream results in real time. Ask questions in natural language and get actionable recommendations for SQL queries, jobs, pipelines, costs, and infrastructure.

```mermaid
%%{init: {'theme':'default', 'themeVariables': {'fontSize':'16px'}}}%%

graph TB
    User[User/Browser] -->|HTTP/SSE| API[FastAPI Backend]
    API -->|Classifies| Router[Intent Router]

    Router -->|Query| QueryAgent[Query Agent]
    Router -->|Job| JobAgent[Job Agent]
    Router -->|UC| UCAgent[UC Agent]
    Router -->|Analytics| AnalyticsAgent[Analytics Agent]
    Router -->|Warehouse| WarehouseAgent[Warehouse Agent]
    Router -->|Diagnostic| DiagAgent[Diagnostic Agent]

    QueryAgent -->|Executes| Tools[Tool System<br/>45+ Tools]
    JobAgent -->|Executes| Tools
    UCAgent -->|Executes| Tools
    AnalyticsAgent -->|Executes| Tools
    WarehouseAgent -->|Executes| Tools
    DiagAgent -->|Executes| Tools

    Tools -->|Fetches| Databricks[Databricks API]

    QueryAgent -->|Reasoning| LLMProvider[LLM Provider<br/>OpenAI/Azure]
    JobAgent -->|Reasoning| LLMProvider
    UCAgent -->|Reasoning| LLMProvider
    AnalyticsAgent -->|Reasoning| LLMProvider
    WarehouseAgent -->|Reasoning| LLMProvider
    DiagAgent -->|Reasoning| LLMProvider

    API -->|Persists| StateStore[(State Store<br/>SQLite/Postgres/Lakebase)]
    API -->|Caches| Cache[(Redis Cache)]

    style User fill:#10b981,color:#fff
    style API fill:#4f46e5,color:#fff
    style Router fill:#7c3aed,color:#fff
    style QueryAgent fill:#06b6d4,color:#fff
    style JobAgent fill:#06b6d4,color:#fff
    style UCAgent fill:#06b6d4,color:#fff
    style AnalyticsAgent fill:#06b6d4,color:#fff
    style WarehouseAgent fill:#06b6d4,color:#fff
    style DiagAgent fill:#06b6d4,color:#fff
    style Tools fill:#f59e0b,color:#fff
    style Databricks fill:#ff6b6b,color:#fff
    style LLMProvider fill:#ff6b6b,color:#fff
```

*High-level system architecture showing the main components and their interactions*

---

## Start Here

| I want to... | Go to |
|--------------|-------|
| **Understand what Starboard does** | [What is Starboard?](overview/what-is-starboard.md) |
| **Get running in 5 minutes** | [Quickstart](QUICKSTART.md) |
| **Learn the web interface** | [Web UI Guide](user-guide/web-ui.md) |
| **Use the CLI** | [CLI Reference](user-guide/cli.md) |
| **Optimize a slow query** | [Query Optimization Workflow](user-guide/workflows/query-optimization.md) |
| **Debug a failing job** | [Job Debugging Workflow](user-guide/workflows/job-debugging.md) |
| **Analyze costs** | [Cost Analysis Workflow](user-guide/workflows/cost-analysis.md) |
| **Integrate via REST API** | [API Quickstart](integration/api-quickstart.md) |
| **Deploy to production** | [Deployment Guide](DEPLOYMENT.md) |
| **Contribute code** | [Developer Getting Started](guides/GETTING_STARTED.md) |

---

## Documentation Sections

### [Overview](overview/what-is-starboard.md)
Product introduction, agent catalog, quickstart, and configuration.

### [User Guide](user-guide/web-ui.md)
Web interface walkthrough, CLI reference, end-to-end workflows for common tasks (query optimization, job debugging, cost analysis, table governance, workspace discovery).

### [Agents](agents/README.md)
Deep documentation for all 8 domain agents — Query, Job, UC, Cluster, Analytics/FinOps, Warehouse, Discovery, and Diagnostic — plus the Intent Router framework.

### [Architecture](architecture/SYSTEM_ARCHITECTURE.md)
System architecture, multi-agent reasoning patterns, tool system design, frontend architecture, and output contracts.

### [Developer Guide](guides/GETTING_STARTED.md)
Setup, contributing, testing, engineering standards, agent/tool development guides, API reference, tool catalog, and package documentation.

### [Operations](DEPLOYMENT.md)
Deployment, runbooks, cloud authentication, state backend configuration, monitoring, and operational procedures.

---

## Agent System

```mermaid
%%{init: {'theme':'default', 'themeVariables': {'fontSize':'16px'}}}%%

sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant MM as MultiAgentManager
    participant IR as IntentRouter
    participant QA as QueryAgent
    participant T as Tools
    participant DB as Databricks

    U->>API: POST /chat/message
    API->>MM: process_message()
    MM->>IR: classify_intent()

    Note over IR: Analyzes message<br/>using LLM

    IR-->>MM: Intent: QUERY_OPTIMIZATION
    MM->>QA: activate(message, context)

    Note over QA: Agent becomes active<br/>builds context

    QA->>T: execute_tool("resolve_query")
    T->>DB: GET /api/2.0/sql/queries
    DB-->>T: query metadata
    T-->>QA: ToolResult(data)

    QA->>QA: analyze_results()<br/>decide_next_action()

    QA->>T: execute_tool("analyze_query_plan")
    T->>DB: GET /api/2.0/sql/history
    DB-->>T: execution history
    T-->>QA: ToolResult(data)

    Note over QA: Generates<br/>recommendations

    QA-->>MM: FinalResponse(recommendations)
    MM->>API: stream_events()
    API-->>U: SSE events

    Note over U: Real-time updates<br/>displayed in UI
```

*Multi-agent coordination flow showing how requests are routed and processed*

| Agent | Domain | Key Capability |
|-------|--------|---------------|
| [Query](agents/domain/query.md) | SQL Optimization | Query plan analysis, rewrite suggestions |
| [Job](agents/domain/job.md) | Job Performance | Failure debugging, config optimization |
| [UC](agents/domain/uc.md) | Unity Catalog | Metadata, lineage, governance, storage |
| [Cluster](agents/domain/cluster.md) | Compute | Right-sizing, health, utilization |
| [Analytics](agents/domain/analytics.md) | FinOps & Cost | Cost analysis, chargeback, forecasting |
| [Warehouse](agents/domain/warehouse.md) | SQL Warehouses | Portfolio optimization, SLO config |
| [Discovery](agents/domain/discovery.md) | Workspace Health | Assessment, inventory, health scoring |
| [Diagnostic](agents/domain/diagnostic.md) | Troubleshooting | Root cause analysis, cross-domain debugging |

See the full [Agent Catalog](overview/agents.md) for capabilities matrix and cross-agent scenarios.

---

## Package Structure

```
packages/
├── starboard-core/         # Core domain models, prompts, shared types
├── starboard-server/       # FastAPI backend with multi-agent system
├── starboard-log-parser/   # Log parsing with cloud storage
└── starboard-cli/          # Command-line interface

frontend/                   # Next.js 16 web UI (React 19, MUI v7)
```

---

## Development Commands

```bash
# Setup
make setup              # Bootstrap environment

# Development
make dev                # Start both backend and frontend
make dev-server         # Backend only (http://localhost:8000)
make dev-frontend       # Frontend only (http://localhost:3000)

# Testing
make test               # Run all tests
make test-unit          # Unit tests only
make test-coverage      # With coverage report

# Code Quality
make lint               # Run linter
make type-check         # Run type checking
make format             # Auto-format code
make pre-commit         # Format + lint + type-check

# Documentation
make diagrams           # Generate diagrams
make docs-serve         # Serve docs locally
```

---

## Community

- **GitHub**: [Repository](https://github.com/starboard-ai/job-agent)
- **Issues**: [Bug Reports & Feature Requests](https://github.com/starboard-ai/job-agent/issues)
- **Discussions**: [Community Discussions](https://github.com/starboard-ai/job-agent/discussions)

## License

See [LICENSE](../LICENSE) file in repository root.

---

**Last Updated**: {{ git_revision_date_localized }}

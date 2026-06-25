# Tool Architecture

> Last verified: 2026-03-24

## Overview

The tool system uses a clean three-layer architecture:

- **Domain Layer**: Pure business logic with no I/O dependencies
- **Service Layer**: Orchestration with protocol-based dependency injection
- **Adapter Layer**: Tool implementations for the multi-agent framework

---

## Architecture

```
Domain (Pure Logic) --> Service (Orchestration) --> Adapters (Tools)
```

### Layer Responsibilities

**Domain Layer** (`tools/domain/`)

- Pure functions, explicit inputs/outputs
- No side effects, no I/O, no infrastructure dependencies
- Easy to test (no mocking needed)
- Reusable across all interfaces

**Service Layer** (`tools/services/`)

- Coordinates domain logic with I/O via protocols
- Handles API calls, data enrichment
- Emits events for observability
- Clean separation of concerns

**Adapter Layer** (`tools/adapters/`)

- **Tool Adapters**: Direct tool implementations (signature: `async def tool(**kwargs) -> dict[str, Any]`)
- **NativeToolAdapter**: Registry adapter for LLM function calling
- **MCP Adapters**: For MCP server exposure (live via `starboard-mcp`)

**Thread-Isolated Execution** (`agents/tools/tool_registry.py`)

- Each tool runs in a **dedicated thread with its own event loop**
- Isolates synchronous SDK calls from the main asyncio event loop
- Keeps SSE streaming responsive during tool execution
- Configurable thread pool size via `TOOL_PARALLELISM` env var (default: 4)

---

## Directory Structure

```
packages/starboard-server/starboard_server/tools/
|-- domain/                     # Pure business logic
|   |-- query/                  # Query resolution and analysis
|   |-- job/                    # Job analysis and optimization
|   |-- uc/                     # Unity Catalog operations
|   |-- cluster/                # Cluster health and metrics
|   |-- warehouse/              # Warehouse portfolio and chargeback
|   |-- analytics/              # FinOps RAG and SQL generation
|   |-- discovery/              # Workspace health assessment
|   |-- diagnostic/             # Cross-domain troubleshooting
|   |-- source/                 # Source code analysis
|   |-- intent/                 # Intent classification
|   +-- utils.py                # Shared utilities
|
|-- services/                   # Orchestration + I/O
|   |-- cluster_service.py
|   |-- uc_service.py
|   |-- warehouse_service.py
|   |-- warehouse_portfolio_service.py
|   |-- chart_renderer.py
|   |-- query_result_cache.py
|   |-- query_workload_service.py
|   |-- validation.py
|   +-- ...
|
+-- adapters/                   # Tool implementations
    |-- query_tools.py          # SQL optimization tools
    |-- job_tools.py            # Job performance tools
    |-- uc_tools.py             # UC + Table operations
    |-- cluster_tools.py        # Cluster configuration and health
    |-- warehouse_tools.py      # SQL warehouse portfolio
    |-- analytics_tools.py      # FinOps cost analysis (Agentic RAG)
    |-- discovery_tools.py      # Workspace health assessment
    |-- diagnostic_tools.py     # Troubleshooting and debugging
    |-- source_tools.py         # Code analysis
    |-- intent_tools.py         # Intent classification
    +-- ...
```

---

## Tool Categories by Domain

9 domains with the **Pragmatic Hybrid (80/20)** strategy for tool sharing:

| Domain | Purpose | Strategy |
|--------|---------|----------|
| **Router** | Intent classification | Minimal tools (3) |
| **Query** | SQL optimization | Primary + strategic table overlap |
| **Job** | Job performance | Primary + strategic cluster/table overlap |
| **UC** | Unity Catalog | ALL UC/table tools (domain expert) |
| **Cluster** | Cluster management | ALL cluster tools (domain expert) |
| **Analytics** | FinOps cost analysis | Agentic RAG workflow tools |
| **Warehouse** | SQL warehouse optimization | ALL warehouse tools (domain expert) |
| **Discovery** | Workspace health | 4-phase workflow tools |
| **Diagnostic** | Troubleshooting | ALL tools (unrestricted access) |

The 80/20 strategy means:

- **80%** of operations: Agents complete independently using strategic tool overlap
- **20%** of complex operations: Agents delegate to domain specialists (no tool needed)

**Source**: `packages/starboard-server/starboard_server/agents/tool_categories.py`

---

## Tool Category Details

### Query Tools

- **Domain**: `QueryResolver`, `QueryAnalyzer`
- **Adapter**: `QueryTools`
- **Tools**: `resolve_query`, `analyze_query_plan`, `get_query_runtime_metrics`, `discover_tables`, `get_table_metadata`, `get_table_history`

### Job Tools

- **Domain**: `JobResolver`, `JobAnalyzer`
- **Adapter**: `JobTools`
- **Tools**: `resolve_job`, `get_job_config`, `analyze_job_history`, `get_run_output`, `get_task_logs`, `get_source_code`, `analyze_code_quality`

### UC Tools (Unity Catalog)

- **Domain**: `UCAnalyzer`, `TableAnalyzer`
- **Service**: `UCService` with Unity Catalog providers
- **Adapter**: `UCTools`
- **Tools**: `list_uc_assets`, `get_table_metadata`, `get_table_lineage`, `get_table_grants`, `analyze_table_schema`, `get_table_history`, `analyze_access_patterns`, `analyze_schema_drift`, `analyze_storage_optimization`, `analyze_query_impact`, `get_table_fingerprint`, `analyze_table_costs`, `generate_schema_diff`, `analyze_policy_coverage`, `get_enriched_table_metadata`, `discover_tables`

### Cluster Tools

- **Domain**: `ClusterResolver`, `ClusterMetricsAnalyzer`, `HealthAnalyzer`
- **Service**: `ClusterService` with cluster data providers
- **Adapter**: `ClusterTools`
- **Tools**: `list_clusters`, `get_cluster_config`, `get_cluster_health`, `get_cluster_metrics`, `get_cluster_events`, `get_spark_logs`

### Warehouse Tools

- **Domain**: `WarehouseTopology`, `Chargeback`
- **Service**: `WarehouseService`, `WarehousePortfolioService`
- **Adapter**: `WarehouseTools`
- **Tools**: `get_warehouse_portfolio`, `get_warehouse_fingerprint`, `get_warehouse_health`, `configure_warehouse_slo`, `analyze_warehouse_topology`, `get_warehouse_user_activity`, `generate_warehouse_chargeback`, `generate_portfolio_chargeback`, `get_query_runtime_metrics`

### Analytics Tools

- **Domain**: Agentic RAG context builder and SQL generation
- **Service**: Analytics context service
- **Adapter**: `AnalyticsTools`
- **Tools**: `build_analytics_context`, `build_sql_query`, `validate_sql_query`, `execute_sql_query`

### Discovery Tools

- **Domain**: Workspace health assessment (4-phase)
- **Service**: Discovery executor, analyzer, synthesizer
- **Adapter**: `DiscoveryTools`
- **Tools**: `discover_active_products`, `run_discovery_queries`, `analyze_discovery_domain`, `synthesize_discovery_report`

### Source Tools

- **Domain**: Source code transformation and analysis
- **Service**: Source analysis providers
- **Adapter**: `SourceTools`
- **Tools**: Code inspection, quality analysis, SQL extraction

### Intent Tools

- **Domain**: Intent resolution and classification
- **Service**: Intent resolver
- **Adapter**: `IntentTools`
- **Tools**: `resolve_user_intent`

---

## Benefits

### Zero Lint Ignores

- Pure domain functions only use parameters they need
- No `# noqa: ARG002` comments required

### Easy to Test

- Domain logic: Pure functions, no mocking
- Service logic: Mock protocols only
- Adapter logic: Integration tests

### Clean Interface

- Explicit parameters (no state dict)
- Dictionary responses optimized for LLM function calling
- Designed for multi-agent framework with dynamic tool selection
- Single implementation pattern (no V1/V2 split)

### Non-Blocking Streaming

- Tools execute in isolated threads
- Main event loop stays free for SSE streaming
- No sync SDK calls can block the response stream

### Future-Proof

- Easy to add MCP adapters
- Clear separation of concerns
- Protocol-based dependency injection
- Unified tool architecture

---

## Usage Patterns

### Tool Adapter Usage (Multi-Agent Framework)

```python
from starboard_server.tools.adapters.query_tools import QueryTools

query_tools = QueryTools(api, context, events)
result = await query_tools.resolve_query(
    target="SELECT * FROM table",
    classification=None
)
# Returns: {"source": "raw_sql", "sql_text": "..."}
```

### Tool Registry Usage

```python
from starboard_server.agents.tool_factory import create_tool_registry

# Create registry with all tools
registry = await create_tool_registry(
    databricks_api=api,
    shared_context=context,
    event_emitter=events,
    llm_client=llm
)

# Execute tool
result = await registry.execute_tool(
    "resolve_query",
    target="SELECT * FROM table"
)
# Returns JSON string: '{"source": "raw_sql", "sql_text": "..."}'
```

---

## Key Principles

### Domain Layer

- **DO**: Pure functions, explicit I/O boundaries, frozen dataclasses
- **DO NOT**: I/O operations, state mutations, infrastructure dependencies

### Service Layer

- **DO**: Protocol-based DI, event emission, error handling
- **DO NOT**: Business logic, direct API instantiation, state management

### Adapter Layer

- **DO**: Thin wrappers, format conversions, backward compatibility
- **DO NOT**: Business logic, direct I/O, complex transformations

---

**Last Updated**: 2026-03-24
**Version**: 4.0 -- All 9 domains documented, Pragmatic Hybrid strategy

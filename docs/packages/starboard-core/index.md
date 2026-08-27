# starboard-core

Pure kernel (`starboard_core`) plus the `starboard_x` progressive CLIs — no SDK/LLM/FastAPI/MCP in the kernel.

## Overview

`starboard-core` is the foundation package. It ships **two import namespaces from one
wheel**:

- **`starboard_core`** — the pure kernel: domain models/DTOs, ports (protocols), the
  Workload-Review rules engine (`RuleRegistry` + the `Finding` priority scorer), the
  Spark event log parser, and reference-file RAG knowledge. **Kernel purity is enforced
  by import-linter** — no `databricks-sdk` / `openai` / `fastapi` / `mcp`.
- **`starboard_x`** — self-contained progressive CLIs (`python -m starboard_x.<cap>`)
  with a stable JSON envelope + exit-code contract (`starboard_x.contract`). Shipped
  caps: `diagnostic`, `discovery`, `review`, `sparklog`, `uc`, `warehouse` (console
  script `starboard-x`). `cluster` / `charts` are declared but **not** implemented.

It also includes the Spark event log parser (the log parser lives here, not in a
separate `starboard-log-parser` package), streaming Spark event logs from multiple
sources (local, DBFS, Unity Catalog Volumes, HTTP/S, S3).

![Architecture Diagram](../../diagrams/generated/packages/starboard-core-architecture.png)

## Quick Links

- **[Architecture Documentation](./architecture.md)** - Complete architectural overview
- **[Data Flow](../../diagrams/generated/packages/starboard-core-dataflow.png)** - Repository pattern flow

## Key Components

### Log Parser (`log_parser/`)
- **SparkApplication**: Immutable parsed application model (jobs, stages, tasks, executors, DAG)
- **Event Parser**: Streaming parser for 30+ Spark event types (~50,000 events/second, O(1) memory)
- **Storage Loaders**: Local, DBFS, Unity Catalog Volumes, HTTP/S, S3
- **Credential Providers**: Protocol-based authentication (pluggable)

### Domain Models (`domain/models/`)
- **Context Types**: Agent and tool execution contexts
- **Databricks Models**: Domain representations of Databricks entities
- **LLM Schemas**: Request/response schemas for LLM interactions
- **Recommendations**: Optimization recommendation types
- **Report Types**: Report generation structures

### Shared Models (`models/`)
- **Conversation**: Message, Episode, Conversation structures
- **Memory**: Facts, UserProfile, Episodes for long-term memory

### Rules & Findings (`domain/rules/`, `domain/models/`)
The kernel-tier Workload-Review contract:
- **`Finding`** (`domain/models/finding.py`): `severity`/`impact`/`effort`/`confidence`
  with a computed priority `score = (severity_weight × impact) / effort_points` bucketed
  into *Fix Immediately / This Sprint / Backlog / Nice-to-Have*.
- **`Rule`/`RuleSet`** (`domain/rules/schema.py`) loaded from YAML seed rulesets.
- **`RuleRegistry`** (`domain/rules/registry.py`): loads rules, validates evidence
  queries (dependency-inverted), and ranks deterministically.
- **`build_review`** evaluator + **Action-Rate** re-scan (`domain/rules/action_rate.py`).

### Ports (`ports/`)
Protocol-based abstractions:
- **StateStore / MemoryStore / CacheStore**: state, memory, and caching interfaces.
- **Gated data ports** — `log_retrieval`, `diagnostic_backend`, `fleet_sql`, `nl_query`:
  the internal-data seam. Public adapters ship in the public packages; internal adapters
  are registered only by `starboard-internal` via `starboard.port_adapters` and used
  only when the enablement gate is open (closed by default).

### Repositories (`repositories/`)
High-level data access patterns:
- **ConversationRepository**: Rich conversation operations
- **MemoryRepository**: Memory management operations
- **CacheManager**: Caching utilities

## Design Principles

1. **Dependency Inversion**: Core depends on nothing
2. **Pure Domain Logic**: No I/O, no side effects
3. **Immutability**: Frozen dataclasses
4. **Type Safety**: Comprehensive type hints
5. **Explicit Abstractions**: Protocol-based interfaces

## Architecture

See [Complete Architecture Documentation](./architecture.md) for detailed information on:
- Package structure and layer responsibilities
- Design patterns (Hexagonal, Repository, Immutability)
- Data flow and dependency rules
- Testing strategy
- Usage examples and common patterns


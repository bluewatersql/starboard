# CLAUDE.md

This file provides guidance to AI coding assistants (Claude Code, Cursor, Codex) when working with this repository.

> **Detailed engineering standards** live in `.cursor/01_engineering_standards.md` through `.cursor/08_frontend_standards.md`. This file is a condensed reference; defer to those files for authoritative rules.

## Repository Overview

**Starboard AI Agent** is a multi-package Python monorepo providing AI-powered Databricks workload analysis and optimization. It uses a multi-agent architecture with LLM-driven reasoning, dynamic tool selection, and real-time streaming.

**Key Characteristics:**
- Multi-package monorepo managed with `uv` workspace
- Async-first architecture with streaming responses
- Multi-agent system with domain-specialized agents
- Type-safe with end-to-end Python type hints and Pydantic validation
- Comprehensive test suite (unit, integration, golden, contract tests)

## Package Structure

```
packages/
├── starboard-core/         # Domain models, prompts, shared types (no I/O dependencies)
├── starboard-log-parser/   # Spark event log parsing with credential provider framework
├── starboard-server/       # FastAPI backend with multi-agent system
├── starboard-cli/          # Command-line interface
└── starboard-sdk/          # Thin SDK for notebook/programmatic use

frontend/                   # Next.js 16 web UI (React 19, Material UI v7)
```

**Dependency flow:** CLI / Server / SDK → Core (pure domain logic, no I/O)

## Development Commands

### First-Time Setup
```bash
make setup              # Bootstrap environment (creates .venv, installs packages)
cp examples/env.example .env  # Then configure Databricks/OpenAI credentials
```

### Development Servers
```bash
make dev                # Start both backend and frontend
make dev-server         # Backend only (http://localhost:8000, API docs at /docs)
make dev-frontend       # Frontend only (http://localhost:3000)
```

### MCP Server (Claude Code / Cursor Integration)
```bash
starboard-mcp                    # Start MCP server (stdio transport, default)
starboard-mcp --transport http   # Start MCP server (HTTP transport, port 8100)
starboard-mcp --config mcp.json  # Start with explicit config file
./scripts/setup-mcp.sh           # Interactive setup wizard
```
See `docs/CLAUDE_CODE_INTEGRATION.md` for full setup guide and tool reference.

### Testing
```bash
make test               # All tests (unit + integration)
make test-unit          # Unit tests only
make test-integration   # Integration tests only
make test-golden        # Golden/snapshot tests
make test-contract      # API contract tests (backend + frontend)
make test-coverage      # With coverage report
make test-frontend      # Frontend tests (Jest)

# Run single test file
cd packages/starboard-server && pytest tests/unit/path/to/test_file.py -v

# Run tests with specific markers
pytest -m unit          # Only unit tests
pytest -m integration   # Only integration tests
pytest -m golden        # Only golden/snapshot tests
```

### Code Quality
```bash
make lint               # Run ruff linter
make lint-frontend      # Frontend linting (eslint + tsc)
make type-check         # Run mypy type checking
make format             # Auto-format code with ruff
make check              # Run all checks (lint + type + test)
make pre-commit         # Run pre-commit hooks
```

### Package Manager
This project uses **uv** (preferred) with pip fallback. The Makefile auto-detects which is available.

## Architecture

### Multi-Agent System

The core architecture is a **multi-agent conversation system** with domain specialization:

```
MultiAgentConversationManager (packages/starboard-server/starboard_server/agents/conversation/)
├── IntentRouter → Classifies user intent and routes to specialist
├── QueryAgent → SQL optimization and analysis
├── JobAgent → Databricks job performance tuning
├── UCAgent → Unity Catalog: metadata, lineage, governance, storage optimization
├── ClusterAgent → Databricks cluster configuration and optimization
├── AnalyticsAgent (FinOps) → Cost analysis, billing, budget forecasting, usage trends
├── WarehouseAgent → SQL warehouse portfolio optimization
└── DiagnosticAgent → Troubleshooting, debugging, and root cause analysis
```

**Key Components:**
- **MultiAgentConversationManager**: Main orchestrator coordinating agents
- **IntentRouter**: Routes requests to appropriate domain agent (hybrid pattern matching + LLM)
- **DomainAgent**: Base agent with dynamic tool selection and step-by-step reasoning
- **SharedAgentContext**: Context shared across agent transitions
- **AgentFactory**: Creates and caches domain agents with specialized prompts/tools
- **AgentRegistry**: Central registry for agent metadata and capabilities

**Architecture Patterns:**
- Agents use **continuous reasoning** (no predefined graphs)
- **Dynamic tool selection** — agents see data before deciding next steps
- **Adaptive workflows** — agents can change plans based on intermediate results
- **Real-time streaming** with SSE (Server-Sent Events)
- **Interruptible reasoning** — user can provide context or corrections mid-reasoning

### Architectural Layers

```
domain/      – pure logic, deterministic, no I/O
adapters/    – I/O boundaries (LLM SDKs, DB, HTTP, FS)
agents/      – policies, tool routing, orchestration, conversation management
app/         – CLI/API/FastAPI entrypoints
infra/       – config, logging, DI/wiring, observability
tools/       – tool implementations with explicit schemas
```

**Rules:**
- **Dependency injection** for all external services (LLM clients, stores, clocks)
- **Pure functions** in domain; side effects only in adapters
- **Separate prompting** from tool calls; schemas live at boundaries
- **Immutable data** preferred (`dataclasses(frozen=True)`, `tuple`)
- **No hidden I/O** in domain functions

### Tool System

45+ tools organized by category in three-layer architecture:

```
Domain (Pure Logic) → Service (Orchestration) → Adapters (Tool Functions)
```

**Tool Categories:**
- Query: `resolve_query`, `analyze_query_plan`, `get_query_runtime_metrics`, `discover_tables`
- Job: `resolve_job`, `get_job_config`, `analyze_job_history`, `get_run_output`, `get_task_logs`, `get_source_code`, `analyze_code_quality`
- UC: `list_uc_assets`, `get_table_metadata`, `get_table_lineage`, `get_table_grants`, `analyze_table_schema`, `get_table_history`, `analyze_access_patterns`, `analyze_schema_drift`, `analyze_storage_optimization`, `analyze_query_impact`, `get_table_fingerprint`, `analyze_table_costs`, `generate_schema_diff`, `analyze_policy_coverage`, `get_enriched_table_metadata`
- Cluster: `list_clusters`, `get_cluster_config`, `get_cluster_health`, `get_cluster_metrics`, `get_cluster_events`, `get_spark_logs`
- Warehouse: `get_warehouse_portfolio`, `get_warehouse_fingerprint`, `get_warehouse_health`, `configure_warehouse_slo`, `analyze_warehouse_topology`, `get_warehouse_user_activity`, `generate_warehouse_chargeback`, `generate_portfolio_chargeback`
- Intent: `resolve_user_intent`
- Source: Data source transformation tools
- Core: `request_user_input`, `complete` (available to all agents)

**Location:** `packages/starboard-server/starboard_server/tools/`

### State Management

Repository pattern with pluggable storage backends:
- **SQLite**: Embedded database for dev/testing (aiosqlite + sqlite-vec for vector search)
- **InMemory**: Development/testing (no persistence)
- **Postgres**: Production (pgvector for vector similarity)
- **Databricks Lakebase**: Postgres-compatible with OAuth refresh
- **Redis**: Session cache and rate limiting

**Data Models:** Conversation, Episode, Fact, UserProfile

### Frontend Architecture

- **Framework**: Next.js 16 with App Router
- **UI**: Material UI v7 + Tailwind CSS v4
- **State**: Zustand + React Query (TanStack)
- **Streaming**: EventSource (SSE) with eventsource-parser
- **Type Safety**: Zod v4 schemas with contract tests
- **Charts**: Recharts for data visualization

## Engineering Standards Summary

> **Authoritative source**: `.cursor/01_engineering_standards.md` through `.cursor/08_frontend_standards.md`

### Code Style
- **PEP 8** via Ruff (88 char line length)
- **Type hints required** on all public functions; mypy in CI (`strict = false`, incrementally tightening)
- **Google-style docstrings** with Args/Returns/Raises/Examples
- **Pydantic V2** at all boundaries (user input, LLM output, HTTP)
- **4 parameters max**; else group via dataclass/TypedDict
- **No boolean flags**; use enums or separate functions

### Error Handling
- **Fail fast** on invalid inputs/config
- **Specific exceptions** only (never generic `Exception` or bare `except:`)
- **Context managers** for resources (files, DB connections, HTTP sessions)
- **Idempotent retries** with exponential backoff + jitter (max 3)
- **Circuit breakers** for external dependencies
- LLM-specific: rate limits (429) → backoff; timeouts → retry; invalid JSON → repair prompt; moderation → refuse gracefully

### Observability
Every log entry must include `trace_id`, `span_id`, `user_id`, `session_id`, `model`, `prompt_version`, `tokens_used`, `latency_ms`, `cost_usd`. Use distributed tracing with child spans for each tool call, LLM call, and retrieval.

### Testing
- **Coverage**: ≥80% overall, 100% for agent policies, schema validators, tool routers
- **Golden tests** for prompts (snapshot + structured assertions)
- **Mock external dependencies**; offline test mode required
- **Use `respx`** for mocking httpx requests in integration tests
- **Adversarial tests**: prompt injection, malformed inputs, resource exhaustion

### Prompts & Schemas
- **Constrain every LLM call** with JSON-mode/function-call schemas
- **Centralized prompts** under `packages/starboard-server/starboard_server/prompts/`
- **Versioned prompts**: `PROMPT_VERSION = "1.0.0"` in each prompt module; never modify in place
- **Golden tests** required for all prompt changes
- **Default temperatures**: structural/tool calls ≤ 0.4; creative ≤ 0.9

### Security
- Never commit secrets; use `.env` + environment variables
- Redact PII in logs; validate all inputs with Pydantic
- Parameterized queries only; `SAFE_MODE=true` to disable external calls

## Common Development Tasks

### Adding a New Tool
1. Create domain logic in `packages/starboard-server/starboard_server/tools/domain/`
2. Create service interface in `tools/services/`
3. Implement adapter in `tools/adapters/`
4. Register tool in `agents/tools/registry.py`
5. Add to appropriate domain in `agents/tool_categories.py`
6. Add unit tests with 100% coverage
7. Add integration tests for external service calls

### Adding a New Agent
1. Add domain to `AgentDomain` literal in `agents/routing/routing_models.py`
2. Create prompts in `packages/starboard-server/starboard_server/prompts/{domain}/v1.py`
   - Include `PROMPT_VERSION = "1.0.0"`
3. Register prompt builder in `prompts/factories.py`
4. Add tools specific to this agent's domain in `tools/adapters/`
5. Update `IntentRouter` to route to new agent (pattern matching + keywords)
6. Add golden tests for prompts in `tests/golden/`
7. Add integration tests for agent workflows

### Modifying Prompts
1. **Always version prompts**: Create `v2.py` alongside `v1.py` (never modify existing versions in production)
2. Increment `PROMPT_VERSION` constant
3. Update golden tests in `tests/golden/`
4. Run `make test-golden` to verify changes
5. Document changes in PR description

## Important Files

### Configuration
- `pyproject.toml` — Workspace configuration, tool settings (ruff, mypy, pytest, coverage)
- `.cursor/` — Detailed engineering standards (7 files)
- `Makefile` — All development commands
- `examples/env.example` — Environment variable template

### Key Source Files
- `packages/starboard-server/starboard_server/agents/conversation/multi_agent_manager.py` — Main orchestrator
- `packages/starboard-server/starboard_server/agents/routing/intent_router.py` — Request routing
- `packages/starboard-server/starboard_server/agents/domain/domain_agent.py` — Base domain agent
- `packages/starboard-server/starboard_server/agents/agent_factory.py` — Agent creation and caching
- `packages/starboard-server/starboard_server/prompts/` — Domain-specific prompts
- `packages/starboard-server/starboard_server/tools/` — Tool implementations
- `packages/starboard-server/starboard_server/infra/reliability/circuit_breaker.py` — Circuit breaker pattern

### Documentation
- `docs/` — MkDocs documentation site (build with `make docs`)
- `docs/ARCHITECTURE.md` — System architecture deep dive
- `docs/QUICKSTART.md` — Getting started guide
- `docs/RUNBOOK.md` — Operational runbook
- `docs/TOOL_ARCHITECTURE.md` — Tool system design
- `docs/INTERRUPTIBLE_REASONING.md` — Agent reasoning patterns

## Anti-Patterns to Avoid

**Never:**
- Modify prompts in place (always version: V1 → V2 → V3)
- Skip golden tests when changing prompts
- Use boolean flags (use enums instead)
- Catch-and-ignore exceptions or use bare `except:`
- Block async event loop with sync I/O
- Log PII or secrets
- Hardcode configuration values
- Proceed after failed validation
- Create implicit agent state (use explicit state machines)
- Skip type hints on public APIs
- Parse free-form LLM text without schemas
- Ignore rate limits or token budgets

## Common Pitfalls

1. **Running tests without test dependencies**: Run `make setup` or `make install-dev` first
2. **Missing environment variables**: Copy `examples/env.example` to `.env`
3. **Forgetting to activate venv**: Use `make` commands which handle this
4. **Not versioning prompts**: Always create V2, V3... never modify existing versions
5. **Skipping golden tests**: Required for all prompt changes
6. **Blocking async code**: Use `async`/`await` for all I/O operations
7. **Missing PROMPT_VERSION**: Every prompt module must export version constant

## Git Workflow

- Main branch: `main`
- Feature branches: `feature/description`
- Create PRs against `main`
- **Pre-commit checks**: `make pre-commit` (runs pre-commit hooks)
- **CI requirements**: All tests pass, coverage ≥ 80%, no type errors, golden tests pass

## Production Readiness Checklist

Before deploying a new agent or major feature:

- [ ] All tools have 100% test coverage
- [ ] Golden tests exist for all prompts
- [ ] PROMPT_VERSION exported from prompt module
- [ ] Pydantic input models at adapter boundaries
- [ ] Structured logging with trace_id, span_id
- [ ] EventEmitter integration for observability
- [ ] Circuit breaker for external calls (via ToolExecutor)
- [ ] No broad `except Exception` without specific handling
- [ ] Prompt accurately reflects available tools
- [ ] Integration tests for agent workflows

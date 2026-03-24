# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Note**: Detailed engineering standards are in `.cursor/`. This file is a condensed reference; defer to `.cursor/` files for authoritative rules.

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
├── starboard-core/         # Domain models, prompts, shared types (no dependencies)
├── starboard-log-parser/   # Log parsing with credential provider framework
├── starboard-server/       # FastAPI backend with multi-agent system
└── starboard-cli/          # Command-line interface

frontend/                   # Next.js 16 web UI (React 19, Material UI v7)
```

**Dependency flow:** CLI/Server → Core (pure domain logic with no I/O dependencies)

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

### Testing
```bash
make test               # All tests (unit + integration)
make test-unit          # Unit tests only
make test-integration   # Integration tests only
make test-golden        # Golden/snapshot tests
make test-contract      # API contract tests (backend + frontend)
make test-coverage      # With coverage report
make test-parallel      # Parallel execution (faster)

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
make type-check         # Run mypy type checking
make format             # Auto-format code with ruff
make check              # Run all checks (lint + type + test)
make pre-commit         # Format + lint + type-check (run before commits)
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

**Important Architecture Patterns:**
- Agents use **continuous reasoning** (no predefined graphs)
- **Dynamic tool selection** - agents see data before deciding next steps
- **Adaptive workflows** - agents can change plans based on intermediate results
- **Real-time streaming** with SSE (Server-Sent Events)
- **Interruptible reasoning** - user can provide context or corrections mid-reasoning

### Architectural Layers

```
domain/      – pure logic, deterministic, no I/O
adapters/    – I/O boundaries (LLM SDKs, DB, HTTP, FS)
agents/      – policies, tool routing, orchestration, conversation management
app/         – CLI/API/Streamlit/FastAPI entrypoints
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

## Engineering Standards

> **Authoritative source**: `.cursor/01_engineering_standards.md` through `.cursor/07_project_structure_and_tooling.md`

### Code Style (Enforced)
- **PEP 8** via Ruff (88 char line length)
- **Type hints required** on all public functions (mypy strict mode)
- **Google-style docstrings** with Args/Returns/Raises/Examples
- **Pydantic V2** at all boundaries (user input, LLM output, HTTP)
- **4 parameters max**; else group via dataclass/TypedDict
- **No boolean flags**; use enums or separate functions

### Error Handling (`.cursor/01_engineering_standards.md`)
- **Fail fast** on invalid inputs/config
- **Use specific exceptions** (never generic `Exception`)
- **No bare `except:`**; catch expected types with explicit handling
- **Context managers** for resources (files, DB connections, HTTP sessions)
- **Log context + correlation IDs** (trace_id, request_id)
- **Idempotent retries** with exponential backoff + jitter (max 3 retries)
- **Circuit breakers** for external dependencies

**LLM-Specific Error Handling:**
- Rate limits (429) → backoff + retry
- Timeouts → retry with extended timeout
- Invalid JSON → repair prompt or fallback
- Moderation flags → log + refuse gracefully

### Observability (`.cursor/05_observability_and_cost.md`)

**Every log entry must include:**
- `trace_id`, `span_id` - distributed tracing
- `user_id`, `session_id` - user context
- `model`, `prompt_version` - LLM context
- `tokens_used`, `latency_ms`, `cost_usd` - cost tracking

**Use structured logging:**
```python
logger.info(
    "llm_call_completed",
    extra={
        "trace_id": trace_id,
        "span_id": span_id,
        "model": model_name,
        "prompt_version": "v2",
        "tokens_used": response.usage.total_tokens,
        "latency_ms": latency,
        "cost_usd": cost,
    },
)
```

**Distributed Tracing:**
- Start a span for agent invocation
- Use child spans for each tool call, LLM call, and retrieval
- Include input/output sizes, latency, and errors in span attributes

**Health Endpoints:**
- `/health/live` – process is alive
- `/health/ready` – ready to serve traffic and dependencies reachable

### Cost Management (`.cursor/05_observability_and_cost.md`)
- **Token budgeting**: Measure tokens per call, track rolling totals per user/session, enforce caps
- **Cost attribution**: Tag every LLM call with `feature`, `agent`, `user_id`, `tenant_id`
- **Caching strategies**: Semantic cache (5min TTL for tool results, 1hr for metadata)
- **Circuit breakers**: Implement for expensive or unstable operations

### Security (`.cursor/06_security_and_privacy.md`)
- **Never commit secrets** - use `.env` + environment variables
- **Secret scanning** in pre-commit (detect-secrets, gitleaks)
- **Redact PII in logs** - avoid logging full prompts with sensitive data
- **Validate all inputs** - Pydantic validation at boundaries
- **Parameterized queries only** - no SQL injection risk
- **Safe mode** available (`SAFE_MODE=true`) to disable external calls

### Prompts & Schemas (`.cursor/03_prompts_and_schemas.md`)
- **Constrain every LLM call** with JSON-mode/function-call schemas
- **Centralized prompts** under `packages/starboard-server/starboard_server/prompts/`
- **Versioned prompts**: `PROMPT_VERSION = "1.0.0"` in each prompt module
- **Golden tests** for prompts (PRs must include diffs)
- **Default temperatures**: structural/tool calls ≤0.4; creative ≤0.9

### Testing (`.cursor/04_testing_and_evals.md`)
- **Coverage**: ≥80% overall, **100% for agent policies, schema validators, tool routers**
- **Golden tests** for prompts (snapshot + structured assertions)
- **Mock external dependencies**; offline test mode required
- **Test edge cases**: timeouts, rate limits, retries, invalid JSON, PII in prompts
- **Adversarial tests**: prompt injection, malformed inputs, resource exhaustion

### Evaluations (`.cursor/04_testing_and_evals.md`)
- Maintain `evals/` directory with task suites, golden datasets, evaluation runners
- Run evals on PRs that touch prompts, schemas, or agents
- Track: latency (p50/p95/p99), success rate, cost per query, retrieval quality

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
- `pyproject.toml` - Workspace configuration, tool settings
- `.cursor/` - Complete engineering standards (must read before contributions)
- `Makefile` - All development commands
- `examples/env.example` - Environment variable template

### Documentation
- `docs/ARCHITECTURE.md` - System architecture deep dive
- `docs/QUICKSTART.md` - Getting started guide
- `docs/RUNBOOK.md` - Operational runbook
- `docs/TOOL_ARCHITECTURE.md` - Tool system design
- `docs/INTERRUPTIBLE_REASONING.md` - Agent reasoning patterns

### Key Source Files
- `packages/starboard-server/starboard_server/agents/conversation/multi_agent_manager.py` - Main orchestrator
- `packages/starboard-server/starboard_server/agents/routing/intent_router.py` - Request routing
- `packages/starboard-server/starboard_server/agents/domain/domain_agent.py` - Base domain agent
- `packages/starboard-server/starboard_server/agents/agent_factory.py` - Agent creation and caching
- `packages/starboard-server/starboard_server/prompts/` - Domain-specific prompts
- `packages/starboard-server/starboard_server/tools/` - Tool implementations
- `packages/starboard-server/starboard_server/infra/reliability/circuit_breaker.py` - Circuit breaker pattern

## Anti-Patterns to Avoid

**Never:**
- Modify prompts in place (always version: V1 → V2 → V3)
- Skip golden tests when changing prompts
- Use boolean flags (use enums instead)
- Catch-and-ignore exceptions
- Use bare `except:` without specific exception types
- Block async event loop with sync I/O
- Log PII or secrets
- Hardcode configuration values
- Proceed after failed validation
- Create implicit agent state (use explicit state machines)
- Skip type hints on public APIs
- Parse free-form LLM text without schemas
- Ignore rate limits or token budgets

## Common Pitfalls

1. **Running tests without test dependencies**: Run `make install-test` first
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
- **Pre-commit checks**: `make pre-commit` (format + lint + type-check)
- **CI requirements**: All tests pass, coverage ≥80%, no type errors, no security issues, golden tests pass, eval smoke tests pass

## Performance Notes

- Use **Polars** for data processing (10x faster than Pandas)
- Connection pooling for all external services
- Virtual scrolling in frontend for long conversations
- Message compression (30-50% reduction)
- Horizontal scaling: Multiple backend instances
- Circuit breakers: Fail fast on external errors

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

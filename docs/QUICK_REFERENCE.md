---
title: Quick Reference
description: Single-page cheat sheet for daily Starboard AI Agent development.
last_reviewed: 2026-03-24
status: current
---

# Starboard AI Agent -- Quick Reference

> **Docs** > **Developer Guide** > **Quick Reference**
> Reading time: 5 minutes

---

## At a Glance

| Metric | Value |
|--------|-------|
| **Packages** | 3 Python (starboard-core, starboard, starboard-skills) |
| **Domain Agents** | 8 + 1 Intent Router |
| **Tools** | 45+ across 9 categories |
| **Python** | 3.12+ |
| **Package Manager** | uv |
| **Streaming** | SSE (Server-Sent Events) |

---

## Domain Agents

| Domain | Agent | Tools | Report Type | Key Capabilities |
|--------|-------|-------|-------------|-----------------|
| `router` | Intent Router | 3 | N/A | Request classification, domain routing |
| `query` | Query | 8 | `advisor` | Execution plans, SQL optimization, partitioning |
| `job` | Job | 14 | `advisor` | Job configs, Spark logs, code quality, task analysis |
| `uc` | UC | 18 | `advisor` | Metadata, lineage, governance, schema drift, costs |
| `cluster` | Cluster | 8 | `compute` | Cluster sizing, health, metrics, autoscaling |
| `analytics` | Analytics (FinOps) | 6 | `analytics` | Agentic RAG, SQL generation, cost analysis |
| `warehouse` | Warehouse | 11 | `compute` | Portfolio optimization, SLO, topology, chargeback |
| `discovery` | Discovery | 6 | `discovery` | Workspace health, resource inventory, 4-phase pipeline |
| `diagnostic` | Diagnostic | ALL | `advisor` | Root cause analysis, cross-domain debugging |

**Source**: `packages/starboard/starboard/agents/tool_categories.py`

---

## Packages

| Package | Purpose | Entry Point |
|---------|---------|-------------|
| **starboard-core** | Domain models, prompts, shared types, log parsing | Pure domain (no I/O) |
| **starboard** | Multi-agent system, MCP server, CLI, tools | `starboard` CLI, `starboard-mcp` MCP server |
| **starboard-skills** | Claude skill files + Databricks helper scripts | `starboard-helper` command |

**Dependency flow**: starboard --> starboard-core; starboard-skills --> starboard-core

---

## Common Commands

### Development

```bash
make setup              # First-time bootstrap
make dev-server         # Start MCP server / backend
```

### Testing

```bash
make test               # All tests
make test-unit          # Unit tests only
make test-integration   # Integration tests
make test-golden        # Snapshot/golden tests
make test-coverage      # With coverage report
make test-parallel      # Parallel execution
```

### Code Quality

```bash
make lint               # Ruff linter
make type-check         # mypy
make format             # Auto-format
make check              # All checks (lint + type + test)
make pre-commit         # Format + lint + type-check
```

### Documentation

```bash
make docs-serve         # Serve docs locally
make docs-build         # Build static site
make diagrams           # Generate diagrams
```

---

## Environment Variables (Top 10)

```bash
# Required
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi...
DATABRICKS_WAREHOUSE_ID=your_warehouse_id
LLM_API_KEY=<your-api-key>

# Model Configuration
LLM_MODEL=databricks-claude-sonnet-4-5
LLM_TEMPERATURE=0.4
LLM_MAX_TOKENS=75000

# Optional
DOMAIN_MODEL_OVERRIDES='{"router":"gpt-4o-mini","diagnostic":"o1-preview"}'
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///dev_data/starboard_state.db
```

**Full reference**: [Configuration Guide](CONFIGURATION.md)

---

## Key File Paths

| Category | Path |
|----------|------|
| Agent Factory | `packages/starboard/starboard/agents/agent_factory.py` |
| Domain Agent Base | `packages/starboard/starboard/agents/domain/domain_agent.py` |
| Intent Router | `packages/starboard/starboard/agents/routing/intent_router.py` |
| Tool Categories | `packages/starboard/starboard/agents/tool_categories.py` |
| Routing Models | `packages/starboard/starboard/agents/routing/routing_models.py` |
| Prompt Builders | `packages/starboard/starboard/prompts/factories.py` |
| Domain Prompts | `packages/starboard/starboard/prompts/{domain}/v1.py` |
| Tool Adapters | `packages/starboard/starboard/tools/adapters/` |
| Tool Services | `packages/starboard/starboard/tools/services/` |
| Tool Domain Logic | `packages/starboard/starboard/tools/domain/` |
| MCP Entry Point | `packages/starboard/starboard/mcp/server.py` |
| Config | `packages/starboard/starboard/infra/core/config.py` |
| Conversation Manager | `packages/starboard/starboard/agents/conversation/multi_agent_manager.py` |

---

## Common Tasks

### Add a New Tool

1. Create domain logic in `tools/domain/`
2. Create service in `tools/services/`
3. Create adapter in `tools/adapters/`
4. Register in `agents/tools/registry.py`
5. Add to `TOOL_CATEGORIES` in `agents/tool_categories.py`
6. Write tests with 100% coverage

**Guide**: [Tool Development](tools/TOOL_DEVELOPMENT_GUIDE.md)

### Add a New Agent

1. Add domain to `AgentDomain` literal in `routing_models.py` and `prompts/base.py`
2. Create prompts in `prompts/{domain}/v1.py` with `PROMPT_VERSION`
3. Register prompt builder in `prompts/factories.py`
4. Configure tools in `TOOL_CATEGORIES`
5. Update IntentRouter patterns
6. Write golden tests and routing tests

**Guide**: [Agent Implementation Guide](developer/agent/IMPLEMENTATION_GUIDE.md)

### Modify a Prompt

1. Create new version (`v2.py` alongside `v1.py`) -- never modify existing versions
2. Increment `PROMPT_VERSION`
3. Update golden tests: `make test-golden`
4. Document changes in PR description

---

## Quick Links

| Resource | Link |
|----------|------|
| System Architecture | [architecture/SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md) |
| Tool Catalog | [tools/TOOL_CATALOG.md](tools/TOOL_CATALOG.md) |
| API Reference | [api/API_REFERENCE.md](api/API_REFERENCE.md) |
| Package Integration | [integration/PACKAGE_INTEGRATION.md](integration/PACKAGE_INTEGRATION.md) |
| Testing Guide | [TESTING.md](TESTING.md) |
| Configuration | [CONFIGURATION.md](CONFIGURATION.md) |
| Makefile Guide | [MAKEFILE_GUIDE.md](MAKEFILE_GUIDE.md) |
| MCP Server | `starboard-mcp --transport stdio` |

---

**Last Updated**: 2026-03-24
**Version**: 2.0

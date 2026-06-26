---
title: Changelog
description: Release history and notable changes for Starboard AI Agent.
last_reviewed: 2026-03-24
status: current
---

# Changelog

> **Docs** > **Overview** > **Changelog**

The canonical changelog is maintained in the repository root at `CHANGELOG.md` (see the [GitHub repository](https://github.com/starboard-ai/job-agent/blob/main/CHANGELOG.md)).

For convenience, the full version history is reproduced below. The root file is the single source of truth — if there is ever a discrepancy, the root file wins.

---

## [Unreleased]

### Added
- Architecture fitness tests (GUIDELINE-001 through GUIDELINE-010)
- Token budget documentation
- Operations runbook with triage flowchart
- AGENTS.md files across all key directories
- docker-compose.yml for local dev (Postgres, Redis)
- Runbook templates for rollback and capacity planning
- Documentation overhaul with persona-based navigation (General, User, Developer, Admin)
- Glossary of Starboard and Databricks terminology
- SDK usage guide for notebook and pipeline integration
- Workflow guides for cluster optimization and warehouse optimization

### Changed
- SDK fully integrated into Makefile (test, coverage, type-check)
- Pre-commit config extended with mypy and check-toml hooks
- pip-audit hook args fixed for environment-based scanning
- test-coverage now spans all packages (core, log-parser, server, cli, sdk)
- TOKEN_BUDGET.md added to mkdocs nav
- Standardized agent count to 8 domain agents + 1 Intent Router across all documentation
- Standardized tool count to 45+ across all documentation
- Updated all references from WebSocket to SSE (Server-Sent Events)
- Updated environment variable references from `OPENAI_API_KEY` to `LLM_API_KEY`
- Updated Python version requirement to 3.12+ across all documentation
- Updated package count to 5 (added starboard-sdk)

### Fixed
- SDK test failures no longer swallowed in `make test-unit`
- Corrected agent counts in FAQ, Quick Reference, and System Architecture (previously listed 5, 6, or 7)
- Corrected tool counts in FAQ and Quick Reference (previously listed 31)
- Fixed hardcoded local paths in Frontend Quickstart
- Fixed `compute` domain name to `cluster` in Implementation Guide

---

## [0.1.0] - 2026-03-26

### Added
- Initial multi-agent conversation system
- 8 domain agents (Query, Job, UC, Cluster, Analytics, Warehouse, Discovery, Diagnostic)
- 45+ tools across 6 categories
- FastAPI backend with SSE streaming
- Next.js 16 frontend with Material UI v7
- MCP server integration
- CLI with interactive analysis
- SDK for programmatic use
- SQLite, Postgres, and Redis state backends
- Discovery Agent with 4-phase workspace health assessment pipeline
- Discovery tools: `discover_active_products`, `run_discovery_queries`, `analyze_discovery_domain`, `synthesize_discovery_report`
- Warehouse Agent for SQL warehouse portfolio optimization
- Warehouse tools: `get_warehouse_portfolio`, `get_warehouse_fingerprint`, `get_warehouse_health`, `configure_warehouse_slo`, `analyze_warehouse_topology`, `get_warehouse_user_activity`, `generate_warehouse_chargeback`, `generate_portfolio_chargeback`
- Analytics Agent v3 with agentic RAG workflow
- Analytics tools: `build_analytics_context`, `build_sql_query`, `validate_sql_query`, `execute_sql_query`
- Starboard SDK (`starboard-sdk` package) for programmatic multi-turn conversations
- Embedding model configuration with `EMBEDDING_MODEL` and `EMBEDDING_BASE_URL`
- Per-domain model and temperature overrides via `DOMAIN_MODEL_OVERRIDES`
- Intent Router with hybrid pattern matching and LLM classification
- SSE streaming for real-time agent progress
- Interruptible reasoning with user-in-the-loop support
- State management with SQLite, Postgres, Lakebase, Redis, and InMemory backends
- Comprehensive documentation (40+ documents)
- Test suite with unit, integration, golden, and contract tests
- Configuration via environment variables with `EnvConfig`
- Deployment guide for Databricks Apps, Docker, and cloud platforms

### Changed
- Separated Cluster and Warehouse into distinct domain agents (previously combined as "Compute")
- Tool count increased from 31 to 45+
- Package count increased from 4 to 5 (added starboard-sdk)
- LLM configuration consolidated under `LLM_*` environment variables
- Agent count increased from 7 to 8 domain agents
- Discovery domain added to `AgentDomain` type literal and Intent Router

### Fixed
- Tool coercion for JSON Schema type handling in tool registry
- Simplified recursion limit handling in event log parser

---

## Next Steps

- [What is Starboard?](what-is-starboard.md) — Product overview
- [Quickstart](../QUICKSTART.md) — Get running in 5 minutes
- [Agent Catalog](agents.md) — Explore all 8 domain agents


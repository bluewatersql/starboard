---
title: Changelog
description: Release history and notable changes for Starboard AI Agent.
last_reviewed: 2026-03-24
status: current
---

# Changelog

> **Docs** > **Overview** > **Changelog**
> Reading time: 5 minutes

All notable changes to the Starboard AI Agent are documented here. This changelog follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention.

---

## [Unreleased]

### Added
- Documentation overhaul with persona-based navigation (General, User, Developer, Admin)
- Glossary of Starboard and Databricks terminology
- SDK usage guide for notebook and pipeline integration
- Workflow guides for cluster optimization and warehouse optimization

### Changed
- Standardized agent count to 8 domain agents + 1 Intent Router across all documentation
- Standardized tool count to 45+ across all documentation
- Updated all references from WebSocket to SSE (Server-Sent Events)
- Updated environment variable references from `OPENAI_API_KEY` to `LLM_API_KEY`
- Updated Python version requirement to 3.12+ across all documentation
- Updated package count to 5 (added starboard-sdk)

### Fixed
- Corrected agent counts in FAQ, Quick Reference, and System Architecture (previously listed 5, 6, or 7)
- Corrected tool counts in FAQ and Quick Reference (previously listed 31)
- Fixed hardcoded local paths in Frontend Quickstart
- Fixed `compute` domain name to `cluster` in Implementation Guide

---

## [1.2.0] - 2026-02-15

### Added
- Discovery Agent with 4-phase workspace health assessment pipeline
- Discovery tools: `discover_active_products`, `run_discovery_queries`, `analyze_discovery_domain`, `synthesize_discovery_report`
- Workspace discovery workflow documentation
- Discovery agent domain documentation

### Changed
- Agent count increased from 7 to 8 domain agents
- Discovery domain added to `AgentDomain` type literal and Intent Router

---

## [1.1.0] - 2026-01-10

### Added
- Warehouse Agent for SQL warehouse portfolio optimization
- Warehouse tools: `get_warehouse_portfolio`, `get_warehouse_fingerprint`, `get_warehouse_health`, `configure_warehouse_slo`, `analyze_warehouse_topology`, `get_warehouse_user_activity`, `generate_warehouse_chargeback`, `generate_portfolio_chargeback`
- Analytics Agent v3 with agentic RAG workflow
- Analytics tools: `build_analytics_context`, `build_sql_query`, `validate_sql_query`, `execute_sql_query`
- Starboard SDK (`starboard-sdk` package) for programmatic multi-turn conversations
- Embedding model configuration with `EMBEDDING_MODEL` and `EMBEDDING_BASE_URL`
- Per-domain model and temperature overrides via `DOMAIN_MODEL_OVERRIDES`

### Changed
- Separated Cluster and Warehouse into distinct domain agents (previously combined as "Compute")
- Tool count increased from 31 to 45+
- Package count increased from 4 to 5 (added starboard-sdk)
- LLM configuration consolidated under `LLM_*` environment variables

### Fixed
- Tool coercion for JSON Schema type handling in tool registry
- Simplified recursion limit handling in event log parser

---

## [1.0.0] - 2025-12-01

### Added
- Multi-agent conversation system with 6 domain agents (Query, Job, UC, Cluster, Analytics, Diagnostic)
- Intent Router with hybrid pattern matching and LLM classification
- 31 tools organized in three-layer architecture (Domain, Service, Adapter)
- SSE streaming for real-time agent progress
- Interruptible reasoning with user-in-the-loop support
- FastAPI backend with REST API (22 endpoints)
- Next.js 16 frontend with Material UI v7
- CLI with natural language interface
- State management with SQLite, Postgres, Lakebase, Redis, and InMemory backends
- Comprehensive documentation (40+ documents)
- Test suite with unit, integration, golden, and contract tests
- Configuration via environment variables with `EnvConfig`
- Deployment guide for Databricks Apps, Docker, and cloud platforms

---

## Next Steps

- [What is Starboard?](what-is-starboard.md) -- Product overview
- [Quickstart](../QUICKSTART.md) -- Get running in 5 minutes
- [Agent Catalog](agents.md) -- Explore all 8 domain agents


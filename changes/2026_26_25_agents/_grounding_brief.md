# Starboard — Grounding Brief (Evidence Base for Envisioning Session)

> Shared factual baseline for the 2026-08-26 "art of the possible" research session.
> Every claim below is sourced from the current codebase (commit `b927dfaa`, starboard 0.1.1).
> **This brief describes what exists — it is NOT a constraint on ideas.** Reason from first principles.

## What Starboard Is

AI-powered Databricks workload analysis & optimization platform. Multi-package Python monorepo.
Analyzes: SQL queries, jobs, Unity Catalog, clusters, FinOps/billing, SQL warehouses, diagnostics/RCA.

## Package Structure (3 packages)

| Package | Purpose | Deps | Entry points |
|---------|---------|------|--------------|
| `starboard-core` | Pure domain: models, prompts, types, **Spark/Photon log parsing** (no I/O) | none (+polars) | — |
| `starboard` | MCP server + CLI + SDK + 7 agents + ~45 tools | starboard-core, databricks-sdk `>=0.73,<1.0`, mcp `>=1.19,<2.0` | `starboard` (CLI), `starboard-mcp` (MCP) |
| `starboard-skills` | 9 dual-mode Claude `skill.md` files + thin `starboard-helper` CLI | starboard-core, databricks-sdk `>=0.60` | `starboard-helper` |

## Architecture (hexagonal)

`domain/` (pure) → `adapters/` (I/O: LLM, Databricks, chat, state) → `agents/` (routing, orchestration) → `app/` (CLI/MCP entry) → `infra/` (config, logging, DI, observability, auth, cache, rag, reliability, streaming) → `tools/` (explicit-schema tool impls).

## Multi-Agent System

`MultiAgentConversationManager` → `IntentRouter` classifies → 7 specialists:
QueryAgent, JobAgent, UCAgent, ClusterAgent, AnalyticsAgent (FinOps), WarehouseAgent, DiagnosticAgent.
Service catalog (`config/service_catalog.yaml`, v1.2.0) drives cross-domain handoff suggestions.

## MCP Server (`starboard/mcp/`, ~4,800 LOC, FastMCP-based)

- Transports: **stdio** (`starboard-mcp`) + **Streamable HTTP** (`create_mcp_app()` FastAPI mount at `/mcp`)
- Surface: ~11 quick tools (tool_bridge) + 4 composite tools + **8 `*_agent` tools** (agent_bridge, headless domain-agent execution) + 8 domain prompts (prompt_bridge) + 5 introspection resources
- Cross-cutting: rate limiter, circuit breakers, sanitizer, observability, auth context, workspace manager/registry (multi-workspace via `WorkspaceProfile`)
- **Known gap (per `changes/mcp_claude/`)**: ToolRegistry/AgentFactory wiring, progress notifications for long agent tools, `tool_scope: full` to expose all 45 tools. Some of this may now be resolved — verify against current `server.py`/`transports.py`.

## Skills (dual-mode, 9 skills)

`starboard-analyze, -cluster, -diagnostic, -discovery, -finops, -job, -query, -uc, -warehouse`.
Each `skill.md`: **if `mcp__starboard__*` tools present → use MCP path (full agent stack); else → shell out to `starboard-helper <domain> <cmd>`** which uses bare `databricks.sdk.WorkspaceClient()` (default auth chain) and prints JSON. Skills exist in BOTH `starboard-skills/skills/` and `starboard/skills/` (duplicated).

## Auth (current)

- **Server side**: `DatabricksAuthProvider` (`infra/auth/providers/databricks.py`) — assumes deployment inside Databricks Apps; `validate_session()` is a no-op returning True (platform reverse-proxy already authenticated). Calls `databricks.users.get_current_user()` + auto-provisions user.
- **Skills/helper side**: bare `WorkspaceClient()` → relies on databricks-sdk **unified auth chain** (env `DATABRICKS_HOST`/`DATABRICKS_TOKEN`, `~/.databrickscfg` profiles, OAuth, etc.).
- **Multi-workspace**: `mcp/workspace_manager.py` + `workspace_registry.py` + config `WorkspaceProfile`. Sprint notes flag "multi-workspace auth is env-var only (no OAuth2, no token refresh)" as a Future item.

## Data Sources — Discovery Query Packs (`discovery/query_packs/`, ~17 packs)

Each pack = curated queries over Databricks **system tables** / APIs:
`ai_gateway, aibi, apps, audit, billing, compute, dlt_pipelines, governance, jobs, lakebase, lakeflow_connect, migration, ml, mlflow, product_surfaces, query_performance, vector_search` + `registry.py`.
→ Evidence that starboard already reasons across the full Databricks system-tables surface.

## Tools Inventory (`tools/`)

- adapters: query, job, cluster, uc, warehouse, analytics_sql, diagnostic, discovery, intent, rag, source tools
- domain analyzers: cluster (health, metrics, fingerprint, resolver), **diagnostic (spark_event_log_extractor, query_profile_extractor, exit_code_triager, evidence_extractor, artifact_explorer)**
- services: warehouse portfolio, query workload, uc (lineage, storage, governance, catalog browser), chart_renderer/builder (viz), query_result_cache

## Internal Databricks Context

- Isaac = Databricks' internal AI coding agent (`.isaac/config.json` present). Internal analog to Claude Code; supports skills/agents. Research its extension model via internal sources (Glean).
- Available internal skills/tools in this environment worth mapping for reuse: `logs-summariser` MCP (ClickHouse log analysis), `fe-internal-tools:logfood-querier`, `dbr-doctor` MCP, `databricks-v2` MCP (`ask_genie`, warehouses, jobs, dashboards), `fe-internal-tools:genie-rooms`, `fe-internal-tools:centralized-system-tables-translator`, cluster-log retrieval skills.

## Just-Added (uncommitted)

`packages/starboard/starboard/notebooks.py` + tests — sync warehouse-resolution / serving-endpoint helpers for notebook use.

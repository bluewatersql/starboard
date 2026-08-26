# Starboard Decomposition — Opportunity Catalog

> Topic: **Decompose Starboard into individually consumable parts.**
> Envisioning study, commit `b927dfaa` (starboard 0.1.1). Research only — no code changes.
> Every unit below is traced to real code (file:line). Packaging is reasoned from first
> principles; it is **not** limited by the current 3-package layout.

---

## 1. The thesis in one paragraph

Starboard today ships as **3 pip packages + 1 monolithic FastMCP server + 2 divergent skill
trees**. But internally it is already built as a *catalog of capabilities*: ~45 explicitly-declared
tools (`agents/tools/registry.py:84-154`), ~17 discovery query packs
(`discovery/query_packs/`), a stack of **pure stateless analyzers** in `starboard-core`, 8
LLM domain agents (`mcp/agent_bridge.py:48-63`), and 9-10 skills. The decomposition
opportunity is to **stop shipping the box and start shipping the contents** — expose each
atomic capability on the surface that best fits its nature (pure → lib/CLI/MCP tool;
LLM-driven → agent/skill/plugin), and let a thin "meta" plugin recombine them.

## 2. What makes decomposition *possible today* (evidence)

| Enabler | Evidence | Why it matters for unbundling |
|---|---|---|
| Pure, I/O-free analyzers | `starboard-core/.../domain/analyzers/warehouse_analyzer.py:1-12` ("No I/O operations - only computation"); `uc_analyzer.py` | Directly shippable as dependency-light libs/CLIs |
| Explicit tool metadata registry | `agents/tools/registry.py:84` `ALL_TOOL_METADATA` (45 entries) | Each tool already has name+description+params schema → trivially re-exposable as standalone MCP tool / CLI subcommand |
| Query packs are declarative data | `discovery/query_packs/*.py` (17 packs) + `registry.py` | SQL-over-system-tables packs are portable data assets, no runtime coupling |
| Discovery has a deterministic mode | `discovery/engine.py:55` `data_only` (skip LLM), `:209` "LLM client not provided — skipping" | Discovery splits cleanly into a pure data unit + an optional LLM layer |
| Log parser is its own hexagon | `starboard-core/.../log_parser/` with `loaders/{dbfs,s3,https,local_file,json}.py`, `auth/providers.py`, `ports` | Already a self-contained sub-package with pluggable I/O — extractable as a standalone product |
| Chart renderer is pure | `tools/services/chart_renderer.py:26-28` (altair+polars+vl_convert only) | Standalone "Vega-Lite spec → PNG/SVG" lib, zero Databricks coupling |
| Agents are uniform + domain-keyed | `mcp/agent_bridge.py:48` `AGENT_DOMAINS`, `agents/domain/domain_agent.py`, `agent_factory.py` | 8 agents built from one template → each can ship as an individual subagent/skill |
| Tool scoping already exists | `mcp/server.py:352` `_register_tools` honors `tool_scope`; `tool_bridge.py:114` `resolve_allowed_tools` | The MCP surface is *already* filterable — a foundation for per-capability MCP bundles |

## 3. Decomposition friction / anti-patterns to fix (evidence)

| Problem | Evidence | Impact on consumability |
|---|---|---|
| **Skill tree duplication + drift** | Top-level `skills/starboard/*/SKILL.md` (10 skills) vs `packages/starboard-skills/skills/starboard/*/skill.md` (9 skills). `diff -rq` shows *different filenames* (`SKILL.md` vs `skill.md`) and *different content* (top-level has `name:`/`description:` metadata; package copies open with `# Starboard: …` markdown, no metadata) | Two sources of truth; the package copy is not even a valid discoverable skill |
| **SKILL.md frontmatter is unfenced** | All 10 `skills/starboard/*/SKILL.md` begin with a bare `name:` line — **no `---` YAML fence** (verified line 1 of every file) | Claude Code / Agent Skills require fenced YAML frontmatter; as written these may not parse as skills |
| **`starboard` package is a mega-distributable** | One wheel pulls fastapi, uvicorn, openai, asyncpg, pgvector, redis, altair, sqlglot, tiktoken, mcp, opentelemetry… (`packages/starboard/pyproject.toml:8-84`) | Cannot consume the exit-code triager without installing a web server + Postgres driver |
| **Core is "pure" but not dependency-trivial** | `starboard-core` depends on `polars` and `databricks-sdk>=0.60` (`starboard-core/pyproject.toml:14,16`); `log_parser/loaders/s3.py` implies cloud I/O adapters | The "no-I/O core" claim is aspirational — the log parser bundles I/O loaders, so a truly dependency-light math core is a *sub*-slice of core |
| **MCP surface omits discovery agent** | `agent_bridge.py:63` `_MCP_EXCLUDED_AGENT_DOMAINS = {"discovery"}` | Capability exists but isn't consumable via MCP — inconsistent surface coverage |
| **No plugin/marketplace manifest** | `find` for `plugin.json`/`marketplace.json` → none. Only `.mcp.json` (single stdio server) | Nothing is installable via the Claude Code plugin ecosystem today |

---

## 4. Unit taxonomy — the atomic capabilities

Grouped by **nature**. "Nature" drives which surfaces make sense (pure → lib/CLI/MCP; LLM → agent/skill).

### 4a. Pure / deterministic units (best as libs + CLIs + MCP tools)

| # | Unit | Current location (file:line) | What it does |
|---|---|---|---|
| P1 | **spark-log-parser** | `starboard-core/.../log_parser/` (`parsing_models/event_log_parser.py`, `loaders/*`, `auth/providers.py`) | Parse Spark/Photon event logs → structured job/stage/task/DAG models; pluggable dbfs/s3/https/local loaders |
| P2 | **warehouse-analyzer** | `starboard-core/.../domain/analyzers/warehouse_analyzer.py` | FingerprintCalculator + HealthScorer over query history (stateless) |
| P3 | **uc-analyzer** | `starboard-core/.../domain/analyzers/uc_analyzer.py` | UC metadata/access-pattern computation (stateless) |
| P4 | **chart-renderer** | `tools/services/chart_renderer.py`, `direct_chart_builder.py`, `chart_config_validator.py` | ChartConfig/Vega-Lite → PNG/SVG via altair+vl_convert |
| P5 | **exit-code-triager** | `tools/domain/diagnostic/exit_code_triager.py` | Map Spark/driver exit codes → failure class + hypothesis |
| P6 | **query-profile-extractor** | `tools/domain/diagnostic/query_profile_extractor.py`, `query_profile_explorer.py` | Extract metrics/bottlenecks from DBSQL query profiles |
| P7 | **spark-event-log-extractor** | `tools/domain/diagnostic/spark_event_log_extractor.py`, `spark_event_log_explorer.py` | Pull salient evidence out of parsed event logs |
| P8 | **diagnostic-pattern-matcher** | `tools/domain/diagnostic/pattern_matcher.py`, `patterns/registry.py`, `patterns/schema.py` | Rule/pattern registry matching failure signatures |
| P9 | **sql-validator** | `tools/domain/analytics_sql/sql_validator.py` (sqlglot) | Validate/lint generated SQL, dialect-check |
| P10 | **discovery-query-packs** | `discovery/query_packs/*.py` (17 packs) + `registry.py` | Curated SQL over Databricks system tables (billing, compute, jobs, governance, ml, …) |
| P11 | **discovery-heuristics** | `discovery/heuristics/{billing,compute,governance,jobs,query_perf}.py` | Deterministic scoring/flagging over query-pack results |
| P12 | **cluster-analyzers** | `tools/domain/cluster/{health_analyzer,cluster_metrics_analyzer,fingerprint_builder,resolver}.py` | Cluster health/metrics/fingerprint computation |
| P13 | **dataframe-profiler** | `tools/domain/analytics/dataframe_profiler.py` | Profile a result frame (types, cardinality, viz hints) |
| P14 | **service-catalog** | `config/service_catalog.yaml` (v1.2.0) + `tools/service_catalog_tool.py` | Cross-domain handoff/routing map (data + lookup) |
| P15 | **domain-models** | `starboard-core/.../domain/models/`, `models/`, `transformers/` | Shared Pydantic DTOs + transformers (the true dependency-light nucleus) |
| P16 | **prompt-library** | `prompts/` (12 domains) + `starboard-core` prompt templates | Versioned prompt/template assets |

### 4b. I/O adapter units (libs; require databricks-sdk)

| # | Unit | Current location | What it does |
|---|---|---|---|
| A1 | **databricks-fetchers** | `tools/adapters/{query,job,cluster,uc,warehouse,discovery,analytics_sql,diagnostic,source}_tools.py` | Thin SDK wrappers: fetch runs, logs, configs, metrics, table metadata, run SQL |
| A2 | **query-result-cache** | `tools/services/query_result_cache.py`, `cached_data_models.py` | Cache/replay SQL result sets |
| A3 | **warehouse-portfolio-service** | `tools/services/warehouse_portfolio_service.py`, `domain/warehouse/{topology,chargeback}.py` | Portfolio rollup, topology, chargeback generation |
| A4 | **query-workload-service** | `tools/services/query_workload_service.py` | Workload aggregation over query history |
| A5 | **notebook-helpers** (new) | `packages/starboard/starboard/notebooks.py` (uncommitted) | Sync warehouse-resolution / serving-endpoint helpers |

### 4c. LLM-driven units (best as subagents + skills + plugin; optionally MCP `*_agent` tools)

| # | Unit | Current location | What it does |
|---|---|---|---|
| L1 | **query-agent** | `agent_bridge.py:66`; `agent_factory.py`; `agents/domain/` | SQL perf reasoning |
| L2 | **job-agent** | `agent_bridge.py:70` | Job/run failure reasoning |
| L3 | **uc-agent** | `agent_bridge.py:74` | Unity Catalog reasoning |
| L4 | **cluster-agent** | `agent_bridge.py:78` | Cluster/compute reasoning |
| L5 | **analytics-agent (FinOps)** | `agent_bridge.py:82` | Cost/billing analytics via agentic SQL RAG |
| L6 | **warehouse-agent** | `agent_bridge.py:86` | DBSQL warehouse portfolio reasoning |
| L7 | **diagnostic-agent** | `agent_bridge.py:89` | RCA orchestration over diagnostic tools |
| L8 | **discovery-agent** | `agent_bridge.py:93` (MCP-excluded `:63`) | Workspace-wide health synthesis |
| L9 | **intent-router** | `agents/routing/`, `tools/domain/intent/resolver.py`, `services/intent/` | Classify user intent → domain |
| L10 | **discovery-engine (orchestrator)** | `discovery/engine.py:97` | 3-phase discover→execute→analyze; deterministic `data_only` mode + optional LLM |

### 4d. Runtime / composition units (infrastructure surfaces)

| # | Unit | Current location | Role |
|---|---|---|---|
| R1 | **agent-runtime** | `agents/domain/{reasoning_loop,reasoning_engine,tool_executor}.py` | The ReAct loop every domain agent runs on |
| R2 | **multi-agent-manager** | `agents/conversation/`, `MultiAgentConversationManager` | Coordinator that routes + hands off across agents |
| R3 | **mcp-server** | `mcp/server.py` (~37KB), `transports.py`, `tool_bridge.py`, `agent_bridge.py`, `composite_tools.py` | The current monolithic surface (stdio + HTTP) |
| R4 | **cli** | `cli/cli/main.py` (argparse), `cli/sessions/` | Interactive chat + session mgmt |
| R5 | **skills-helper** | `starboard_skills/helpers/{query,job,cluster,uc,warehouse,finops,diagnostic}.py` | `starboard-helper <domain> <cmd>` JSON emitter (no-MCP fallback) |
| R6 | **infra** | `infra/{auth,cache,rag,reliability,streaming,observability,...}` | Cross-cutting services |

---

## 5. Master decomposition table

Surfaces legend: **Lib** (pip import), **CLI** (console entry-point), **Skill** (SKILL.md), **Plugin** (Claude Code plugin), **MCP** (MCP tool), **Agent** (subagent). Reuse value = usefulness *outside* Starboard. LOE: S<1wk, M~1-2wk, L~3-4wk, XL>1mo.

| Unit | Loc (file:line) | Nature | Candidate surfaces | Reuse value | Strengths | Weaknesses | Trade-offs | Cx | LOE |
|---|---|---|---|---|---|---|---|---|---|
| **spark-log-parser** (P1) | `core/log_parser/` | Pure+pluggable I/O | Lib, CLI, MCP | **Very high** — any Spark shop | Self-contained hexagon; loaders already abstracted | `log_parser.*` excluded from mypy strict (`pyproject.toml`); loaders drag cloud deps | Split "pure parse" from "loaders" to stay light | Med | L |
| **warehouse-analyzer** (P2) | `core/.../warehouse_analyzer.py` | Pure | Lib, CLI, MCP | High | Stateless, documented no-I/O | Needs query-history DTO as input contract | Ship DTOs (P15) alongside | Low | S |
| **uc-analyzer** (P3) | `core/.../uc_analyzer.py` | Pure | Lib, MCP | Med | Stateless | Coupled to UC model shapes | — | Low | S |
| **chart-renderer** (P4) | `tools/services/chart_renderer.py` | Pure | Lib, CLI, MCP | **Very high** — generic | Zero Databricks coupling; PNG/SVG out | Heavy dep `vl-convert-python` | Optional extra for rasterization | Low | S |
| **exit-code-triager** (P5) | `.../diagnostic/exit_code_triager.py` | Pure | Lib, CLI, MCP, Skill | High | Tiny, deterministic, demo-friendly | Rule coverage is Databricks-specific | — | Low | S |
| **query-profile-extractor** (P6) | `.../diagnostic/query_profile_extractor.py` | Pure | Lib, CLI, MCP | High | Deterministic parse of DBSQL profiles | Profile JSON schema drift risk | Version the schema | Med | M |
| **spark-event-log-extractor** (P7) | `.../diagnostic/spark_event_log_extractor.py` | Pure | Lib, MCP | Med-High | Complements P1 | Depends on P1 models | Bundle with P1 | Med | M |
| **diagnostic-pattern-matcher** (P8) | `.../diagnostic/pattern_matcher.py` | Pure | Lib, MCP | Med | Extensible rule registry | Rules encode tribal knowledge | Ship rules as data pack | Low | M |
| **sql-validator** (P9) | `.../analytics_sql/sql_validator.py` | Pure | Lib, CLI, MCP | High | sqlglot-based, generic | Dialect edge cases | — | Low | S |
| **discovery-query-packs** (P10) | `discovery/query_packs/*` | Pure data | Lib, CLI, MCP, Skill | **Very high** — reusable SQL asset | 17 curated packs over system tables | SQL assumes system-table access/grants | Ship as data + a runner | Low | M |
| **discovery-heuristics** (P11) | `discovery/heuristics/*` | Pure | Lib, MCP | Med | Deterministic scoring | Coupled to pack output shape | Pair with P10 | Low | M |
| **cluster-analyzers** (P12) | `tools/domain/cluster/*` | Pure | Lib, MCP | Med | Stateless health/fingerprint | Needs metrics DTO input | — | Low | M |
| **dataframe-profiler** (P13) | `.../analytics/dataframe_profiler.py` | Pure | Lib, MCP | High (generic) | Works on any polars frame | — | — | Low | S |
| **service-catalog** (P14) | `config/service_catalog.yaml` | Data+lookup | Lib, MCP | Med | Declarative routing map | Only useful with ≥2 agents | Ship with meta-bundle | Low | S |
| **domain-models** (P15) | `core/.../models/` | Pure | Lib | High (foundation) | Zero-dep-ish nucleus | Pydantic dep only | The true light core | Low | S |
| **prompt-library** (P16) | `prompts/`, core templates | Data | Lib, Plugin | Med | Versioned, testable (golden tests) | Prompts tied to agent design | Ship with agents | Low | S |
| **databricks-fetchers** (A1) | `tools/adapters/*` | I/O | Lib, MCP | High | Uniform SDK wrappers | Needs SDK + auth | The I/O boundary; keep separate from pure units | Med | L |
| **query-result-cache** (A2) | `tools/services/query_result_cache.py` | I/O | Lib | Low-Med | Reusable cache | Storage-backend choices | — | Low | M |
| **warehouse-portfolio-service** (A3) | `tools/services/warehouse_portfolio_service.py` | I/O+pure | Lib, CLI, MCP | Med | Chargeback is a killer feature | Composes A1+P2 | — | Med | M |
| **query-workload-service** (A4) | `tools/services/query_workload_service.py` | I/O+pure | Lib, MCP | Med | — | Composes A1+P6 | — | Med | M |
| **notebook-helpers** (A5) | `notebooks.py` (uncommitted) | I/O | Lib | Med | Notebook-native UX | New, untested surface | — | Low | S |
| **7 domain agents** (L1-L7) | `agent_bridge.py:66-89` | LLM | Agent, Skill, Plugin, MCP `*_agent` | High (in-ecosystem) | Uniform factory template | Need LLM creds + runtime R1 | Ship each as subagent + skill pair | Med | L (all) |
| **discovery-agent** (L8) | `agent_bridge.py:93` | LLM | Agent, Skill, Plugin | Med | Whole-workspace synthesis | MCP-excluded today (`:63`) | Re-include or ship as skill | Med | M |
| **intent-router** (L9) | `agents/routing/` | LLM | Lib, MCP, Agent | Med | Enables one-entry UX | Only valuable with many agents | Optional coordinator | Med | M |
| **discovery-engine** (L10) | `discovery/engine.py:97` | Hybrid | Lib, CLI, MCP, Agent | High | Deterministic `data_only` + LLM layer | Orchestration complexity | Expose data_only as pure CLI | Med | L |
| **agent-runtime** (R1) | `agents/domain/reasoning_loop.py` | Infra | Lib | High (framework) | The reusable ReAct engine | Tightly-typed to Starboard events | Could become "starboard-agent-kit" | High | L |
| **multi-agent-manager** (R2) | `agents/conversation/` | Infra | Lib, MCP | Med | Coordinator + handoff | Heavy; needs all agents | The "meta" composition point | High | L |
| **mcp-server** (R3) | `mcp/server.py` | Surface | (stays a surface) | — | Already scope-filterable (`:352`) | Monolithic; 37KB server.py | Refactor to compose per-capability bundles | High | L |
| **cli** (R4) | `cli/cli/main.py` | Surface | CLI | — | argparse-based | Not plugin-friendly | Becomes umbrella CLI over units | Med | M |
| **skills-helper** (R5) | `starboard_skills/helpers/*` | Surface | CLI | Med | No-MCP fallback path | Bare `WorkspaceClient()` auth | Fold into per-unit CLIs | Low | M |

---

## 6. Reuse-value ranking (outside-Starboard usefulness)

1. **chart-renderer (P4)** — generic Vega-Lite→image, no Databricks coupling.
2. **spark-log-parser (P1)** — valuable to *any* Spark/Databricks user.
3. **discovery-query-packs (P10)** — a portable, curated system-tables SQL asset.
4. **exit-code-triager (P5)** + **query-profile-extractor (P6)** — tiny, deterministic, demo-ready diagnostic primitives.
5. **dataframe-profiler (P13)** + **sql-validator (P9)** — generic data-tooling.
6. **warehouse-analyzer (P2)** / **uc-analyzer (P3)** — reusable given DTO contracts.

These six are the strongest candidates to lead an unbundling program: high external value, low LOE, minimal dependencies.

## 7. Cross-topic note (agent_integration)

The *formats* for skill/plugin/MCP packaging are owned by the **agent_integration** topic. This
catalog assumes those formats and focuses on **which capability maps to which surface**. See
`technical.md` for the concrete manifests, and `open_questions.md` for the format questions that
must be resolved jointly.

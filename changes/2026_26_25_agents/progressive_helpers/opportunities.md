# Dep-ful Progressive-Disclosure Helpers — Opportunity Catalog

> Topic A (Round 2): a **middle tier** between the ultra-thin, zero-starboard-dep
> `starboard-helper` CLI and the heavy long-lived MCP server. Middle-tier helpers **MAY
> `pip install` starboard deps** and are surfaced through **Agent-Skills progressive disclosure**:
> a `SKILL.md` names a script + reference files, Claude loads them only when the skill fires,
> then shells out to `python -m …`. Context cost stays near-zero until used; deps are installed
> once, but never loaded into the model context.
> Envisioning study, commit `b927dfaa` (starboard 0.1.1). Research only — no code changes.
> Every capability traced to real code (`file:line`); packaging reasoned from first principles.

---

## 1. The thesis: the weight is in the *wheel*, not the *code*

The single most important finding, verified from the import graph:

- The `starboard` distributable declares **~40 heavy runtime deps** — fastapi, uvicorn,
  starlette, python-multipart, openai, tiktoken, redis, asyncpg, pgvector, aiosqlite, sqlite-vec,
  slowapi, mcp, opentelemetry, cryptography/cffi/protobuf pins
  (`packages/starboard/pyproject.toml:8-82`).
- But the **analytical capabilities themselves import almost none of that.** The package root is
  effectively empty — `packages/starboard/starboard/__init__.py:17` is just `__version__`; it does
  **not** import the server. `tools/__init__.py` has **0 imports**; `tools/domain/__init__.py` has 1.
- The diagnostic extractors import only stdlib + a `structlog`-based logger:
  `exit_code_triager.py:18-19` (dataclasses, enum — **zero third-party**);
  `evidence_extractor.py:18-21` (hashlib, re — **zero third-party**);
  `query_profile_extractor.py:21-26` and `spark_event_log_extractor.py:22-27` (json + the shared
  logger `infra/observability/logging.py`, which imports only `structlog` — verified `:11-19`).
  `pattern_matcher.py:20-30` adds `pyyaml`+`pydantic` (via `patterns/registry.py:23-25`).

⇒ **Repackaging, not rewriting.** The middle tier is a *new slim distributable* (call it
`starboard-x`) that re-exposes these modules with **per-capability extras**, so a helper can be
installed with only the deps it needs (`pydantic`+`polars` for analyzers; `+altair,vl-convert` for
charts; `+databricks-sql-connector` for the I/O ones). This is the same "layered catalog / thin
wheels" target the **decomposition** topic recommends (`starboard_decomposition/recommendation.md:83-108`),
consumed here through progressive disclosure instead of an always-on server.

### One real friction point
`tools/domain/diagnostic/__init__.py:16-96` **eagerly imports the whole diagnostic subsystem**
(artifact_explorer, exploration_observability, handoff_protocol, …). Importing one extractor today
therefore drags every sibling. Those siblings are still light (stdlib + structlog + pydantic +
pyyaml — verified), so the sub-package as a whole is cheap; but a clean per-capability helper wants
the eager `__init__` trimmed (or the module imported by full path from a re-cut package). LOE-relevant.

---

## 2. The 3-tier model

| Dimension | **Tier 0 — no-dep helper** | **Tier 1 — dep-ful progressive helper** (this topic) | **Tier 2 — MCP server** |
|---|---|---|---|
| Artifact | `starboard-helper` CLI (`packages/starboard-skills/`, `pyproject.toml:12-13`) | `starboard-x` slim wheel + `python -m` modules, installed per-capability extras | `starboard-mcp` (`packages/starboard/starboard/mcp/`, ~4,800 LOC) |
| Deps installed | `databricks-sdk`, `rich`, `python-dotenv` (`starboard-skills/pyproject.toml:6-10`) | per-capability: `pydantic`/`polars`(+`sqlglot`/`altair`+`vl-convert`/`pyyaml`/`databricks-sql-connector`) | full ~40-dep mega-wheel (`starboard/pyproject.toml:8-82`) |
| What it does | **fetch** raw Databricks telemetry → JSON (bare `WorkspaceClient()`) | **analyze** with the real Starboard analyzers/extractors, deterministically | **reason** — 7 LLM agents, IntentRouter, cross-domain handoff, RAG SQL |
| Context cost | near-zero (subprocess, JSON) | **near-zero until the skill fires** (only ~1.5KB description resident) | persistent: tool schemas + resources always in the model's tool list |
| Lifecycle | one-shot subprocess | one-shot subprocess (`python -m …`) | **long-lived server** (stdio/HTTP), rate limiter, circuit breakers, auth ctx |
| Depth | shallow (raw rows) | **deep, deterministic** (fingerprints, RCA chains, heuristics, charts) | **deepest** (LLM synthesis + memory + cross-agent) |
| Auth | unified SDK chain | unified SDK chain (I/O helpers) / none (pure helpers) | `DatabricksAuthProvider`, Apps reverse-proxy (`infra/auth/providers/databricks.py`) |
| Best for | quick lookups, "list/get" verbs | **the 80%: real single-domain analysis without a server** | multi-turn, cross-domain, natural-language orchestration |

**Design rule:** a verb that only *fetches* stays Tier 0; a verb that *computes/analyzes*
deterministically becomes a Tier 1 progressive helper; a verb that needs *LLM reasoning, memory, or
cross-domain routing* stays Tier 2.

---

## 3. Progressive-disclosure mechanics (verified against current docs)

Source: `https://code.claude.com/docs/en/skills` (fetched 2026-08-26) and the Agent Skills open
standard `https://agentskills.io`. Three disclosure levels — each costs context only at its level:

1. **Always resident (~cheap):** only the skill's `name` + `description` (+ optional `when_to_use`),
   **truncated at 1,536 chars** in the skill listing (docs: Frontmatter reference). This is the sole
   permanent context cost. Claude auto-invokes on match; the body is *not* resident yet.
2. **On fire — `SKILL.md` body loads** and then "stays in context across turns" (docs: Skill content
   lifecycle) — so keep the body **< 500 lines** (docs Tip). This is the trigger + shell-out recipe.
3. **On demand — supporting files.** `reference.md` / `examples.md` are "loaded when needed";
   `scripts/*.py` are **"executed, not loaded"** (docs: Add supporting files). Deep reference material
   and the dep-ful code therefore **never enter context** — Claude runs the script and reads only its
   JSON stdout.

Key primitives this topic relies on (all verified in the docs):
- **`allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)`** pre-approves the exact shell-out so
  the dep-ful script runs **without a permission prompt** (docs: "the `allowed-tools` rule then
  matches the exact command the skill body tells Claude to run, so the script runs without prompting").
- **`${CLAUDE_SKILL_DIR}` / `${CLAUDE_PLUGIN_ROOT}`** resolve the bundled script path regardless of cwd
  (docs: Available string substitutions).
- **`` !`cmd` `` dynamic context injection** runs a command *before* the body is sent and inlines its
  output — usable to inline a `--help` or a small JSON result directly (docs: Inject dynamic context).
- **`context: fork` + `agent`** run the skill in a subagent so even the body cost is isolated from the
  main thread (docs: Run skills in a subagent).
- **Spec portability:** outside Claude Code, only `name, description, license, compatibility, metadata,
  allowed-tools` are valid (docs: Using skill frontmatter outside Claude Code) — so the dep-ful helper
  design stays portable to OpenCode `.opencode/skills/` and the claude.ai Skills API.

**How context stays low with real depth:** the model never sees polars/altair/sqlglot, never sees the
extractor source, never holds a tool schema. It sees ~1.5KB of description until the user asks a
matching question; then a <500-line body telling it to run `python -m starboard_x.diagnostic
triage-exit --exit-code 137`; then only the compact JSON verdict. Depth lives in the subprocess.

---

## 4. Capability catalog

Deps legend — **P** pydantic, **Po** polars, **Sg** sqlglot, **Al** altair+vl-convert-python,
**Y** pyyaml, **Sl** structlog, **Np** numpy, **Sdk** databricks-sdk, **Sql** databricks-sql-connector,
**Su** stream-unzip. "0-dep" = Python stdlib only. LOE: S<1wk, M~1-2wk, L~3-4wk, XL>1mo.

| # | Capability | Current loc (file:line) | What it does | Deps dragged | Script interface (`python -m …`) | Disclosure trigger | Depth gained vs Tier 0 | Cx | LOE |
|---|---|---|---|---|---|---|---|---|---|
| C1 | **exit-code-triager** | `tools/domain/diagnostic/exit_code_triager.py:239` (`ExitCodeTriager.triage` :256) | Exit code → failure class + ranked hypotheses + confidence + next steps | **0-dep** (+Sl,P via `__init__`) | `starboard_x.diagnostic triage-exit --exit-code 137 [--context k=v]` | "exit code", "137/143", "OOM killed", "job failed with code" | hypotheses+proof-signals+remediation vs a bare number | Low | **S** |
| C2 | **evidence-extractor** | `tools/domain/diagnostic/evidence_extractor.py:244` (`.extract` :275) | Slice raw error text into typed evidence windows (dedup by hash) | **0-dep** | `starboard_x.diagnostic extract-evidence --text err.log` | "error log", "stack trace", "what happened in this log" | structured windows + summary vs a text blob | Low | **S** |
| C3 | **query-profile-extractor** | `tools/domain/diagnostic/query_profile_extractor.py:60` (`.__init__(top_operators)` :79) | DBSQL query-profile JSON → slowest/scan/shuffle operators, distilled bottleneck | Sl (+P) | `starboard_x.diagnostic query-profile --profile p.json [--top 10]` | "query profile", "why is this query slow", "spill/shuffle" | ranked operator bottlenecks vs raw profile JSON | Med | **M** |
| C4 | **spark-event-log-extractor** | `tools/domain/diagnostic/spark_event_log_extractor.py:87` (skew detect :253) | Parsed Spark app → skew flags, slow stages (>60s), summary | Sl (+P); pairs w/ C9 | `starboard_x.diagnostic spark-evidence --app parsed.json` | "spark stages", "data skew", "slow stage" | skew/slow-stage evidence vs raw event log | Med | **M** |
| C5 | **pattern-matcher + registry** | `pattern_matcher.py:76`; `patterns/registry.py:52`; `patterns/catalog/*.yaml` (8 rule packs: tier1_memory/network/sql, tier1b_execution, tier2_data/delta/misc/uc) | Regex/rule catalog → matched failure signatures + confidence | Y,P,Sl | `starboard_x.diagnostic match-patterns --text err.log [--catalog dir]` | "known error", "recognize this failure", "match pattern" | curated failure taxonomy vs manual grep | Low | **M** |
| C6 | **root-cause-synthesizer** | `tools/domain/diagnostic/root_cause_synthesizer.py:145` (`.synthesize` :156) | Fuse pattern matches + tool outputs → primary symptom, root causes, evidence chain, actions | **0-dep** (+P) | `starboard_x.diagnostic synthesize --matches m.json --tools t.json` | (composite) "root cause", "why did this fail" | **deterministic RCA** (no LLM) vs nothing at Tier 0 | Med | **M** |
| C7 | **diagnostic RCA bundle** (C2+C5+C6, opt C1/C3/C4) | as above | End-to-end: text → evidence → patterns → synthesized RCA | Y,P,Sl | `starboard_x.diagnostic rca --text err.log [--exit-code N] [--profile p.json]` | "diagnose this failure end to end" | full local RCA pipeline sans server/LLM | Med | **L** |
| C8 | **discovery `data_only` + query packs** | `discovery/engine.py:97` (`EngineConfig.data_only` :65; `data_only` branch :202-211 "LLM client not provided — skipping"); `query_packs/*` (**17 packs**) + `registry.py`; `heuristics/{billing,compute,governance,jobs,query_perf}.py` | Run curated system-table SQL packs + deterministic heuristic scoring; skip LLM synthesis | Po,P,Sql,Sdk | `starboard_x.discovery run --data-only [--packs billing,jobs,compute]` | "workspace health scan", "what's costing money", "audit my workspace" | scored findings across 17 domains vs raw fetch | Med | **L** |
| C9 | **spark-log-parser** | `starboard-core/.../log_parser/` (`parsing_models/event_log_parser.py`; loaders `dbfs,s3,https,local_file,json`; `auth/providers.py`; `application/factory.py`) | Parse Spark/Photon event logs → job/stage/task/DAG/executor models | Po,Np,Su,P,httpx; **loaders as extras**: `[aws]`boto3 / `[azure]` / `[gcp]` (`starboard-core/pyproject.toml:20-33`) | `starboard_x.sparklog parse --source dbfs --path … [--out json]` | "parse event log", "stage/task breakdown", "photon metrics" | full structured Spark model vs opaque log | Med | **L** |
| C10 | **warehouse-analyzer (pure)** | `starboard-core/.../domain/analyzers/warehouse_analyzer.py:134` (`FingerprintCalculator`), `:651` (`HealthScorer`) | Query-history → workload fingerprint + health score (stateless, no I/O) | Po,P | `starboard_x.warehouse analyze --history hist.json [--window-days 30]` | "warehouse health", "warehouse fingerprint" | fingerprint+health score vs raw history rows | Low | **S** |
| C11 | **warehouse-portfolio-service (I/O)** | `tools/services/warehouse_portfolio_service.py:83` (`.get_portfolio` :207, `.get_fingerprint` :360); `tools/domain/warehouse/{topology,chargeback}.py` | Portfolio rollup, topology, **chargeback** across warehouses (composes C10 + fetch) | Po,P,Sdk,Sql | `starboard_x.warehouse portfolio --window-days 30` | "warehouse portfolio", "chargeback", "cost by warehouse" | chargeback/topology vs per-warehouse rows | Med | **M** |
| C12 | **query-workload-service** | `tools/services/query_workload_service.py:137` (`QueryPatternAnalyzer.analyze` :160) | SQL-history → join keys, filter columns, aggregation patterns, fingerprints | Po,Sg,P,Sql | `starboard_x.warehouse workload --window-days 7` | "workload patterns", "what queries hit this warehouse" | pattern/fingerprint clustering vs raw SQL list | Med | **M** |
| C13 | **uc-analyzer (pure)** | `starboard-core/.../domain/analyzers/uc_analyzer.py:40` (`UCAnalyzer`), `:1003` (`TableAnalyzer`) | UC metadata/access-pattern anomaly computation (stateless) | P (+statistics stdlib) | `starboard_x.uc analyze --input uc.json` | "UC anomaly", "access pattern" | anomaly scoring vs raw grants | Low | **S** |
| C14 | **uc lineage/storage/governance services** | `tools/services/uc_service.py:65`; `services/uc/{lineage,storage_analysis,governance,catalog_browser,table_metadata}.py` | Table lineage, storage analysis, policy coverage, catalog browsing (composes C13 + fetch) | P,Sdk,Sql | `starboard_x.uc {lineage\|storage\|governance\|browse} --table c.s.t` | "table lineage", "storage bloat", "policy coverage" | lineage/policy analysis vs metadata dump | Med | **L** |
| C15 | **cluster analyzers** | `tools/domain/cluster/{health_analyzer,cluster_metrics_analyzer:140,fingerprint_builder,resolver}.py` | Cluster health scoring, metrics analysis, fingerprint, compute resolution | P,Sl (+Sdk for resolver I/O) | `starboard_x.cluster {health\|metrics\|fingerprint} --input metrics.json` | "cluster health", "cluster fingerprint", "is my cluster sized right" | health/fingerprint vs raw metrics | Med | **M** |
| C16 | **chart-renderer** | `tools/services/chart_renderer.py:41` (`ChartRenderer`); `direct_chart_builder.py`; `chart_config_validator.py` | ChartConfig/Vega-Lite → PNG/SVG (zero Databricks coupling) | **Al** (altair+vl-convert-python), Po | `starboard_x.charts render --config c.json --out c.png` | "render chart", "visualize this", "make a PNG" | publishable image vs a data table | Low | **S** |

---

## 5. Strengths / weaknesses / trade-offs per capability class

| Class (caps) | Strengths | Weaknesses | Trade-offs |
|---|---|---|---|
| **0-dep diagnostics** (C1,C2,C6) | Trivially light; demo-ready; deterministic; huge value/weight | Rules/heuristics are Databricks-specific; C6 needs C5 inputs | Ship first; almost free to add to `starboard-helper` itself if desired |
| **light-dep diagnostics** (C3,C4,C5) | Real bottleneck/skew/pattern depth for +`structlog`/`pyyaml`; C5's 8 YAML rule packs are portable data | JSON-schema drift risk (profile/event-log/pattern formats); C4 depends on C9's parsed model | Version the input schemas; bundle C4 with C9 |
| **discovery** (C8) | Highest breadth — 17 system-table packs + heuristics; deterministic path already exists in code | Needs SQL warehouse + system-table grants; heavier deps (polars+sql connector) | The flagship dep-ful helper; the LLM synthesis layer stays Tier 2 |
| **spark-log-parser** (C9) | Highest external reuse; already a self-contained hexagon with pluggable loaders + cloud extras | Loaders drag cloud SDKs (gate behind extras); parser is the heaviest pure unit | Split "pure parse" (local/json) from cloud loaders via extras |
| **warehouse/uc/cluster** (C10-C15) | Pure analyzers are light; I/O services add chargeback/lineage — genuine killer features | I/O services need SDK+auth; compose pure+fetch, so more surface | Ship the pure analyzer as a helper first; add the I/O service verb when auth story is set |
| **chart-renderer** (C16) | Generic, no Databricks coupling; instant visual payoff | `vl-convert-python` is a heavy binary wheel | Gate behind a `[charts]` extra so non-viz helpers stay slim |

---

## 6. Depth-vs-weight ranking (value ÷ dep-weight)

1. **C1 exit-code-triager**, **C2 evidence-extractor**, **C6 synthesizer** — 0-dep, high value. *Best ratio.*
2. **C10 warehouse-analyzer**, **C13 uc-analyzer** — pydantic-only pure analyzers.
3. **C3 query-profile-extractor**, **C5 pattern-matcher** — light deps, real diagnostic depth.
4. **C16 chart-renderer** — high payoff but a heavy binary dep ⇒ its own extra.
5. **C8 discovery data_only** — highest breadth; worth polars+sql-connector weight.
6. **C9 spark-log-parser** — highest reuse; heaviest pure unit; cloud loaders behind extras.
7. **C11/C12/C14/C15 I/O services** — deep, but drag SDK + auth; ship after the pure tier.

**Not worth the dep cost — stay Tier 0 (`starboard-helper`):** raw fetch verbs (`job list`,
`warehouse list`, `cluster list`, `uc catalogs`, `run-state`) — SDK passthrough with no analytical
depth (`packages/starboard-skills/starboard_skills/helpers/*.py`).

**Cannot be a helper — stay Tier 2 (MCP server):** the 7 LLM domain agents + IntentRouter +
`MultiAgentConversationManager` (cross-domain handoff), RAG-backed Analytics SQL generation, and any
multi-turn/long-running flow needing progress notifications, conversation memory, or persistent
state. These need an LLM, a tool registry, and a lifecycle a one-shot `python -m` cannot provide.

# Hero Workflows

Five end-to-end, **public** Starboard workflows — the persuasive story of what the
agent experience feels like from goal to answer. Every workflow uses only public
`system.*` data, and every dollar figure is a **list-price DBU estimate**.

Each flow shows the same three beats: **goal → invocation → what the user sees**,
and how the flow is reached across the four hosts — **Claude Code**, **Codex**,
**Genie**, and **OpenCode**. Every surface named here is a real catalogued
capability (see the [Capability Catalog](../reference/CATALOG.md)); a CI job
([`scripts/validate_examples.py`](../reference/CATALOG.md)) runs each example
against a mocked Databricks + LLM and fails the docs build on a stale date or a
reference to a surface that does not exist.

> **Dollar figures are list-price DBU estimates** — always labelled as such.
> These flows never touch a live workspace to validate; they run against
> synthetic `system.*` data.

---

## 1. Query Optimization Sprint

<!-- VALIDATED: 2026-08-29 -->

**Goal.** "I have a SQL query running ~10 minutes; help me make it fast and cheap."

**Invocation.**

- **Claude Code / Codex / OpenCode** — the `starboard-query` skill triggers on
  intent, or invoke the domain agent directly (`mcp__starboard__query_agent`).
- **CLI** — `starboard --goal "optimize query statement_id:01f0…"`.
- **Genie** — reach the same query agent as an MCP tool from a Genie space.

**Flow.** `resolve_query` fetches the SQL from the statement id →
`analyze_query_plan` runs `EXPLAIN EXTENDED` → `get_table_metadata` reads
partitioning and size → the agent ranks the fixes.

**What the user sees.** An advisor report: the query scans ~480 GB with only 3%
file pruning; the top fix is a partition filter / Z-ORDER to prune the scan, with
a **list-price DBU $** estimate of the savings and the plan evidence cited.

| Host | Entry point |
|------|-------------|
| Claude Code / Codex / OpenCode | skill `starboard-query` → `mcp__starboard__query_agent` |
| CLI | `starboard --goal "optimize query …"` |
| Genie | `query_agent` MCP tool |

---

## 2. Job Debugging Detective

<!-- VALIDATED: 2026-08-29 -->

**Goal.** "My ETL job keeps failing. What went wrong and how do I stop paying for
retries?"

**Invocation.**

- **Claude Code / Codex / OpenCode** — the `starboard-job` skill, or
  `mcp__starboard__job_agent`.
- **CLI** — `starboard --goal "why is job 987654321 failing"`.
- **Genie** — the `job_agent` MCP tool.

**Flow.** `resolve_job` normalizes the job/run target → `get_run_output` pulls the
run + task logs → `get_source_code` retrieves the task source → `analyze_code_quality`
flags Spark anti-patterns.

**What the user sees.** A root-cause report: the job fails on 35% of runs and wastes
billed DBU on retries; the fix is the failing task plus a retry ceiling, with the
failing run and log lines cited and a **list-price DBU $** estimate of the wasted
spend.

| Host | Entry point |
|------|-------------|
| Claude Code / Codex / OpenCode | skill `starboard-job` → `mcp__starboard__job_agent` |
| CLI | `starboard --goal "debug job …"` |
| Genie | `job_agent` MCP tool |

---

## 3. Unity Catalog Governance Audit

<!-- VALIDATED: 2026-08-29 -->

**Goal.** "Show me the Unity Catalog governance gaps — tables without owners,
grants, or tracked lineage."

**Invocation.**

- **Claude Code / Codex / OpenCode** — the `starboard-uc` skill, or
  `mcp__starboard__uc_agent`.
- **CLI** — `starboard --goal "find UC governance gaps in sales.public"`.
- **Genie** — the `uc_agent` MCP tool.

**Flow.** `list_uc_assets` enumerates catalogs/schemas/tables → `get_table_grants`
reads effective permissions → `get_table_lineage` maps upstream/downstream →
`analyze_policy_coverage` scores the governance posture.

**What the user sees.** A ranked governance report: `sales.public.orders` has no
owner and no grants; the fix is to assign an owner and least-privilege grants,
with the offending tables and missing-policy evidence cited.

| Host | Entry point |
|------|-------------|
| Claude Code / Codex / OpenCode | skill `starboard-uc` → `mcp__starboard__uc_agent` |
| CLI | `starboard --goal "find UC governance gaps"` |
| Genie | `uc_agent` MCP tool |

---

## 4. FinOps Cost Drill-Down

<!-- VALIDATED: 2026-08-29 -->

**Goal.** "Where is our compute spend going? Show me the top cost drivers."

**Invocation.**

- **Claude Code / Codex / OpenCode** — the `starboard-finops` skill, or the
  analytics agent (`mcp__starboard__analytics_agent`).
- **CLI** — `starboard --goal "top 10 cost drivers this month"`.
- **Genie** — the `analytics_agent` MCP tool over a Genie space.

**Flow.** `build_analytics_context` builds RAG context over the billing
`system.*` tables → `build_sql_query` generates the attribution SQL →
`execute_sql_query` runs it and formats the result.

**What the user sees.** A ranked cost report: SQL compute is the top driver at 34%
of **list-price DBU $** spend; the fix is fleet right-sizing plus aggressive
auto-stop, with each cost line attributed to a SKU from `system.billing.usage`.

| Host | Entry point |
|------|-------------|
| Claude Code / Codex / OpenCode | skill `starboard-finops` → `mcp__starboard__analytics_agent` |
| CLI | `starboard --goal "top cost drivers"` |
| Genie | `analytics_agent` MCP tool |

---

## 5. Workspace Health Scorecard

<!-- VALIDATED: 2026-08-29 -->

**Goal.** "Give me a one-page health check of my workspace."

**Invocation.**

- **CLI** — `starboard --discover` (non-agentic, four-phase discovery pipeline).
- **Claude Code / Codex / OpenCode** — the `starboard-discovery` skill, or
  `run_workspace_discovery` as an MCP tool.
- **Offline / embedded** — `python -m starboard_x.discovery` (the progressive
  helper) for a dependency-light run.

**Flow.** `run_workspace_discovery` queries the `system.*` tables, applies
best-practice heuristics, and grades each domain → the report ranks the top
issues.

**What the user sees.** A scorecard: the workspace scores 62/100, dragged down by
the jobs domain (three jobs without a run-as identity); the fix is to attribute
run-as identities and remediate the top issues, with per-domain scores and
evidence.

| Host | Entry point |
|------|-------------|
| CLI | `starboard --discover` |
| Claude Code / Codex / OpenCode | skill `starboard-discovery` → `run_workspace_discovery` |
| Offline | `python -m starboard_x.discovery` |

---

## See also

- [Capability Catalog](../reference/CATALOG.md) — every surface these flows use
- [How to choose: skill vs tool vs agent vs helper](../guides/AGENT_EXPERIENCE.md)
- [Validated Examples](VALIDATED_EXAMPLES.md) — the tested registry behind this page
- [Personas](PERSONAS.md) — internal Isaac flows (clearly scoped)

---
# Registry of tested example prompts (machine-readable source of truth).
#
# `scripts/validate_examples.py` reads this frontmatter, resolves every `surface`
# against the LIVE capability catalog (public surfaces via scripts/gen_catalog.py;
# gated ports via starboard.ports.registry.Port), runs each `prompt` against a
# MOCKED Databricks + LLM, asserts the report contains every `expect` key, and
# enforces `last_verified` freshness. `--check` fails the docs build on a stale
# date or a reference to a surface that does not exist.
last_verified: 2026-08-29
examples:
  - id: query-optimization-sprint
    title: Query Optimization Sprint
    page: examples/HERO_WORKFLOWS.md
    audience: public
    domain: query
    hosts: [Claude Code, Codex, Genie, OpenCode]
    prompt: "Optimize query statement_id:01f0mock-query-history-0001 — it runs ~10 minutes."
    surfaces:
      - {kind: skills, name: starboard-query}
      - {kind: agents, name: starboard-query}
      - {kind: mcp-tools, name: resolve_query}
      - {kind: mcp-tools, name: analyze_query_plan}
      - {kind: mcp-tools, name: get_table_metadata}
      - {kind: cli-commands, name: "starboard --goal / --chat"}
    expect: [summary, findings, recommendations, cost_estimate]
    last_verified: 2026-08-29
  - id: job-debugging-detective
    title: Job Debugging Detective
    page: examples/HERO_WORKFLOWS.md
    audience: public
    domain: job
    hosts: [Claude Code, Codex, Genie, OpenCode]
    prompt: "Why does job 987654321 keep failing and wasting DBU on retries?"
    surfaces:
      - {kind: skills, name: starboard-job}
      - {kind: agents, name: starboard-job}
      - {kind: mcp-tools, name: resolve_job}
      - {kind: mcp-tools, name: get_run_output}
      - {kind: mcp-tools, name: get_source_code}
      - {kind: mcp-tools, name: analyze_code_quality}
      - {kind: cli-commands, name: "starboard --goal / --chat"}
    expect: [summary, findings, recommendations, cost_estimate]
    last_verified: 2026-08-29
  - id: uc-governance-audit
    title: Unity Catalog Governance Audit
    page: examples/HERO_WORKFLOWS.md
    audience: public
    domain: uc
    hosts: [Claude Code, Codex, Genie, OpenCode]
    prompt: "Find Unity Catalog governance gaps in sales.public — tables without owners or grants."
    surfaces:
      - {kind: skills, name: starboard-uc}
      - {kind: agents, name: starboard-uc}
      - {kind: mcp-tools, name: list_uc_assets}
      - {kind: mcp-tools, name: get_table_grants}
      - {kind: mcp-tools, name: get_table_lineage}
      - {kind: mcp-tools, name: analyze_policy_coverage}
      - {kind: cli-commands, name: "starboard --goal / --chat"}
    expect: [summary, findings, recommendations, cost_estimate]
    last_verified: 2026-08-29
  - id: finops-cost-drill-down
    title: FinOps Cost Drill-Down
    page: examples/HERO_WORKFLOWS.md
    audience: public
    domain: finops
    hosts: [Claude Code, Codex, Genie, OpenCode]
    prompt: "Where is our compute spend going? Show me the top 10 cost drivers this month."
    surfaces:
      - {kind: skills, name: starboard-finops}
      - {kind: agents, name: starboard-finops}
      - {kind: mcp-tools, name: build_analytics_context}
      - {kind: mcp-tools, name: build_sql_query}
      - {kind: mcp-tools, name: execute_sql_query}
    expect: [summary, findings, recommendations, cost_estimate]
    last_verified: 2026-08-29
  - id: workspace-health-scorecard
    title: Workspace Health Scorecard
    page: examples/HERO_WORKFLOWS.md
    audience: public
    domain: discovery
    hosts: [Claude Code, Codex, Genie, OpenCode]
    prompt: "Give me a one-page health check of my workspace."
    surfaces:
      - {kind: skills, name: starboard-discovery}
      - {kind: agents, name: starboard-discovery}
      - {kind: mcp-tools, name: run_workspace_discovery}
      - {kind: cli-commands, name: "starboard --discover"}
      - {kind: progressive-helpers, name: discovery}
    expect: [summary, findings, recommendations, cost_estimate]
    last_verified: 2026-08-29
  - id: isaac-account-team-multitenant
    title: "Isaac — Account team: multi-tenant management"
    page: examples/PERSONAS.md
    audience: internal
    domain: internal
    hosts: [Isaac]
    prompt: "Show workload distribution and cost trends across my Pro-tier customers."
    surfaces:
      - {kind: agents, name: starboard-discovery}
      - {kind: agents, name: starboard-finops}
      - {kind: internal-gated, name: fleet_sql, gated: true}
      - {kind: internal-gated, name: log_retrieval, gated: true}
    expect: [summary, findings, recommendations, cost_estimate]
    last_verified: 2026-08-29
  - id: isaac-field-engineer-poc
    title: "Isaac — Field engineer: pre-sales POC"
    page: examples/PERSONAS.md
    audience: internal
    domain: internal
    hosts: [Isaac]
    prompt: "I'm running a POC across five customer workspaces. What should I measure and where are the bottlenecks?"
    surfaces:
      - {kind: agents, name: starboard-discovery}
      - {kind: internal-gated, name: nl_query, gated: true}
      - {kind: internal-gated, name: fleet_sql, gated: true}
      - {kind: internal-gated, name: diagnostic_backend, gated: true}
    expect: [summary, findings, recommendations, cost_estimate]
    last_verified: 2026-08-29
---

# Validated Examples

The registry of tested example prompts behind the [Hero Workflows](HERO_WORKFLOWS.md)
and [Personas](PERSONAS.md) pages. The YAML frontmatter above is the
machine-readable source of truth; the table below is its human-readable view.

Each example is validated by [`scripts/validate_examples.py`](../reference/CATALOG.md):

1. **No dead references** — every `surface` resolves against the *live* capability
   catalog. Public surfaces come from the same live sources as
   [`scripts/gen_catalog.py`](../reference/CATALOG.md); gated ports resolve
   against `starboard.ports.registry.Port`.
2. **Runs against a mocked Databricks + LLM** — no live workspace. Synthetic
   `system.*` rows flow through a deterministic runner; the emitted report must be
   non-empty and contain every declared `expect` key.
3. **Freshness** — each example carries a `last_verified` date and a matching
   `<!-- VALIDATED: YYYY-MM-DD -->` tag on its page. `--check` fails on a stale
   date (older than 90 days), a missing tag, or a missing surface.

> Dollar figures on the public flows are **list-price DBU estimates**. The
> internal personas use an internal cost model and are clearly scoped on the
> [Personas](PERSONAS.md) page.

| Example | Page | Audience | Domain | Last verified |
|---------|------|----------|--------|---------------|
| Query Optimization Sprint | [Hero](HERO_WORKFLOWS.md) | public | query | 2026-08-29 |
| Job Debugging Detective | [Hero](HERO_WORKFLOWS.md) | public | job | 2026-08-29 |
| Unity Catalog Governance Audit | [Hero](HERO_WORKFLOWS.md) | public | uc | 2026-08-29 |
| FinOps Cost Drill-Down | [Hero](HERO_WORKFLOWS.md) | public | finops | 2026-08-29 |
| Workspace Health Scorecard | [Hero](HERO_WORKFLOWS.md) | public | discovery | 2026-08-29 |
| Isaac — Account team (multi-tenant) | [Personas](PERSONAS.md) | internal | internal | 2026-08-29 |
| Isaac — Field engineer (POC) | [Personas](PERSONAS.md) | internal | internal | 2026-08-29 |

## Running the validator

```bash
export PATH="$PWD/.venv/bin:$PATH"
python scripts/validate_examples.py          # run + stamp last-verified to today
python scripts/validate_examples.py --check   # enforce only (CI); exit 1 on stale/missing-surface
```

## See also

- [Hero Workflows](HERO_WORKFLOWS.md)
- [Personas](PERSONAS.md)
- [Capability Catalog](../reference/CATALOG.md)
- [How to choose: skill vs tool vs agent vs helper](../guides/AGENT_EXPERIENCE.md)

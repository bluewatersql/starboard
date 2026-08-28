---
title: Quick Reference
description: One-page cheat sheet for running Starboard analyses from the CLI and skills.
last_reviewed: 2026-08-27
status: current
---

# Starboard AI Agent — Quick Reference

> A one-page cheat sheet for running analyses. For the full CLI, see
> [CLI Reference](user-guide/cli.md).

---

## Install

```bash
pip install starboard          # full experience: CLI + starboard_x + optional MCP
pip install starboard-core     # kernel + `python -m starboard_x.<cap>` middle tier
pip install starboard-skills   # skills tree + `starboard-helper` (Claude Code/Cursor)
```

The default install pulls **no** store/vector drivers. Opt in only if you change a
backend: `starboard[sqlite]`, `starboard[postgres]`, `starboard[vectorsearch]`,
`starboard-kernel[discovery]`, etc.

---

## Authenticate

```bash
starboard auth login --host https://ws.cloud.databricks.com --profile my-ws
starboard auth status                     # verify identity (no secrets printed)
# or: export DATABRICKS_HOST / DATABRICKS_TOKEN
# or: export DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET  (OAuth SP)
export LLM_API_KEY="<your-api-key>"
```

---

## The three flagship surfaces

```bash
# 1. Workload Review — ranked, evidence-cited findings over public system.* data
starboard review                          # domains: jobs,sql,warehouse (default)
starboard review --domains warehouse,sql --lookback-days 60
starboard review --validate               # gate findings through the validator council
starboard review --json                   # JSON envelope

# 2. genie ask — natural language → SQL over public workspace data
starboard genie ask "why did spend spike last week?"

# 3. Workspace discovery — 30/60/90-day health assessment
starboard --discover
starboard --discover --lookback-days 90 --discovery-domains jobs warehouse
starboard --discover --data-only          # skip LLM analysis, raw data only
```

---

## General agent commands

```bash
starboard --goal "Optimize query with statement_id 01ef-abc123"
starboard --goal "Analyze job 12345 for performance issues"
starboard --goal "Optimize this SQL" --input-file query.sql
starboard --chat                          # interactive multi-turn session
starboard --goal "..." --session my-proj  # named, resumable session
starboard --goal "..." --output-path ./reports/   # save JSON + Markdown
starboard --goal "..." --json             # structured envelope to stdout
```

Modes: `--mode online` (default, full API access) · `offline` (static, no API
calls) · `diagnostic` (focused cross-domain troubleshooting).

---

## Middle tier (`python -m starboard_x.<cap>`)

Lightweight, per-capability commands (installable via `starboard-core` + extras):

```
diagnostic   discovery   review   sparklog   uc   warehouse
```

```bash
python -m starboard_x.review score --rows rows.json --domains jobs,sql,warehouse
python -m starboard_x.discovery --help
```

All emit the shared JSON envelope (`{ok, domain, command, data|error, meta}`) and
exit codes: `0` ok · `1` auth · `2` not-found · `3` api-error · `4` arg-error.

---

## Key environment variables

```bash
# Databricks (any one path)
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi...
DATABRICKS_CONFIG_PROFILE=my-ws          # a ~/.databrickscfg profile

# LLM
LLM_API_KEY=<your-api-key>
LLM_MODEL=databricks-claude-sonnet-4-5   # default
LLM_TEMPERATURE=0.4                       # default
LLM_MAX_TOKENS=75000                      # default token budget
LLM_BASE_URL=...                          # for Databricks Model Serving / custom

# Optional per-domain model overrides
DOMAIN_MODEL_OVERRIDES='{"router":"databricks-gpt-5-mini"}'
```

Full reference: [Configuration Guide](CONFIGURATION.md).

---

## Defaults you should know

| Setting | Default | Notes |
|---------|---------|-------|
| State backend | `memory` | Durable option is UC-native (`uc`); `sqlite`/`postgres`/`lakebase` are extras |
| Vector backend | `none` | Analytics context = curated reference files + query packs, not embeddings |
| Semantic cache | TTL-only | Similarity cache is opt-in behind a real `vector_backend` |
| Reflexion | off | Opt-in behind `starboard[sqlite]` / `[vectorsearch]` |
| `$` figures | list-price DBU estimates | Public path only; labelled everywhere |

---

## Skills (Claude Code / Cursor)

10 canonical skills ship in `starboard-skills`:

```
starboard-analyze     starboard-cluster   starboard-diagnostic
starboard-discovery   starboard-finops    starboard-job
starboard-query       starboard-uc        starboard-warehouse
starboard-workload-review
```

See [Skills](SKILLS.md) for setup and the full catalog.

---

## Quick links

| Resource | Link |
|----------|------|
| CLI reference | [user-guide/cli.md](user-guide/cli.md) |
| Skills | [SKILLS.md](SKILLS.md) |
| Configuration | [CONFIGURATION.md](CONFIGURATION.md) |
| What is Starboard? | [overview/what-is-starboard.md](overview/what-is-starboard.md) |
| Workspace discovery workflow | [user-guide/workflows/workspace-discovery.md](user-guide/workflows/workspace-discovery.md) |
| MCP server | `starboard-mcp --transport stdio` |

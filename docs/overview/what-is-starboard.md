# What is Starboard?

**Starboard** is an AI-powered analysis and optimization tool for Databricks workloads. It ships three surfaces over one kernel: a **CLI** (`starboard`), an optional **MCP server** (`starboard-mcp`), and **Skills** (a Claude Code plugin). All three share the same domain agents, tools, and Databricks connectivity.

## How It Works

Requests sent via `--goal` or `--chat` flow through an **Intent Router** that classifies your input and dispatches it to the right domain agent. That agent reasons step-by-step, dynamically selects and calls Databricks tools, and streams findings live to the terminal.

**Two deterministic surfaces** run outside the agent loop, directly over public `system.*` data:

- **`starboard review`** — ranked, evidence-cited findings across jobs, SQL, and warehouses. Includes a `SeverityGate`; all `$` figures are list-price DBU estimates.
- **`starboard --discover`** — workspace health assessment and resource inventory (30/60/90-day lookback).

For the full system design, see [Architecture](../architecture.md).

## Domain Agents

The agent path (`--goal` / `--chat`) routes through 8 domain agents:

| Agent | Domain | What it does |
|-------|--------|-------------|
| Query | SQL optimization | Analyzes query plans, identifies bottlenecks, suggests rewrites |
| Job | Job performance | Debugs failing jobs, optimizes configurations, analyzes task dependencies |
| UC | Unity Catalog | Explores metadata, traces lineage, audits governance and access patterns |
| Cluster | Compute | Right-sizes clusters, diagnoses health, analyzes utilization |
| Analytics | FinOps & cost | Cost analysis, chargeback, usage trends (list-price DBU estimates) |
| Warehouse | SQL warehouses | Portfolio optimization, topology analysis, SLO configuration |
| Discovery | Workspace health | Workspace-wide assessment, resource inventory, health scoring |
| Diagnostic | Troubleshooting | Root cause analysis, cross-domain debugging |

See [Agents](agents.md) for the full capabilities matrix and cross-agent scenarios.

## Store-Free by Default

- **Memory-only state** — no database to provision; conversation and long-term memory are ephemeral and in-process.
- **Durable CLI sessions** — the JSON-file `SessionManager` persists CLI session state across invocations.
- **Reference-file analytics context** — curated on-disk reference files and query packs; no vector database or embeddings.
- **Redis cache** — opt-in via `pip install 'starboard[redis]'`; in-memory TTL cache by default.

## Install

```bash
pip install starboard           # CLI + agents + optional MCP server (no store drivers)
pip install starboard-core      # Pure kernel + starboard_x helpers only
pip install starboard-skills    # Skills plugin for Claude Code / Cursor
pip install 'starboard[redis]'  # Add Redis cache support
```

## Next Steps

- [Quickstart](../guide/quickstart.md) — get running in 5 minutes
- [CLI Reference](../guide/cli.md) — command flags, subcommands, and output options
- [Reports](../guide/reports.md) — understanding `starboard review` output
- [Agents](agents.md) — full agent catalog and capabilities matrix
- [Architecture](../architecture.md) — system design deep-dive

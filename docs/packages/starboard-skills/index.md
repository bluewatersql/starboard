# starboard-skills

Lightweight Claude skill files and Databricks helper scripts for dual-mode Claude integration.

## Overview

`starboard-skills` is a lightweight package providing:

- **Claude Skill Files**: Nine domain-specific skills for Claude Code and Cursor
- **Helper Scripts**: Thin Databricks data-fetching scripts (no LLM, no agents)
- **Dual-Mode Operation**: Works with or without a running `starboard-mcp` server

## Install

```bash
pip install starboard-skills
```

Dependencies: `databricks-sdk`, `rich`, `python-dotenv` only — no FastAPI, no LLM frameworks.

## Dual-Mode Behavior

Each skill instructs Claude:

> "If `mcp__starboard__*` tools are available in your context, use them. Otherwise, call `starboard-helper <domain> <command>` via Bash and apply analytical reasoning to the structured output."

### MCP Path (with starboard installed)

```
Claude reads skill -> mcp__starboard__analyze_job -> full agent -> result
```

### Non-MCP Path (starboard-skills only)

```
Claude reads skill -> starboard-helper job fetch --job-id 123 (Bash)
                   -> structured JSON stdout
                   -> Claude applies analytical reasoning
                   -> produces recommendations
```

## Entry Points

| Command | Description |
|---------|-------------|
| `starboard-helper` | Data-fetching CLI: `starboard-helper <domain> <command>` |

## Helper Script Contract

- **Input**: domain + subcommand + params via CLI args
- **Output**: structured JSON to stdout
- **Errors**: to stderr with exit codes (0=ok, 1=auth, 2=not found, 3=API error)
- **No LLM calls**: pure data fetching

## Package Structure

```
starboard-skills/
├── pyproject.toml
├── starboard_skills/
│   └── helpers/
│       ├── job.py          # Job data fetching
│       ├── query.py        # Query data fetching
│       ├── warehouse.py    # Warehouse data fetching
│       ├── uc.py           # Unity Catalog data fetching
│       ├── cluster.py      # Cluster data fetching
│       ├── finops.py       # FinOps/billing data fetching
│       ├── diagnostic.py   # Diagnostic data fetching
│       └── __main__.py     # Entry: starboard-helper <domain> <command>
└── skills/
    └── starboard/          # Claude skill files (one per domain)
        ├── starboard-job/
        ├── starboard-query/
        ├── starboard-warehouse/
        ├── starboard-uc/
        ├── starboard-cluster/
        ├── starboard-finops/
        ├── starboard-diagnostic/
        ├── starboard-analyze/
        └── starboard-discovery/
```

## Skills

| Skill | Domain | MCP Tool | Helper Command |
|-------|--------|----------|----------------|
| `starboard-job` | Job performance | `mcp__starboard__job_agent` | `starboard-helper job fetch` |
| `starboard-query` | SQL optimization | `mcp__starboard__query_agent` | `starboard-helper query fetch` |
| `starboard-warehouse` | Warehouse portfolio | `mcp__starboard__warehouse_agent` | `starboard-helper warehouse fetch` |
| `starboard-uc` | Unity Catalog | `mcp__starboard__uc_agent` | `starboard-helper uc fetch` |
| `starboard-cluster` | Cluster config | `mcp__starboard__cluster_agent` | `starboard-helper cluster fetch` |
| `starboard-finops` | Cost analysis | `mcp__starboard__analytics_agent` | `starboard-helper finops fetch` |
| `starboard-diagnostic` | Troubleshooting | `mcp__starboard__diagnostic_agent` | `starboard-helper diagnostic fetch` |
| `starboard-analyze` | Cross-domain | Multiple MCP tools | Multiple helper commands |
| `starboard-discovery` | Workspace health | `mcp__starboard__job_agent` | `starboard-helper discovery fetch` |

## Quick Links

- [Package README](../../../packages/starboard-skills/README.md) -- Installation and quick start
- [Skills Guide](../../SKILLS.md) -- Complete skills documentation
- [System Architecture](../../architecture/SYSTEM_ARCHITECTURE.md) -- Full system design

---
title: Changelog
description: Release history and notable changes for Starboard AI Agent.
last_reviewed: 2026-08-27
status: current
---

# Changelog

> **Docs** > **Overview** > **Changelog**

The canonical changelog is maintained in the repository root at `CHANGELOG.md`. If
there is ever a discrepancy, the root file wins. This page summarizes the
user-facing capabilities of the current shipped design (Phases 0–3).

---

## Current capabilities

### Entry points
- **`starboard` CLI** — flag-based natural-language goals (`--goal`), interactive
  `--chat`, named `--session`s, and workspace discovery (`--discover`).
- **Subcommands** — `starboard review` (Workload Review),
  `starboard auth {login,status}` (SDK-delegated auth).
- **Middle tier** — `python -m starboard_x.<capability>` for
  `diagnostic`, `discovery`, `review`, `sparklog`, `uc`, and `warehouse`.
- **Skills** — 10 canonical skills for Claude Code / Cursor (`starboard-skills`).
- **MCP server** — optional (`starboard-mcp`); plugins are not MCP servers.

### Flagship analyses (public `system.*` data)
- **Workload Review** — ranked, evidence-cited findings over jobs, SQL, and
  warehouses; rule-registry scoring, a severity gate (`--min-severity` /
  `--min-score`), and a read-only Action-Rate re-scan (`--since`/`--snapshot-out`).
- **Workspace discovery** — 30/60/90-day workspace health assessment with graded
  domain report cards.

### Defaults
- **Memory-only state** — `database_backend="memory"` is the only value; no
  external database. Durable CLI session persistence via JSON-file `SessionManager`.
- **Reference-file analytics context** — analytics context comes from curated
  reference files + query packs; no embeddings, no vector database.
- **TTL cache** — exact-key TTL cache by default; Redis opt-in via `starboard[redis]`.
- **Auth by subtraction** — one resolver delegates to the Databricks SDK credential
  chain; `--profile`/ambient credentials work, and a PAT is optional.

### Packages
- `starboard` — CLI, agents, tools, optional FastAPI/MCP server, public API facade.
- `starboard-core` — pure kernel + the `starboard_x` progressive helpers.
- `starboard-skills` — canonical skills tree + `starboard-helper`.

### Cost semantics
- All `$` figures on the public path are **list-price DBU estimates**, labelled as
  such throughout.

---

## Agents

8 domain agents (Query, Job, UC, Cluster, Analytics, Warehouse, Discovery,
Diagnostic) plus the Intent Router. `--goal` and `--chat` run the multi-agent
conversation; `review` and `--discover` are deterministic public-data paths.

---

## Next Steps

- [What is Starboard?](what-is-starboard.md) — Product overview
- [Quickstart](../QUICKSTART.md) — Install and run your first analysis
- [Agent Catalog](agents.md) — Explore the domain agents

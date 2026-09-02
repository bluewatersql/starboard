---
name: starboard-discovery
description: "Discover and map a Databricks workspace — enumerate jobs, clusters, warehouses, and Unity Catalog assets to build a comprehensive inventory. Use when the user wants a workspace inventory, a health assessment, or to explore what exists in a workspace."
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *), Bash(starboard-helper:*), Read
---

# Starboard: Workspace Discovery

Discover and map a Databricks workspace — enumerate jobs, clusters, warehouses,
and Unity Catalog assets to build a comprehensive inventory.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic workspace
data; **you** read the rows and write the inventory, observations, and
recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below runs pure Python (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Load the data (deterministic Python, no LLM)

Run the bundled helper. It executes the audit plus the discovery query packs
out-of-context in Python and prints a single JSON envelope to stdout. The
command is pre-approved by this skill's `allowed-tools`, so it runs without a
permission prompt:

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh run --data-only
```

Scope to specific domains with `--packs`, or widen the window with
`--lookback-days`:

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh run --data-only --packs billing jobs
${CLAUDE_SKILL_DIR}/scripts/run.sh run --data-only --lookback-days 60
```

Pass `--profile <name>` to target a specific `~/.databrickscfg` profile
(otherwise the ambient `DATABRICKS_*` env / default profile is used).

Requires `pip install "starboard-kernel[discovery]"`.

### What comes back

The envelope is `{ok, domain, command, data, meta}`:

- `data.audit.succeeded` — did the workspace audit run.
- `data.packs[]` — one entry per query pack (`audit`, `billing`, `jobs`,
  `governance`, `migration`, and any you selected). Each `results[]` query
  carries the **actual rows**: `columns`, `rows`, `row_count`, and a
  `truncated` flag.
- `data.domain_analyses` — always `[]` on this path (proof no LLM ran).

### Fallback — raw per-resource fetch

If the bundled helper is unavailable, enumerate directly with `starboard-helper`
and reason over what it returns:

```bash
starboard-helper job list --limit 100
starboard-helper cluster list
starboard-helper warehouse list
starboard-helper uc catalogs
```

Drill into specific resources as needed:

```bash
starboard-helper uc schemas --catalog <CATALOG>
starboard-helper cluster fetch --cluster-id <CLUSTER_ID>
starboard-helper warehouse fetch --warehouse-id <WH_ID>
```

## Step 2 — Analyze the data yourself

Read the returned rows and build a workspace map:

- **Jobs** — count, schedule patterns, cluster attachment types
- **Clusters** — running vs. terminated, job vs. interactive
- **Warehouses** — types (classic/serverless), sizes, states
- **Data** — Unity Catalog hierarchy, schema and table counts

## Step 3 — Produce the discovery report

1. **Workspace summary** — counts of each resource type
2. **Jobs inventory** — scheduled vs. manual, production vs. development indicators
3. **Compute inventory** — cluster and warehouse utilization snapshot
4. **Data inventory** — Unity Catalog hierarchy overview
5. **Observations** — notable patterns, potential issues, quick wins
6. **Recommended next steps** — which domains to analyze in depth

`$` figures are **list-price DBU estimates** — label them as such.

## Exit codes (from the bundled helper)

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` / `DATABRICKS_TOKEN` (or `--profile`)
- 2: resource not found
- 3: API error — check workspace connectivity
- 4: bad arguments (e.g. an unknown `--packs` value)

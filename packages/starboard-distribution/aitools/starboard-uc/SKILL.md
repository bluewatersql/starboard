---
name: starboard-uc
description: "Analyze Unity Catalog metadata and governance — explore catalogs, schemas, tables, lineage, and governance posture. Use when the user asks about Unity Catalog, data governance, catalog/schema/table structure, or data lineage."
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *), Bash(starboard-helper:*), Read, Write
---

# Starboard: Unity Catalog Analysis

Analyze Unity Catalog metadata — explore catalogs, schemas, tables, lineage, and
governance posture.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic catalog and
schema data; **you** read the rows and write the governance assessment and
recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below runs pure Python (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "analyze catalog my_catalog"), use it and skip that question. If they say
"just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Scope** — which catalog and/or schema to analyze, or survey all catalogs?
  Default: **survey all catalogs**.
- **Workspace / profile** — which `--profile` to target, if it's ambiguous
  (default: the ambient `DATABRICKS_*` env / default profile).

## Step 2 — Load the data (deterministic, no LLM)

### Analyze a table schema on disk (bundled helper)

If you already have a table's **schema JSON** on disk (columns + optional
`table_name`), run the pure UC analyzer — no network required. It emits the stable
JSON envelope to stdout and is pre-approved (no permission prompt):

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh analyze --input <table.json>
```

Input shape:
`{"table_name": "cat.sch.tbl", "columns": [{"name": ..., "data_type": ..., "nullable": ...}, ...]}`.

Read the returned `data.anomalies`, `data.classification` (table type + medallion
layer), `data.semantic_patterns`, and `data.schema_health`, then proceed to
Step 2. Requires `pip install "starboard-kernel[uc]"`.

### Explore live catalog metadata (starboard-helper)

To explore a live workspace catalog hierarchy, use `starboard-helper`:

```bash
starboard-helper uc catalogs
starboard-helper uc schemas --catalog <CATALOG>
starboard-helper uc tables --catalog <CATALOG> --schema <SCHEMA>
starboard-helper uc table --full-name <CATALOG>.<SCHEMA>.<TABLE>
starboard-helper uc lineage --full-name <CATALOG>.<SCHEMA>.<TABLE>
```

## Step 3 — Analyze the data yourself

Read the returned rows and assess governance posture:

- **Governance** — do tables have owners and comments? Missing metadata is a
  governance gap.
- **Lineage** — are there orphaned tables (no upstream/downstream)? Potential dead
  data.
- **Table types** — are MANAGED vs EXTERNAL tables used appropriately?
- **Data formats** — are legacy formats (CSV, JSON) used where Delta would be
  better?
- **Access patterns** — are schemas organized logically (bronze/silver/gold or
  domain-based)?

## Step 4 — Produce the report

1. Catalog/schema overview and health
2. Governance gaps (missing owners, comments, tags)
3. Data organization recommendations
4. Lineage observations
5. Priority: critical / high / medium / low

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to
> `./starboard-reports/uc-<YYYY-MM-DD>.md`."

If the user accepts, create the `./starboard-reports/` directory if needed and
write the full report there (use today's date; if a file for today already
exists, add a `-2`, `-3`, … suffix). Confirm the path you wrote. Don't write
anything unless the user opts in.

## Exit codes

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
- 2: object not found — verify catalog/schema/table name
- 3: API error — check workspace connectivity

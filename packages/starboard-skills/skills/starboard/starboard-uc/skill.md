# Starboard: Unity Catalog Analysis

Analyze Unity Catalog metadata — explore catalogs, schemas, tables, lineage, and governance posture.

## Dual-Mode Behavior

**Check which tools are available before proceeding:**

If `mcp__starboard__*` tools are available in your context, use them for full agent orchestration:
```
mcp__starboard__analyze_uc  (or similar MCP tool)
```

If MCP tools are NOT available, use `starboard-helper` via Bash to fetch data, then apply analytical reasoning:
```bash
starboard-helper uc catalogs
starboard-helper uc schemas --catalog <CATALOG>
starboard-helper uc tables --catalog <CATALOG> --schema <SCHEMA>
starboard-helper uc table --full-name <CATALOG>.<SCHEMA>.<TABLE>
starboard-helper uc lineage --full-name <CATALOG>.<SCHEMA>.<TABLE>
```

## MCP Path

When `mcp__starboard__*` tools are available:
1. Call the relevant MCP tool — the full agent stack handles orchestration, analysis, and recommendations.
2. Return the agent's response directly.

## Non-MCP Path

When MCP tools are NOT available, follow these steps:

### Step 1: Explore the catalog hierarchy
```bash
starboard-helper uc catalogs
starboard-helper uc schemas --catalog <CATALOG>
starboard-helper uc tables --catalog <CATALOG> --schema <SCHEMA>
```

### Step 2: Inspect specific table(s)
```bash
starboard-helper uc table --full-name <CATALOG>.<SCHEMA>.<TABLE>
starboard-helper uc lineage --full-name <CATALOG>.<SCHEMA>.<TABLE>
```

### Step 3: Apply analytical reasoning

Based on the structured JSON output, analyze:
- **Governance**: Do tables have owners and comments? Missing metadata is a governance gap.
- **Lineage**: Are there orphaned tables (no upstream/downstream)? Potential dead data.
- **Table types**: Are MANAGED vs EXTERNAL tables used appropriately?
- **Data formats**: Are legacy formats (CSV, JSON) used where Delta would be better?
- **Access patterns**: Are schemas organized logically (bronze/silver/gold or domain-based)?

### Step 4: Produce recommendations

Output a structured analysis:
1. Catalog/schema overview and health
2. Governance gaps (missing owners, comments, tags)
3. Data organization recommendations
4. Lineage observations
5. Priority: critical / high / medium / low

## Exit Codes
- 0: success
- 1: authentication error — check DATABRICKS_HOST and DATABRICKS_TOKEN env vars
- 2: object not found — verify catalog/schema/table name
- 3: API error — check workspace connectivity

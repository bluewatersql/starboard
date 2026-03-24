# Workflow: Table Governance

This guide walks through an end-to-end workflow for auditing table access,
governance policies, and data quality using the Starboard AI agent. You will
learn what to ask, how the UC agent investigates, and how to interpret the
governance findings.

---

## When to Use This Workflow

- You need to audit who can access a table before a compliance review.
- You want to identify policy gaps across a catalog or schema.
- You need to trace data lineage to understand where sensitive data flows.
- You want to detect schema drift that may indicate uncontrolled changes.
- You are preparing for a data governance review or access recertification.
- You need to verify that row-level or column-level security is applied correctly.

---

## What the UC Agent Can Do

The UC Expert agent has access to the following tools:

| Tool | Purpose |
|------|---------|
| `list_uc_assets` | List catalogs, schemas, tables, volumes, and functions in Unity Catalog. |
| `get_table_metadata` | Retrieve table schema, columns, partitions, and statistics. |
| `get_table_grants` | Retrieve access policies and grants for a table. |
| `get_table_lineage` | Trace upstream and downstream table dependencies. |
| `get_table_history` | Get Delta table version history and operations. |
| `analyze_access_patterns` | Analyze query frequency, reader/writer tracking over a time window. |
| `analyze_schema_drift` | Track schema changes over time and detect uncontrolled drift. |
| `analyze_policy_coverage` | Assess security policy completeness across a catalog or schema. |
| `generate_schema_diff` | Compare table schema between two Delta versions. |
| `get_table_fingerprint` | Generate a comprehensive workload profile for a table. |

---

## Step 1: Start the Conversation

### Scenario A: Audit a specific table

If you know the fully qualified table name, ask directly:

**Web UI:**
```
Audit the access and governance posture of analytics.gold.customer_orders.
Who can read it, who writes to it, and are there any policy gaps?
```

**CLI:**
```bash
starboard --goal "Audit governance for table analytics.gold.customer_orders"
```

### Scenario B: Audit an entire schema or catalog

For broader governance reviews across multiple tables:

**Web UI:**
```
Review policy coverage across the analytics.gold schema.
Are there tables without proper access controls?
```

**CLI:**
```bash
starboard --goal "Analyze policy coverage for the analytics.gold schema"
```

### Scenario C: Investigate schema drift

If you suspect uncontrolled schema changes:

**Web UI:**
```
Has the schema of analytics.gold.customer_orders changed recently?
Show me what changed and when.
```

### Scenario D: Trace sensitive data flow

If you need to understand where data comes from or where it goes:

**Web UI:**
```
Trace the lineage of analytics.gold.customer_orders.
Where does the data originate and which downstream tables consume it?
```

!!! tip "Always use fully qualified table names"
    The UC agent requires 3-part names (`catalog.schema.table`). If you use a
    short name like `customer_orders`, the agent will search for matches and ask
    you to choose from the results.

---

## Step 2: What the Agent Does

Once you submit your request, the UC Expert follows one of three investigation
patterns depending on your question.

### Pattern 1: Access and Policy Audit

For questions about who can access a table and whether policies are adequate:

```
-> Get Table Metadata
-> Get Table Grants
-> Analyze Access Patterns
-> Analyze Policy Coverage
```

1. **Metadata retrieval** -- The agent fetches the table's schema, storage
   format, partition columns, and statistics to understand what is being
   protected.

2. **Grant inspection** -- The agent retrieves all grants (SELECT, MODIFY,
   ALL PRIVILEGES, etc.) on the table, including inherited grants from the
   schema and catalog levels.

3. **Access pattern analysis** -- The agent queries system tables to determine
   who actually reads from and writes to the table, how frequently, and during
   which time windows.

4. **Policy coverage assessment** -- The agent evaluates whether the table has
   appropriate security policies (row filters, column masks, ownership) and
   identifies gaps.

### Pattern 2: Schema Drift Investigation

For questions about schema changes over time:

```
-> Get Table Metadata
-> Get Table History
-> Analyze Schema Drift
-> Generate Schema Diff (if specific versions identified)
```

1. **Current schema** -- The agent retrieves the current table schema as a
   baseline.

2. **Version history** -- The agent reviews Delta table operations (ALTER TABLE,
   MERGE, WRITE, etc.) to identify when schema changes occurred.

3. **Drift analysis** -- The agent examines schema changes across versions,
   flagging additions, removals, type changes, and nullability changes.

4. **Version diff** -- If specific versions are of interest, the agent generates
   a precise diff showing exactly what changed between two points in time.

### Pattern 3: Lineage and Data Flow

For questions about data dependencies and sensitive data flow:

```
-> Get Table Lineage
-> Get Table Metadata (parallel, for key upstream/downstream tables)
-> Get Table Grants (for tables in the lineage chain)
```

1. **Lineage tracing** -- The agent traces upstream sources (where data comes
   from) and downstream consumers (where data goes).

2. **Metadata for key tables** -- The agent fetches metadata for important
   tables in the lineage chain, running these calls in parallel for efficiency.

3. **Grant comparison** -- The agent checks whether access policies are
   consistent across the lineage chain, identifying tables where sensitive data
   may flow to a less-protected destination.

---

## Step 3: Understanding the Report

The agent produces a **UC Analysis Report** with several sections:

### Summary

A brief overview of the table's governance posture, including asset type, data
layer (bronze/silver/gold), and key findings.

### Findings

Each finding includes:

- **Category** -- POLICY, SCHEMA, LINEAGE, STORAGE, or DATA.
- **Title** -- A short description of the issue.
- **Recommendation** -- A specific, actionable fix.
- **Fixes** -- SQL commands or process changes to resolve the issue.
- **Evidence** -- Facts from tool outputs that support the finding.
- **Impact Estimate** -- Projected improvements to governance, query performance,
  data quality, or cost.
- **Effort** -- Implementation difficulty (low, medium, high) with hour estimate.
- **Rank** -- Priority order (1 = most impactful).

Example finding:

> **Overly Broad SELECT Grant on PII Table (Rank 1)**
>
> Category: POLICY | Effort: Low (~1 hour)
>
> The table `analytics.gold.customer_orders` contains PII columns
> (`customer_email`, `phone_number`) but has `SELECT` granted to the
> `all_analysts` group (142 users). Only 12 users have queried this table
> in the last 30 days.
>
> **Recommendation:** Replace the broad group grant with specific user grants
> or apply column-level masking to PII fields.
>
> ```sql
> -- Apply column mask to email
> ALTER TABLE analytics.gold.customer_orders
>   ALTER COLUMN customer_email
>   SET MASK mask_pii;
>
> -- Revoke broad group access
> REVOKE SELECT ON TABLE analytics.gold.customer_orders
>   FROM `all_analysts`;
>
> -- Grant to specific users who need access
> GRANT SELECT ON TABLE analytics.gold.customer_orders
>   TO `customer_analytics_team`;
> ```

### Interactive Next Steps

The agent provides 2-5 actionable options after the report:

- **Continue with UC agent** -- Trace lineage, review Delta history, or inspect
  another table's policies.
- **Route to Query agent** -- Analyze downstream queries that read from the
  table.
- **Route to Job agent** -- Review ETL jobs that write to the table.
- **Route to Analytics agent** -- Break down per-table compute and storage costs.

---

## Step 4: Follow Up

After the report, you can ask follow-up questions to go deeper:

```
Show me the full lineage graph for this table.
```

```
Which downstream tables also contain the customer_email column?
```

```
Compare the schema from version 15 to the current version.
```

```
List all tables in analytics.gold that have no row-level security.
```

```
Who wrote to this table in the last 7 days?
```

---

## Example Conversation

---

**You:**
> Audit the governance posture of analytics.gold.customer_orders.
> Who can access it, are there policy gaps, and has the schema changed recently?

**UC Expert** (thinking for 8s):
> *-> Get Table Metadata*
> *-> Get Table Grants*
> *-> Analyze Access Patterns*
> *-> Analyze Schema Drift*
> *-> Analyze Policy Coverage*

**UC Expert:**
> ## Governance Audit: analytics.gold.customer_orders
>
> ### Summary
> `analytics.gold.customer_orders` is a managed Delta table in the gold layer
> with 45M rows across 18 columns, including 3 PII fields. The table has broad
> read access (142 users via group grant) but only 12 active readers in the last
> 30 days. Two schema changes were detected in the past 60 days. Policy coverage
> is 68% -- below the recommended 85% threshold.
>
> ### Findings
>
> **1. Overly Broad Read Access on PII Table (Category: POLICY)**
> The `all_analysts` group (142 users) has `SELECT` on this table, but only
> 12 users accessed it in the last 30 days. The table contains PII columns:
> `customer_email`, `phone_number`, `shipping_address`.
>
> **Recommendation:** Apply column masks to PII fields and tighten group
> membership.
> ```sql
> ALTER TABLE analytics.gold.customer_orders
>   ALTER COLUMN customer_email SET MASK mask_pii;
> ALTER TABLE analytics.gold.customer_orders
>   ALTER COLUMN phone_number SET MASK mask_pii;
> ```
>
> **2. Unreviewed Schema Change (Category: SCHEMA)**
> On 2026-02-18, column `loyalty_tier` (STRING) was added via ALTER TABLE.
> No corresponding change was found in the upstream bronze or silver tables,
> suggesting a manual modification outside the standard ETL pipeline.
>
> **Recommendation:** Verify the change was intentional and propagate the
> column through the upstream pipeline if needed.
>
> **3. Missing Row-Level Security (Category: POLICY)**
> The table has no row filter function applied. Given that it contains
> customer data from multiple regions, row-level filtering by region would
> limit analyst access to their own region's data.
>
> **Recommendation:** Create and apply a row filter function:
> ```sql
> CREATE FUNCTION analytics.gold.region_filter(region STRING)
>   RETURN IF(IS_ACCOUNT_GROUP_MEMBER('global_analysts'), true, region = CURRENT_USER_REGION());
>
> ALTER TABLE analytics.gold.customer_orders
>   SET ROW FILTER analytics.gold.region_filter ON (customer_region);
> ```

**What would you like to do next?**

1. Trace full data lineage for this table -- **Continue**
2. Review the ETL jobs that write to this table -- **Expert** (Job)
3. Analyze downstream queries consuming this data -- **Expert** (Query)
4. Check policy coverage across the entire analytics.gold schema -- **Continue**

---

**You:**
> Check policy coverage across the entire analytics.gold schema.

**UC Expert** (thinking for 6s):
> *-> List UC Assets (analytics.gold)*
> *-> Analyze Policy Coverage (scope: schema, catalog: analytics, schema: gold)*

**UC Expert:**
> ## Policy Coverage: analytics.gold
>
> | Metric | Value |
> |--------|-------|
> | Tables analyzed | 24 |
> | With column masks | 8 (33%) |
> | With row filters | 3 (12%) |
> | With explicit grants | 18 (75%) |
> | Inherited-only access | 6 (25%) |
> | Security score | 68/100 |
>
> ### Tables Missing Policies
> | Table | PII Columns | Readers (30d) | Issue |
> |-------|-------------|---------------|-------|
> | customer_profiles | 5 | 34 | No column masks |
> | payment_transactions | 3 | 12 | No row filter |
> | employee_records | 8 | 6 | No column masks, no row filter |
>
> **Recommendation:** Prioritize `employee_records` (highest PII density) and
> `customer_profiles` (highest reader count) for immediate policy remediation.

---

## Tips

!!! tip "Start with a specific table, then widen"
    Begin your governance audit with a single high-value table (e.g., one
    containing PII or financial data). Once you understand the findings, ask
    the agent to check the entire schema for similar issues:
    ```
    Are there other tables in analytics.gold with the same policy gaps?
    ```

!!! tip "Combine access patterns with grants"
    The most actionable governance insights come from comparing *who can*
    access a table (grants) with *who actually does* (access patterns). This
    reveals over-provisioned access that can be tightened.

!!! tip "Use schema drift detection before migrations"
    Before running a major ETL change or migration, use schema drift analysis
    to establish a baseline. After the migration, run it again to verify only
    intended changes were applied:
    ```
    Compare the schema of analytics.gold.customer_orders
    from version 42 to the current version.
    ```

!!! note "Unity Catalog API required"
    Governance analysis requires a live connection to the Databricks Unity
    Catalog API. Most governance tools do not work in offline mode because
    they query UC metadata and system tables in real time. The agent will
    inform you if a specific operation is unavailable.

!!! warning "Policy changes require appropriate permissions"
    The SQL commands in the agent's recommendations (GRANT, REVOKE, ALTER
    TABLE SET MASK, SET ROW FILTER) require admin or table-owner permissions.
    Review and test all policy changes in a non-production environment first.

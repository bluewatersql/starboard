# Workflow: Workspace Discovery

This guide walks through an end-to-end workflow for assessing the overall health
of your Databricks workspace using the Starboard AI agent. You will learn what
to ask, how the Discovery agent's 4-phase pipeline works, and how to interpret
the graded health report.

---

## When to Use This Workflow

- You are onboarding to a new Databricks workspace and want to understand its state.
- You want a periodic health check across billing, compute, governance, and jobs.
- You need to identify the highest-impact optimization opportunities across the platform.
- You are preparing for a capacity planning review or FinOps assessment.
- Multiple teams report issues and you suspect systemic platform problems.
- You want an evidence-based baseline before a major migration or upgrade.

---

## What the Discovery Agent Can Do

The Discovery agent executes a structured 4-phase pipeline using the following
tools:

| Phase | Tool | Purpose |
|-------|------|---------|
| 1. Audit | `discover_active_products` | Query `system.billing.usage` to detect active Databricks products. |
| 2. Query | `run_discovery_queries` | Execute SQL query packs against system tables for each active domain. |
| 3. Analyze | `analyze_discovery_domain` | Run heuristics and LLM analysis per domain to produce grades and findings. |
| 4. Synthesize | `synthesize_discovery_report` | Assemble the final report with executive summary and output files. |

The agent reasons between each phase, adapting its approach based on
intermediate results. For example, if the audit finds few active products, the
agent adjusts expectations and communicates the limited scope.

---

## Step 1: Start the Conversation

### Scenario A: Full workspace health check

For a comprehensive assessment of all active domains:

**Web UI:**
```
Run a workspace health check.
```

**CLI:**
```bash
starboard --discover
```

### Scenario B: Scoped assessment

To focus on specific domains or adjust the lookback period:

**Web UI:**
```
Run a health check focusing on billing and compute for the last 90 days.
```

**CLI:**
```bash
starboard --discover --lookback-days 90 --discovery-domains billing compute
```

### Scenario C: Data-only mode

If you want raw query data without LLM analysis (useful for piping into other
tools):

**CLI:**
```bash
starboard --discover --data-only
```

!!! tip "Use the `--discover` flag for direct execution"
    The CLI `--discover` flag runs the full 4-phase pipeline directly.
    Alternatively, you can ask the agent conversationally in the Web UI and it
    will route your request to the Discovery agent automatically.

---

## Step 2: How the 4-Phase Pipeline Works

Once you submit your request, the Discovery agent executes four sequential
phases with reasoning between each step.

### Phase 1: Audit

```
-> Discover Active Products
```

The agent queries `system.billing.usage` to determine which Databricks products
have been active in the lookback window (default: 30 days). Products include
JOBS, SQL, SERVING, NOTEBOOKS, DLT, and others.

The audit result determines which domains will be analyzed in subsequent phases.
If a product is not active, its domain is skipped automatically.

**Agent reasoning after Phase 1:**
> "Found 6 active products across 4 domains (billing, compute, governance,
> jobs). Running queries now."

### Phase 2: Query

```
-> Run Discovery Queries
```

The agent executes SQL query packs against system tables for each active domain.
Each domain has multiple queries that gather usage data, configuration data, and
operational metrics.

The agent reviews per-domain query summaries, noting which domains have the most
data (more activity) and whether any queries failed.

**Agent reasoning after Phase 2:**
> "Gathered data from all 4 domains. Billing has 15,000 rows of usage data.
> Compute has 8,200 rows. All queries succeeded. Analyzing now."

### Phase 3: Analyze

```
-> Analyze Discovery Domain (all domains in a single call)
```

The agent calls the analysis tool once with all domains that returned data. The
tool handles parallelism internally:

- **Heuristic rules** -- Deterministic, rule-based checks applied first
  (e.g., "idle cluster ratio > 30% = finding").
- **LLM analysis** -- Deeper pattern recognition on the query data to surface
  insights that rules alone would miss.
- **Bounded parallelism** -- A semaphore limits concurrent LLM calls (default 4)
  with a 120-second per-domain timeout.

Each domain receives a letter grade (A-F) and a numeric score (0-100).

**Agent reasoning after Phase 3:**
> "Analysis complete. Billing: C (65/100). Compute: D (42/100) -- this is a
> priority area. Governance: A (92/100). Jobs: B (78/100)."

### Phase 4: Synthesize

```
-> Synthesize Discovery Report
```

The agent assembles all domain analyses into a final report with:

- Executive summary and overall health assessment.
- Per-domain report cards with grades and discussion.
- Top findings ranked by priority and impact.
- Recommended actions (immediate and medium-term).
- Output files saved to disk for team review.

---

## Step 3: Understanding the Report

### Health Grades

Each domain receives a letter grade based on deterministic heuristic scoring:

| Grade | Score | Meaning |
|-------|-------|---------|
| A | 90-100 | Excellent -- following best practices |
| B | 80-89 | Good -- minor optimization opportunities |
| C | 65-79 | Fair -- several areas need attention |
| D | 50-64 | Poor -- significant issues detected |
| F | 0-49 | Critical -- immediate action required |

!!! note "Grades are evidence-based"
    Every grade is backed by system table query data and deterministic heuristic
    rules. The agent never assigns a grade based on assumptions -- only on data
    it has gathered and analyzed.

### Report Cards

The report includes a card for each analyzed domain with:

- **Grade and score** -- The overall assessment.
- **Discussion** -- A brief explanation of why the domain received its grade.
- **Top findings** -- The most impactful issues in that domain.

### Top Findings

Findings are ranked across all domains by priority and impact. Each includes:

- **Title** -- A short description of the issue.
- **Priority** -- Critical, High, Medium, or Low.
- **Impact** -- The business or operational consequence.
- **Domain** -- Which domain the finding belongs to.

### Recommended Actions

A prioritized list of next steps:

1. **Immediate actions** -- Quick wins that can be applied now (e.g., reduce
   idle cluster auto-termination timeout).
2. **Medium-term actions** -- Changes requiring planning or coordination
   (e.g., consolidate underutilized warehouses).

### Output Files

Phase 4 writes structured output files for detailed review and historical
tracking:

```
discovery_output/
  +-- report.md          # Full Markdown report with all domains
  +-- report.json        # Machine-readable report data
  +-- domain_*.md        # Per-domain detailed findings
```

!!! tip "Save reports for trend tracking"
    Run discovery periodically and save the output to compare grades over time:
    ```bash
    starboard --discover --lookback-days 30 2>&1 | tee discovery-$(date +%Y-%m).log
    ```
    The JSON output in `discovery_output/report.json` is ideal for building
    dashboards or tracking grade trends programmatically.

---

## Step 4: Follow Up

After the report, the Discovery agent may suggest routing to specialist agents
for deeper investigation. Common follow-ups include:

- **Billing scored D or F** -- Route to the **Analytics (FinOps) agent** for
  detailed cost breakdown and optimization recommendations.
- **Compute scored poorly** -- Route to the **Cluster agent** to analyze
  specific cluster configurations and right-sizing opportunities.
- **Warehouse issues detected** -- Route to the **Warehouse agent** for fleet
  analysis and consolidation recommendations.
- **Job performance issues** -- Route to the **Job agent** to debug specific
  failing or slow jobs.
- **Governance gaps found** -- Route to the **UC agent** for table-level policy
  audits and access reviews.

You can also ask follow-up questions directly:

```
Which clusters are responsible for the low compute score?
```

```
Show me the billing breakdown for the top 3 cost drivers.
```

```
Run discovery again but only for the billing domain with a 90-day lookback.
```

```
What specific governance gaps were identified?
```

---

## Example Conversation

---

**You:**
> Run a workspace health check for the last 30 days.

**Discovery Agent** (thinking for 3s):
> *-> Discover Active Products*

**Discovery Agent:**
> Found 7 active products across 4 domains: billing, compute, governance, and
> jobs. Running system table queries now.

**Discovery Agent** (thinking for 8s):
> *-> Run Discovery Queries*

**Discovery Agent:**
> Gathered data from all 4 domains. Billing has 18,400 rows, compute has
> 9,800 rows, governance has 340 rows, and jobs has 6,200 rows. All queries
> succeeded. Analyzing each domain now.

**Discovery Agent** (thinking for 15s):
> *-> Analyze Discovery Domain (billing, compute, governance, jobs)*

**Discovery Agent:**
> Analysis complete. Here are the preliminary grades:
>
> | Domain | Grade | Score |
> |--------|-------|-------|
> | Governance | A | 94 |
> | Jobs | B | 81 |
> | Billing | C | 68 |
> | Compute | D | 45 |
>
> Compute scored poorly -- this is the priority area. Assembling the full report.

**Discovery Agent** (thinking for 5s):
> *-> Synthesize Discovery Report*

**Discovery Agent:**
> ## Workspace Health Report
>
> ### Overall Health
> Your workspace is in **fair** condition. Governance practices are strong,
> but compute resource management needs immediate attention. Billing efficiency
> has room for improvement.
>
> ### Report Cards
>
> | Domain | Grade | Discussion |
> |--------|-------|------------|
> | Governance | A (94) | Unity Catalog is well configured. 92% of tables have explicit grants. Row-level security is applied to PII tables. |
> | Jobs | B (81) | Most jobs run successfully (96% pass rate). 3 jobs have degrading performance trends worth investigating. |
> | Billing | C (68) | 35% of total DBU spend is on idle or underutilized resources. Warehouse auto-stop timeouts are too high across the fleet. |
> | Compute | D (45) | 8 of 14 clusters have auto-termination disabled. Average idle ratio is 42%. 3 clusters have not run a workload in 14+ days. |
>
> ### Top Findings
>
> 1. **3 Zombie Clusters with No Recent Workloads** (Compute, Critical)
>    Clusters `dev-scratch-01`, `legacy-etl`, and `test-cluster-v2` have
>    consumed 12,400 DBUs in the last 30 days with zero job runs.
>
> 2. **Fleet-Wide Auto-Stop Timeout Too High** (Billing, High)
>    Average auto-stop timeout across SQL warehouses is 85 minutes. Reducing
>    to 10-15 minutes would save an estimated 8,200 DBUs/month.
>
> 3. **Auto-Termination Disabled on 8 Clusters** (Compute, High)
>    8 of 14 all-purpose clusters have auto-termination disabled, leading to
>    prolonged idle running.
>
> 4. **3 Jobs with Degrading Duration Trends** (Jobs, Medium)
>    Jobs `daily-etl-pipeline`, `hourly-sync`, and `report-generator` show
>    25-40% duration increases over the last 30 days.
>
> 5. **6 Tables with Inherited-Only Access** (Governance, Low)
>    6 tables in the gold layer rely solely on inherited catalog grants with
>    no explicit table-level policies.
>
> ### Recommended Actions
> 1. (Immediate) Terminate or archive the 3 zombie clusters.
> 2. (Immediate) Enable auto-termination on the 8 clusters that have it disabled.
> 3. (Immediate) Reduce warehouse auto-stop timeouts to 10-15 minutes.
> 4. (Medium-term) Investigate the 3 jobs with degrading performance.
> 5. (Medium-term) Add explicit grants to the 6 inherited-only gold tables.
>
> Full report saved to `discovery_output/report.md`.

**What would you like to do next?**

1. Investigate the zombie clusters in detail -- **Expert** (Cluster)
2. Analyze the 3 degrading jobs -- **Expert** (Job)
3. Deep-dive into billing and cost optimization -- **Expert** (FinOps)
4. Review the governance gaps on those 6 tables -- **Expert** (UC)

---

**You:**
> Investigate the zombie clusters in detail.

**Cluster Expert** (thinking for 10s):
> *-> Get Cluster Config (dev-scratch-01)*
> *-> Get Cluster Config (legacy-etl)*
> *-> Get Cluster Config (test-cluster-v2)*
> *-> Get Cluster Health (all 3)*

*The conversation continues with the Cluster agent providing detailed analysis
and termination recommendations for each cluster.*

---

## Tips

!!! tip "Run discovery as a monthly health check"
    Schedule a monthly discovery run to track workspace health trends over time.
    Compare grades month-over-month to verify that optimization actions are
    having an effect:
    ```bash
    # Monthly health check
    starboard --discover --lookback-days 30
    ```

!!! tip "Scope discovery for faster results"
    A full workspace assessment can take 2-5 minutes. If you only care about
    specific domains, scope the run to get results faster:
    ```bash
    starboard --discover --discovery-domains billing compute
    ```

!!! tip "Use discovery before major changes"
    Run discovery before and after major platform changes (migrations, upgrades,
    new team onboarding) to measure the impact and catch regressions.

!!! note "DBU-only metrics"
    The Discovery agent expresses all resource consumption in Databricks Units
    (DBUs), not dollar amounts. DBUs provide consistent, comparable metrics
    across workspaces regardless of pricing tier, discounts, or commitment
    agreements.

!!! warning "System tables required"
    Workspace discovery requires access to Databricks system tables
    (`system.billing.usage`, `system.compute.*`, etc.). If system tables are
    not enabled in your workspace, contact your Databricks admin. The agent
    requires an active SQL connection and does not support offline mode.

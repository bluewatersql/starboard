---
title: Frequently Asked Questions
description: Answers to common questions about Starboard AI Agent capabilities, setup, and usage.
last_reviewed: 2026-03-24
status: current
---

# Frequently Asked Questions

> **Docs** > **Getting Started** > **FAQ**
> Reading time: 10 minutes

**What you'll learn:**

- What Starboard AI Agent is and how it works
- Which agents and tools are available
- How to set up and configure the system
- LLM provider options and cost management
- Troubleshooting common issues

---

## General

### What is Starboard AI Agent?

Starboard AI Agent is an AI-powered analysis and optimization platform for Databricks workloads. It uses 8 domain-specialized agents that reason step-by-step, call specialized tools, and deliver actionable recommendations for queries, jobs, clusters, warehouses, costs, and governance — all from the command line (and from AI coding assistants via skills).

### How does it work?

When you run `starboard --goal "…"` or `--chat`, an **Intent Router** classifies your request and dispatches it to the appropriate domain agent. That agent reasons about your question, selects tools dynamically to gather real data from Databricks APIs, analyzes the results, and streams progress to your terminal as it works. Starboard also ships three deterministic, public-data surfaces — `starboard review` (Workload Review), `starboard genie ask` (NL → SQL), and `starboard --discover` (workspace discovery) — that answer common questions without the full agent loop.

### Who is it for?

- **Data engineers** optimizing SQL queries and debugging failing jobs
- **Platform administrators** right-sizing clusters and warehouses
- **FinOps analysts** analyzing costs, generating chargeback reports, and forecasting budgets
- **Developers** extending the system with new agents, tools, and integrations

### What interfaces are available?

The primary interface is the **`starboard` CLI**. On top of that, Starboard ships
**skills** for AI coding assistants (Claude Code / Cursor) and an **optional
`starboard-mcp` server** for MCP clients. Notebooks can drive the agent through the
in-package SDK (`from starboard.sdk import StarboardClient`). All paths share the same
multi-agent backend and produce the same analysis results.

---

## Agents

### How many agents does Starboard have?

Starboard has **8 domain agents** plus an **Intent Router** that classifies requests and routes them to the right specialist:

| Agent | Domain | What It Does |
|-------|--------|-------------|
| **Query** | SQL Optimization | Analyzes execution plans, identifies bottlenecks, suggests rewrites |
| **Job** | Job Performance | Debugs failing jobs, optimizes configurations, analyzes Spark logs |
| **UC** | Unity Catalog | Explores metadata, traces lineage, audits governance and access |
| **Cluster** | Compute | Analyzes cluster sizing, health, utilization, and autoscaling |
| **Analytics** | FinOps & Cost | Cost analysis, chargeback, budget forecasting (list-price DBU estimates) |
| **Warehouse** | SQL Warehouses | Portfolio optimization, SLO management, topology analysis |
| **Discovery** | Workspace Health | Workspace-wide assessment, resource inventory, health scoring |
| **Diagnostic** | Troubleshooting | Root cause analysis, debugging, cross-domain investigation |

### How does agent routing work?

The Intent Router uses a hybrid approach combining pattern matching and LLM classification. It identifies keywords and context in your message, classifies the domain, and dispatches to the best agent. If the confidence is low, it asks you for clarification. Agents can also hand off to each other mid-analysis when they discover issues outside their domain.

### Can agents work together?

Yes. Agents follow a handoff protocol where they pass context (resource IDs, partial findings) to the next specialist. For example, the Job Agent might discover a slow SQL query and hand off to the Query Agent with the statement ID already resolved.

---

## Setup

### What are the prerequisites?

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.12+ | Required for all backend components |
| Databricks workspace | Any | With API token and SQL warehouse access |
| LLM API key | -- | OpenAI, Azure OpenAI, or Databricks Model Serving |

### How long does setup take?

A few minutes: `pip install starboard`, authenticate (`starboard auth login` or set
environment variables), set `LLM_API_KEY`, then run `starboard review` or
`starboard --goal "…"`.

### Can I run Starboard without a Databricks connection?

Not for live analysis, but you can use **offline mode** (`--mode offline`) for static
analysis of a file you pass with `--input-file` and best-practice guidance without any
API calls.

### What environment variables do I need?

At minimum:

```bash
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi...
LLM_API_KEY=<your-api-key>
```

See the [Configuration Guide](../CONFIGURATION.md) for the complete reference.

---

## LLM and Cost

### Which LLM providers are supported?

Starboard supports any OpenAI-compatible API:

- **OpenAI** (GPT-4o, GPT-4o-mini, o1-preview)
- **Azure OpenAI** (via `LLM_BASE_URL` configuration)
- **Databricks Model Serving** (Claude, Llama, and other hosted models)
- **Any OpenAI-compatible endpoint** (local models, Ollama, etc.)

Configure the provider using `LLM_API_KEY`, `LLM_MODEL`, and optionally `LLM_BASE_URL`.

### How much does each analysis cost?

Costs vary by complexity and model:

| Analysis Type | Typical Tokens | Estimated Cost (GPT-4o) |
|---------------|---------------|------------------------|
| Simple query optimization | 1,000-5,000 | $0.01-$0.05 |
| Job debugging | 5,000-15,000 | $0.05-$0.15 |
| Complex multi-step analysis | 10,000-50,000 | $0.10-$0.50 |

### Can I set a token budget?

Yes. Set `LLM_MAX_TOKENS` in your environment to cap token usage per request. Agents will complete their analysis with best-effort recommendations when the budget is exhausted. You can also set per-domain model overrides to use cheaper models for simpler routing tasks.

### Can I use different models for different agents?

Yes. Use `DOMAIN_MODEL_OVERRIDES` to assign specific models per domain:

```bash
DOMAIN_MODEL_OVERRIDES='{"router": "gpt-4o-mini", "query": "gpt-4o", "diagnostic": "o1-preview"}'
```

---

## Output and integration

### Do I see progress while the agent works?

Yes. In `--goal` and `--chat` runs, the CLI streams the agent's reasoning steps, tool
calls, and intermediate results to your terminal as they happen, then prints the final
report. Use `--quiet` to suppress progress, or `--json` for a structured envelope only.

### How do I get machine-readable output?

Add `--json` to emit the shared JSON envelope (`{ok, domain, command, data|error,
meta}`) to stdout, and `--output-path ./reports/` to save JSON + Markdown report files.
The `python -m starboard_x.<cap>` middle-tier commands emit the same envelope.

### Can I call Starboard programmatically?

Yes. From Python, use the in-package SDK — `from starboard.sdk import StarboardClient`
— which is how the `examples/` notebooks drive the agent. AI coding assistants use the
[skills](../SKILLS.md); MCP clients can use the optional `starboard-mcp` server.

---

## Troubleshooting

### `starboard` can't authenticate

Check these common causes:

1. **No credentials resolved**: Provide `--profile <name>`, `--host` + `--token`, or
   `--client-id` + `--client-secret` — or run `starboard auth login`.
2. **Missing `.env`**: Put `DATABRICKS_HOST`/`DATABRICKS_TOKEN` and `LLM_API_KEY` in a
   `.env` file in the current directory (auto-loaded) or export them.
3. **Invalid credentials**: Run `starboard auth status` to see the resolved identity.
4. **`LLM_API_KEY` not set**: `export LLM_API_KEY="<your-api-key>"`.

### The agent picked the wrong domain

The Intent Router sometimes misclassifies ambiguous requests. Be specific in your query -- mention the resource type (query, job, table, cluster, warehouse) and include resource IDs when possible. You can also check debug logs to see the classification confidence.

### Analysis is slow

Response times depend on the number of tool calls, LLM model speed, and network latency. To speed things up:

1. Use a faster model for simple tasks (set `LLM_MODEL` or `--llm-model`)
2. Reduce the token budget if full analysis is unnecessary (`--llm-max-tokens`)
3. Narrow the scope (e.g. `starboard review --domains warehouse`)
4. Check network connectivity to Databricks and LLM endpoints

### A backend needs a driver I don't have installed

The default install is store-free. If you switch to a durable state backend or a vector
backend, Starboard raises an actionable error naming the extra to install, e.g.
`pip install 'starboard[sqlite]'`, `'starboard[postgres]'`, or `'starboard[vectorsearch]'`.

### How do I enable debug logging?

```bash
starboard --debug --goal "..."                       # debug logs to stderr
starboard --log-level DEBUG --log-file starboard.log --goal "..."
```

---

## Next Steps

- [Quickstart](../QUICKSTART.md) -- Get running in 5 minutes
- [Configuration Guide](../CONFIGURATION.md) -- Complete environment variable reference
- [What is Starboard?](../overview/what-is-starboard.md) -- Architecture overview
- [Agent Catalog](../overview/agents.md) -- Deep dive into each agent

---

**Last Updated**: 2026-03-24
**Version**: 2.0

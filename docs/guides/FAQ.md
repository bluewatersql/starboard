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

Starboard AI Agent is an AI-powered analysis and optimization platform for Databricks workloads. It uses 8 domain-specialized agents that reason step-by-step, call 45+ tools, and deliver actionable recommendations for queries, jobs, clusters, warehouses, costs, and governance.

### How does it work?

When you ask a question, an **Intent Router** classifies your request and dispatches it to the appropriate domain agent. That agent reasons about your question, selects tools dynamically to gather real data from Databricks APIs, analyzes the results, and streams back specific recommendations via SSE (Server-Sent Events).

### Who is it for?

- **Data engineers** optimizing SQL queries and debugging failing jobs
- **Platform administrators** right-sizing clusters and warehouses
- **FinOps analysts** analyzing costs, generating chargeback reports, and forecasting budgets
- **Developers** extending the system with new agents, tools, and integrations

### What interfaces are available?

Starboard provides three ways to interact: a **Web UI** (Next.js), a **CLI** (Python), and a **REST API** (FastAPI). All three share the same multi-agent backend and produce identical analysis results.

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
| **Analytics** | FinOps & Cost | Cost analysis, chargeback reports, budget forecasting |
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
| Node.js | 18+ | Required for the Web UI frontend |
| Databricks workspace | Any | With API token and SQL warehouse access |
| LLM API key | -- | OpenAI, Azure OpenAI, or Databricks Model Serving |

### How long does setup take?

First-time setup takes 15-30 minutes, mostly waiting for dependency installation. After that, starting development servers takes under 2 minutes with `make dev`.

### Can I run Starboard without a Databricks connection?

Not for live analysis, but you can use **offline mode** (`--mode offline`) for static analysis and testing. You can also enable **safe mode** (`SAFE_MODE=true`) to disable all external API calls. Unit tests run fully offline.

### What environment variables do I need?

At minimum:

```bash
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi...
LLM_API_KEY=sk-...
```

See the [Configuration Guide](../../CONFIGURATION.md) for the complete reference.

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

## Streaming and API

### How does real-time streaming work?

Starboard uses **SSE (Server-Sent Events)** to stream agent progress in real-time. As the agent reasons and calls tools, events are pushed to the client so you can see thinking steps, tool calls, intermediate results, and the final report as they happen.

### Why SSE instead of WebSockets?

SSE is simpler for one-way server-to-client streaming, works through HTTP firewalls and proxies without special configuration, and includes built-in auto-reconnect via the browser EventSource API. Since Starboard only needs to push data from server to client, SSE is the right protocol.

### Can I use the API without the Web UI?

Yes. The REST API is fully standalone with OpenAPI documentation at `/docs`. You can call it from any HTTP client, the CLI, or the Python SDK.

---

## Troubleshooting

### The server won't start

Check these common causes:

1. **Port in use**: Run `lsof -i :8000` to find conflicting processes
2. **Missing `.env`**: Copy `examples/env.example` to `.env` and configure credentials
3. **Invalid credentials**: Verify `DATABRICKS_TOKEN` and `LLM_API_KEY` are correct
4. **Dependencies missing**: Run `make setup` to install all packages

### The agent picked the wrong domain

The Intent Router sometimes misclassifies ambiguous requests. Be specific in your query -- mention the resource type (query, job, table, cluster, warehouse) and include resource IDs when possible. You can also check debug logs to see the classification confidence.

### Analysis is slow

Response times depend on the number of tool calls, LLM model speed, and network latency. To speed things up:

1. Use a faster model (`gpt-4o-mini` for simple tasks)
2. Reduce token budget if full analysis is unnecessary
3. Check network connectivity to Databricks and LLM endpoints

### Tests are failing

Common causes:

1. **Packages not installed**: Run `uv sync` or `make setup`
2. **Environment variables missing**: Unit tests should not need credentials
3. **Snapshot mismatch**: Run `make test-golden` to update golden files after prompt changes

### How do I enable debug logging?

```bash
LOG_LEVEL=DEBUG make dev-server
```

Or set `LOG_LEVEL=DEBUG` in your `.env` file.

---

## Next Steps

- [Quickstart](../../QUICKSTART.md) -- Get running in 5 minutes
- [Configuration Guide](../../CONFIGURATION.md) -- Complete environment variable reference
- [What is Starboard?](../../overview/what-is-starboard.md) -- Architecture overview
- [Agent Catalog](../../overview/agents.md) -- Deep dive into each agent

---

**Last Updated**: 2026-03-24
**Version**: 2.0

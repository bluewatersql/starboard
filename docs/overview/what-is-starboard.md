# What is Starboard AI Agent?

**Starboard AI Agent** is an AI-powered analysis and optimization platform for Databricks workloads. It uses a multi-agent architecture where domain-specialized AI agents reason step-by-step to analyze SQL queries, jobs, pipelines, costs, and infrastructure — then provide actionable recommendations.

---

## How It Works

Instead of a single chatbot, Starboard uses **8 specialized agents**, each expert in a different Databricks domain. When you ask a question, an Intent Router classifies your request and dispatches it to the right agent. That agent then:

1. **Reasons** about your question step-by-step
2. **Selects tools** dynamically based on what data it needs
3. **Calls Databricks APIs** to gather real information
4. **Analyzes** the results using domain expertise
5. **Streams** a response with specific, actionable recommendations

```
You: "Why is my nightly ETL job taking 3 hours?"

→ Intent Router classifies as "Job Analysis"
→ Job Agent activates
→ Calls: resolve_job → get_job_config → analyze_job_history → get_cluster_config
→ Finds: Undersized cluster, no autoscaling, shuffle spill
→ Returns: Specific optimization recommendations with expected improvement
```

---

## Domain Agents

| Agent | Domain | What It Does |
|-------|--------|-------------|
| **Query Agent** | SQL Optimization | Analyzes query plans, identifies bottlenecks, suggests rewrites |
| **Job Agent** | Job Performance | Debugs failing jobs, optimizes configurations, analyzes task dependencies |
| **UC Agent** | Unity Catalog | Explores metadata, traces lineage, audits governance and access patterns |
| **Cluster Agent** | Compute | Analyzes cluster configurations, health, utilization, and right-sizing |
| **Analytics Agent** | FinOps & Cost | Cost analysis, chargeback reports, budget forecasting, usage trends |
| **Warehouse Agent** | SQL Warehouses | Portfolio optimization, topology analysis, SLO configuration |
| **Discovery Agent** | Workspace Health | Workspace-wide assessment, resource inventory, health scoring |
| **Diagnostic Agent** | Troubleshooting | Root cause analysis, debugging, cross-domain issue diagnosis |

Each agent has access to specialized tools (45+ total) and domain-specific prompts that encode Databricks best practices.

---

## Key Capabilities

### Intelligent Analysis
- **Natural language interface** — Ask questions in plain English
- **Multi-step reasoning** — Agents gather data iteratively, not in one shot
- **Cross-agent handoffs** — Complex questions span multiple domains automatically
- **Interruptible reasoning** — Provide additional context mid-analysis

### Real-Time Streaming
- **Server-Sent Events (SSE)** — Watch the agent think and work in real-time
- **Tool call visibility** — See which APIs are being called and what data is returned
- **Progressive results** — Get partial answers as the agent works

### Production Ready
- **Multiple interfaces** — Web UI, CLI, REST API
- **Pluggable state backends** — SQLite (dev), Postgres (production), Databricks Lakebase
- **Conversation history** — Full persistence with search
- **Caching** — Semantic cache for repeated queries, metadata cache for API results

---

## Architecture at a Glance

```
┌──────────────────────────────────────────────────────┐
│                    User Interfaces                     │
│   Web UI (Next.js)  │  CLI (Python)  │  REST API     │
└──────────┬───────────┴────────┬───────┴──────┬────────┘
           │                    │              │
           ▼                    ▼              ▼
┌──────────────────────────────────────────────────────┐
│                   FastAPI Backend                      │
│  ┌─────────────┐  ┌──────────────────────────────┐   │
│  │Intent Router │→│ Multi-Agent Conversation Mgr  │   │
│  └─────────────┘  └──────────────────────────────┘   │
│                           │                           │
│  ┌────────────────────────┼───────────────────────┐  │
│  │  Query │ Job │ UC │ Cluster │ Analytics │ ...  │  │
│  │                Domain Agents                    │  │
│  └────────────────────────┼───────────────────────┘  │
│                           │                           │
│  ┌────────────────────────┼───────────────────────┐  │
│  │              45+ Tools (3-Layer)                │  │
│  │   Domain (Logic) → Service (I/O) → Adapter     │  │
│  └────────────────────────┼───────────────────────┘  │
└───────────────────────────┼──────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        Databricks      LLM Provider    State Store
        APIs            (OpenAI/etc)    (SQLite/PG)
```

For the complete architecture deep-dive, see [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12, FastAPI, asyncio, Pydantic V2, structlog |
| **Frontend** | Next.js 16, React 19, Material UI v7, Tailwind CSS v4, Zustand v5 |
| **LLM** | OpenAI-compatible (GPT-4o, Claude via Databricks Model Serving) |
| **State** | SQLite/Postgres/Databricks Lakebase, Redis (cache), sqlite-vec/pgvector (embeddings) |
| **Package Manager** | uv (Python workspace), npm (frontend) |
| **Quality** | ruff, mypy, pytest (3,200+ tests), pre-commit hooks |

---

## Who Is This For?

- **Data Engineers** — Optimize slow queries, debug failing jobs, understand table lineage
- **Platform Admins** — Deploy, configure, monitor, and troubleshoot the system
- **FinOps Analysts** — Cost analysis, chargeback reports, budget optimization
- **Developers** — Extend the system with new agents, tools, and integrations

---

## Next Steps

- [Quickstart](../QUICKSTART.md) — Get running in 5 minutes
- [Web UI Guide](../user-guide/web-ui.md) — Learn the web interface
- [CLI Reference](../user-guide/cli.md) — Command-line usage
- [Agent Catalog](agents.md) — Deep dive into each agent's capabilities

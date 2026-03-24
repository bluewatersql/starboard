---
title: Capacity Planning Guide
description: Infrastructure sizing guidance for Starboard deployments based on expected usage.
last_reviewed: 2026-03-24
status: current
---

# Capacity Planning Guide

> **Docs** > **Administration** > **Capacity Planning**
> Reading time: 10 minutes

## What You'll Learn

- How to size compute, memory, and storage for your deployment
- How to estimate LLM API costs based on usage patterns
- When and how to scale Starboard horizontally
- Monitoring thresholds that indicate it is time to scale

---

## Sizing Dimensions

Capacity planning for Starboard involves four dimensions:

| Dimension | Key Metric | Scales With |
|-----------|-----------|-------------|
| **Compute** | CPU cores and memory | Concurrent conversations |
| **Storage** | Database size | Total conversations and memory entries |
| **LLM API** | Tokens per month | Conversations per day and complexity |
| **Network** | SSE connections | Concurrent Web UI users |

---

## Sizing Tiers

The following table provides reference configurations for three deployment sizes. Adjust based on your actual usage patterns.

| Resource | Small (1--10 users) | Medium (10--50 users) | Large (50+ users) |
|----------|--------------------|-----------------------|-------------------|
| **Conversations/day** | 5--20 | 20--100 | 100--500+ |
| **Backend CPU** | 2 cores | 4 cores | 8+ cores (2+ instances) |
| **Backend Memory** | 4 GB | 8 GB | 16 GB per instance |
| **Frontend CPU** | 1 core | 2 cores | 2 cores per instance |
| **Frontend Memory** | 1 GB | 2 GB | 2 GB per instance |
| **State DB (Postgres)** | 1 GB initial | 5 GB initial | 20 GB initial |
| **Vector Store** | 500 MB | 2 GB | 10 GB |
| **Redis Cache** | 256 MB | 1 GB | 4 GB |
| **LLM Tokens/month** | ~5M | ~25M | ~125M+ |
| **Est. LLM Cost/month** | $15--75 | $75--375 | $375--1,800+ |

!!! tip "Start small"
    Most teams start with the Small tier and scale up as usage grows. Starboard is designed to scale horizontally, so you can add backend instances without downtime.

---

## Compute Requirements

### Backend (FastAPI)

The backend is CPU-bound during request parsing and tool execution, and I/O-bound while waiting for LLM and Databricks API responses. Key factors:

- **Concurrent conversations**: Each active conversation uses one async task. FastAPI handles hundreds of concurrent connections per process.
- **Tool parallelism**: The `TOOL_PARALLELISM` setting (default: 4) controls how many tools can execute in parallel per conversation.
- **Memory per conversation**: Each conversation context uses approximately 10--50 MB depending on message history length.

**Recommendation:**

| Concurrent Conversations | CPU | Memory |
|--------------------------|-----|--------|
| 1--5 | 2 cores | 4 GB |
| 5--20 | 4 cores | 8 GB |
| 20--50 | 4 cores x 2 instances | 8 GB each |
| 50+ | 4 cores x N instances | 8 GB each |

### Frontend (Next.js)

The frontend is lightweight. A single instance handles hundreds of concurrent browser sessions. SSE connections are long-lived but consume minimal server resources.

**Recommendation:** 1--2 cores, 1--2 GB memory for all tiers. Scale only if serving 100+ concurrent browser sessions.

---

## Storage Requirements

### State Database

The state database stores conversations, messages, episodes, facts, and user profiles.

**Growth estimates:**

| Data Type | Size Per Entry | Retention |
|-----------|---------------|-----------|
| Conversation metadata | ~1 KB | Indefinite |
| Message (user or agent) | ~2--10 KB | Indefinite |
| Agent report (structured) | ~5--50 KB | Indefinite |
| Episode (memory) | ~1--5 KB | Indefinite |
| Fact (extracted knowledge) | ~500 bytes | Indefinite |

**Monthly growth estimate:**

| Conversations/Month | Approx. Storage Growth |
|---------------------|----------------------|
| 100 | ~50 MB |
| 500 | ~250 MB |
| 2,000 | ~1 GB |
| 10,000 | ~5 GB |

!!! note "Backend choice affects sizing"
    SQLite is suitable for up to ~10,000 conversations. Beyond that, migrate to PostgreSQL for better concurrent access and query performance. See the [State Backends](state-backends.md) guide.

### Vector Store

The vector store holds embeddings for semantic search and caching. Each embedding is approximately 6 KB (1536 dimensions x 4 bytes).

**Estimated size:** ~100 MB per 10,000 embeddings. Growth depends on the `ENABLE_SEMANTIC_CACHE` setting and conversation volume.

### Redis Cache

Redis stores transient data: session state, rate limit counters, and tool result caches. Data expires via TTL, so Redis memory usage stays bounded.

**Recommendation:** Set `maxmemory` to 256 MB (small), 1 GB (medium), or 4 GB (large) with an `allkeys-lru` eviction policy.

---

## LLM API Budget

LLM API costs are typically the largest operational expense. The cost depends on the model, conversation complexity, and number of reasoning steps.

### Token Usage by Agent

| Agent | Avg. Tokens/Conversation | Typical Cost (GPT-4o) |
|-------|-------------------------|----------------------|
| **Router** | 2,000--5,000 | $0.01--0.03 |
| **Query** | 15,000--40,000 | $0.08--0.20 |
| **Job** | 20,000--60,000 | $0.10--0.30 |
| **UC** | 15,000--50,000 | $0.08--0.25 |
| **Cluster** | 10,000--30,000 | $0.05--0.15 |
| **Analytics** | 15,000--40,000 | $0.08--0.20 |
| **Warehouse** | 15,000--40,000 | $0.08--0.20 |
| **Discovery** | 40,000--100,000 | $0.20--0.50 |
| **Diagnostic** | 30,000--80,000 | $0.15--0.40 |

!!! warning "Discovery is expensive"
    The Discovery agent runs a full 4-phase pipeline that can consume significant tokens. Consider limiting discovery runs to weekly or monthly schedules.

### Monthly Cost Projections

| Scenario | Conversations/Month | Avg. Tokens/Conv | Monthly Tokens | Est. Monthly Cost |
|----------|--------------------|--------------------|----------------|-------------------|
| **Light usage** (5 users, occasional) | 100 | 25,000 | 2.5M | $12--25 |
| **Regular usage** (20 users, daily) | 500 | 30,000 | 15M | $75--150 |
| **Heavy usage** (50 users, frequent) | 2,000 | 35,000 | 70M | $350--700 |
| **Enterprise** (100+ users) | 10,000 | 30,000 | 300M | $1,500--3,000 |

> Cost estimates assume GPT-4o pricing ($2.50/1M input, $10.00/1M output). Databricks-hosted models and other providers have different pricing. Check your provider's current rates.

### Cost Optimization Strategies

1. **Use smaller models for routing.** Set `DOMAIN_MODEL_OVERRIDES='{"router": "gpt-4o-mini"}'` to use a cheaper model for intent classification.
2. **Enable semantic caching.** Set `ENABLE_SEMANTIC_CACHE=true` to cache similar queries (default TTL: 5 minutes for tool results).
3. **Set token budgets.** Use `LLM_MAX_TOKENS` to cap per-conversation spend.
4. **Disable unused agents.** Set `DISABLED_AGENT_DOMAINS=diagnostic,discovery` if those domains are not needed.
5. **Use message compression.** Reduces context window usage by 30--50% for long conversations.

---

## Scaling Patterns

### Vertical Scaling

Add more CPU and memory to existing instances. Effective up to about 50 concurrent conversations per backend instance.

### Horizontal Scaling (Backend)

Run multiple backend instances behind a load balancer. Requirements:

- **Shared state backend**: All instances must connect to the same PostgreSQL (or Lakebase) database.
- **Shared cache**: All instances should use the same Redis instance for session state.
- **Sticky sessions (optional)**: SSE connections benefit from sticky sessions to avoid reconnection overhead, but the system works without them.

```
                    ┌──────────────────┐
                    │   Load Balancer   │
                    └────────┬─────────┘
                 ┌───────────┼───────────┐
                 ▼           ▼           ▼
          ┌──────────┐ ┌──────────┐ ┌──────────┐
          │Backend 1 │ │Backend 2 │ │Backend 3 │
          └────┬─────┘ └────┬─────┘ └────┬─────┘
               │            │            │
          ┌────▼────────────▼────────────▼────┐
          │         PostgreSQL + Redis         │
          └───────────────────────────────────┘
```

### Read Replicas

For high-traffic deployments, add PostgreSQL read replicas for conversation history queries. Write operations (new messages, state updates) go to the primary.

---

## Monitoring Thresholds

Set up alerts at these thresholds to know when to scale:

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Backend CPU (avg) | > 60% sustained | > 80% sustained | Add backend instance |
| Backend memory | > 70% | > 85% | Increase memory or add instance |
| Request latency (p95) | > 2s first token | > 5s first token | Check LLM provider; add instance |
| Active SSE connections | > 80% of max | > 95% of max | Add backend instance |
| PostgreSQL connections | > 70% of pool | > 90% of pool | Increase pool size or add instance |
| Redis memory | > 70% of maxmemory | > 90% of maxmemory | Increase maxmemory |
| State DB size | > 80% of disk | > 90% of disk | Expand storage; consider archival |
| LLM token usage | > 80% of monthly budget | > 95% of monthly budget | Review usage; reduce budgets |

!!! tip "Use the health endpoints"
    Monitor `/health/live` and `/health/ready` with your preferred monitoring tool (Datadog, Prometheus, CloudWatch, etc.). The readiness probe confirms all dependencies are available.

---

## Databricks Apps Deployment

When deploying via Databricks Apps, capacity planning is simplified:

- **Auto-scaling**: Databricks Apps scales from 1 to 10 instances automatically based on load.
- **Resource requests**: Configure CPU and memory per instance in `databricks.yml`.
- **No separate database management**: Use Databricks Lakebase for state storage.

```yaml
compute:
  - name: main
    autoscaling:
      enabled: true
      min_instances: 1
      max_instances: 10
    resources:
      requests:
        cpu: "2"
        memory: "4Gi"
```

---

## Next Steps

- [LLM Cost Estimation](cost-estimation.md) -- Detailed cost modeling and optimization
- [State Backends](state-backends.md) -- Choosing and configuring storage backends
- [Monitoring and Observability](monitoring.md) -- Setting up dashboards and alerts
- [Deployment Guide](../DEPLOYMENT.md) -- Deploying Starboard to production

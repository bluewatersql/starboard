# Capacity Planning Runbook Template

## Overview
Use this template for periodic capacity reviews and scaling decisions.

## Current Resource Inventory

| Resource | Provider | Current Spec | Utilization | Notes |
|----------|----------|-------------|-------------|-------|
| Postgres | (provider) | (instance type) | (%) | Primary state store |
| Redis | (provider) | (instance type) | (%) | Session cache |
| Application | (provider) | (instance count) | (%) | FastAPI backend |
| LLM API | OpenAI | (tier) | (tokens/day) | GPT-4o / GPT-4o-mini |

## Key Metrics to Monitor

### Application Layer
- Request latency (p50, p95, p99)
- Requests per second (RPS)
- Active WebSocket/SSE connections
- Error rate (4xx, 5xx)

### Database Layer
- Connection pool utilization
- Query latency (p95)
- Disk usage and growth rate
- Replication lag (if applicable)

### LLM / Token Budget
- Tokens consumed per request (prompt + completion)
- Daily/monthly token spend (USD)
- Rate limit headroom (requests/min, tokens/min)
- Queue depth for pending LLM calls

### Infrastructure
- CPU utilization (target: < 70% sustained)
- Memory utilization (target: < 80%)
- Network I/O
- Disk I/O and latency

## Scaling Triggers

| Metric | Warning Threshold | Critical Threshold | Action |
|--------|-------------------|-------------------|--------|
| CPU utilization | > 60% sustained (15 min) | > 80% sustained (5 min) | Scale horizontally |
| Memory utilization | > 70% | > 85% | Scale vertically or add nodes |
| p95 latency | > 2s | > 5s | Investigate bottleneck |
| DB connections | > 70% pool | > 90% pool | Increase pool or add read replicas |
| LLM rate limits | > 50% quota | > 80% quota | Request quota increase or add caching |

## Capacity Review Cadence
- **Weekly**: Review dashboards for anomalies
- **Monthly**: Full capacity review with metrics trends
- **Quarterly**: Cost optimization review and right-sizing

## Scaling Playbook

### Horizontal Scaling (Application)
1. Increase instance count in deployment config
2. Verify load balancer health checks pass
3. Monitor for even traffic distribution

### Vertical Scaling (Database)
1. Schedule maintenance window
2. Snapshot current database
3. Resize instance
4. Verify connections and query performance

### LLM Cost Optimization
1. Review token usage by agent domain
2. Identify opportunities to reduce prompt size
3. Evaluate model downgrades for simple tasks (GPT-4o-mini)
4. Check token budget configuration (see TOKEN_BUDGET.md)

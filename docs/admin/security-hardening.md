---
title: Security Hardening Guide
description: Comprehensive security checklist and procedures for hardening a Starboard deployment.
last_reviewed: 2026-03-24
status: current
---

# Security Hardening Guide

> **Docs** > **Administration** > **Security Hardening**
> Reading time: 15 minutes

## What You'll Learn

- How to secure network communication, authentication, and secrets
- How to protect against LLM-specific threats (prompt injection, data exfiltration)
- How to configure rate limiting, audit logging, and PII protection
- A pre-production security checklist

---

## Trust Boundaries

Starboard has four trust zones. Security controls must be applied at each boundary crossing.

```mermaid
graph LR
    subgraph Public Zone
        U[User Clients<br/>Browser / CLI / SDK]
    end
    subgraph DMZ
        LB[Load Balancer<br/>TLS Termination]
        RL[Rate Limiter]
    end
    subgraph Private Zone
        API[FastAPI Backend]
        AG[Agents]
        TL[Tools]
    end
    subgraph External Zone
        DB[Databricks APIs]
        LLM[LLM Provider<br/>OpenAI / Azure / Databricks]
        SS[State Store<br/>Postgres / Lakebase]
    end

    U -->|HTTPS| LB
    LB --> RL
    RL --> API
    API --> AG
    AG --> TL
    TL -->|HTTPS| DB
    AG -->|HTTPS| LLM
    API -->|TLS| SS

    style U fill:#F5A623,color:#fff
    style API fill:#4A90E2,color:#fff
    style DB fill:#7ED321,color:#fff
    style LLM fill:#7ED321,color:#fff
```

*Trust boundary diagram: user traffic enters through TLS/rate limiter, agents and tools operate in the private zone, and external API calls use HTTPS.*

---

## Network Security

### TLS Configuration

All external-facing endpoints must use TLS 1.2 or later.

1. **Load balancer / reverse proxy**: Terminate TLS at the load balancer (e.g., nginx, Caddy, ALB).
2. **Backend**: The FastAPI backend listens on HTTP internally. Do not expose port 8000 directly to the internet.
3. **Database connections**: Use `sslmode=require` for PostgreSQL connections:
   ```
   DATABASE_URL=postgres://user:pass@host:5432/db?sslmode=require
   ```
4. **Redis**: Use TLS-enabled Redis (e.g., `rediss://` scheme) in production:
   ```
   REDIS_URL=rediss://user:pass@host:6380
   ```

### Firewall Rules

| Source | Destination | Port | Protocol | Purpose |
|--------|-------------|------|----------|---------|
| Users | Load Balancer | 443 | HTTPS | Web UI and API |
| Load Balancer | Backend | 8000 | HTTP | Internal proxy |
| Backend | PostgreSQL | 5432 | TCP/TLS | State storage |
| Backend | Redis | 6379/6380 | TCP/TLS | Cache |
| Backend | LLM Provider | 443 | HTTPS | LLM API calls |
| Backend | Databricks | 443 | HTTPS | Workspace APIs |

!!! danger "Do not expose the backend directly"
    The backend has no built-in TLS. Always place it behind a reverse proxy or load balancer that handles TLS termination.

### CORS Configuration

The backend includes CORS middleware. In production, restrict allowed origins:

```bash
# Restrict to your domain (do NOT use * in production)
ALLOWED_ORIGINS=https://starboard.your-company.com
```

---

## Authentication and Authorization

### Databricks Authentication

Starboard authenticates to Databricks using one of:

- **Personal Access Token (PAT)**: Set `DATABRICKS_TOKEN`. Suitable for development and small teams.
- **Service Principal**: Recommended for production. Create a Databricks service principal with the minimum required permissions.
- **OAuth (Databricks Apps)**: When deployed as a Databricks App, authentication is handled by workspace SSO automatically.

!!! warning "Principle of least privilege"
    The Databricks token or service principal should have only the permissions needed by the tools:

    - `SELECT` on system tables (`system.billing.usage`, `system.compute.*`, etc.)
    - `SELECT` on Unity Catalog tables being analyzed
    - `CAN_VIEW` on jobs and clusters
    - `CAN_USE` on SQL warehouses (for executing queries)

### LLM Provider Authentication

- Set `LLM_API_KEY` as an environment variable or via a secrets manager.
- For Azure OpenAI, use managed identity where possible.
- Rotate API keys on a regular schedule (every 90 days recommended).

### User Authentication

Starboard does not currently include a built-in user authentication system. For production deployments:

1. **Databricks Apps**: Workspace SSO is built in.
2. **Self-hosted**: Place an authentication proxy (e.g., OAuth2 Proxy, Authelia) in front of the backend.
3. **API access**: Implement API key or JWT validation in a middleware layer.

---

## Secret Management

### Environment Variables

Secrets are stored in environment variables. Never commit them to source control.

| Secret | Environment Variable | Rotation Schedule |
|--------|---------------------|-------------------|
| Databricks token | `DATABRICKS_TOKEN` | Every 90 days |
| LLM API key | `LLM_API_KEY` | Every 90 days |
| Database password | `DATABASE_URL` (embedded) | Every 90 days |
| Redis password | `REDIS_URL` (embedded) | Every 90 days |

### Secret Storage Options

| Approach | When to Use |
|----------|-------------|
| `.env` file | Local development only. Add to `.gitignore`. |
| Databricks Secret Scope | Databricks Apps deployments. Use `dbutils.secrets.get()`. |
| AWS Secrets Manager | AWS deployments. Inject into environment at container startup. |
| Azure Key Vault | Azure deployments. Use managed identity for access. |
| HashiCorp Vault | Multi-cloud or on-premises. Inject via sidecar or init container. |

!!! danger "Never commit secrets"
    The repository includes `.gitignore` rules for `.env` files. If you suspect a secret has been committed:
    1. Rotate the compromised credential immediately.
    2. Remove the secret from git history using `git filter-branch` or BFG Repo-Cleaner.
    3. Force-push the cleaned history.

---

## PII Protection

### Log Redaction

Starboard uses structured logging. Production logs should never contain:

- User prompts (may contain PII or sensitive business data)
- Full LLM responses (may echo user data)
- Databricks tokens or API keys
- Database credentials

Configure log level and format for production:

```bash
LOG_LEVEL=INFO          # Do not use DEBUG in production
LOG_JSON=true           # Structured JSON logs for parsing
ENVIRONMENT=production  # Enables production log filtering
```

### Prompt Sanitization

The agent system processes user prompts that may contain sensitive data. Mitigations:

1. **Do not log full prompts** at INFO level. Debug logging includes prompts but should never be enabled in production.
2. **Token-level PII detection** is available via the observability layer. Enable it for regulated environments.
3. **LLM provider data policies**: Review your LLM provider's data retention and training policies. Most enterprise tiers do not use your data for training.

---

## Rate Limiting and Abuse Prevention

### Built-in Rate Limiting

Starboard includes a rate limiter configured via environment variables:

```bash
RATE_LIMIT_ENABLED=true
RATE_LIMIT_STORAGE=redis://localhost:6379   # Use Redis for multi-instance
RATE_LIMIT_DEFAULT=100/minute               # Default limit
MAX_REQUEST_SIZE=10485760                   # 10 MB max request body
```

### Recommended Limits

| Endpoint | Recommended Limit | Rationale |
|----------|-------------------|-----------|
| `POST /api/chat/conversations/{id}/messages` | 20/minute per user | Prevents runaway LLM costs |
| `POST /api/chat/conversations` | 10/minute per user | Limits conversation creation |
| `GET /health/*` | No limit | Monitoring must not be throttled |
| All other endpoints | 100/minute per user | General protection |

### LLM Cost Protection

Beyond rate limiting, protect against excessive LLM costs:

1. **Token budgets**: Set `LLM_MAX_TOKENS=75000` to cap per-conversation token usage.
2. **Step limits**: The agent has a maximum reasoning step limit (default: 20) that prevents infinite loops.
3. **Disabled agents**: Set `DISABLED_AGENT_DOMAINS` to disable expensive agents (e.g., `discovery`) if they are not needed.

---

## LLM-Specific Security

### Prompt Injection Defense

Prompt injection is an attack where a user crafts input that causes the LLM to ignore its instructions. Mitigations:

1. **System prompt isolation**: Agent system prompts are separated from user input and tool results.
2. **Tool result validation**: Tool outputs are validated by Pydantic schemas before being processed.
3. **Structured output**: Agents use JSON-mode / function-calling schemas that constrain output format.
4. **Scope limitation**: Each agent can only call tools in its domain (except the Diagnostic agent).

### Data Exfiltration Prevention

Prevent the agent from leaking sensitive data:

1. **Tool restrictions**: Agents cannot make arbitrary HTTP calls. All external access is through registered tools.
2. **No code execution**: Agents analyze code but do not execute arbitrary user code.
3. **Output validation**: Agent outputs pass through report formatters that strip unexpected content.

### Model Output Validation

1. **JSON schema validation**: All LLM outputs are validated against Pydantic models.
2. **Fallback handling**: Invalid JSON triggers a repair prompt or graceful fallback.
3. **Hallucination mitigation**: Tools provide real data; agents are instructed to cite tool results, not generate data.

---

## Dependency Scanning

### Pre-commit Hooks

The repository includes pre-commit hooks for secret scanning:

```bash
# Install pre-commit hooks
make setup  # Includes pre-commit install

# Manual run
pre-commit run --all-files
```

### Dependency Auditing

Regularly audit Python dependencies for known vulnerabilities:

```bash
# Using pip-audit
pip install pip-audit
pip-audit

# Using safety
pip install safety
safety check
```

!!! tip "Automate in CI"
    Add dependency scanning to your CI pipeline. Run `pip-audit` on every PR that modifies `pyproject.toml` or lock files.

---

## Audit Logging

### What to Log

In production, ensure the following events are logged with structured fields:

| Event | Fields | Purpose |
|-------|--------|---------|
| Conversation created | `conversation_id`, `user_id`, `timestamp` | Usage tracking |
| Message sent | `conversation_id`, `user_id`, `domain`, `timestamp` | Audit trail |
| Tool called | `tool_name`, `conversation_id`, `trace_id`, `duration_ms` | Debugging |
| Agent error | `error_type`, `trace_id`, `conversation_id` | Incident response |
| LLM call | `model`, `tokens_used`, `cost_usd`, `trace_id` | Cost tracking |
| Auth failure | `source_ip`, `timestamp`, `reason` | Security monitoring |

### Log Retention

| Log Type | Minimum Retention | Recommended Retention |
|----------|-------------------|-----------------------|
| Access logs | 90 days | 1 year |
| Agent activity | 90 days | 6 months |
| Error logs | 90 days | 1 year |
| Audit events | 1 year | 3 years (compliance) |

---

## Pre-Production Security Checklist

Complete this checklist before deploying to production:

### Network

- [ ] TLS 1.2+ on all external-facing endpoints
- [ ] Backend not directly exposed to the internet
- [ ] CORS restricted to specific origins (no wildcards)
- [ ] Firewall rules limit traffic to required ports only
- [ ] Database connections use TLS (`sslmode=require`)

### Authentication

- [ ] Databricks token is a service principal (not a personal token)
- [ ] Service principal has minimum required permissions
- [ ] LLM API key has appropriate rate limits at the provider level
- [ ] User authentication proxy is in place (self-hosted deployments)

### Secrets

- [ ] No secrets in source code or git history
- [ ] `.env` file is in `.gitignore`
- [ ] Secrets stored in a secrets manager (not environment files on disk)
- [ ] Secret rotation schedule defined and documented
- [ ] Pre-commit hooks for secret scanning are active

### Data Protection

- [ ] `LOG_LEVEL=INFO` (not DEBUG) in production
- [ ] `LOG_JSON=true` for structured log parsing
- [ ] Full prompts are not logged at INFO level
- [ ] PII detection enabled for regulated environments
- [ ] LLM provider data policies reviewed and documented

### Rate Limiting

- [ ] `RATE_LIMIT_ENABLED=true`
- [ ] Per-endpoint rate limits configured
- [ ] Token budget (`LLM_MAX_TOKENS`) set appropriately
- [ ] Max request size limited (`MAX_REQUEST_SIZE`)

### Monitoring

- [ ] Health endpoints monitored (`/health/live`, `/health/ready`)
- [ ] Alerting on auth failures and error rate spikes
- [ ] LLM cost monitoring with budget alerts
- [ ] Log aggregation configured (ELK, Datadog, CloudWatch, etc.)

### Dependencies

- [ ] Dependency audit run (`pip-audit`)
- [ ] No known critical vulnerabilities in dependencies
- [ ] Dependency scanning in CI pipeline

---

## Next Steps

- [Deployment Guide](../DEPLOYMENT.md) -- Deploy Starboard to production
- [Monitoring and Observability](monitoring.md) -- Set up dashboards and alerts
- [Backup and Recovery](backup-recovery.md) -- Data protection procedures
- [Configuration Reference](../CONFIGURATION.md) -- Complete environment variable reference

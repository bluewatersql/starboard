---
title: Backup and Recovery Procedures
description: Backup procedures for Starboard deployments.
last_reviewed: 2026-09-02
status: current
---

# Backup and Recovery Procedures

> **Docs** > **Administration** > **Backup and Recovery**
> Reading time: 5 minutes

## What You'll Learn

- What data needs to be backed up and how often
- Backup procedures for configuration and CLI sessions
- Redis cache recovery

---

## What to Back Up

Starboard uses **in-memory state only** — there is no external database. Data to back
up is limited to configuration and, optionally, CLI session files.

| Data Category | Storage | Criticality | Backup Required |
|---------------|---------|-------------|-----------------|
| **Configuration** (environment variables, credentials) | `.env` / secrets manager | High | Yes — version-controlled or stored in a secrets manager |
| **CLI sessions** (`SessionManager` JSON file) | `~/.starboard/sessions.db` (local) | Low | Optional — lost sessions can be re-created |
| **Cache** (tool results, sessions) | Redis / InMemory | None | No (transient, regenerates automatically) |

!!! info "In-memory state"
    Conversation state lives only in the running process. When the process exits, state
    is lost. There is no database file to back up. If you need to retain analysis results
    across restarts, save them with `--output-path ./reports/` (writes JSON + Markdown)
    or use `--json` to pipe output to a file.

---

## Recovery Objectives

| Objective | Deployment |
|-----------|------------|
| **RPO** (Recovery Point Objective) | N/A for runtime state (memory-only); configuration: per secrets-manager policy |
| **RTO** (Recovery Time Objective) | Minutes (restart process + reload configuration) |

---

## Configuration Backup

Environment variables and credentials are the only durable Starboard configuration.
Back them up using your standard secrets management tooling.

### Best Practices

- Store secrets in a secrets manager (AWS Secrets Manager, HashiCorp Vault, Azure Key
  Vault, GCP Secret Manager, Databricks Secrets).
- Keep a version-controlled, **non-secret** reference in `examples/env.example` that
  documents every variable name without values.
- Never commit `.env` files containing real credentials to source control.

### Recovery

1. Retrieve credentials from your secrets manager.
2. Write them to `.env` or export as environment variables.
3. Restart the Starboard process — no schema migration or data import is needed.

---

## CLI Sessions

Named CLI sessions are persisted by the `SessionManager` as a JSON file at
`~/.starboard/sessions.db` (overridable with `--session-db`). This file is
per-machine and stores session metadata for the `--session <name>` feature.

### Backup (optional)

```bash
# Copy the session file
cp ~/.starboard/sessions.db /backups/starboard/sessions_$(date +%Y%m%d).db
```

### Restore

```bash
cp /backups/starboard/sessions_20260901.db ~/.starboard/sessions.db
```

If the session file is lost, named sessions will start fresh — no analysis data is
lost, only the conversation history for that session name.

---

## Redis Cache

Redis stores transient data (tool result caches). All data has a TTL and regenerates
automatically.

**Backup is not required.** If Redis is lost:

1. Restart Redis.
2. Restart the Starboard backend. It reconnects automatically.
3. Cache misses will be warmed up organically as tools are called.

If you want to persist Redis snapshots for faster warm-up after a restart:

```bash
# Trigger an RDB snapshot
redis-cli BGSAVE

# Copy the dump file
cp /var/lib/redis/dump.rdb /backups/starboard/redis_$(date +%Y%m%d).rdb
```

---

## Saving Analysis Results

Because runtime state is in-memory, save important results immediately:

```bash
# Save JSON + Markdown to a directory
starboard --goal "Analyze job 12345" --output-path ./reports/

# Pipe structured JSON to a file
starboard review --json > reports/review_$(date +%Y%m%d).json
```

---

## Next Steps

- [State Management](state-backends.md) — State architecture
- [Capacity Planning](capacity-planning.md) — Resource sizing
- [Monitoring and Observability](monitoring.md) — Operational health

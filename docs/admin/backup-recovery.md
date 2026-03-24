---
title: Backup and Recovery Procedures
description: Backup procedures for each state backend and recovery runbooks for Starboard deployments.
last_reviewed: 2026-03-24
status: current
---

# Backup and Recovery Procedures

> **Docs** > **Administration** > **Backup and Recovery**
> Reading time: 12 minutes

## What You'll Learn

- What data needs to be backed up and how often
- Backup procedures for SQLite, PostgreSQL, and Databricks Lakebase
- How to restore from a backup
- How to test your backup and recovery process

---

## What to Back Up

Starboard stores data in three categories. Each has different backup requirements.

| Data Category | Storage | Criticality | Backup Required |
|---------------|---------|-------------|-----------------|
| **State store** (conversations, messages) | SQLite / Postgres / Lakebase | High | Yes |
| **Memory store** (episodes, facts, user profiles) | SQLite / Postgres / Lakebase | Medium | Yes |
| **Vector store** (embeddings for semantic search) | SQLite / Postgres | Low | Optional (can be rebuilt) |
| **Reflexion store** (agent learnings) | SQLite / Postgres | Low | Optional (can be rebuilt) |
| **Cache** (tool results, sessions) | Redis / InMemory | None | No (transient, regenerates automatically) |
| **Configuration** (environment variables) | `.env` / secrets manager | High | Yes (version-controlled or in secrets manager) |

!!! tip "Minimum viable backup"
    At minimum, back up the state store and memory store. The vector store and reflexion store can be rebuilt from the state data, though this takes time.

---

## Recovery Objectives

Define your targets before choosing a backup strategy:

| Objective | Small Deployment | Production Deployment |
|-----------|------------------|-----------------------|
| **RPO** (Recovery Point Objective) | 24 hours | 1 hour |
| **RTO** (Recovery Time Objective) | 1 hour | 15 minutes |
| **Backup frequency** | Daily | Hourly or continuous (WAL) |
| **Retention** | 7 days | 30 days |

---

## SQLite Backup Procedures

SQLite is used for local development and small deployments. The database files are stored on disk.

### Default File Locations

| Database | Default Path | Environment Variable |
|----------|-------------|---------------------|
| State | `./dev_data/starboard_state.db` | `SQLITE_STATE_PATH` |
| Memory | `./dev_data/starboard_memory.db` | `SQLITE_MEMORY_PATH` |
| Vector | `./dev_data/starboard_vectors.db` | `SQLITE_VECTOR_PATH` |
| Reflexion | `./dev_data/starboard_reflexion.db` | `SQLITE_REFLEXION_PATH` |

### Online Backup (Recommended)

Use the SQLite `.backup` command for a consistent snapshot while the server is running:

```bash
#!/bin/bash
# backup_sqlite.sh - Online SQLite backup
BACKUP_DIR="/backups/starboard/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

for db in starboard_state starboard_memory starboard_vectors starboard_reflexion; do
    SOURCE="./dev_data/${db}.db"
    if [ -f "$SOURCE" ]; then
        sqlite3 "$SOURCE" ".backup '${BACKUP_DIR}/${db}.db'"
        echo "Backed up: ${db}.db"
    fi
done

echo "Backup complete: $BACKUP_DIR"
```

!!! warning "Do not copy SQLite files directly"
    Copying a `.db` file while the server is writing to it can produce a corrupted backup. Always use the `.backup` command or stop the server first.

### Offline Backup

If you can stop the server:

```bash
# Stop the server
make stop

# Copy files
cp -r ./dev_data/ /backups/starboard/$(date +%Y%m%d)/

# Restart
make dev-server
```

### Restore from SQLite Backup

1. Stop the server:
   ```bash
   make stop
   ```

2. Replace the database files:
   ```bash
   cp /backups/starboard/20260324_120000/*.db ./dev_data/
   ```

3. Verify integrity:
   ```bash
   for db in ./dev_data/*.db; do
       echo "Checking: $db"
       sqlite3 "$db" "PRAGMA integrity_check;"
   done
   ```

4. Restart the server:
   ```bash
   make dev-server
   ```

5. Verify the restore:
   ```bash
   curl http://localhost:8000/health/ready
   ```

---

## PostgreSQL Backup Procedures

PostgreSQL is recommended for production deployments. Use standard PostgreSQL backup tools.

### Logical Backup (pg_dump)

Best for small-to-medium databases and cross-version restores:

```bash
#!/bin/bash
# backup_postgres.sh - PostgreSQL logical backup
BACKUP_DIR="/backups/starboard"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/starboard_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

pg_dump "$DATABASE_URL" \
    --format=custom \
    --compress=6 \
    --verbose \
    --file="$BACKUP_FILE"

echo "Backup complete: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
```

### Physical Backup (pg_basebackup)

Best for large databases and point-in-time recovery:

```bash
pg_basebackup \
    --host=postgres-host \
    --username=starboard \
    --pgdata=/backups/starboard/base_$(date +%Y%m%d) \
    --format=tar \
    --gzip \
    --checkpoint=fast \
    --progress
```

### Continuous Archiving (WAL)

For production deployments with RPO < 1 hour, enable WAL archiving:

```ini
# postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'cp %p /backups/starboard/wal/%f'
```

This allows point-in-time recovery to any moment after the last base backup.

### Restore from pg_dump

1. Create a fresh database:
   ```bash
   createdb starboard_restored
   ```

2. Restore the backup:
   ```bash
   pg_restore \
       --dbname=starboard_restored \
       --verbose \
       /backups/starboard/starboard_20260324_120000.sql.gz
   ```

3. Update the connection string:
   ```bash
   export DATABASE_URL=postgres://user:pass@host:5432/starboard_restored
   ```

4. Restart the server and verify:
   ```bash
   make dev-server
   curl http://localhost:8000/health/ready
   ```

### Restore to a Point in Time

If using WAL archiving:

1. Stop PostgreSQL.
2. Restore the base backup.
3. Configure `recovery.conf` (or `postgresql.conf` in PG 12+):
   ```ini
   restore_command = 'cp /backups/starboard/wal/%f %p'
   recovery_target_time = '2026-03-24 11:30:00'
   ```
4. Start PostgreSQL. It replays WAL until the target time.
5. Verify data and update the connection string if needed.

---

## Databricks Lakebase Backup

Databricks Lakebase is a managed PostgreSQL-compatible database. Backup depends on your Databricks workspace configuration.

### Managed Backups

Lakebase includes automatic daily backups with a default retention period. Check your workspace settings:

```bash
# View Lakebase instance details
databricks lakebase get --instance-name starboard-state
```

> **Note**: Lakebase backup and restore capabilities depend on your Databricks workspace tier and configuration. Consult your Databricks administrator for specific procedures.

### Manual Export

For additional protection, export data using `pg_dump` since Lakebase is PostgreSQL-compatible:

```bash
pg_dump "$LAKEBASE_DATABASE_URL" \
    --format=custom \
    --compress=6 \
    --file="/backups/starboard/lakebase_$(date +%Y%m%d).sql.gz"
```

!!! note "OAuth token refresh"
    Lakebase connections use OAuth tokens that expire. Ensure your backup script handles token refresh. The `LAKEBASE_OAUTH_*` environment variables control OAuth configuration.

---

## Redis Cache

Redis stores transient data (session state, rate limit counters, tool result caches). All data has a TTL and regenerates automatically.

**Backup is not required.** If Redis is lost:

1. Restart Redis.
2. Restart the Starboard backend. It reconnects automatically.
3. Active sessions may need to reauthenticate. Conversation history (in the state store) is not affected.

If you want to persist Redis data for faster recovery:

```bash
# Trigger an RDB snapshot
redis-cli BGSAVE

# Copy the dump file
cp /var/lib/redis/dump.rdb /backups/starboard/redis_$(date +%Y%m%d).rdb
```

---

## Testing Backups

!!! danger "Untested backups are not backups"
    Schedule regular restore tests (at minimum, quarterly) to verify your backups are valid.

### Restore Test Procedure

1. **Create a test environment** -- Use a separate database instance or local machine.

2. **Restore the latest backup** following the procedures above.

3. **Verify data integrity:**
   ```bash
   # Check the health endpoint
   curl http://localhost:8000/health/ready

   # Verify conversation count (PostgreSQL)
   psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM conversations;"

   # Verify recent data exists
   psql "$DATABASE_URL" -c \
       "SELECT id, created_at FROM conversations ORDER BY created_at DESC LIMIT 5;"
   ```

4. **Run a test conversation** to verify the full stack works:
   ```bash
   starboard --goal "Hello, are you working?"
   ```

5. **Document the results** -- Record the restore time, any issues encountered, and the data freshness.

---

## Backup Schedule Recommendations

| Deployment Size | State Store | Vector/Reflexion | Retention | Test Frequency |
|-----------------|-------------|------------------|-----------|----------------|
| **Development** | Manual (before upgrades) | Not needed | 3 backups | As needed |
| **Small** (1--10 users) | Daily | Weekly | 7 days | Quarterly |
| **Medium** (10--50 users) | Every 6 hours | Daily | 14 days | Monthly |
| **Large** (50+ users) | Hourly + WAL | Daily | 30 days | Monthly |

### Automation with Cron

```bash
# /etc/cron.d/starboard-backup

# Daily logical backup at 2 AM
0 2 * * * starboard /opt/starboard/scripts/backup_postgres.sh >> /var/log/starboard-backup.log 2>&1

# Weekly full backup on Sundays
0 3 * * 0 starboard /opt/starboard/scripts/backup_full.sh >> /var/log/starboard-backup.log 2>&1

# Clean backups older than retention period
0 4 * * * starboard find /backups/starboard -mtime +30 -delete
```

---

## Next Steps

- [Upgrade Guide](upgrade-guide.md) -- Always back up before upgrading
- [State Backends](state-backends.md) -- Backend configuration and migration
- [Capacity Planning](capacity-planning.md) -- Storage growth estimates
- [Monitoring and Observability](monitoring.md) -- Monitor backup job success

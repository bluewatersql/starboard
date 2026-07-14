# Databricks Lakebase State Adapter

This adapter provides state management for the Starboard AI Agent using **Databricks Lakebase**, a managed PostgreSQL service within your Databricks workspace.

## Overview

The Databricks Lakebase adapter extends the existing PostgreSQL adapters with automatic OAuth token management, enabling seamless integration with Databricks' authentication system.

### Features

- **Automatic OAuth Token Refresh**: Tokens are refreshed every 50 minutes (tokens expire after 1 hour)
- **PostgreSQL-Compatible**: Uses asyncpg driver for full PostgreSQL compatibility
- **Vector Search Support**: Leverages pgvector extension for semantic similarity search
- **Connection Pooling**: Optimized connection management with configurable pool sizes
- **SSL Security**: Enforces SSL connections for secure data transmission
- **Databricks SDK Integration**: Uses official Databricks SDK for credential management
- **Structured Logging**: Comprehensive logging with structlog for observability

### What is Lakebase?

[Databricks Lakebase](https://docs.databricks.com/en/lakebase/index.html) provides:

- **Fully managed PostgreSQL** instances within your Databricks workspace
- **Automatic OAuth authentication** using Databricks credentials
- **Unity Catalog integration** for unified data governance
- **High availability** and automatic backups
- **Seamless data synchronization** with Unity Catalog tables

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Application Layer                                   │
│  (FastAPI / CLI)                                     │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│  Repository Layer                                    │
│  (ConversationRepository, MemoryRepository)          │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│  Databricks Lakebase Adapters                        │
│  ┌────────────────────────────────────────────────┐ │
│  │ DatabricksLakebaseStateStore                   │ │
│  │  extends PostgresStateStore                    │ │
│  │  + OAuth token refresh                         │ │
│  └────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────┐ │
│  │ DatabricksLakebaseMemoryStore                  │ │
│  │  extends PostgresMemoryStore                   │ │
│  │  + OAuth token refresh                         │ │
│  └────────────────────────────────────────────────┘ │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│  Databricks Lakebase (PostgreSQL)                    │
│  - asyncpg connections                               │
│  - OAuth token authentication                        │
│  - pgvector for embeddings                           │
│  - SSL encryption                                    │
└─────────────────────────────────────────────────────┘
```

## Configuration

### Required Environment Variables

```bash
# Lakebase Instance Configuration
LAKEBASE_INSTANCE_NAME=my-lakebase-instance  # Required
LAKEBASE_DATABASE_NAME=starboard_db             # Required

# Application Configuration
ENVIRONMENT=production                        # staging or production
DATABASE_BACKEND=databricks                   # Set to enable Lakebase

# Optional: OAuth Client ID (falls back to current user)
DATABRICKS_CLIENT_ID=your-client-id

# Optional: Connection Pool Settings (defaults shown)
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=10
DB_POOL_RECYCLE_INTERVAL=3600  # 1 hour
DB_COMMAND_TIMEOUT=30
DATABRICKS_DATABASE_PORT=5432
```

### Configuration Precedence

1. **Instance Discovery**: SDK automatically discovers instance details
2. **Username Resolution**: Uses `DATABRICKS_CLIENT_ID` or falls back to current user
3. **Token Generation**: SDK generates OAuth tokens via workspace API
4. **Connection Pooling**: Configurable via environment variables

### Minimal Configuration

For most use cases, only two variables are required:

```bash
export LAKEBASE_INSTANCE_NAME="my-lakebase"
export LAKEBASE_DATABASE_NAME="starboard_db"
export DATABASE_BACKEND="databricks"
```

## Usage

### Setup Database Schema

Before using the adapter, create the required database tables:

```bash
# Set environment variables
export LAKEBASE_INSTANCE_NAME="my-lakebase"
export LAKEBASE_DATABASE_NAME="starboard_db"

# Run setup script
python scripts/setup_databricks_lakebase.py
```

This creates:
- `conversations` table for state management
- `episodes`, `facts`, `profiles` tables for long-term memory
- pgvector extension for semantic search
- Performance indexes

### Application Integration

The adapter is automatically selected when `DATABASE_BACKEND=databricks`:

```python
from starboard.infra.config import AppConfig
from starboard.infra.state_factory import (
    create_state_store,
    create_memory_store,
)

# Load configuration
config = AppConfig.from_env()

# Create adapters
state_store = create_state_store(config)
memory_store = create_memory_store(config)

# Connect (starts token refresh)
await state_store.connect()
await memory_store.connect()

# Use like regular PostgreSQL adapters
conversation = await state_store.get_conversation("conv-123")

# Cleanup
await state_store.close()
await memory_store.close()
```

### FastAPI Integration

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starboard.infra.container import Container
from starboard.infra.config import AppConfig

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    config = AppConfig.from_env()
    container = Container(config)
    await container.initialize()  # Starts token refresh
    
    app.state.container = container
    yield
    
    # Shutdown
    await container.shutdown()  # Stops token refresh

app = FastAPI(lifespan=lifespan)
```

## Token Refresh Mechanism

### How It Works

1. **Initial Connection**: SDK generates OAuth token on first connect
2. **Background Refresh**: Task runs every 50 minutes
3. **Token Regeneration**: SDK requests new token from Databricks API
4. **Pool Recreation**: Connection pool recreated with fresh credentials
5. **Automatic Retry**: Continues on failure, retries next cycle

### Token Lifecycle

Tokens are automatically managed:
- **0 min**: Initial token generation → Connected
- **50 min**: Background refresh triggered → New token generated
- **50 min + ~1s**: Connection pool recreated → Connected (refreshed)
- Repeat every 50 minutes

### Monitoring Token Refresh

All token operations are logged with structlog:

```json
{
  "event": "databricks_token_background_refresh_start",
  "instance": "my-lakebase",
  "last_refresh_age": 3000,
  "timestamp": "2025-11-18T12:00:00Z"
}
```

## Connection Pooling

### Pool Configuration

| Parameter                | Default | Description                     | Recommendation        |
|-------------------------|---------|----------------------------------|-----------------------|
| `DB_POOL_SIZE`          | 5       | Base connection pool size       | 5-10 for most apps    |
| `DB_MAX_OVERFLOW`       | 10      | Additional connections on load  | 2x pool_size          |
| `DB_POOL_TIMEOUT`       | 10      | Max wait time (seconds)         | 10-30 seconds         |
| `DB_COMMAND_TIMEOUT`    | 30      | Query timeout (seconds)         | 30-60 seconds         |
| `DB_POOL_RECYCLE_INTERVAL` | 3600 | Recycle connections (seconds)  | 3600 (1 hour)         |

### Performance Tuning

```bash
# High-traffic production
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30

# Development/testing
DB_POOL_SIZE=2
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=10
```

## Security

### Authentication

- **OAuth Flow**: Handled automatically by Databricks SDK
- **Token Storage**: Tokens stored in memory only, never persisted
- **SSL Enforcement**: All connections require SSL encryption
- **Workspace Integration**: Uses workspace-level authentication

### Best Practices

1. **Use Service Principals**: Set `DATABRICKS_CLIENT_ID` for production
2. **Rotate Credentials**: Leverage automatic token refresh
3. **Monitor Access**: Review Lakebase audit logs in workspace
4. **Least Privilege**: Grant minimal required permissions on instance
5. **Network Security**: Use Databricks VPC/private link if available

## Troubleshooting

### Common Issues

#### 1. Token Refresh Failures

**Symptom**: Background refresh errors in logs

**Solutions**:
- Verify Databricks SDK authentication: `databricks auth login`
- Check workspace connectivity
- Ensure service principal has database access
- Review Databricks audit logs

#### 2. Connection Pool Exhaustion

**Symptom**: `asyncpg.exceptions.TooManyConnectionsError`

**Solutions**:
```bash
# Increase pool size
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
```

#### 3. Instance Not Found

**Symptom**: `RuntimeError: LAKEBASE_INSTANCE_NAME not found`

**Solutions**:
- Verify instance name matches exactly in workspace
- Check instance is in `RUNNING` state
- Ensure user/service principal has access

#### 4. SSL Connection Errors

**Symptom**: SSL handshake failures

**Solutions**:
- Lakebase requires SSL - cannot be disabled
- Check network connectivity to `*.cloud.databricks.com`
- Verify firewall rules allow port 5432

### Debug Logging

Enable debug logging for detailed troubleshooting:

```python
from starboard.infra.logging import setup_structured_logging
import logging

setup_structured_logging(level=logging.DEBUG)
```

## Performance Considerations

### Connection Management

- **Pool Pre-ping**: Disabled (OAuth tokens handle stale connections)
- **Pool Recycle**: Set to 1 hour to align with token refresh
- **Max Overflow**: Set to 2x pool size for burst traffic
- **Command Timeout**: Set to 30-60 seconds for long queries

### Query Optimization

- **Indexes**: Created automatically by setup script
- **JSONB**: Used for flexible metadata storage
- **pgvector**: IVFFlat indexes for vector similarity search
- **Prepared Statements**: Handled automatically by asyncpg

## Monitoring and Observability

### Metrics to Track

1. **Connection Pool Usage**: Monitor active/idle connections
2. **Token Refresh Success Rate**: Should be ~100%
3. **Query Latency**: p50, p95, p99 percentiles
4. **Error Rates**: Connection failures, timeout errors
5. **Token Age**: Time since last refresh

### Structured Logging Events

```python
# Token refresh events
"databricks_token_refresh_start"
"databricks_token_refresh_complete"
"databricks_token_background_refresh_start"
"databricks_token_background_refresh_complete"
"databricks_token_background_refresh_error"

# Connection events
"databricks_lakebase_connect_start"
"databricks_lakebase_connect_complete"
"databricks_lakebase_close_start"
"databricks_lakebase_close_complete"
```

## Migration from PostgreSQL

### Step-by-Step Migration

1. **Create Lakebase Instance** in Databricks workspace
2. **Run Setup Script** to create schema
3. **Export Data** from existing PostgreSQL (optional)
4. **Update Configuration**:
   ```bash
   export DATABASE_BACKEND=databricks
   export LAKEBASE_INSTANCE_NAME=my-lakebase
   export LAKEBASE_DATABASE_NAME=starboard_db
   # Remove DATABASE_URL
   ```
5. **Restart Application** - adapter will auto-switch

### Data Migration (Optional)

```bash
# Export from PostgreSQL
pg_dump $DATABASE_URL > backup.sql

# Import to Lakebase (after setup)
psql "postgresql://user:token@instance.cloud.databricks.com:5432/starboard_db?ssl=require" < backup.sql
```

## API Reference

### DatabricksLakebaseStateStore

Extends `PostgresStateStore` with OAuth token management.

**Methods**: All inherited from `PostgresStateStore`
- `get_conversation(conversation_id: str) -> Conversation | None`
- `save_conversation(conversation: Conversation) -> None`
- `delete_conversation(conversation_id: str) -> bool`
- `list_conversations(user_id: str, limit: int, offset: int) -> list[ConversationMetadata]`
- `update_metadata(conversation_id: str, updates: dict[str, Any]) -> None`

### DatabricksLakebaseMemoryStore

Extends `PostgresMemoryStore` with OAuth token management.

**Methods**: All inherited from `PostgresMemoryStore`
- `store_episode(episode: Episode) -> str`
- `recall_episodes_by_embedding(user_id: str, query_embedding: list[float], limit: int) -> list[Episode]`
- `store_fact(fact: Fact) -> str`
- `query_facts(user_id: str, query: SemanticQuery) -> list[Fact]`
- `get_profile(user_id: str) -> UserProfile`
- `update_profile(user_id: str, updates: dict[str, Any]) -> None`
- `delete_user_data(user_id: str) -> None`

### DatabricksLakebaseConfig

Configuration dataclass for Lakebase connection.

**Required Fields**:
- `instance_name: str` - Lakebase instance name
- `database_name: str` - Database name within instance

**Optional Fields** (with defaults):
- `pool_size: int = 5`
- `max_overflow: int = 10`
- `pool_timeout: int = 10`
- `pool_recycle_interval: int = 3600`
- `command_timeout: int = 30`
- `port: int = 5432`

## Testing

See `tests/integration/adapters/test_databricks_lakebase.py` for integration tests.

```bash
# Run integration tests (requires Lakebase instance)
export LAKEBASE_INSTANCE_NAME=test-instance
export LAKEBASE_DATABASE_NAME=test_db
pytest tests/integration/adapters/test_databricks_lakebase.py -v
```

## Related Documentation

- [Databricks Lakebase Documentation](https://docs.databricks.com/en/lakebase/index.html)
- [Databricks SDK for Python](https://databricks-sdk-py.readthedocs.io/)
- [Lakebase Connection Example](https://apps-cookbook.dev/docs/fastapi/getting_started/lakebase_connection)
- [System Architecture](../../../../../../docs/architecture/SYSTEM_ARCHITECTURE.md)
- [Configuration Guide](../../../../../../docs/CONFIGURATION.md)

## License

Databricks Open Model License - See LICENSE file for details


# Configuration Guide

Complete configuration reference for the Starboard AI Agent.

---

## Configuration Overview

**Starboard is configured entirely through environment variables.** All settings are loaded from `os.environ` at startup via the `EnvConfig` class.

Configuration file support (config.yaml) has been removed in favor of environment-variable-only configuration for:
- **Simplicity**: Single source of truth
- **Cloud-native**: Standard practice for containerized deployments
- **Security**: Secrets managed through environment/secrets management
- **Transparency**: Easy to inspect and debug

---

## Quick Start

1. **Copy the example environment file**:
   ```bash
   cp examples/env.example .env
   ```

2. **Edit `.env` with your credentials**:
   ```bash
   # Required: Databricks
   DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
   DATABRICKS_TOKEN=dapi...
   DATABRICKS_WAREHOUSE_ID=your_warehouse_id

   # Required: LLM Provider
   LLM_API_KEY=<your-api-key>  # OpenAI API key or Azure OpenAI key
   
   # Optional: Adjust defaults
   LLM_MODEL=databricks-claude-sonnet-4-5
   LLM_TEMPERATURE=0.4
   ```

3. **Load environment and start**:
   ```bash
   source .env  # or use direnv, docker-compose, etc.
   make dev-server   # Start the MCP server / backend
   ```

---

## Environment Variables Reference

### Required Settings

These must be set for the application to function (unless `OFFLINE_MODE=true`):

```bash
# Databricks Connection
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi_your_token_here
DATABRICKS_WAREHOUSE_ID=your_warehouse_id

# LLM Provider
LLM_API_KEY=<your-api-key>  # OpenAI API key
```

### LLM Configuration

```bash
# Model Selection
LLM_PROVIDER=openai                          # Provider: openai, azure, databricks
LLM_MODEL=databricks-claude-sonnet-4-5       # Default model for all agents
LLM_BASE_URL=                                # Optional: Custom OpenAI-compatible endpoint
LLM_TEMPERATURE=0.4                          # Sampling temperature (0.0-2.0)
LLM_MAX_TOKENS=75000                         # Max tokens per response
LLM_SEED=                                    # Optional: Seed for deterministic output

# Embeddings
EMBEDDING_MODEL=databricks-bge-large-en      # Model for vector embeddings
EMBEDDING_BASE_URL=                          # Separate base URL for embeddings (optional)
EMBEDDING_CACHE_TTL=86400                    # Cache TTL in seconds (24 hours)

# Specialized Models (Optional)
LLM_PLANNING_MODEL=                          # Override for planning phase
LLM_PLANNING_TEMPERATURE=                    # Override temperature for planning
LLM_JUDGE_MODEL=                             # Override for judgment/evaluation
LLM_JUDGE_TEMPERATURE=                       # Override temperature for judgment
LLM_REVIEW_MODEL=                            # Override for review phase
LLM_REVIEW_TEMPERATURE=                      # Override temperature for review
LLM_SYNTH_MODEL=                             # Override for synthesis phase
LLM_SYNTH_TEMPERATURE=                       # Override temperature for synthesis
```

### Multi-Agent Configuration

```bash
# Domain Model Overrides (JSON format)
DOMAIN_MODEL_OVERRIDES='{"router": "gpt-4o-mini", "query": "gpt-4o", "diagnostic": "o1-preview"}'
DOMAIN_TEMPERATURE_OVERRIDES='{"router": 0.2, "query": 0.3, "diagnostic": 0.7}'

# Disable Specific Agents
DISABLED_AGENT_DOMAINS=diagnostic,warehouse  # Comma-separated list of domains to disable

# Agent Behavior
TOOL_PARALLELISM=4                           # Max parallel tool executions
```

### Analytics Agent Configuration

```bash
# Query Execution
MAX_ANALYSIS_RESULT_ROWS=50                  # Max rows returned from analytics queries

# Foundation Components
SQLITE_VECTOR_PATH=./dev_data/starboard_vectors.db     # Vector store path
SQLITE_REFLEXION_PATH=./dev_data/starboard_reflexion.db  # Reflexion store path
EMBEDDING_DIMENSION=1536                      # Vector embedding dimension
SEMANTIC_CACHE_THRESHOLD=0.95                 # Similarity threshold for cache hits

# Feature Flags
ENABLE_REFLEXION=false                        # Enable reflexion-based learning
ENABLE_SEMANTIC_CACHE=true                    # Enable semantic caching
```

### Database Configuration

```bash
# Backend Selection
DATABASE_BACKEND=sqlite                       # Options: sqlite, postgres, databricks
DATABASE_URL=                                 # Connection string for postgres/databricks

# SQLite Paths
SQLITE_STATE_PATH=./dev_data/starboard_state.db
SQLITE_MEMORY_PATH=./dev_data/starboard_memory.db
SQLITE_VECTOR_PATH=./dev_data/starboard_vectors.db
SQLITE_REFLEXION_PATH=./dev_data/starboard_reflexion.db

# PostgreSQL Connection Pools
POSTGRES_MIN_POOL_SIZE=5
POSTGRES_MAX_POOL_SIZE=20
POSTGRES_COMMAND_TIMEOUT=60                   # Seconds
```

### Cache Configuration

```bash
# Cache Backend
CACHE_BACKEND=memory                          # Options: memory, redis, postgres
CACHE_TTL=300                                 # Default cache TTL (seconds)
REDIS_URL=redis://localhost:6379              # Redis connection string (if using redis)

# Vector Store Backend
VECTOR_BACKEND=sqlite                         # Options: sqlite, chroma, databricks, postgres
```

### Server Configuration

```bash
# Server
HOST=0.0.0.0                                  # Bind address
PORT=8000                                     # Server port
DEBUG=false                                   # Debug mode
LOG_LEVEL=INFO                                # Logging level: DEBUG, INFO, WARNING, ERROR
LOG_JSON=false                                # JSON-formatted logs
ENVIRONMENT=dev                               # Environment: dev, test, staging, production

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_STORAGE=memory://                  # Storage backend for rate limits
RATE_LIMIT_DEFAULT=100/minute                 # Default rate limit
MAX_REQUEST_SIZE=10485760                     # Max request size in bytes (10MB)

# Memory Consolidation
MEMORY_CONSOLIDATION_ENABLED=false
MEMORY_CONSOLIDATION_INTERVAL=3600            # Seconds between consolidation runs
```

### Databricks Catalog

```bash
# Unity Catalog Defaults
DEFAULT_CATALOG=main
DEFAULT_SCHEMA=default
```

### Optional Features & Testing

```bash
# Feature Flags
SAFE_MODE=false                               # Disable external API calls (testing)
OFFLINE_MODE=false                            # Skip Databricks/LLM validation (testing)
MOCK_LLM=false                                # Use mock LLM responses (testing)
ENABLE_CACHING=true                           # Enable response caching
ENABLE_OBSERVABILITY=true                     # Enable metrics/tracing
```

---

## Configuration Loading

### How It Works

1. **Startup**: `EnvConfig.from_env()` reads all values from `os.environ`
2. **Validation**: `config.validate()` checks required fields
3. **Singleton**: `get_config()` returns the global config instance

```python
# packages/starboard/starboard/infra/core/config.py
from starboard.infra.core.config import get_config

# Get configuration (loaded from environment variables)
config = get_config()
print(f"Using model: {config.llm_model}")
print(f"Databricks host: {config.databricks_host}")
```

### Environment File Loading

Use one of these methods to load your `.env` file:

**Option 1: Manual (Development)**
```bash
source .env
make dev
```

**Option 2: direnv (Automatic)**
```bash
# Install direnv: https://direnv.net
echo 'source .env' > .envrc
direnv allow
make dev  # .env automatically loaded
```

**Option 3: Docker Compose**
```yaml
# docker-compose.yml
services:
  starboard:
    env_file:
      - .env
```

**Option 4: Kubernetes**
```yaml
# Use ConfigMap or Secret
apiVersion: v1
kind: ConfigMap
metadata:
  name: starboard-config
data:
  DATABRICKS_HOST: "https://..."
  LLM_MODEL: "databricks-claude-sonnet-4-5"
---
# Then reference in Pod spec
envFrom:
  - configMapRef:
      name: starboard-config
```

---

## Per-Conversation Configuration

Individual conversations can override certain settings via the API:

| Setting | Type | Range | Default | Description |
|---------|------|-------|---------|-------------|
| `model` | string | - | `databricks-claude-sonnet-4-5` | LLM model identifier |
| `temperature` | float | 0.1-1.0 | 0.4 | Sampling temperature |
| `max_tokens` | int | 10K-200K | 75,000 | Maximum tokens in response |
| `streaming` | bool | - | true | Stream responses via SSE |

### API Usage

```bash
curl -X POST http://localhost:8000/api/chat/conversations \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "config": {
      "model": "gpt-4o",
      "temperature": 0.7,
      "max_tokens": 50000
    }
  }'
```

**Note**: Per-conversation config only affects that specific conversation. It does NOT modify the global `EnvConfig` or environment variables.

---

## Configuration Validation

The application validates configuration at startup:

```python
config = get_config()
config.validate()  # Raises ValueError if invalid
```

### Validation Rules

**In Normal Mode**:
- ✅ `DATABRICKS_HOST` required
- ✅ `DATABRICKS_TOKEN` required
- ✅ `LLM_API_KEY` required

**In Offline Mode** (`OFFLINE_MODE=true`):
- ⏭️ Databricks credentials optional (for testing)
- ⏭️ LLM credentials optional (if `MOCK_LLM=true`)

**Database Validation**:
- If `DATABASE_BACKEND=postgres` or `databricks`: `DATABASE_URL` required
- If `CACHE_BACKEND=redis`: `REDIS_URL` required

---

## Common Patterns

### Development Setup

```bash
# .env (development)
DATABRICKS_HOST=https://my-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi_dev_token
DATABRICKS_WAREHOUSE_ID=abc123
LLM_API_KEY=sk-dev_key
LLM_MODEL=databricks-claude-sonnet-4-5
ENVIRONMENT=dev
DEBUG=true
LOG_LEVEL=DEBUG
```

### Production Setup

```bash
# Managed via secrets management (AWS Secrets Manager, HashiCorp Vault, etc.)
DATABRICKS_HOST=https://prod-workspace.cloud.databricks.com
DATABRICKS_TOKEN=${DATABRICKS_TOKEN_SECRET}  # Injected by secrets manager
LLM_API_KEY=${OPENAI_API_KEY_SECRET}
LLM_MODEL=databricks-claude-sonnet-4-5
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
LOG_JSON=true
ENABLE_OBSERVABILITY=true
RATE_LIMIT_ENABLED=true
DATABASE_BACKEND=postgres
DATABASE_URL=${POSTGRES_CONNECTION_STRING}
CACHE_BACKEND=redis
REDIS_URL=${REDIS_CONNECTION_STRING}
```

### Testing Setup

```bash
# .env.test
OFFLINE_MODE=true
MOCK_LLM=true
SAFE_MODE=true
DATABASE_BACKEND=sqlite
CACHE_BACKEND=memory
ENVIRONMENT=test
LOG_LEVEL=WARNING
```

---

## Troubleshooting

### Missing Required Configuration

**Symptom**: `ValueError: Configuration validation failed: - DATABRICKS_HOST required`

**Solution**: Set the required environment variable:
```bash
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
```

Or add to `.env` and reload:
```bash
echo 'DATABRICKS_HOST=https://...' >> .env
source .env
```

### Configuration Not Loading

**Symptom**: Changes to `.env` not taking effect

**Solutions**:
1. Ensure `.env` is sourced: `source .env`
2. Restart the application (config loads at startup)
3. Check for typos in variable names (case-sensitive)
4. Verify no conflicting environment variables set elsewhere

### Debugging Configuration

Print current configuration:
```bash
uv run python -c "
from starboard.infra.core.config import get_config
config = get_config()
print(f'Model: {config.llm_model}')
print(f'Host: {config.databricks_host}')
print(f'Environment: {config.environment}')
"
```

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
export DEBUG=true
make dev
```

---

## Migration from Config Files

If you previously used `config.yaml`, migrate to environment variables:

### Old Way (Deprecated - No Longer Supported)
```yaml
# ~/.starboard/config.yaml (NO LONGER USED)
databricks:
  host: https://...
  token: dapi...
llm:
  model: gpt-4o
```

### New Way (Current)
```bash
# .env or export directly
export DATABRICKS_HOST=https://...
export DATABRICKS_TOKEN=dapi...
export LLM_MODEL=gpt-4o
```

**Why the change?**
- ✅ Simpler: One configuration method instead of multiple
- ✅ Standard: Follows 12-factor app principles
- ✅ Secure: Environment variables naturally integrate with secrets management
- ✅ Container-friendly: Works seamlessly with Docker, Kubernetes, etc.

---

## See Also

- [examples/env.example](../examples/env.example) - Complete environment variable template
- [QUICKSTART.md](QUICKSTART.md) - Getting started guide
- [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment guide
- [RUNBOOK.md](RUNBOOK.md) - Operational procedures

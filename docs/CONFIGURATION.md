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
   make dev-server   # Start the FastAPI backend (uvicorn)
   ```

---

## Installation and Extras

`pip install starboard` installs the **store-free** experience wheel: **no** state/vector drivers are pulled in. The default runtime is `database_backend="memory"` and `vector_backend="none"`. Driver-backed backends lazy-import their driver and raise an actionable `pip install 'starboard[<extra>]'` error if the matching extra is missing.

### `starboard` (server package) extras

| Extra | Pulls in | Enables |
|---|---|---|
| `observability` | `opentelemetry-instrumentation-fastapi`, `prometheus-client` | OTEL/Prometheus export |
| `sqlite` | `aiosqlite`, `sqlite-vec` | `DATABASE_BACKEND=sqlite`; SQLite ANN vector path; reflexion |
| `postgres` | `asyncpg` | `DATABASE_BACKEND=postgres` **and** `lakebase` |
| `redis` | `redis` | `CACHE_BACKEND=redis` / Redis rate-limit storage |
| `memory` | `pgvector`, `asyncpg` | pgvector similarity recall in the Postgres memory store |
| `vectorsearch` | `databricks-vectorsearch` | managed `VECTOR_BACKEND=vectorsearch` (opt-in ANN) |
| `all-stores` | `starboard[sqlite,postgres,redis,memory,vectorsearch]` | every store/vector driver |
| `test`, `lint`, `load`, `dev`, `all` | dev/CI tooling | development, testing, load testing |

There is **no** `lakebase` extra — the Lakebase adapter reuses `asyncpg` from the `postgres` extra. There is **no** `charts` extra on the server package.

### `starboard-core` extras (kernel + `starboard_x` helpers)

The `starboard-core` wheel ships the pure kernel **and** the `starboard_x` progressive helpers (`python -m starboard_x.<capability>`). Its extras are per-capability:

| Extra | Enables |
|---|---|
| `databricks` | DBFS / UC Volumes log loader (Databricks SDK) |
| `diagnostics-core` | stdlib-only diagnostic trio |
| `diagnostics` | + pattern registry (`pyyaml`) |
| `discovery` | workspace discovery (`polars`, `databricks-sql-connector`, `databricks-sdk`) |
| `sparklog` (+ `sparklog-aws` / `sparklog-azure` / `sparklog-gcp`) | Spark event-log parsing (+ cloud object stores) |
| `warehouse` | warehouse analyzers (`sqlglot`, SQL connector, SDK) |
| `uc` | Unity Catalog analyzers (SDK + SQL connector) |
| `cluster` | cluster analyzers (SDK) |
| `charts` | **stub** — reserved; the chart renderer is not shipped (see open items) |
| `aws` / `azure` / `gcp` | S3 / ADLS / GCS credential + object-store support |
| `all` | `diagnostics,discovery,sparklog,warehouse,uc,cluster,charts` |

!!! note "Layered catalog"
    These map to additive **layered-catalog** tiers: `kernel` (= `starboard-core`) → `capability` → `experience`. `pip install starboard` remains the full experience wheel; the tier aliases are additive and do not change the default install.

---

## Environment Variables Reference

### Required Settings

Starboard uses **auth by subtraction**: a single resolver delegates to the Databricks SDK credential chain, so `DATABRICKS_HOST`/`DATABRICKS_TOKEN` are **not** individually required. Outside `OFFLINE_MODE`, startup validation requires only that *some* Databricks credential is resolvable **and** that an LLM API key is set:

```bash
# Databricks — provide ANY ONE of these (the SDK chain resolves the rest):
#   * DATABRICKS_HOST + DATABRICKS_TOKEN (inline PAT), or
#   * DATABRICKS_CONFIG_PROFILE / STARBOARD_WORKSPACE (a ~/.databrickscfg profile), or
#   * DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET (OAuth), or
#   * a ~/.databrickscfg file, or an ambient Databricks runtime (notebook/job/App).
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi_your_token_here

# LLM Provider — required unless OFFLINE_MODE=true (falls back to OPENAI_API_KEY)
LLM_API_KEY=<your-api-key>
```

!!! note "Warehouse is optional"
    `DATABRICKS_WAREHOUSE_ID` is optional. When it is unset and `AUTOCREATE_DBX_DW=true` (the default), Starboard auto-creates a serverless SQL warehouse (`DATABRICKS_WAREHOUSE_NAME`, default `STARBOARD_AGENT_DW`; `DATABRICKS_WAREHOUSE_SIZE`, default `X-Large`).

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
SQLITE_VECTOR_PATH=./dev_data/starboard_vectors.db     # Vector store path (sqlite vector path)
SQLITE_REFLEXION_PATH=./dev_data/starboard_reflexion.db  # Reflexion store path
EMBEDDING_DIMENSION=1024                      # Vector embedding dimension (used only on vector paths)
SEMANTIC_CACHE_THRESHOLD=0.95                 # Similarity threshold — consulted ONLY on the opt-in vector path

# Feature Flags
ENABLE_REFLEXION=false                        # Reflexion is OFF by default; opt-in behind starboard[sqlite]/[vectorsearch]
ENABLE_SEMANTIC_CACHE=true                    # Semantic cache runs TTL-only (exact-key) unless a vector_backend is set
```

!!! note "Default RAG/memory is store-free"
    With `VECTOR_BACKEND=none` (the default) the analytics context comes from on-disk curated reference files + query packs — no embeddings. The semantic cache is TTL-only and `SEMANTIC_CACHE_THRESHOLD` is ignored unless you set a real `vector_backend`. Reflexion is dormant unless `ENABLE_REFLEXION=true` **and** a vector-store extra is installed.

### Database Configuration

```bash
# Backend Selection
DATABASE_BACKEND=memory                       # Options: memory (default), sqlite, postgres, lakebase, uc
                                              # ("databricks" = deprecated alias for "lakebase")
                                              # sqlite -> starboard[sqlite]; postgres/lakebase -> starboard[postgres]
DATABASE_URL=                                 # Connection string; required for postgres and lakebase

# SQLite Paths (used when DATABASE_BACKEND=sqlite)
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
CACHE_BACKEND=memory                          # Options: memory (default), redis, postgres
CACHE_TTL=300                                 # Default cache TTL (seconds)
REDIS_URL=redis://localhost:6379              # Redis connection string; selects Redis when set (needs starboard[redis])

# Vector Store Backend
VECTOR_BACKEND=none                           # Options: none (default), inmemory, sqlite, chroma, databricks, postgres, vectorsearch
VECTORSEARCH_COLUMNS=                         # JSON list; required for vectorsearch (wildcard "*" is invalid)
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
ENABLE_PII_REDACTION=true                     # Redact PII in logs/responses (EnvConfig default is true)
```

### Internal-data enablement gate

Starboard ships a **closed-by-default** seam for internal-only data sources. Public ports and public adapters ship in the public packages; internal adapters live only in the separate `starboard-internal` package (never in the public wheel).

```bash
# EMPTY by default => gate CLOSED (public path only). Comma-separated substrings.
INTERNAL_CONTEXT_HOST_ALLOWLIST=
ENABLE_INTERNAL_ADAPTERS=false                # Reserved; public-only by default
```

Leave these at their defaults for public deployments. `$` figures throughout Starboard are **list-price DBU estimates**.

---

## Configuration Loading

### How It Works

1. **Startup**: `EnvConfig.from_env()` reads all values from `os.environ`
2. **Validation**: `config.validate_config()` checks required fields
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
config.validate_config()  # Raises ValueError if invalid
```

### Validation Rules

**In Normal Mode**:
- ✅ *Some* Databricks credential must be resolvable (auth by subtraction — inline host+token, a profile, OAuth client creds, `~/.databrickscfg`, or an ambient Databricks runtime)
- ✅ `LLM_API_KEY` required

**In Offline Mode** (`OFFLINE_MODE=true`):
- ⏭️ Databricks credentials optional (for testing)
- ⏭️ LLM credentials optional (if `MOCK_LLM=true`)

**Database Validation**:
- If `DATABASE_BACKEND=postgres` or `lakebase`: `DATABASE_URL` required
- If `CACHE_BACKEND=redis`: `REDIS_URL` required
- `DATABASE_BACKEND=sqlite` is rejected for `staging`/`production`
- Discovery: `DISCOVERY_LOOKBACK_DAYS` must be 30/60/90; `DISCOVERY_MAX_PARALLELISM` must be 1–16

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

**Symptom**: `ValueError: Configuration validation failed: - No Databricks auth resolved...`

**Solution**: Provide any one resolvable credential — set `DATABRICKS_HOST` + `DATABRICKS_TOKEN`, or point at a profile via `DATABRICKS_CONFIG_PROFILE` / `STARBOARD_WORKSPACE`, or configure `~/.databrickscfg`:
```bash
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_TOKEN=dapi_your_token_here
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

- [examples/env.example](https://github.com/starboard-ai/job-agent/blob/main/examples/env.example) - Complete environment variable template
- [QUICKSTART.md](QUICKSTART.md) - Getting started guide
- [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment guide
- [RUNBOOK.md](RUNBOOK.md) - Operational procedures

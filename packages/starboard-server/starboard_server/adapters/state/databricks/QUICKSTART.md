# Databricks Lakebase Adapter - Quick Start Guide

Get started with Databricks Lakebase state management in under 5 minutes.

## Prerequisites

1. **Databricks Workspace** with Lakebase enabled
2. **Lakebase Instance** created in your workspace
3. **Python 3.12+** installed locally
4. **Databricks SDK** authentication configured

## Step 1: Create Lakebase Instance

If you haven't created a Lakebase instance yet:

1. Open your Databricks workspace
2. Navigate to **Data** → **Lakebase**
3. Click **Create Instance**
4. Configure:
   - Name: `starboard-lakebase`
   - Size: Select based on load (start with Small)
   - Region: Same as workspace
5. Click **Create** and wait for status: `RUNNING`

## Step 2: Configure Authentication

Ensure Databricks SDK can authenticate:

```bash
# Option 1: Use Databricks CLI (recommended)
databricks auth login --host https://your-workspace.cloud.databricks.com

# Option 2: Set environment variables
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_TOKEN=your-pat-token

# Verify authentication
databricks current-user me
```

## Step 3: Set Environment Variables

Create a `.env` file or export variables:

```bash
# Required: Lakebase Configuration
export LAKEBASE_INSTANCE_NAME=starboard-lakebase
export LAKEBASE_DATABASE_NAME=starboard_db

# Required: Enable Databricks Backend
export DATABASE_BACKEND=databricks
export ENVIRONMENT=production

# Optional: OAuth Client ID (defaults to current user)
export DATABRICKS_CLIENT_ID=your-service-principal-id

# Optional: Connection Pool (use defaults for most cases)
export DB_POOL_SIZE=5
export DB_MAX_OVERFLOW=10
```

## Step 4: Install Dependencies

```bash
# Navigate to project root
cd /path/to/job-agent

# Install with databricks support
pip install -e packages/starboard-server[all]

# Or use uv
uv pip install -e packages/starboard-server[all]
```

## Step 5: Create Database Schema

Run the setup script to create tables:

```bash
python scripts/setup_databricks_lakebase.py
```

Expected output:

```
[INFO] Starting Databricks Lakebase database setup
[INFO] Configuration loaded instance=starboard-lakebase database=starboard_db
[INFO] Connecting to Lakebase instance instance=starboard-lakebase
[INFO] Retrieved database instance details hostname=xxx.cloud.databricks.com name=starboard-lakebase
[INFO] Connected to Lakebase successfully
[INFO] Running migration file=001_initial.sql
[INFO] Migration completed successfully file=001_initial.sql
[INFO] Running migration file=002_memory.sql
[INFO] Migration completed successfully file=002_memory.sql
[INFO] Running migration file=003_indexes.sql
[INFO] Migration completed successfully file=003_indexes.sql
[INFO] Database setup complete tables=['conversations', 'episodes', 'facts', 'profiles']
[INFO] pgvector extension is installed
[INFO] Database connection closed
```

## Step 6: Test Connection

Verify with a simple test script:

```python
import asyncio
from starboard_server.infra.config import AppConfig
from starboard_server.infra.state_factory import create_state_store

async def test():
    config = AppConfig.from_env()
    store = create_state_store(config)
    await store.connect()
    print("✓ Connected successfully")
    await store.close()

asyncio.run(test())
```

## Step 7: Integrate with Application

### Application Integration

The adapter is automatically selected when `DATABASE_BACKEND=databricks`. Use the container pattern for FastAPI or factory pattern for CLI apps.

See [README.md](./README.md#usage) for detailed integration examples.

## Step 8: Verify Token Refresh

Monitor application logs for automatic token refresh events occurring every 50 minutes:

```
[INFO] databricks_token_background_refresh_start instance=starboard-lakebase
[INFO] databricks_token_refresh_complete instance=starboard-lakebase
```

## Common Quick Start Issues

### Issue: "LAKEBASE_INSTANCE_NAME environment variable is required"

**Solution**: Verify environment variables are set:

```bash
echo $LAKEBASE_INSTANCE_NAME
echo $LAKEBASE_DATABASE_NAME
echo $DATABASE_BACKEND
```

### Issue: "Instance not found"

**Solution**: Verify instance name matches exactly:

```bash
# List instances in workspace
databricks lakebase instances list

# Update LAKEBASE_INSTANCE_NAME to match exactly
```

### Issue: "Authentication failed"

**Solution**: Re-authenticate with Databricks:

```bash
databricks auth login --host https://your-workspace.cloud.databricks.com
```

### Issue: "Connection timeout"

**Solution**: Check network connectivity:

```bash
# Test connectivity to Databricks
curl -I https://your-workspace.cloud.databricks.com

# Ensure port 5432 is not blocked by firewall
```

## Next Steps

- [Read Full Documentation](./README.md) - Comprehensive guide
- [View Configuration Guide](../../../../../../docs/CONFIGURATION.md) - Configuration details
- [Monitor Performance](./README.md#monitoring-and-observability) - Set up metrics
- [Configure Production](./README.md#security) - Security best practices
- [Deployment Guide](../../../../../../docs/DEPLOYMENT.md) - Production deployment

## Quick Reference

### Essential Environment Variables

```bash
# Minimum required
LAKEBASE_INSTANCE_NAME=your-instance
LAKEBASE_DATABASE_NAME=your-database
DATABASE_BACKEND=databricks
ENVIRONMENT=production
```

### Setup Commands

```bash
# Initial setup
python scripts/setup_databricks_lakebase.py

# Verify connection
python test_lakebase.py

# Run application
uvicorn starboard_server.main:app --reload
```

### Monitoring Commands

```bash
# Check instance status
databricks lakebase instances get --name your-instance

# View logs
tail -f your-app.log | grep databricks

# Test token refresh (wait 50 minutes or check logs)
grep "token_refresh" your-app.log
```

## Support

- **Documentation**: [README.md](./README.md)
- **Examples**: Check `examples/` directory
- **Issues**: Create GitHub issue with `databricks-lakebase` label
- **Databricks Support**: Contact workspace admin or Databricks support

## Quick Troubleshooting Checklist

- [ ] Lakebase instance is in `RUNNING` state
- [ ] Environment variables are set correctly
- [ ] Databricks SDK authentication is configured
- [ ] Database schema created successfully
- [ ] Test connection script passes
- [ ] Application starts without errors
- [ ] Token refresh logs appear every 50 minutes

If all items are checked, you're ready for production! 🚀


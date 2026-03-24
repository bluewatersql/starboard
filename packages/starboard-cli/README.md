# Starboard CLI

Command-line interface for the Starboard AI Agent platform.

## Overview

`starboard-cli` provides a natural language terminal interface for interacting with the Starboard multi-agent system. Describe what you want to do in plain English, and the agent routes your request to the appropriate domain specialist.

**Key Features:**
- **Natural language interface**: No need to specify query/job/pipeline -- just describe your goal
- **Multi-agent routing**: Automatically routes to the right specialist (8 domain agents)
- **Streaming progress**: Real-time feedback with Rich terminal UI
- **File input**: Pass source code, SQL files, or other inputs
- **Multiple output formats**: JSON and Markdown reports
- **Comprehensive logging**: Separate agent telemetry from console output

## Installation

```bash
pip install starboard-cli
```

## Quick Start

```bash
# Set environment variables
export DATABRICKS_HOST="https://your-workspace.databricks.com"
export DATABRICKS_TOKEN="your-databricks-token"
export LLM_API_KEY="your-llm-api-key"

# Optimize a query
starboard "Optimize query with statement_id abc123"

# Analyze a job
starboard "Analyze job 456 for performance issues"

# Run workspace discovery
starboard "Run a health assessment of my workspace"
```

## Usage

### Basic Usage

```bash
starboard "your goal in natural language"
```

The agent will:
1. Classify your intent (query, job, uc, cluster, analytics, warehouse, discovery, diagnostic)
2. Route to the appropriate specialist agent
3. Execute tools and gather information
4. Provide recommendations and analysis

### Examples

```bash
# Query optimization
starboard "Optimize this SQL query: SELECT * FROM large_table WHERE date > '2024-01-01'"

# Job analysis
starboard "Analyze Databricks job 12345 for performance bottlenecks"

# Unity Catalog lineage
starboard "Show me the lineage and dependencies for table prod.analytics.user_events"

# Cluster configuration
starboard "Review cluster configuration for cluster-abc-123"

# Cost analysis
starboard "What are my top 10 most expensive queries this month?"

# Warehouse optimization
starboard "Analyze my SQL warehouse portfolio for optimization opportunities"

# Workspace discovery
starboard "Run a discovery assessment of my workspace"

# Troubleshooting
starboard "Help me debug why job 789 is failing"
```

### With Input File

```bash
# Pass source code from file
starboard "Optimize this Spark job" --input-file job.py

# Pass SQL from file
starboard "Review this query for performance issues" --input-file query.sql
```

### Output Options

```bash
# Save results to directory
starboard "Optimize query abc123" --output-path ./results/

# Plain text output (no Rich formatting)
starboard "Analyze job 456" --plain

# Quiet mode (only show final results)
starboard "Optimize table lineage" --quiet
```

## Command Line Options

### Core Parameters

| Option | Description |
|--------|-------------|
| `user_goal` | What you want the agent to do (natural language, required) |
| `--config` | Path to YAML config file |
| `--input-file` | File to load and pass to agent (source code, SQL, etc.) |
| `--output-path` | Directory to save JSON and Markdown reports |

### Databricks Credentials

| Option | Environment Variable | Description |
|--------|---------------------|-------------|
| `--databricks-host` | `DATABRICKS_HOST` | Databricks workspace URL |
| `--databricks-token` | `DATABRICKS_TOKEN` | Databricks personal access token |

### LLM Configuration

| Option | Environment Variable | Description |
|--------|---------------------|-------------|
| `--llm-model` | `LLM_MODEL` | Model name (e.g., gpt-4o, databricks-claude-sonnet-4-5) |
| `--llm-api-key` | `LLM_API_KEY` | LLM provider API key |
| `--llm-base-url` | `LLM_BASE_URL` | API base URL for custom endpoints |
| `--llm-temperature` | `LLM_TEMPERATURE` | Temperature (0.0-1.0, default: 0.4) |
| `--llm-max-tokens` | `LLM_MAX_TOKENS` | Max token budget (default: 120000) |

### Display and Logging

| Option | Description |
|--------|-------------|
| `--plain` | Use plain text instead of Rich formatting |
| `--quiet` | Suppress progress output |
| `--log-level` | Logging level: DEBUG, INFO, WARNING, ERROR (default: ERROR) |
| `--log-file` | Write logs to file instead of console |
| `--debug` | Enable debug logging to stderr |

### Agent Options

| Option | Values | Description |
|--------|--------|-------------|
| `--mode` | `online`, `offline`, `diagnostic` | Optimization mode (default: online) |

**Modes:**
- `online`: Full analysis with Databricks API access and runtime data
- `offline`: Static analysis without execution data
- `diagnostic`: Focused troubleshooting

## Agent Domains

The CLI routes to 8 domain agents:

| Domain | Handles | Example |
|--------|---------|---------|
| **Query** | SQL optimization | "Optimize query statement_id abc123" |
| **Job** | Job performance | "Analyze job 12345" |
| **UC** | Unity Catalog | "Show lineage for catalog.schema.table" |
| **Cluster** | Compute resources | "Review cluster configuration" |
| **Analytics** | FinOps and cost | "Top expensive queries this month" |
| **Warehouse** | SQL warehouses | "Analyze warehouse portfolio" |
| **Discovery** | Workspace health | "Run workspace discovery" |
| **Diagnostic** | Troubleshooting | "Debug why job 789 is failing" |

## Custom LLM Providers

Use Databricks-hosted models or other OpenAI-compatible APIs:

```bash
# Databricks Model Serving
starboard "Analyze job 123" \
  --llm-model "databricks-claude-sonnet-4-5" \
  --llm-base-url "https://workspace.databricks.com/serving-endpoints" \
  --llm-api-key "dapi..."

# Azure OpenAI
starboard "Optimize query abc" \
  --llm-model "gpt-4" \
  --llm-base-url "https://your-resource.openai.azure.com/" \
  --llm-api-key "your-azure-key"
```

## Error Handling

The CLI handles errors gracefully:

```bash
# Missing credentials
$ starboard "Optimize job 123"
# Error: Missing Databricks credentials

# Network errors
$ starboard "Analyze job 456"
# Error: Analysis failed: Connection timeout

# User interruption (Ctrl+C)
$ starboard "Optimize large query"
# Warning: Analysis interrupted by user
```

## Development

```bash
# Install in editable mode
pip install -e ".[test]"

# Run tests
pytest

# Run CLI directly
python -m starboard_cli.cli.main "Optimize job 123"
```

## Documentation

- [System Architecture](../../docs/architecture/SYSTEM_ARCHITECTURE.md) -- Multi-agent system design
- [API Reference](../../docs/api/API_REFERENCE.md) -- Backend API
- [Configuration Guide](../../docs/CONFIGURATION.md) -- Environment setup
- [Quickstart](../../docs/QUICKSTART.md) -- Getting started

## Related Packages

- **starboard-core**: Core domain models (dependency)
- **starboard-server**: Backend server with multi-agent system (dependency)
- **starboard-sdk**: Python SDK for programmatic access

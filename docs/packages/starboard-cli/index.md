# starboard-cli

Command-line interface for the Starboard multi-agent system.

## Overview

`starboard-cli` provides a natural language interface to the multi-agent system. Simply describe what you want in plain English, and the agent handles domain routing and tool execution automatically.

## Quick Links

- **[Complete Architecture](./architecture.md)** - Detailed architecture guide

## Quick Start

```bash
# Set credentials
export DATABRICKS_HOST="https://your-workspace.databricks.com"
export DATABRICKS_TOKEN="your-databricks-token"
export LLM_API_KEY="your-openai-api-key"

# Use natural language to describe your goal
starboard --goal "Optimize query with statement_id abc123"
starboard --goal "Analyze job 456 for performance issues"
starboard --goal "Show lineage for catalog.schema.table"
```

## Key Features

### Natural Language Interface

**No commands needed** - just describe your goal:

```bash
# Query optimization
starboard --goal "Optimize this SQL: SELECT * FROM large_table WHERE date > '2024-01-01'"

# Job analysis
starboard --goal "Analyze Databricks job 12345 for performance bottlenecks"

# Pipeline lineage
starboard --goal "Show me the lineage for table prod.analytics.user_events"

# Cluster configuration
starboard --goal "Review cluster configuration for cluster-abc-123"

# Troubleshooting
starboard --goal "Help me debug why job 789 is failing"
```

### Multi-Agent Routing

The CLI automatically routes to the appropriate domain agent:
- **Query Agent**: SQL optimization, query plans
- **Job Agent**: Job performance, task analysis
- **UC Agent**: Unity Catalog - schema, lineage, metadata, governance
- **Cluster Agent**: Cluster configuration and optimization
- **Diagnostic Agent**: Troubleshooting and debugging

### Streaming Progress

Real-time feedback during execution:

```
🤖 Initializing Starboard Agent...
✓ Agent ready: model=gpt-4o, budget=120,000 tokens

🔍 Starting analysis...

✅ resolve_query (1.2s)
✅ analyze_query_plan (2.5s)
✅ get_query_stats (0.8s)

======================================================================
✅ RESULTS
======================================================================

Steps taken: 8
Tools used: resolve_query, analyze_query_plan, get_query_stats
Tokens used: 15,420
Cost: $0.0234
Duration: 12.5s
```

### File Input

Pass source code, SQL, or config files:

```bash
# Pass Spark job code
starboard --goal "Optimize this Spark job" --input-file job.py

# Pass SQL query
starboard --goal "Review this query" --input-file query.sql

# Pass job configuration
starboard --goal "Analyze this config" --input-file job_config.json
```

### Multiple Output Formats

**Console Display** (Rich formatted):
- Real-time tool execution
- Colored status indicators
- Formatted markdown report

**JSON Output** (`--output-path`):
```json
{
  "user_goal": "Optimize query abc123",
  "summary": "...",
  "recommendations": [...],
  "complete_report": {...},
  "steps_taken": 8,
  "tools_used": [...],
  "tokens_used": 15420,
  "cost_usd": 0.0234,
  "duration_seconds": 12.5
}
```

**Markdown Report** (`--output-path`):
```markdown
# Starboard Agent Analysis Report

## Goal
Optimize query with statement_id abc123

## Summary
[Analysis summary...]

## Recommendations
1. [Recommendation 1]
2. [Recommendation 2]

---
**Tokens Used**: 15,420
**Cost**: $0.0234
```

### Clean Logging

Separate agent telemetry from console output:

```bash
# Default: Clean console (logs suppressed)
starboard --goal "Optimize job 123"

# Debug mode: Logs to stderr
starboard --goal "Optimize job 123" --debug

# Logs to file: Rich UI on console, logs to file
starboard --goal "Optimize job 123" --log-file agent.log

# Quiet mode: Only show final results
starboard --goal "Optimize job 123" --quiet
```

## Command Line Options

### Core Parameters

| Option | Description |
|--------|-------------|
| `--goal` | What you want the agent to do (natural language, required) |
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
| `--llm-model` | `LLM_MODEL` | Model name (e.g., gpt-4o, gpt-4o-mini) |
| `--llm-api-key` | `LLM_API_KEY` | OpenAI API key (or compatible provider) |
| `--llm-base-url` | `LLM_BASE_URL` | API base URL for custom endpoints |
| `--llm-temperature` | `LLM_TEMPERATURE` | Temperature (0.0-1.0, default: 0.4) |
| `--llm-max-tokens` | `LLM_MAX_TOKENS` | Max token budget (default: 120000) |

### Display & Logging

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
- `online`: Comprehensive analysis with runtime data
- `offline`: Fast analysis without execution data
- `diagnostic`: Focused troubleshooting

## Configuration

### Environment Variables

```bash
# Databricks
export DATABRICKS_HOST="https://workspace.databricks.com"
export DATABRICKS_TOKEN="dapi..."

# LLM
export LLM_MODEL="gpt-4o-mini"
export LLM_API_KEY="sk-..."
export LLM_BASE_URL="https://api.openai.com/v1"  # Optional
export LLM_TEMPERATURE="0.4"
export LLM_MAX_TOKENS="120000"
```

### Config File (YAML)

```yaml
databricks:
  host: "https://workspace.databricks.com"
  token: "dapi123..."

llm:
  model: "gpt-4o"
  api_key: "sk-..."
  base_url: "https://api.openai.com/v1"  # Optional
  temperature: 0.4
  max_tokens: 120000

# Domain-specific model overrides (optional)
domain_model_overrides:
  query: "gpt-4o-mini"
  job: "gpt-4o"
  diagnostic: "gpt-4o"
```

**Usage**:
```bash
starboard --goal "Optimize job 123" --config config.yaml
```

## Advanced Usage

### Custom LLM Providers

**Databricks Foundation Models**:
```bash
starboard --goal "Analyze job 123" \
  --llm-model "databricks-meta-llama-3-1-70b-instruct" \
  --llm-base-url "https://workspace.databricks.com/serving-endpoints" \
  --llm-api-key "dapi..."
```

**Azure OpenAI**:
```bash
starboard --goal "Optimize query abc" \
  --llm-model "gpt-4" \
  --llm-base-url "https://your-resource.openai.azure.com/" \
  --llm-api-key "your-azure-key"
```

### Saving Results

```bash
starboard --goal "Optimize query abc123" --output-path ./results/

# Creates:
#   ./results/20241202_142530_Optimize.json
#   ./results/20241202_142530_Optimize.md
```

### Debugging

```bash
# Enable debug logging
starboard --goal "Analyze job 456" --debug

# Log to file
starboard --goal "Analyze job 456" --log-file debug.log

# View log
cat debug.log
```

## Architecture Highlights

### Single Entry Point

```
User Input → MultiAgentConversationManager → Domain Agent → Tools → Results
```

### Configuration Priority

1. **CLI arguments** (highest)
2. **Config file**
3. **Environment variables**
4. **Defaults** (lowest)

### Event Streaming

The CLI processes streaming events:
- `ToolStartEvent`: Show tool execution start
- `ToolEndEvent`: Show completion with duration
- `StepCompleteEvent`: Track step boundaries
- `FinalOutputEvent`: Capture final output
- `ErrorEvent`: Display errors

### Clean Output

Logs are separated from console output:
- **Console (stdout)**: Rich UI with tool execution
- **Logs (stderr/file)**: Agent telemetry and debugging

See [Complete Architecture](./architecture.md) for detailed information.

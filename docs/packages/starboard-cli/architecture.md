# starboard-cli Architecture

**Package**: `starboard-cli`  
**Version**: 0.1.0  
**Purpose**: Command-line interface for multi-agent system  
**Last Updated**: 2025-12-02

---

## Overview

`starboard-cli` provides a simplified terminal interface for the Starboard multi-agent system. Users describe goals in natural language, and the CLI routes requests to appropriate domain specialists.

### Key Features

- **Natural Language Interface**: No explicit commands, just describe your goal
- **Multi-Agent Routing**: Automatic domain classification
- **Streaming Progress**: Real-time feedback with Rich terminal UI
- **File Input**: Pass source code, SQL files, or other inputs
- **Multiple Output Formats**: JSON and Markdown reports
- **Comprehensive Logging**: Separate agent telemetry from console output

### Design Philosophy

- **Simplicity**: Single natural language interface
- **Transparency**: Show tool execution in real-time
- **Flexibility**: Support multiple LLM providers and configurations
- **Clean Output**: Separate logs from user-facing content

---

## Architecture

### High-Level Design

```
┌────────────────────────────────────────┐
│            CLI Entry Point             │
│         (main.py, parse_args)          │
└───────────────┬────────────────────────┘
                │
┌───────────────▼────────────────────────┐
│        Configuration Loading           │
│  ┌──────────────────────────────────┐ │
│  │  1. Load YAML config (optional)   │ │
│  │  2. Load environment variables    │ │
│  │  3. Merge CLI arguments           │ │
│  │  4. Validate required params      │ │
│  └──────────────────────────────────┘ │
└───────────────┬────────────────────────┘
                │
┌───────────────▼────────────────────────┐
│        Agent Manager Creation          │
│  ┌──────────────────────────────────┐ │
│  │  create_agent_manager()           │ │
│  │  ├─ LLM Client (OpenAI/etc)       │ │
│  │  ├─ Databricks API                │ │
│  │  ├─ Tool Registry                 │ │
│  │  ├─ Intent Router                 │ │
│  │  ├─ Agent Factory                 │ │
│  │  └─ MultiAgentConversationManager │ │
│  └──────────────────────────────────┘ │
└───────────────┬────────────────────────┘
                │
┌───────────────▼────────────────────────┐
│          Streaming Execution           │
│  ┌──────────────────────────────────┐ │
│  │  handle_streaming_events()        │ │
│  │  ├─ Send user message             │ │
│  │  ├─ Process event stream          │ │
│  │  │  ├─ ThinkingEvent              │ │
│  │  │  ├─ ToolStartEvent              │ │
│  │  │  ├─ ToolEndEvent (display)     │ │
│  │  │  ├─ StepCompleteEvent          │ │
│  │  │  ├─ FinalOutputEvent            │ │
│  │  │  └─ ErrorEvent                 │ │
│  │  └─ Capture final output          │ │
│  └──────────────────────────────────┘ │
└───────────────┬────────────────────────┘
                │
┌───────────────▼────────────────────────┐
│           Output Display               │
│  ┌──────────────────────────────────┐ │
│  │  1. Show execution metrics        │ │
│  │  2. Format markdown report        │ │
│  │  3. Display on console (Rich)     │ │
│  │  4. Save to files (optional)      │ │
│  └──────────────────────────────────┘ │
└────────────────────────────────────────┘
```

---

## Package Structure

```
starboard-cli/
├── starboard_cli/
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py              # Main CLI entry point (1664 lines)
│   │   ├── chat.py              # Interactive chat mode (284 lines)
│   │   └── exit_codes.py        # Exit code definitions
│   └── sessions/
│       └── session_manager.py   # Session persistence (294 lines)
│
├── tests/
│   └── test_cli.py              # CLI tests
│
├── pyproject.toml               # Package metadata & dependencies
└── README.md                    # User documentation
```

### Key Files

**main.py**: Complete CLI implementation with:
- Argument parsing
- Configuration loading and merging
- Agent manager creation
- Event streaming and display
- Output formatting and saving

---

## Key Components

### 1. Argument Parsing (`parse_args()`)

Handles CLI arguments with three priority levels:

```python
def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments.
    
    Arguments include:
    - Core: --goal, --config, --input-file, --output-path
    - Databricks: --databricks-host, --databricks-token
    - LLM: --llm-model, --llm-api-key, --llm-base-url, etc.
    - Display: --plain, --quiet
    - Logging: --log-level, --log-file, --debug
    - Agent: --mode (online/offline/diagnostic)
    """
```

**Priority Order** (highest to lowest):
1. CLI arguments (e.g., `--llm-model`)
2. Config file (YAML)
3. Environment variables (e.g., `LLM_MODEL`)
4. Defaults

---

### 2. Configuration Loading (`merge_env_config()`)

Merges configuration from three sources:

```python
def merge_env_config(
    file_config: dict[str, Any],
    args: argparse.Namespace,
) -> EnvConfig:
    """
    Merge file config with CLI args and environment variables.
    
    Returns:
        EnvConfig instance with merged configuration
    """
```

**Configuration Sections**:
- **Databricks**: host, token, warehouse_id, catalog, schema
- **LLM**: provider, model, api_key, base_url, temperature, max_tokens
- **Domain Overrides**: Per-domain model and temperature settings

**Example Config File** (YAML):
```yaml
databricks:
  host: "https://workspace.databricks.com"
  token: "dapi123..."

llm:
  model: "gpt-4o"
  api_key: "sk-..."
  temperature: 0.4
  max_tokens: 120000

# Domain-specific model overrides
domain_model_overrides:
  query: "gpt-4o-mini"
  job: "gpt-4o"
  diagnostic: "gpt-4o"
```

---

### 3. Agent Manager Creation (`create_agent_manager()`)

Instantiates the complete multi-agent system:

```python
def create_agent_manager(config: EnvConfig) -> MultiAgentConversationManager:
    """
    Create multi-agent conversation manager.
    
    Creates:
    - OpenAIProvider (LLM client)
    - DatabricksAPI (Databricks client)
    - SharedContextProvider
    - Tool Registry (40+ tools)
    - IntentRouter
    - AgentFactory
    - MultiAgentConversationManager
    """
```

**Wiring Complexity Hidden**:
- Users don't see internal wiring
- All dependencies injected correctly
- Ready-to-use manager returned

---

### 4. Event Streaming (`handle_streaming_events()`)

Processes streaming events from the agent:

```python
async def handle_streaming_events(
    manager: MultiAgentConversationManager,
    conversation_id: str,
    user_message: str,
    mode: OptimizationMode,
    console: Console,
    plain: bool = False,
    quiet: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Handle streaming events with real-time display.
    
    Event Types:
    - ThinkingEvent: Ignored (don't display reasoning)
    - ToolStartEvent: Show tool execution start
    - ToolEndEvent: Show completion with duration
    - StepCompleteEvent: Track step boundaries
    - FinalOutputEvent: Capture final output
    - UserInputRequestEvent: Handle interruption
    - ErrorEvent: Display errors
    """
```

**Display Modes**:

1. **Rich Mode** (default):
   ```
   ✅ resolve_query (1.2s)
   ✅ analyze_query_plan (2.5s)
   ✅ get_query_stats (0.8s)
   ```

2. **Plain Mode** (`--plain`):
   ```
   ✓ resolve_query (1.2s)
   ✓ analyze_query_plan (2.5s)
   ✓ get_query_stats (0.8s)
   ```

3. **Quiet Mode** (`--quiet`):
   ```
   [No output until completion]
   ```

---

### 5. Output Formatting

#### Markdown Report Generation

```python
def _generate_markdown_report(output: dict[str, Any]) -> str:
    """
    Generate Markdown report from agent output.
    
    Report Sections:
    - Goal
    - Summary
    - Recommendations (numbered list)
    - Implementation steps
    - Execution metadata (tokens, cost, duration)
    """
```

**Report Format**:
```markdown
# Starboard Agent Analysis Report

**Generated**: 2025-12-02 14:30:00

## Goal

Optimize query with statement_id abc123

## Summary

[Agent analysis summary...]

## Recommendations

### 1. [Recommendation Title]

[Description and implementation...]

---

**Conversation ID**: cli_abc123
**Tokens Used**: 15,420
**Cost**: $0.0234
```

#### Output Files

When `--output-path` is specified, creates two files:

1. **JSON** (`20241202_142530_Optimize.json`):
   - Structured data
   - Programmatic consumption
   - Complete metadata

2. **Markdown** (`20241202_142530_Optimize.md`):
   - Human-readable report
   - Formatted recommendations
   - Execution summary

---

### 6. Logging Strategy (`setup_cli_logging()`)

Separates agent telemetry from console output:

```python
def setup_cli_logging(
    log_level: str,
    log_file: str | None = None,
    quiet: bool = False,
) -> None:
    """
    Configure logging for CLI context.
    
    Strategies:
    - Default: Logs suppressed (clean console)
    - --debug: Logs to stderr (Rich UI on stdout)
    - --log-file: Logs to file
    - --quiet: Only errors to stderr
    """
```

**Log Destinations**:

| Mode | Console (stdout) | Logs (stderr) | Notes |
|------|------------------|---------------|-------|
| Default | Rich UI | Suppressed | Clean output |
| `--debug` | Rich UI | Debug logs | Shows internal ops |
| `--log-file` | Rich UI | File | Best for debugging |
| `--quiet` | Minimal | Errors only | Batch processing |

**Suppressed Loggers**:
- `httpx`, `httpcore`: HTTP client noise
- `openai`: OpenAI SDK logging

---

## Usage Patterns

### Basic Usage

```bash
# Simple natural language request
starboard --goal "Optimize query with statement_id abc123"

# With file input
starboard --goal "Optimize this Spark job" --input-file job.py

# With config file
starboard --goal "Analyze job 456" --config config.yaml

# Save results
starboard --goal "Show lineage for catalog.schema.table" \
  --output-path ./results/
```

### Advanced Usage

```bash
# Custom LLM provider (Databricks Foundation Models)
starboard --goal "Analyze job 123" \
  --llm-model "databricks-meta-llama-3-1-70b-instruct" \
  --llm-base-url "https://workspace.databricks.com/serving-endpoints" \
  --llm-api-key "dapi..."

# Debug mode with file logging
starboard --goal "Optimize large query" \
  --debug \
  --log-file debug.log

# Offline mode (fast analysis without runtime data)
starboard --goal "Review job configuration 789" \
  --mode offline
```

---

## Configuration Priority

**Example**: Setting `llm_model`

```
┌────────────────────────────────────┐
│  1. CLI argument (highest)         │
│     --llm-model "gpt-4o"           │
└────────────────────────────────────┘
                ↓
┌────────────────────────────────────┐
│  2. Config file                    │
│     llm:                           │
│       model: "gpt-4o-mini"         │
└────────────────────────────────────┘
                ↓
┌────────────────────────────────────┐
│  3. Environment variable           │
│     LLM_MODEL="gpt-3.5-turbo"      │
└────────────────────────────────────┘
                ↓
┌────────────────────────────────────┐
│  4. Default (lowest)               │
│     "gpt-4o-mini"                  │
└────────────────────────────────────┘

Result: "gpt-4o" (from CLI argument)
```

---

## Error Handling

### Graceful Failures

1. **Missing Credentials**:
   ```
   ❌ Missing Databricks credentials
   Set DATABRICKS_HOST and DATABRICKS_TOKEN environment variables...
   ```

2. **Network Errors**:
   ```
   ❌ Analysis failed: Connection timeout
   Check your network connection and Databricks credentials...
   ```

3. **User Interruption** (Ctrl+C):
   ```
   ⚠️  Analysis interrupted by user
   ```

4. **Agent Errors**:
   ```
   ❌ Error: ToolExecutionError
   Failed to execute resolve_query: Query not found
   ```

---

## Design Decisions

### Why Single Natural Language Interface?

**Before**: Multiple commands (query, job, table, etc.)
```bash
starboard query optimize --statement-id abc123
starboard job analyze --job-id 456
starboard table lineage --table catalog.schema.table
```

**After**: Single natural language interface
```bash
starboard --goal "Optimize query abc123"
starboard --goal "Analyze job 456"
starboard --goal "Show lineage for catalog.schema.table"
```

**Rationale**:
- Users don't need to know domain classification
- IntentRouter automatically determines domain
- More flexible and natural
- Reduces cognitive load

### Why Separate Logs from Console?

**Problem**: Agent logs clutter console output
```
INFO: Tool execution started
DEBUG: HTTP request to Databricks
INFO: Query resolved
✅ resolve_query (1.2s)
DEBUG: Analyzing query plan
```

**Solution**: Separate logs and console
```
[Logs go to file or stderr]

✅ resolve_query (1.2s)
✅ analyze_query_plan (2.5s)
```

**Benefits**:
- Clean console for users
- Full logs for debugging
- Flexible logging modes

### Why Not Support User Input in CLI?

**Challenge**: Interruptible reasoning requires mid-stream input
```
🤔 Agent needs input:
Should I analyze all downstream tables or just direct dependencies?
> [User types response]
```

**CLI Limitation**: Async event stream + Rich UI makes input injection complex

**Solution**: Display question but continue without input
```
🤔 Agent needs input:
Should I analyze all downstream tables or just direct dependencies?

Note: User input injection is not fully supported in CLI mode.
For interactive workflows, use the web UI or API.
```

**Recommendation**: Use web UI for interruptible workflows

---

## Dependencies

### Direct Dependencies

```toml
[tool.uv.dependencies]
starboard-core = { workspace = true }        # Domain models
starboard-server = { workspace = true }      # Multi-agent system

# CLI
argparse = "*"                               # Argument parsing
rich = "^13.0"                               # Terminal UI
structlog = "^24.0"                          # Structured logging

# Config
pyyaml = "^6.0"                              # YAML config files
python-dotenv = "^1.0"                       # Environment variables
```

### Transitive Dependencies

Via `starboard-server`:
- FastAPI
- Pydantic
- OpenAI SDK
- Databricks SDK
- SQLAlchemy

---

## Testing Strategy

### Unit Tests

- Argument parsing with various flags
- Configuration merging priority
- Markdown report generation
- Error handling paths

### Integration Tests

- End-to-end CLI execution (with mocked agent)
- Config file loading
- Output file generation
- Logging configuration

### Manual Testing

```bash
# Test all modes
starboard --goal "test" --mode online
starboard --goal "test" --mode offline
starboard --goal "test" --mode diagnostic

# Test output options
starboard --goal "test" --plain
starboard --goal "test" --quiet
starboard --goal "test" --output-path ./results/

# Test logging
starboard --goal "test" --debug
starboard --goal "test" --log-file debug.log
```

---

## Performance Characteristics

### Startup Time

- **Cold start**: ~2-3 seconds (LLM client init, Databricks connection)
- **Warm start**: N/A (no persistent process)

### Memory Usage

- **Base**: ~100 MB (Python + dependencies)
- **Peak**: ~500 MB (agent reasoning + tool execution)

### Execution Time

Varies by task:
- **Simple query**: 10-30 seconds
- **Job analysis**: 30-60 seconds
- **Complex lineage**: 60-120 seconds

---

## Related Documentation

- [Multi-Agent Architecture](../starboard-server/architecture.md) - Agent system
- [API Reference](../../api/API_REFERENCE.md) - Backend API
- [Configuration](../../CONFIGURATION.md) - Environment setup

---

## Future Enhancements

Potential improvements:
- Interactive mode with user input support
- Session persistence across invocations
- Shell autocompletion
- Rich progress bars during long operations
- Colored diff output for recommendations
- Export to additional formats (HTML, PDF)

---

**Last Updated**: 2025-12-02


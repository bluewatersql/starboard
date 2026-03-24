# Starboard SDK

Python SDK for multi-turn conversations with the Starboard AI Agent.

## Overview

`starboard-sdk` provides programmatic access to the Starboard multi-agent system from Python scripts, notebooks, and pipelines. It wraps the same agent stack used by the CLI and server, enabling multi-turn conversations where each turn builds on prior context.

**Key Features:**
- **Multi-turn conversations**: Maintain context across successive questions
- **Named sessions**: Resume previous analysis sessions by name
- **Streaming support**: Access raw agent events for custom UIs
- **In-process execution**: No HTTP server required -- runs the agent stack directly
- **Async-first**: Built on asyncio for non-blocking execution

## Installation

```bash
# Using uv (recommended)
uv pip install starboard-sdk

# Using pip
pip install starboard-sdk
```

## Quick Start

```python
from starboard_sdk import StarboardClient

async def main():
    # Create client from environment variables
    client = await StarboardClient.from_env()

    async with client:
        # Create a named session (resumable)
        session = await client.create_session(name="etl-tuning")

        # First turn: analyze a job
        r1 = await session.ask("Analyze job 12345 for performance issues")
        print(r1.report)

        # Second turn: follow-up question (agent sees prior context)
        r2 = await session.ask("Can we convert it to streaming?")
        print(r2.report)

        # Check response metadata
        print(f"Domain: {r2.domain}")
        print(f"Tools used: {r2.tools_used}")
        print(f"Duration: {r2.duration_seconds}s")

# Run
import asyncio
asyncio.run(main())
```

## Configuration

The SDK reads the same environment variables as the CLI:

```bash
# Required
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi..."
export LLM_API_KEY="sk-..."

# Optional
export LLM_MODEL="databricks-claude-sonnet-4-5"
export LLM_TEMPERATURE="0.4"
export LLM_MAX_TOKENS="75000"
```

Or use a `.env` file -- `StarboardClient.from_env()` loads it automatically via `python-dotenv`.

## API Reference

### StarboardClient

Factory for creating conversation sessions. Bootstraps the full agent stack (LLM client, Databricks client, tool registry, intent router, agent factory).

```python
# Create from environment variables
client = await StarboardClient.from_env(session_db="~/.starboard/sessions.db")

# Create a new session
session = await client.create_session(name="my-analysis", mode=OptimizationMode.ONLINE)

# Resume an existing session by name
session = await client.resume_session("my-analysis")

# List all saved sessions
sessions = await client.list_sessions()

# Close resources
await client.close()

# Or use as async context manager
async with client:
    session = await client.create_session()
    ...
```

### ConversationSession

A stateful handle to a single multi-turn conversation. Each `ask()` call sends a message to the same conversation so the agent sees prior context.

```python
# Send a message and get the full response
response = await session.ask(
    message="Optimize query abc123",
    mode=OptimizationMode.ONLINE,  # Override mode for this turn
    timeout=300.0,                  # Seconds (default: 5 minutes)
)

# Stream raw events for custom handling
async for event in session.ask_stream("Analyze job 456"):
    if isinstance(event, ToolEndEvent):
        print(f"Tool: {event.tool_name}")
    elif isinstance(event, FinalOutputEvent):
        print(f"Done: {event.output}")

# Session properties
session.session_id     # Underlying conversation ID
session.session_name   # Human-friendly name
session.turn_count     # Number of completed turns
```

### AgentResponse

Immutable response from a single agent turn.

```python
response.ok                # True if turn completed successfully
response.report            # Formatted markdown report
response.markdown          # Report as markdown (with fallbacks)
response.raw_output        # Full agent output dictionary
response.tools_used        # List of tool names invoked
response.tokens_used       # Total tokens consumed (if available)
response.cost_usd          # Estimated cost in USD (if available)
response.duration_seconds  # Wall-clock time for this turn
response.domain            # Domain agent that handled the request
response.conversation_id   # Underlying conversation ID
response.turn_number       # Which turn this response corresponds to
response.error             # Error message if turn failed, None otherwise
```

## Streaming Usage

For custom UIs or real-time processing, use `ask_stream()` to receive raw agent events:

```python
from starboard_server.agents.events import (
    ThinkingEvent,
    ToolStartEvent,
    ToolEndEvent,
    FinalOutputEvent,
    ErrorEvent,
)

async for event in session.ask_stream("Analyze job 12345"):
    match event:
        case ThinkingEvent():
            print(f"Thinking: {event.content[:80]}...")
        case ToolStartEvent():
            print(f"Calling: {event.tool_name}")
        case ToolEndEvent():
            print(f"Result: {event.tool_name} -> {len(str(event.result))} chars")
        case FinalOutputEvent():
            print(f"Report ready: {event.output.get('summary', '')[:100]}")
        case ErrorEvent() if not event.is_recoverable:
            print(f"Error: {event.error}")
```

## Error Handling

```python
from starboard_sdk import StarboardClient

async with await StarboardClient.from_env() as client:
    session = await client.create_session()

    try:
        response = await session.ask("Analyze job 12345", timeout=60.0)
    except TimeoutError:
        print("Agent did not respond in time")
    else:
        if response.ok:
            print(response.report)
        else:
            print(f"Agent error: {response.error}")
```

Common failure modes:
- **TimeoutError**: Agent did not respond within the specified timeout
- **ValueError**: Cannot resume session without a SessionManager
- **Connection errors**: Invalid Databricks credentials or LLM API key
- **Agent errors**: Surfaced in `response.error` (non-recoverable tool failures)

## Examples

### Jupyter/Databricks Notebook

```python
from starboard_sdk import StarboardClient

client = await StarboardClient.from_env()
session = await client.create_session(name="notebook-analysis")

# Analyze a query
r = await session.ask("Optimize query with statement_id 01948a0b-1ebb-17a4-959c-70dde9c5e3fc")
display(Markdown(r.markdown))
```

### Batch Analysis Pipeline

```python
import asyncio
from starboard_sdk import StarboardClient

async def analyze_jobs(job_ids: list[int]):
    async with await StarboardClient.from_env() as client:
        for job_id in job_ids:
            session = await client.create_session(name=f"job-{job_id}")
            response = await session.ask(f"Analyze job {job_id} for performance issues")
            if response.ok:
                print(f"Job {job_id}: {response.domain} - {len(response.tools_used)} tools")
                with open(f"reports/job_{job_id}.md", "w") as f:
                    f.write(response.markdown)

asyncio.run(analyze_jobs([123, 456, 789]))
```

### Cost Analysis

```python
async with await StarboardClient.from_env() as client:
    session = await client.create_session(name="cost-review")

    # First turn: overview
    r1 = await session.ask("What are my top 10 most expensive queries this month?")
    print(r1.report)

    # Second turn: drill down (agent remembers prior context)
    r2 = await session.ask("Show me a chargeback breakdown by team for those queries")
    print(r2.report)
```

## Development

```bash
# Install in editable mode
uv pip install -e ".[test]"

# Run tests
cd packages/starboard-sdk
pytest

# Run type checks
mypy starboard_sdk/
```

## Related Packages

- **starboard-core**: Core domain models (dependency)
- **starboard-server**: Backend server with multi-agent system (dependency)
- **starboard-cli**: Command-line interface

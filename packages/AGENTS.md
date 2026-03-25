# packages/ — Python Monorepo Packages

This directory contains all Python packages managed as a `uv` workspace. Each package is independently installable and versioned.

## Package Overview

### starboard-core
**Purpose:** Pure domain logic, shared models, and types. No I/O dependencies.
- Domain models (Pydantic V2), prompt constants, shared utilities
- Zero external I/O; all functions are deterministic and testable in isolation
- Dependency direction: all other packages depend on this one

### starboard-server
**Purpose:** FastAPI backend with the full multi-agent system.
- Multi-agent conversation manager, intent router, domain agents
- Tool system (45+ tools), state management, SSE streaming
- Depends on: `starboard-core`, `starboard-log-parser`

### starboard-log-parser
**Purpose:** Spark event log parsing with pluggable credential providers.
- Parses Databricks/Spark event logs from local filesystem, S3, ADLS, GCS
- Credential provider framework for cloud auth
- Depends on: `starboard-core`

### starboard-cli
**Purpose:** Command-line interface for Starboard.
- Interactive and non-interactive CLI workflows
- Depends on: `starboard-core`, `starboard-server`

### starboard-sdk
**Purpose:** Thin Python SDK for notebook and programmatic access.
- Designed for Databricks notebooks and CI/CD pipelines
- Wraps server API with a clean Python interface
- Depends on: `starboard-core`, `starboard-server`

## Dependency Flow

```
starboard-cli  ──┐
starboard-sdk  ──┼──► starboard-server ──► starboard-log-parser ──► starboard-core
                 └──► starboard-core
```

## Development

Install all packages with dev extras:
```bash
make install-dev
```

Run tests for a specific package:
```bash
cd packages/starboard-server && pytest tests/unit/ -v
```

# Packages

Monorepo workspace managed by `uv`. Dependency flow: CLI / Server / SDK → Core.

| Package | Purpose |
|---------|---------|
| `starboard-core` | Domain models, prompts, shared types. No I/O dependencies. |
| `starboard-log-parser` | Spark event log parsing with credential provider framework. |
| `starboard-server` | FastAPI backend with multi-agent system, tools, and MCP server. |
| `starboard-cli` | Command-line interface for interactive analysis. |
| `starboard-sdk` | Thin SDK for notebook/programmatic use. |

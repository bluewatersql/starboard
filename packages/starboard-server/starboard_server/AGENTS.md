# starboard-server

FastAPI backend with multi-agent system, tools, and MCP server.

## Key Directories
- `agents/` -- Multi-agent conversation system (routing, domain agents, factory)
- `tools/` -- 45+ tools in three-layer architecture (domain, services, adapters)
- `prompts/` -- Domain-specific prompt templates (versioned)
- `adapters/` -- I/O boundaries (LLM clients, DB, HTTP)
- `mcp/` -- Model Context Protocol server
- `infra/` -- Config, logging, DI, observability, circuit breakers
- `api/` -- FastAPI route definitions
- `config/` -- Server configuration
- `discovery/` -- Workspace discovery logic
- `domain/` -- Server-specific domain models
- `repositories/` -- State management with pluggable backends
- `services/` -- Service-layer orchestration

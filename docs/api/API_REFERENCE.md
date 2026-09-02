# Starboard AI Agent — HTTP / MCP Reference

> Last verified: 2026-08-27 (against `packages/starboard/starboard/main.py` and `starboard.mcp`)

**Base URL** (server mode): `http://localhost:8000`

---

## Scope

Starboard is **not** a REST application. Its primary consumption paths are:

- **`starboard`** — the CLI, which runs the agent **in-process** (no HTTP). See the
  [User CLI guide](../user-guide/cli.md) and [Quickstart](../QUICKSTART.md).
- **`starboard-mcp`** — a **stdio** MCP server for Claude Code / Cursor / Codex and
  other MCP hosts (no FastAPI).
- **`starboard-server`** — a **minimal** FastAPI process (`starboard.main:create_app`,
  console script `starboard-server`) that exposes health probes and, when configured,
  mounts the MCP HTTP transport at `/mcp`. It does **not** expose a chat/conversation
  REST API.

There are no `/api/chat`, `/api/feedback`, `/api/data`, or `/api/visualization` routes:
the FastAPI app defines only the endpoints below (source: `starboard/main.py`).

---

## HTTP endpoints (`starboard-server`)

The FastAPI app (`create_app()`) registers exactly these routes:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Service metadata (name, version, links to health and `/mcp`) |
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe |
| `*` | `/mcp` | Streamable-HTTP MCP transport — **mounted only when MCP config is present** |

Interactive OpenAPI docs are served at `/docs`, `/redoc`, and `/openapi.json`
**outside production** (`ENVIRONMENT=production` disables them).

### GET /

```json
{
  "name": "Starboard AI Agent",
  "version": "0.1.0",
  "status": "running",
  "docs": "/docs",
  "health": {"live": "/health/live", "ready": "/health/ready"},
  "mcp": "/mcp"
}
```

### GET /health/live

Liveness probe — returns `200` while the process is running.

```json
{"status": "ok"}
```

### GET /health/ready

Readiness probe.

```json
{"status": "ok"}
```

### /mcp (conditional)

The MCP HTTP transport is mounted only when `load_mcp_config()` returns a config
(see [MCP transports](#mcp-transports)). On success the server logs
`mcp_server_mounted path=/mcp`; on failure it logs `mcp_server_mount_failed` and keeps
serving the health/root routes.

---

## Running the server

```bash
# Console script (entry point: starboard.main:run)
starboard-server

# or, equivalently
python -m starboard.main
```

The host/port/reload come from config (`STARBOARD_HOST`, `STARBOARD_PORT`,
`STARBOARD_DEBUG`); see the [Configuration Guide](../CONFIGURATION.md).

### Optional middleware (not auto-wired)

The server package ships reusable Starlette middleware — `AuthMiddleware`
(`starboard.infra.auth.middleware`), `RequestSizeLimitMiddleware`
(`starboard.infra.middleware.request_size`), and error-sanitisation — as building
blocks for a hosting layer (e.g. a Databricks App with per-user OBO auth). The default
`create_app()` does **not** attach them; a deployment wires them explicitly via
`app.add_middleware(...)`. Auth follows the "auth by subtraction" model — see the
[Security standards](../developer/standards/security.md).

---

## MCP transports

Starboard's richest programmatic surface is MCP, not HTTP. The tools exposed over MCP
are the agent tools plus the Phase-3 surfaces (Workload Review, workspace discovery).

- **stdio** (default for hosts): `starboard-mcp` (`starboard.mcp.cli:main`).
- **Streamable HTTP**: mounted at `/mcp` by `starboard-server` when MCP config is present.

Plugins register additional per-domain tools through the `starboard.mcp_tools`
entry-point group (a `ToolPlugin` object; contract in `starboard.tools.plugins`). Note:
**plugins are not MCP servers** — they are thin wheels discovered at runtime. See
[Tool Architecture](../TOOL_ARCHITECTURE.md) and the reference
`starboard-plugin-sample` package.

---

## In-process events (CLI/SDK)

The agent emits a stream of typed events while it reasons — reasoning steps, tool
start/end, final output, user-input requests, errors. These are delivered
**in-process** to the CLI and SDK (rendered in the terminal / surfaced to callers);
they are **not** an HTTP Server-Sent-Events endpoint. The event vocabulary and
interrupt model are documented in
[Interruptible Reasoning](../INTERRUPTIBLE_REASONING.md).

---

## Related documentation

- [Tool Catalog](../tools/TOOL_CATALOG.md) — complete tool reference
- [Tool Architecture](../TOOL_ARCHITECTURE.md) — tool layering + plugin/adapter seams
- [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md) — system design
- [Package Integration](../integration/PACKAGE_INTEGRATION.md) — how the packages compose
- [Quickstart](../QUICKSTART.md) — getting started

---

**Last Updated**: 2026-08-27

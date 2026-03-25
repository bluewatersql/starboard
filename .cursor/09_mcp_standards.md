# 09 – MCP Standards

Rules for Model Context Protocol (MCP) server implementation, tool registration, and protocol compliance.

---

## Tool Registration & Schema Contract

**GUIDELINE-006: MUST: Every MCP tool must declare an `inputSchema` (JSON Schema) at registration time.** Tools registered without schemas violate the MCP protocol specification and will fail schema validation in compliant clients. Enforced by `tests/architecture/test_mcp_contract.py`.

MUST: All MCP tools must:
- Declare `inputSchema` with JSON Schema type definitions for all parameters
- Include `description` fields for each parameter
- Mark required parameters in the `required` array
- Return structured error responses with `isError: true` on failure

MUST: Tool execution errors must be caught and returned as MCP error responses (never unhandled exceptions).

---

## Resource Registration

MUST: MCP servers must implement `list_resources()` returning all available resources with:
- Unique `uri` for each resource
- Human-readable `name` and `description`
- Correct `mimeType`

---

## Session Management

MUST: Session-scoped state (rate limiters, caches, context) must use bounded data structures with:
- LRU or TTL-based eviction
- Configurable size limits
- Cleanup on session termination

MUST NOT: Use unbounded dicts for session state — this causes memory leaks under load.

---

## Transport Security

MUST: HTTP transport must implement authentication (API key or OAuth).
MUST: Validate all tool inputs against declared `inputSchema` before execution.
SHOULD: Implement request size limits and rate limiting at the transport layer.

---

## Testing

MUST: MCP tools must have:
- Unit tests for each tool function
- Integration tests verifying MCP protocol compliance
- Contract tests asserting schema presence and correctness

SHOULD: Use the MCP inspector tool for protocol conformance testing.

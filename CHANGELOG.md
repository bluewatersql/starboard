# Changelog

All notable changes to Starboard AI Agent are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### chore/archive-recommendations
- Added `AGENTS.md` files for `packages/`, `frontend/`, and `tests/` directories
- Added `docs/TOKEN_BUDGET.md` documenting the token budget system
- Added `docs/runbooks/incident_template.md` for incident response
- Wired `starboard-sdk` tests into `Makefile` (`test-sdk`, `test-unit`)
- Added `pip-audit` hook to `.pre-commit-config.yaml`
- Verified Python 3.12 alignment across `Makefile`, `pyproject.toml`, `.python-version`
- Added eval smoke test TODO in `Makefile`

---

## Previous Workstreams

### fix/resource-leaks
- Fixed resource leaks in HTTP sessions and database connections
- Added context managers for all external service connections
- Ensured async generators are properly closed on cancellation

### fix/ai-safety
- Added structured output validation for all LLM responses
- Enforced JSON-mode / function-call schemas on every LLM call
- Improved prompt injection defences in tool input handlers

### fix/mcp-protocol
- Fixed MCP protocol compliance issues
- Improved error handling and authentication in MCP server
- Added rate limiting to MCP endpoints

### fix/security-critical
- Redacted PII from structured logs
- Parameterised all database queries
- Removed hardcoded credentials from configuration examples
- Added `SAFE_MODE` guard for disabling external calls in test environments

---

## [0.1.0] — Initial Release

### Added
- Multi-agent conversation system with domain specialisation
  - QueryAgent, JobAgent, UCAgent, ClusterAgent, AnalyticsAgent, WarehouseAgent, DiagnosticAgent
- IntentRouter with hybrid pattern-matching + LLM classification
- 45+ domain tools across Query, Job, Unity Catalog, Cluster, Warehouse, and Analytics
- FastAPI backend with Server-Sent Events streaming
- Next.js 16 frontend with Material UI v7
- SQLite (dev) and PostgreSQL (prod) state backends with vector search
- Redis session cache and rate limiting
- Comprehensive test suite: unit, integration, golden, contract
- MkDocs documentation site

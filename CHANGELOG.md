# Changelog

All notable changes to Starboard AI Agent are documented here.

## [Unreleased] — 2026-03-25

### Slot 1: Foundation (Phase 0)
- Added 10 architecture fitness tests (GUIDELINE-001 through 010)
- Removed 9 unused Python dependencies and 2 unused frontend dependencies
- Generated `examples/env.example` from all EnvConfig fields
- Updated 6 engineering guideline documents

### Slot 2: Security, MCP, AI Safety, Resource Leaks
- Fixed SQL injection in UC adapter `_format_value`
- Removed info disclosure from error responses
- Defaulted `enable_pii_redaction=True`, tightened CORS
- Implemented MCP resources, composite tools, error handling
- Added injection detector blocking mode
- Moved user input to separate user-role messages
- Cached `_rest_client`, fixed resource lifecycle cleanup

### Slot 3: Architecture, Error Handling, Config
- Implemented StateStore Protocol across 24 store classes
- Fixed 15 layer violations: agents no longer import from api layer
- Merged exception hierarchy, migrated 34 modules to structlog
- Created `bootstrap.py` public facade

### Slot 4: AI Hardening, SDK/CLI, Frontend
- Created `BaseToolAdapter`, `OutputFormat` enum, `@tool_schema` decorator
- SDK: Exception hierarchy, removed Any types, events facade
- CLI: `--json`, `--no-color` flags, stderr for errors
- Frontend: Removed 14 `as any` casts, added ARIA attributes

### Slot 5: Observability & DX, Archive
- Added `make audit-deps`, `make test-sdk` targets
- Relaxed numpy/pyarrow upper bounds
- Created AGENTS.md, CHANGELOG.md, runbook templates

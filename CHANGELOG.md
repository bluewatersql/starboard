# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Architecture fitness tests (GUIDELINE-001 through GUIDELINE-010)
- Token budget documentation
- Operations runbook with triage flowchart
- AGENTS.md files across all key directories
- docker-compose.yml for local dev (Postgres, Redis)
- Runbook templates for rollback and capacity planning

### Changed
- SDK fully integrated into Makefile (test, coverage, type-check)
- Pre-commit config extended with mypy and check-toml hooks
- pip-audit hook args fixed for environment-based scanning
- test-coverage now spans all packages (core, log-parser, server, cli, sdk)
- TOKEN_BUDGET.md added to mkdocs nav

### Fixed
- SDK test failures no longer swallowed in `make test-unit`

## [0.1.0] - 2026-03-26

### Added
- Initial multi-agent conversation system
- 8 domain agents (Query, Job, UC, Cluster, Analytics, Warehouse, Discovery, Diagnostic)
- 45+ tools across 6 categories
- FastAPI backend with SSE streaming
- Next.js 16 frontend with Material UI v7
- MCP server integration
- CLI with interactive analysis
- SDK for programmatic use
- SQLite, Postgres, and Redis state backends

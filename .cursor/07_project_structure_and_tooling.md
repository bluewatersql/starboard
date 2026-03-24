# 07 – Project Structure, Tooling & DX

---

## Project Structure (Agent-Ready)

Typical structure (conceptual):

project/  
- app/ (entrypoints: API, CLI, UI)  
- agents/ (agent policies, planners, routers)  
- adapters/ (LLM, DB, HTTP, filesystem)  
- domain/ (pure logic and types)  
- tools/ (tool implementations and schemas)  
- prompts/ (versioned prompt templates)  
- retrievers/ (RAG online queries)  
- indexers/ (offline indexing pipelines)  
- infra/ (config, logging, DI wiring)  
- tests/  
- evals/  
- docs/  
- scripts/  
- build & env files (pyproject.toml, uv.lock, Makefile, .env.example, Dockerfile, etc.)

---

## Tooling Defaults (Cursor-Friendly)

When generating code in this project, Cursor should:

1. Add full type hints on all functions (parameters and return types).  
2. Use Google-style docstrings with Args/Returns/Raises/Examples.  
3. Use Pydantic models or TypedDicts for AI input/output validation.  
4. Add unit tests (pytest) in the appropriate tests/ module.  
5. Add or update golden tests for any prompt changes.  
6. Use structured logging (trace_id, cost, latency).  
7. Include token accounting hooks where relevant (input_tokens, output_tokens, cost_usd).  
8. Prefer async implementations where appropriate (no blocking calls on event loops).  
9. Implement robust error handling with retries, circuit breakers, and fallbacks.  
10. Add observability (logs, metrics, traces) for new code paths.

MUST: Propose minimal diffs and preserve public APIs unless a spec change requires otherwise.  
MUST: Never insert secrets directly; use environment variables and document them in .env.example.

---

## Version Control & CI/CD

MUST: Use small, focused commits with clear messages (Conventional Commits or similar).  
MUST: Use feature branches; PRs must pass at least:
- Formatting (Ruff)  
- Linting (Ruff, mypy)  
- Tests (pytest with coverage targets)  
- Golden tests for prompts  

MUST: Exclude typical build artifacts and secrets from version control (pycache, .env, logs, local data, etc.).  
MUST: CI should publish coverage and block merges on serious regressions.

---

## Developer Experience

MUST: Provide a local dev setup:
- .env.example documenting all required variables  
- a simple bootstrap command (e.g., make setup)  

SHOULD: Support hot-reload for prompt changes and configuration where feasible.  
SHOULD: Provide a small playground/REPL for testing agents interactively.  
SHOULD: Use pre-commit hooks for formatting and linting.

---

## Production Readiness & Operations

MUST: Implement graceful degradation (fallbacks, cached responses, feature flags).  
MUST: Implement circuit breakers and health checks for critical dependencies.  
MUST: Have a clear rollback path for prompt and agent changes.  

SHOULD: Use blue-green or canary patterns for rolling out high-impact changes.

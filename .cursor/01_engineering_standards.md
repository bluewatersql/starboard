# 01 – Engineering Standards (General)

These rules apply broadly to all Python code across the project.

---

## Functions & Methods

SHOULD: Typical size 20-30 lines; refactor if larger.  

MUST: 4 parameters or fewer; else group via dataclass/TypedDict.  

MUST: Avoid boolean flags; prefer enums or separate functions.  

SHOULD: Return early; 3 levels of nesting or fewer.  

MUST: No hidden I/O in domain functions.

Bad example:

    def process(data: dict, flag: bool) -> dict: ...

Better pattern:

    class ProcessMode(Enum):
        STRICT = "strict"
        LENIENT = "lenient"

    def process(data: ProcessInput, mode: ProcessMode) -> ProcessOutput: ...

---

## Data Structures

MUST: Dataclasses for DTOs (frozen=True when feasible).  
MUST: Pydantic V2 models at all untrusted boundaries (user input, LLM output, HTTP).  
SHOULD: Prefer Polars over Pandas for performance/memory.  
SHOULD: TypedDict for flexible dict interfaces; document required/optional keys.  
MUST: Use tuple for immutable sequences; list only for mutable collections.

---

## Error Handling

MUST: Fail fast on invalid inputs/config; raise specific exceptions (never generic Exception).  
MUST: No bare except:; catch expected types with explicit handling.  
MUST: Use context managers for resources (files, DB connections, HTTP sessions).  
MUST: Log context + correlation IDs; include request_id/trace_id for LLM/tool calls.  
MUST: Implement idempotent retries with exponential backoff + jitter where relevant (max 3 retries).

SHOULD: Circuit breakers for external dependencies (open after N failures, half-open retry, close on success).

MUST: Handle these LLM-specific errors explicitly:
- Rate limits (429) -> backoff + retry
- Timeouts -> retry with extended timeout
- Invalid JSON -> repair prompt or fallback
- Moderation flags -> log + refuse gracefully

---

## Type Checking

MUST: Type hints required on all public functions/classes.  
MUST: Run mypy in CI via `make type-check`.  

Current configuration (`pyproject.toml`):
- `strict = false` — incrementally tightening; goal is strict mode once legacy issues are resolved.  
- `check_untyped_defs = true` — type-checks function bodies even without annotations.  
- Pydantic mypy plugin enabled.  
- Several modules have `ignore_missing_imports` or `ignore_errors` overrides for legacy/third-party code.  

SHOULD: Use `@override` decorator from `typing` (Python 3.12+) when implementing protocols.  
SHOULD: When adding new modules, aim for mypy-strict-compatible annotations from the start.

---

## Dependencies

MUST: Minimize deps; prefer stdlib. Pin in pyproject.toml and lockfile.  
SHOULD: Prefer async SDKs where available (aiohttp, httpx); never block event loops.  
SHOULD: Use Polars unless a documented gap requires Pandas.

Recommended stack (non-exhaustive):

- pydantic>=2.0, python-dotenv, cryptography  
- litellm or provider SDKs (openai, anthropic, google-generativeai), tiktoken, instructor  
- structlog, opentelemetry, prometheus-client  
- asyncio, httpx or aiohttp, tenacity  
- polars, numpy, faiss-cpu, qdrant-client

---

## Anti-Patterns (Avoid)

NEVER:
- God objects / monolithic Agent classes  
- Deep nesting (>3 levels), boolean argument switches  
- Mutable default args; globals/singletons  
- Catch-and-ignore; proceeding after failed validation  
- Premature optimization without profiling  
- Magic numbers; unversioned prompts  
- Parsing free-form LLM text without schemas  
- Logging secrets or full PII-containing prompts  
- Blocking calls in async contexts  
- Ignoring rate limits or token budgets  
- Implicit state in agents (use explicit state machines)

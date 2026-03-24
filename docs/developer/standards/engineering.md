# Engineering Standards

These standards apply to all Python code in the Starboard AI Agent project. They are enforced through code review, linting (ruff), type checking (mypy), and pre-commit hooks.

!!! info "Source of truth"
    These standards are mirrored from `.cursor/01_engineering_standards.md` and `.cursor/02_agents_and_architecture.md`. When in doubt, the `.cursor/` files are authoritative.

---

## Functions & Methods

| Rule | Level |
|------|-------|
| Typical size 20-30 lines; refactor if larger | SHOULD |
| 4 parameters or fewer; group via dataclass/TypedDict if more | MUST |
| Avoid boolean flags; prefer enums or separate functions | MUST |
| Return early; 3 levels of nesting or fewer | SHOULD |
| No hidden I/O in domain functions | MUST |

**Bad:**
```python
def process(data: dict, flag: bool) -> dict: ...
```

**Good:**
```python
class ProcessMode(Enum):
    STRICT = "strict"
    LENIENT = "lenient"

def process(data: ProcessInput, mode: ProcessMode) -> ProcessOutput: ...
```

---

## Data Structures

| Rule | Level |
|------|-------|
| Dataclasses for DTOs (`frozen=True` when feasible) | MUST |
| Pydantic V2 models at all untrusted boundaries | MUST |
| Prefer Polars over Pandas for performance | SHOULD |
| TypedDict for flexible dict interfaces | SHOULD |
| `tuple` for immutable sequences; `list` only for mutable | MUST |

---

## Error Handling

| Rule | Level |
|------|-------|
| Fail fast on invalid inputs/config | MUST |
| Raise specific exceptions (never generic `Exception`) | MUST |
| No bare `except:` | MUST |
| Context managers for resources (files, DB, HTTP) | MUST |
| Log context + correlation IDs (`trace_id`, `request_id`) | MUST |
| Idempotent retries with exponential backoff + jitter (max 3) | MUST |
| Circuit breakers for external dependencies | SHOULD |

**LLM-Specific Error Handling:**

| Error | Action | Level |
|-------|--------|-------|
| Rate limits (429) | Backoff + retry | MUST |
| Timeouts | Retry with extended timeout | MUST |
| Invalid JSON | Repair prompt or fallback | MUST |
| Moderation flags | Log + refuse gracefully | MUST |

---

## Dependencies

- Minimize deps; prefer stdlib. Pin in `pyproject.toml` and lockfile.
- Security checks in CI (`pip-audit` / OSV).
- Prefer async SDKs (aiohttp, httpx); never block event loops.
- Use Polars unless a documented gap requires Pandas.

---

## Architectural Layers

```
domain/      – pure logic, deterministic, no I/O
adapters/    – I/O boundaries (LLM SDKs, DB, HTTP, FS)
agents/      – policies, tool routing, orchestration
app/         – CLI/API/FastAPI entrypoints
infra/       – config, logging, DI/wiring, observability
tools/       – tool implementations with explicit schemas
```

**Rules:**
- Dependency injection for all external services
- Pure functions in domain; side effects only in adapters
- Separate prompting from tool calls; schemas live at boundaries
- Immutable data preferred (`dataclasses(frozen=True)`, `tuple`)

---

## Anti-Patterns

Never do these:

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

# Prompts & Schemas Standards

Rules for prompt design, schema discipline, and prompt testing in the Starboard AI Agent project.

---

## Schema Discipline

Every LLM call must be constrained:

| Rule | Level |
|------|-------|
| Use JSON-mode or function-call schemas for all LLM calls | MUST |
| Validate outputs with Pydantic V2 | MUST |
| On invalid output: retry with repair prompt (max 3 attempts) | MUST |
| Never continue on parse errors | MUST |

---

## Prompt Organization

| Rule | Level |
|------|-------|
| Centralize prompts under `prompts/` with semantic versions | MUST |
| Maintain golden tests for prompts | MUST |
| PRs that modify prompts must include updated snapshots | MUST |
| Version prompts in code (e.g., `PROMPT_VERSION = "1.0.0"`) | MUST |

**Prompt location:** `packages/starboard-server/starboard_server/prompts/`

Each domain agent has versioned prompts:
```
prompts/
├── query/v1.py
├── job/v1.py
├── uc/v1.py
├── cluster/v1.py
├── analytics/v1.py
├── warehouse/v1.py
├── discovery/v1.py
├── diagnostic/v1.py
└── factories.py       # Registry mapping domains to prompt builders
```

---

## Temperature Defaults

| Use Case | Temperature | Level |
|----------|------------|-------|
| Structural/tool calls | 0.0 – 0.4 | MUST |
| Creative tasks | Up to ~0.9 | SHOULD (document exceptions) |

---

## Prompt Template Standards

System messages must clearly specify:

1. **Role** — Who the agent is
2. **Constraints** — What it cannot do
3. **Output format** — JSON schema or explicit structure

Best practices:

| Practice | Level |
|----------|-------|
| Stream tokens for UX when structure is loose | SHOULD |
| Buffer when strict structure is required | SHOULD |
| Include 2-4 few-shot examples for complex tasks | SHOULD |
| Use chain-of-thought triggers for reasoning-heavy tasks | SHOULD |
| A/B test prompt variations and track performance metrics | SHOULD |

---

## Anti-Jailbreak Patterns

| Rule | Level |
|------|-------|
| Validate outputs against expected schemas | MUST |
| Detect obvious prompt injection attempts | MUST |
| Log and alert on suspicious patterns | MUST |

---

## Prompt Testing

| Rule | Level |
|------|-------|
| Golden tests in `tests/golden/` for critical prompts | MUST |
| Assert both shape and key fields, not just bare text | MUST |
| Regression tests for output structure stability | SHOULD |

# 03 – Prompts & Schemas

Rules for prompt design, schema discipline, and prompt testing.

---

## Prompting & Schema Discipline

MUST: Constrain every LLM call:
- Use JSON-mode or function-call schemas.  
- Validate outputs with Pydantic V2 or equivalent.  
- On invalid output: retry with a repair prompt (max 3 attempts); never continue on parse errors.

MUST: Centralize prompts under prompts/ with semantic versions (prompts/v1/, prompts/v2/).  
MUST: Maintain golden tests for prompts; PRs that modify prompts should include updated snapshots.  

MUST: Default temperatures:
- Structural/tool calls: 0.0–0.4  
- Creative tasks: up to ~0.9 (document exceptions)

SHOULD: Stream tokens for UX when structure is loose; buffer when strict structure is required.  
SHOULD: Include 2–4 few-shot examples for complex tasks; keep format consistent.  
SHOULD: Use chain-of-thought triggers for reasoning-heavy tasks when appropriate.

---

## Prompt Template Standards

MUST: System messages should clearly specify:
- Role: who the agent is  
- Constraints: what it cannot do  
- Output format: JSON schema or explicit structure  

MUST: Version prompts in code (e.g., TOOL_SELECTION_PROMPT_V2).  
SHOULD: A/B test prompt variations and track performance metrics per variant.  

MUST: Anti-jailbreak patterns:
- Validate outputs against expected schemas.  
- Detect obvious prompt injection attempts (e.g., "Ignore previous instructions").  
- Log and alert on suspicious patterns.

---

## Prompt Testing

MUST: Golden tests in tests/golden/ for critical prompts.  
MUST: Assert both shape and key fields of outputs, not just bare text.  
SHOULD: Regression tests that ensure output structure and key fields remain stable across prompt changes.

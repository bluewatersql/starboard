# Token Budget System

Starboard's agent reasoning loop is governed by a token budget that prevents unbounded LLM spending on a single request and ensures predictable cost per conversation turn.

## Overview

Every agent reasoning step consumes tokens from two sources:

1. **Input tokens** — the system prompt, conversation history, tool schemas, and intermediate results passed to the LLM.
2. **Output tokens** — the LLM's response (reasoning text + tool call JSON).

The token budget system tracks cumulative usage per agent turn and enforces soft and hard limits.

## Per-Domain Budgets

Token budgets are configured per domain in `agents/config/agent_config.py` (`DEFAULT_TOKEN_BUDGETS`). Each domain agent has its own budget tuned to the complexity of its workflows. Budget enforcement is implemented in `tools/domain/diagnostic/tool_governance.py`.

## How It Works

### Prompt Truncation

When the accumulated context approaches the soft limit, the system applies progressive truncation:

1. **Oldest tool results** are summarised or dropped first (least-recently-needed).
2. **Conversation history** is trimmed to the most recent N turns.
3. **System prompt** sections are compressed (verbose examples removed).

The truncation strategy preserves the current user intent and the most recent tool outputs.

### Hard Limit Enforcement

If the estimated token count for the next LLM call would exceed the hard limit, the agent:

1. Terminates its reasoning loop immediately.
2. Returns a partial response with a `token_budget_exceeded` signal in the SSE stream.
3. Logs the event with `trace_id`, `agent`, `tokens_used`, and `budget_hard`.

### Cost Tracking

Every LLM call emits a structured log entry:

```json
{
  "event": "llm_call",
  "trace_id": "...",
  "span_id": "...",
  "model": "gpt-4o",
  "prompt_tokens": 4200,
  "completion_tokens": 380,
  "total_tokens": 4580,
  "cost_usd": 0.0183,
  "budget_soft": 8000,
  "budget_hard": 16000,
  "budget_remaining": 3420
}
```

These events feed the FinOps / Analytics agent's cost dashboards.

## Temperature Defaults

Token efficiency is also affected by output verbosity. Starboard uses conservative temperature settings:

| Call Type | Temperature |
|-----------|-------------|
| Tool selection / JSON schema | ≤ 0.4 |
| Structured analysis | ≤ 0.4 |
| Narrative explanation | ≤ 0.7 |
| Creative suggestions | ≤ 0.9 |

## Relevant Source Files

- `packages/starboard/starboard/agents/config/agent_config.py` — `DEFAULT_TOKEN_BUDGETS` per-domain budget configuration
- `packages/starboard/starboard/tools/domain/diagnostic/tool_governance.py` — budget enforcement logic
- `packages/starboard/starboard/infra/core/config.py` — environment variable configuration
- `packages/starboard/starboard/adapters/llm/` — token counting and cost calculation

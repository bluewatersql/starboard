---
title: Interruptible Reasoning (User Guide)
description: How to guide, correct, and redirect Starboard agents while they are working.
last_reviewed: 2026-03-24
status: current
---

# Interruptible Reasoning

> **Docs** > **User Guide** > **Interruptible Reasoning**
> Reading time: 6 minutes

## What You'll Learn

- What interruptible reasoning is and why it matters
- When and how to interrupt an agent mid-analysis
- How to provide corrections, context, and redirections
- What happens behind the scenes when you interrupt

---

## What Is Interruptible Reasoning?

Traditional AI assistants work in a strict request-response pattern: you ask a question, wait for the full answer, and then course-correct if needed. This wastes time when the agent heads in the wrong direction.

Starboard supports **interruptible reasoning**, which lets you steer the agent across a
conversation instead of only after a single request completes. In the CLI you do this
**turn by turn** in an interactive `--chat` session (or a named `--session`): after each
result you can add context, correct a wrong assumption, narrow the scope, or stop. The
agent retains the full prior context — including data it already fetched — so follow-ups
are cheap. You can:

- **Add context** -- Share information the agent does not have yet
- **Correct assumptions** -- Fix a wrong direction before the agent invests more time
- **Redirect focus** -- Ask the agent to concentrate on a specific area
- **Cancel** -- Stop the analysis entirely if it is no longer needed

```
Single request:                       Interactive --chat:

You: "Optimize my query"              You: "Optimize my query"
Agent: [works, returns 10 findings]   Agent: [returns initial findings]
You: run again, more specific         You: "Focus on indexes only"
Agent: [works again from scratch]     Agent: [continues with full context]
Agent: "Here are index findings"      Agent: "Here are index findings"
```

> **CLI is turn-based.** In the CLI you provide input between turns, not while a single
> turn is mid-execution. Fine-grained, mid-flight injection (interrupting the agent
> during a running turn) is available programmatically via the in-package SDK and the
> optional server — see [Programmatic use](#programmatic-mid-flight-injection).

---

## When to Interrupt

### Good Reasons to Interrupt

| Situation | What to Say |
|-----------|-------------|
| The agent is analyzing the wrong resource | "That is the wrong job. I meant job 67890, not 12345." |
| You have additional context | "The table was recently migrated from Hive to Unity Catalog." |
| You want to narrow the scope | "Focus only on the cluster configuration, skip the code review." |
| You realize the question was unclear | "To clarify, I want cost trends by team, not by warehouse." |
| The analysis is taking too long | "Just give me a quick summary of what you have found so far." |

### When Not to Interrupt

- The agent is making steady progress and you agree with the direction
- You want to wait for complete results before deciding next steps
- The task is fully specified and does not need course correction

!!! tip "Watch the tool calls"
    The CLI streams the agent's reasoning steps and tool calls to your terminal as they happen. This helps you decide whether to steer the next turn. If the agent is calling the right tools on the right resources, let it finish the turn.

---

## How to Interrupt

### Interactive chat (`--chat`)

Start an interactive session and steer the agent between turns:

```bash
starboard --chat
```

1. Ask your question and let the current turn complete (progress streams to the terminal).
2. Type a follow-up to add context, correct, narrow, or stop.
3. Because the session keeps full context, the agent builds on prior work instead of
   starting over.

### Named sessions (`--session`)

Continue a conversation across separate invocations by reusing a session name:

```bash
starboard --goal "Analyze job 12345" --session my-project
starboard --goal "Focus on the cluster configuration you mentioned" --session my-project
```

### Programmatic mid-flight injection

For true mid-turn interruption (sending input while a single turn is still executing),
use the in-package SDK — `from starboard.sdk import StarboardClient` — or the optional
server. This is how the `examples/` notebooks and MCP integrations drive the agent:

```python
session = await client.create_session()

# Start the analysis
r1 = await session.ask("Analyze job 12345")

# Redirect based on initial findings
r2 = await session.ask("Focus on the cluster configuration you mentioned")
```

---

## Examples of Effective Interrupts

### Example 1: Adding Missing Context

```
You: "Why is my ETL job slow?"

Agent: [resolving job...] [analyzing history...]
Agent: "I see the job runs on a fixed 2-worker cluster..."

You: "We recently doubled the input data volume. Could that be related?"

Agent: [replans - factors in data volume change]
Agent: "Yes, the input data doubled but the cluster size stayed the same.
        The job now processes 4TB instead of 2TB with only 2 workers..."
```

### Example 2: Correcting a Wrong Direction

```
You: "Optimize query abc-123"

Agent: [resolving query...] [analyzing execution plan...]
Agent: "I'm analyzing the JOIN strategy..."

You: "The JOINs are fine. The problem is the WHERE clause filtering."

Agent: [replans - focuses on filter predicates]
Agent: "Looking at the WHERE clause: the filter on 'created_date' is not
        leveraging the partition column. The table is partitioned by 'event_date'
        but you are filtering on 'created_date'..."
```

### Example 3: Narrowing Scope

```
You: "Run a full workspace health check"

Agent: [Phase 1: auditing products...] [Phase 2: running queries...]
Agent: "Found 8 active products. Running analysis across billing, compute,
        governance, and jobs..."

You: "I only need the billing and compute sections. Skip governance and jobs."

Agent: [adjusts scope]
Agent: "Understood. Focusing on billing and compute domains only..."
```

---

## What Happens When You Interrupt

When you send your next turn, the agent incorporates it like this:

1. **Read** -- The agent reads your new message alongside the retained session context.
2. **Evaluate** -- It decides how your input affects the current plan.
3. **Decide** -- It chooses one of four strategies:
   - **Continue** -- Your input is acknowledged but does not change the plan (e.g., "thanks for the info").
   - **Soft Replan** -- The agent adjusts its approach to incorporate your input while keeping prior work.
   - **Hard Replan** -- Your input fundamentally changes the direction. The agent starts fresh with new context.
   - **Cancel** -- You asked to stop. The agent wraps up with whatever it has so far.
4. **Resume** -- The agent continues (or stops) based on its decision.

!!! note "Prior work is not lost"
    Even during a hard replan, the agent retains data from tools it has already called. It does not re-fetch data it already has.

---

## Responding to Agent Questions

Sometimes the agent asks you a question instead of the other way around. This happens when:

- The agent encounters repeated errors and needs clarification
- Critical information is missing (e.g., which job ID to analyze)
- The request is ambiguous and could go in multiple directions
- The agent is stuck and cannot make progress

When the agent asks a question in an interactive `--chat` session, it pauses for your
answer — just type your reply at the prompt and press **Enter** (e.g. "The job ID is
12345"). In a single `--goal` run the agent proceeds with best-effort assumptions; if
you need to answer a clarifying question, re-run in `--chat` or continue with a
`--session` so the context is preserved.

---

## Next Steps

- [CLI Reference](cli.md) -- Command-line usage reference
- [Understanding Reports](understanding-reports.md) -- Interpret agent output
- [Common Tasks](../guides/COMMON_TASKS.md) -- Recipes including multi-turn sessions
- [Troubleshooting](troubleshooting.md) -- Common issues and solutions

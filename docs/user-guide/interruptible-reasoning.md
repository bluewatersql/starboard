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

Starboard supports **interruptible reasoning**, which means you can communicate with the agent while it is still thinking. You can:

- **Add context** -- Share information the agent does not have yet
- **Correct assumptions** -- Fix a wrong direction before the agent invests more time
- **Redirect focus** -- Ask the agent to concentrate on a specific area
- **Cancel** -- Stop the analysis entirely if it is no longer needed

```
Without interruption:                 With interruption:

You: "Optimize my query"              You: "Optimize my query"
Agent: [works for 2 minutes]          Agent: [starts working]
Agent: "Here are 10 findings"         Agent: [analyzing indexes...]
You: "I only care about indexes"      You: "Focus on indexes only"
Agent: [works for 2 more minutes]     Agent: [replans immediately]
Agent: "Here are index findings"      Agent: "Here are index findings"
                                              (saved 2 minutes!)
```

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
    In the Web UI, you can see which tools the agent is calling in real time. This helps you decide whether an interrupt is needed. If the agent is calling the right tools on the right resources, let it work.

---

## How to Interrupt

### In the Web UI

While the agent is working, the chat input remains active. Simply type your message and press **Enter**. The agent processes your input at its next checkpoint (typically after the current tool call completes).

1. Watch the agent's progress in the conversation panel. You will see thinking steps and tool calls appear in real time.
2. When you want to provide input, type your message in the chat box.
3. Press **Enter** to send. The message appears in the conversation immediately.
4. The agent acknowledges your input and adjusts its approach.

!!! note "Processing delay"
    The agent processes interrupts at checkpoint boundaries (between reasoning steps or tool calls). There may be a brief delay before your input takes effect.

### In the CLI

The CLI operates in a single-turn mode by default. For interruptible sessions, use the Web UI or the SDK.

With the SDK, you can use streaming to monitor progress and send follow-up messages:

```python
session = await client.create_session()

# Start the analysis
r1 = await session.ask("Analyze job 12345")

# Redirect based on initial findings
r2 = await session.ask("Focus on the cluster configuration you mentioned")
```

### Via the API

Send an interrupt to an active conversation using the inject endpoint:

```bash
curl -X POST http://localhost:8000/api/chat/conversations/{id}/inject-input \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "context_injection",
    "content": "Focus on partition pruning"
  }'
```

**Interrupt types:**

| Type | Purpose | Example |
|------|---------|---------|
| `context_injection` | Add information | "The table has 500M rows and is partitioned by date." |
| `replan_request` | Change approach | "Skip the code review and focus on cluster sizing." |
| `cancel_request` | Stop immediately | "Cancel -- I found the issue myself." |

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

When you send a message during an active analysis, the agent goes through this process:

1. **Checkpoint** -- The agent finishes its current tool call or reasoning step.
2. **Evaluate** -- The agent reads your input and decides how it affects the current plan.
3. **Decide** -- The agent chooses one of four strategies:
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

When the agent asks a question:

**Web UI:** The question appears in the chat. Type your answer and press **Enter**.

**API:** The agent emits a `UserInputRequestEvent`. Respond via the solicitation endpoint:

```bash
curl -X POST http://localhost:8000/api/chat/conversations/{id}/respond-to-solicitation \
  -H "Content-Type: application/json" \
  -d '{
    "content": "The job ID is 12345"
  }'
```

---

## Next Steps

- [Web Interface Guide](web-ui.md) -- Learn the full Web UI interface
- [CLI Reference](cli.md) -- Command-line usage reference
- [SDK Usage Guide](sdk.md) -- Programmatic access with streaming
- [Troubleshooting](troubleshooting.md) -- Common issues and solutions

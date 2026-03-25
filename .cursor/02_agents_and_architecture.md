# 02 – Agents & Architecture

Rules focused on agent-centric design, state machines, multi-agent coordination, and AI-specific engineering.

---

## Architecture & Design (Agent-Centric)

Layers (conceptual):

- domain/      – pure logic, deterministic, no I/O  
- adapters/    – I/O boundaries (LLM SDKs, DB, HTTP, FS)  
- agents/      – policies, tool routing, orchestration, conversation management  
- app/         – CLI/API/Streamlit/FastAPI entrypoints  
- infra/       – config, logging, DI/wiring, observability  
- tools/       – tool implementations with explicit schemas  

MUST: Dependency injection for all external services (LLM clients, stores, clocks).
MUST: Pure functions in domain; side effects only in adapters.
MUST: Separate prompting from tool calls; schemas live at boundaries.
SHOULD: Prefer immutable data (frozen dataclasses, NamedTuple, tuple).
SHOULD: Use explicit AgentState objects for multi-turn flows.

**GUIDELINE-001: MUST: All state store implementations must conform to the `StateStore` Protocol.** The Protocol defines `connect()`, `close()`, `get()`, `set()`, and `delete()` methods. New stores must implement all Protocol methods. Enforced by `tests/architecture/test_state_store_protocol_compliance.py`.

**GUIDELINE-002: MUST: The domain layer (`domain/`) must never import from the infrastructure layer (`infra/`).** Dependencies flow inward: infra → agents → domain. Domain code must remain pure and free of I/O concerns. Enforced by `tests/architecture/test_layer_violations.py`.

Example shape:

    class AgentState(TypedDict):
        conversation_history: tuple[Message, ...]
        working_memory: dict[str, Any]
        current_step: str  # or enum name

---

## Agent-Specific Patterns

MUST: Define explicit tool selection policies in agent module docstrings:  
- routing mode (round-robin, priority-based, LLM-driven)  
- fallback chains when tools fail or LLM refuses  
- timeout and retry strategies per tool  

MUST: Implement human-in-the-loop approval workflows for destructive actions (delete, payments, external API calls).  

SHOULD: Use enums + match/if-ladders for state machines in complex flows.  
SHOULD: Separate conversation context (message history) from agent working memory (scratchpad, intermediate results).

---

## Multi-Agent Coordination

SHOULD: Use explicit message-passing protocols (dataclasses or TypedDicts with type discriminators).  
SHOULD: Define shared context patterns (read-only projections, copy-on-write).  
MUST: Implement conflict resolution for concurrent actions on shared resources.  
MAY: Use orchestration patterns: sequential (pipeline), parallel (fan-out/fan-in), conditional (decision trees).

---

## AI-Specific Engineering

MUST: Provide a single LLMClient-style interface; do not leak provider SDKs into business logic.  
SHOULD: Implement adapters per provider (OpenAIAdapter, AnthropicAdapter, etc.).  

MUST: Measure tokens per call; track rolling totals per user/session; enforce caps via config.  
MUST: Handle rate limits, network faults, schema errors with bounded retries (max 3) and exponential backoff + jitter.  
MUST: Record metadata for each LLM call (model, temp, tokens, latency, cost, timestamp, trace_id).  

MUST: Implement moderation checks on inputs and outputs.  
MUST: Use allow-lists for sensitive operations; require explicit user confirmation for high-risk actions.  
SHOULD: Detect probable prompt injection attempts and refuse or escalate.

---

## RAG & Memory

MUST: Separate indexing vs retrieval:
- indexers/ – offline pipelines (chunking, embedding, indexing)  
- retrievers/ – online queries (search, rerank)  

MUST: No implicit writes during inference (retrieval is read-only).  
MUST: Evaluate retrieval quality using golden query sets.  

SHOULD: Use sensible chunking strategies (512–1024 tokens with small overlap, semantic boundaries).  
SHOULD: Keep embedding models pinned; reindex when changing models; track embedding drift.  

MUST: Vector store patterns:
- Namespace by tenant/user for isolation  
- Use metadata filters (date, category, permissions)  
- Prefer hybrid search (vector + keyword) where possible

---

## Reusability Patterns

SHOULD: Extract cross-cutting concerns (tracing, token counting, metrics) into decorators or helper functions.  
SHOULD: Keep orchestration steps small and composable with explicit inputs and outputs.  
SHOULD: Wrap tools behind simple, typed interfaces and adapt per provider behind the scenes.

# Multi-Turn Conversation Support: Design Specification

**Status:** Proposal  
**Branch:** `feat/multi-turn-conversations`  
**Date:** 2026-03-17  
**Scope:** CLI, Notebook/SDK, API adaptation  

---

## 1. Problem Statement

Today, each CLI invocation and notebook call is a **one-shot interaction**:

- The CLI generates a fresh `conversation_id = f"cli_{uuid4().hex[:12]}"` per run.
- It uses `InMemoryConversationStateManager`, so all state is lost when the process exits.
- There is no interactive REPL, no `--conversation-id` flag, and no persistence across invocations.
- There is no Python SDK for notebooks; they must use raw HTTP.

The **API already supports multi-turn conversations** — the web frontend creates a conversation once and sends subsequent messages to it. But the CLI and notebook surfaces don't expose this capability.

### Desired User Experience

```
# CLI — Interactive session
$ starboard chat
starboard> Help me tune query 1111-2222-3333-4444
  [Intent Router → Query Agent → Report]

starboard> Would this query benefit from liquid clustering or serverless?
  [Receives prior context → Intent Router → Agent → Contextual response]

starboard> How about running it as a streaming job instead?
  [Continues conversation → Cost/perf analysis with full context]

starboard> /exit

# CLI — Scripted continuation
$ starboard --goal "Analyze job 12345" --session my-project
$ starboard --goal "Can we convert it to streaming?" --session my-project

# Notebook — Python SDK
from starboard import StarboardClient
client = StarboardClient()
session = client.create_session()
r1 = session.ask("Help me tune query 1111-2222-3333-4444")
r2 = session.ask("Would liquid clustering help?")
r3 = session.ask("What code changes would I need?")
```

---

## 2. Current Architecture Assessment

### What Already Works (API Layer)

The server-side architecture **already handles multi-turn conversations correctly**:

| Component | Multi-Turn Support | Notes |
|---|---|---|
| `MultiAgentConversationManager.handle_message_stream()` | **Yes** | Calls `context_manager.load_or_create(conversation_id)` — loads existing context if found |
| `SharedAgentContext` | **Yes** | Accumulates `conversation_history`, `working_memory`, `agent_transitions`, discovered entities |
| `ContextManager.load_or_create()` | **Yes** | Reconstructs full context from storage |
| `ConversationRepository` | **Yes** | Persists `SharedAgentContext` to SQLite/Postgres via `StateStore` |
| `StateStore` (SQLite/Postgres) | **Yes** | Stores full conversation with messages and metadata in `data` JSON column |
| `SpecialistContextBuilder.build()` | **Yes** | Passes `conversation_history` from `SharedAgentContext.to_dict()` into specialist context |
| `StateInitializer.initialize()` | **Partial** | Builds handoff context from `conversation_history` but only uses last assistant message |
| Intent Router | **Partial** | Routes based on current message; doesn't consider conversation history for routing decisions |

### What's Missing (CLI + SDK Layer)

| Gap | Impact |
|---|---|
| CLI creates new `conversation_id` every run | No continuity between invocations |
| CLI uses `InMemoryConversationStateManager` | State lost on process exit |
| No interactive REPL mode | Can't have back-and-forth in single session |
| No `--session` / `--conversation-id` flag | Can't resume previous conversation |
| No Python SDK | Notebooks must use raw HTTP |
| `StateInitializer` only uses last assistant message | Follow-up agents miss earlier tool results and reasoning |
| Intent Router doesn't see conversation history | May misroute follow-up questions that reference prior context |

---

## 3. Design Principles

1. **Leverage existing architecture** — The server already supports multi-turn. Wire the CLI and SDK to use what exists.
2. **Session = Conversation** — A session is just a `conversation_id` that persists across calls.
3. **Storage-agnostic** — Sessions work with any `StateStore` backend (SQLite for CLI, Postgres for production).
4. **Progressive disclosure** — Simple one-shot usage remains the default; multi-turn is opt-in.
5. **Context window management** — As conversations grow, use summarization to stay within LLM context limits.
6. **Industry alignment** — Follow the same patterns as OpenAI Assistants API, LangChain memory, and Anthropic's conversation threading.

---

## 4. Architectural Design

### 4.1 Layer Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User Surfaces                                │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────────┐ │
│  │  CLI (REPL)  │  │  Python SDK      │  │  Web Frontend         │ │
│  │  starboard   │  │  StarboardClient │  │  (already works)      │ │
│  │  chat        │  │  session.ask()   │  │                       │ │
│  └──────┬───────┘  └────────┬─────────┘  └───────────┬───────────┘ │
└─────────┼──────────────────┼─────────────────────────┼─────────────┘
          │                  │                         │
          │ In-process       │ HTTP/SSE                │ HTTP/SSE
          │                  │                         │
┌─────────┼──────────────────┼─────────────────────────┼─────────────┐
│         ▼                  ▼                         ▼             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │            MultiAgentConversationManager                     │  │
│  │  • load_or_create(conversation_id) → SharedAgentContext      │  │
│  │  • handle_message_stream(conversation_id, message, mode)     │  │
│  │  • save_context(context) after each turn                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                     │
│  ┌───────────────────────────┼──────────────────────────────────┐  │
│  │                    ContextManager                             │  │
│  │  load_or_create() → reconstruct SharedAgentContext            │  │
│  │  • conversation_history (all prior turns)                     │  │
│  │  • working_memory (facts, entities, constraints)              │  │
│  │  • agent_transitions (handoff log)                            │  │
│  └───────────────────────────┼──────────────────────────────────┘  │
│                              │                                     │
│  ┌───────────────────────────┼──────────────────────────────────┐  │
│  │               ConversationStateManager                       │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │  │
│  │  │ InMemory    │  │ SQLite      │  │ Postgres            │  │  │
│  │  │ (REPL mode) │  │ (CLI disk)  │  │ (production)        │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### 4.2 Session Lifecycle

```
┌────────┐     ┌────────────┐     ┌────────────┐     ┌──────────┐
│  New   │────▶│   Active   │────▶│ Continued  │────▶│  Closed  │
│Session │     │  (Turn 1)  │     │ (Turn 2+)  │     │          │
└────────┘     └────────────┘     └────────────┘     └──────────┘
                                       │
                                       │ context grows
                                       ▼
                                ┌──────────────┐
                                │ Summarized   │
                                │ (Turn 10+)   │
                                └──────────────┘
```

---

## 5. Component Design

### 5.1 CLI: Interactive Chat Mode

**New command: `starboard chat`**

```
starboard chat [--session NAME] [--backend sqlite|inmemory] [--model MODEL]
```

| Flag | Default | Purpose |
|---|---|---|
| `--session NAME` | Auto-generated | Named session for resumption |
| `--backend` | `sqlite` | State store backend |
| `--model` | From config | LLM model override |

**Implementation approach:**

```python
# packages/starboard-cli/starboard_cli/cli/chat.py

class InteractiveChatSession:
    """Interactive REPL for multi-turn conversations."""

    def __init__(
        self,
        manager: MultiAgentConversationManager,
        conversation_id: str,
        display: ChatDisplay,
    ):
        self._manager = manager
        self._conversation_id = conversation_id
        self._display = display

    async def run(self) -> None:
        """Main REPL loop."""
        self._display.show_welcome(self._conversation_id)

        while True:
            user_input = await self._display.prompt()

            if self._is_exit_command(user_input):
                self._display.show_goodbye(self._conversation_id)
                break

            if self._is_meta_command(user_input):
                await self._handle_meta_command(user_input)
                continue

            async for event in self._manager.handle_message_stream(
                conversation_id=self._conversation_id,
                user_message=user_input,
                mode=self._mode,
            ):
                self._display.render_event(event)
```

**Key behaviors:**

- Session persists to SQLite by default (survives process restart).
- `--session my-project` resumes a named session.
- Meta commands: `/history`, `/context`, `/new`, `/exit`, `/sessions`.
- Ctrl+C gracefully interrupts current agent reasoning.
- Conversation state is saved after every turn (already happens in `handle_message_stream`).

**Enhancement to existing `starboard --goal` mode:**

```
starboard --goal "Follow-up question" --session my-project
```

This enables scripted multi-turn from shell scripts or CI pipelines without needing the REPL.

### 5.2 CLI: Session Persistence

**New: `SessionManager`** — thin wrapper for naming and listing sessions.

```python
# packages/starboard-cli/starboard_cli/sessions/session_manager.py

class SessionManager:
    """Manage named CLI sessions backed by a StateStore."""

    def __init__(self, state_store: StateStore):
        self._store = state_store

    async def get_or_create(
        self, session_name: str | None = None
    ) -> str:
        """Get existing conversation_id for name, or create new one."""

    async def list_sessions(self) -> list[SessionInfo]:
        """List all sessions with metadata."""

    async def delete_session(self, session_name: str) -> bool:
        """Delete a session and its conversation data."""
```

**Session naming strategy:**

- `--session my-project` → `conversation_id = "cli_session_my-project"`
- No `--session` flag → `conversation_id = f"cli_{uuid4().hex[:12]}"` (current behavior, one-shot)
- `starboard chat` without `--session` → auto-generated name, shown to user

**Storage location:**

- Default: `~/.starboard/sessions.db` (SQLite)
- Configurable via `STARBOARD_SESSION_DB` env var or `--session-db` flag

### 5.3 Python SDK (for Notebooks)

**New package: `starboard-sdk`** (or added to `starboard-core`)

```python
# packages/starboard-sdk/starboard_sdk/client.py

class StarboardClient:
    """Python SDK for Starboard AI Agent.

    Supports both direct (in-process) and HTTP modes.

    Example (Databricks notebook):
        client = StarboardClient.from_env()
        session = client.create_session(name="etl-optimization")
        
        r1 = session.ask("Help me tune query 1111-2222-3333-4444")
        print(r1.report)
        
        r2 = session.ask("Would liquid clustering help?")
        print(r2.report)
        
        r3 = session.ask("What code changes do I need?")
        print(r3.report)
        
        # Resume later
        session = client.resume_session("etl-optimization")
        r4 = session.ask("How about running as streaming instead?")
    """

    @classmethod
    def from_env(cls) -> "StarboardClient":
        """Create client from environment variables."""

    @classmethod
    def from_config(cls, config: StarboardConfig) -> "StarboardClient":
        """Create client from explicit config."""

    def create_session(
        self,
        name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> "ConversationSession":
        """Create a new conversation session."""

    def resume_session(self, name: str) -> "ConversationSession":
        """Resume an existing session by name."""

    def list_sessions(self) -> list[SessionInfo]:
        """List available sessions."""


class ConversationSession:
    """A multi-turn conversation session.

    Maintains conversation_id and passes it to every call,
    ensuring the server loads prior context.
    """

    def __init__(
        self,
        conversation_id: str,
        manager: MultiAgentConversationManager,
    ):
        self._conversation_id = conversation_id
        self._manager = manager

    async def ask(
        self,
        message: str,
        mode: OptimizationMode = OptimizationMode.BALANCED,
    ) -> AgentResponse:
        """Send a message and get a response.

        The server automatically loads prior conversation context
        from the SharedAgentContext stored for this conversation_id.
        """

    async def ask_stream(
        self,
        message: str,
        mode: OptimizationMode = OptimizationMode.BALANCED,
    ) -> AsyncIterator[StreamingEvent]:
        """Send a message and stream events."""

    @property
    def history(self) -> list[Message]:
        """Get conversation history."""

    @property
    def session_id(self) -> str:
        """Get the underlying conversation_id."""
```

**Transport modes:**

| Mode | When | How |
|---|---|---|
| **In-process** | Notebook on same machine, CLI | Direct `MultiAgentConversationManager` calls (current CLI pattern) |
| **HTTP** | Remote server, Databricks notebook | `httpx` + SSE to `/api/chat/` endpoints |

The SDK auto-detects: if `STARBOARD_API_URL` is set, use HTTP; otherwise, bootstrap in-process.

### 5.4 Context Window Management

As conversations grow, raw history will exceed LLM context windows. This requires a **conversation memory strategy**.

**Tiered approach (industry standard):**

```
Turn 1-5:    Full history passed to LLM (all messages verbatim)
Turn 6-10:   Recent 3 turns full + summarized earlier turns
Turn 10+:    Rolling summary + recent 2 turns full + working memory
```

**Implementation: `ConversationContextStrategy`**

```python
# packages/starboard-server/starboard_server/agents/state/context_strategy.py

class ConversationContextStrategy:
    """Manage what context is passed to the LLM as conversations grow.

    Implements a tiered strategy:
    - Short conversations: full history
    - Medium conversations: recent turns + summary of earlier
    - Long conversations: rolling summary + recent window
    """

    def __init__(
        self,
        full_history_threshold: int = 5,
        summary_threshold: int = 10,
        recent_window: int = 3,
    ):
        ...

    def prepare_context(
        self,
        shared_context: SharedAgentContext,
    ) -> ContextWindow:
        """Prepare context for LLM consumption.

        Returns a ContextWindow with:
        - system_context: Summary of earlier conversation
        - recent_messages: Recent turn messages (verbatim)
        - working_memory: Accumulated facts, entities, constraints
        """

    async def summarize_history(
        self,
        messages: list[Message],
        llm_client: BaseLLMClient,
    ) -> str:
        """Generate a summary of conversation history for context compression."""
```

**Integration point:** `StateInitializer.initialize()` will use `ConversationContextStrategy` instead of the current `build_handoff_context()` which only grabs the last assistant message.

### 5.5 Intent Router Enhancement

The Intent Router needs to be conversation-context-aware for follow-up routing:

```python
# Current: routes based on current message only
route = await intent_router.classify(user_message)

# Enhanced: routes with conversation context
route = await intent_router.classify(
    user_message,
    conversation_context=ConversationRoutingContext(
        previous_agent="query",
        previous_domain="query_optimization",
        discovered_entities={"statement_id": "1111-2222-3333-4444"},
        turn_number=2,
        conversation_summary="User asked about query optimization for statement 1111-2222-3333-4444. Agent provided optimization report.",
    ),
)
```

**Routing rules for follow-ups:**

1. **Same-domain follow-up** ("Can we add an index?"): Route to same agent with full context.
2. **Cross-domain follow-up** ("What about the cluster config?"): Route to new agent with handoff context.
3. **Continuation** ("Tell me more" / "What else?"): Route to same agent with continuation flag.
4. **New topic** ("Now analyze job 5678"): Clear context, route as new query.

The `SharedAgentContext` already has `get_current_agent()`, `get_last_intent()`, and `get_discovered_entities()` — these should feed into the router's classification prompt.

---

## 6. Data Flow: Multi-Turn Example

```
Turn 1: "Help me tune query 1111-2222-3333-4444"
─────────────────────────────────────────────────
1. CLI/SDK calls manager.handle_message_stream(conv_id, message, mode)
2. ContextManager.load_or_create(conv_id) → new SharedAgentContext
3. User message added to context.conversation_history
4. Context saved (user message persisted)
5. IntentRouter classifies → "query" domain
6. AgentHandoffCoordinator records transition: router → query
7. SpecialistContextBuilder builds context dict (includes conversation_history)
8. QueryAgent runs: tools discover statement_id, tables, metrics
9. EventContextUpdater tracks entities in shared_context
10. Assistant message + metadata added to context.conversation_history
11. Context saved (full turn persisted: user msg + assistant msg + working_memory)

Turn 2: "Would this query benefit from liquid clustering or serverless?"
─────────────────────────────────────────────────────────────────────────
1. CLI/SDK calls manager.handle_message_stream(same conv_id, message, mode)
2. ContextManager.load_or_create(conv_id) → LOADS existing context
   ├── conversation_history: [user_msg_1, assistant_msg_1]
   ├── working_memory: {discovered_entities: {statement_id: ...}, facts: [...]}
   └── agent_transitions: [router → query]
3. User message added → conversation_history now has 3 messages
4. Context saved
5. IntentRouter classifies WITH conversation context
   ├── Sees previous domain was "query"
   ├── Sees discovered entities (statement_id, tables)
   └── Routes to appropriate agent (query or cluster, depending on analysis)
6. SpecialistContextBuilder passes full context including prior history
7. StateInitializer builds enriched input with ConversationContextStrategy
   ├── Includes summary of Turn 1 findings
   ├── Includes discovered entities and constraints
   └── Agent has full context of what was already analyzed
8. Agent responds contextually (knows the specific query, prior findings)
9. Context saved with accumulated history
```

---

## 7. File Changes Summary

### New Files

| File | Purpose |
|---|---|
| `packages/starboard-cli/starboard_cli/cli/chat.py` | Interactive REPL chat command |
| `packages/starboard-cli/starboard_cli/sessions/session_manager.py` | Named session management |
| `packages/starboard-cli/starboard_cli/display/chat_display.py` | REPL display formatting |
| `packages/starboard-sdk/` (new package) | Python SDK for notebooks |
| `packages/starboard-server/.../agents/state/context_strategy.py` | Context window management |
| `tests/unit/cli/test_chat.py` | REPL tests |
| `tests/unit/cli/test_session_manager.py` | Session management tests |
| `tests/unit/agents/state/test_context_strategy.py` | Context strategy tests |

### Modified Files

| File | Change |
|---|---|
| `packages/starboard-cli/starboard_cli/cli/main.py` | Add `--session` flag, `chat` subcommand, use persistent StateStore |
| `packages/starboard-server/.../agents/domain/state_initializer.py` | Use `ConversationContextStrategy` instead of raw `build_handoff_context()` |
| `packages/starboard-server/.../agents/routing/intent_router.py` | Accept conversation context for follow-up routing |
| `packages/starboard-server/.../agents/conversation/multi_agent_manager.py` | Pass conversation context to intent router |

### Unchanged (Already Works)

| Component | Why It Works |
|---|---|
| `SharedAgentContext` | Already accumulates history, memory, transitions |
| `ContextManager` | Already loads/creates based on conversation_id |
| `ConversationRepository` | Already persists/loads full context |
| `StateStore` (SQLite/Postgres) | Already stores conversations |
| `SpecialistContextBuilder` | Already passes conversation_history |
| API endpoints | Already support multi-turn via conversation_id |

---

## 8. Implementation Phases

### Phase 1: CLI Session Persistence (Foundation)
**Effort: ~2 days**

1. Add `--session NAME` flag to `starboard --goal`
2. When `--session` is provided, use `SQLiteStateStore` instead of `InMemoryConversationStateManager`
3. Map session names to conversation_ids via a lightweight sessions table
4. Reuse conversation_id across invocations → `load_or_create` automatically loads prior context

This alone enables multi-turn from shell scripts:
```bash
starboard --goal "Analyze query X" --session proj1
starboard --goal "Would liquid clustering help?" --session proj1
```

### Phase 2: Interactive REPL
**Effort: ~3 days**

1. Add `starboard chat` subcommand with REPL loop
2. Implement `ChatDisplay` for rich terminal output (tool progress, reports)
3. Add meta commands (`/history`, `/new`, `/sessions`, `/exit`)
4. Support Ctrl+C for graceful interrupt
5. Session auto-persistence (every turn saved to SQLite)

### Phase 3: Context Window Management
**Effort: ~2 days**

1. Implement `ConversationContextStrategy` with tiered summarization
2. Update `StateInitializer` to use strategy instead of `build_handoff_context()`
3. Add conversation summary generation (LLM-based)
4. Test with long conversations (10+ turns)

### Phase 4: Intent Router Context Awareness
**Effort: ~2 days**

1. Enhance intent router to accept conversation context
2. Add follow-up detection (same-domain, cross-domain, continuation, new-topic)
3. Update routing prompt to consider prior agent and discovered entities
4. Golden tests for follow-up routing scenarios

### Phase 5: Python SDK
**Effort: ~3 days**

1. Create `starboard-sdk` package with `StarboardClient` and `ConversationSession`
2. Support both in-process and HTTP transport
3. Provide `ask()` (blocking) and `ask_stream()` (async) methods
4. Example notebooks for Databricks
5. SDK documentation

---

## 9. Industry Alignment

| Pattern | Our Approach | Industry Examples |
|---|---|---|
| **Thread/Session ID** | `conversation_id` passed on every call | OpenAI Assistants `thread_id`, LangChain `session_id`, Anthropic `conversation_id` |
| **Server-side state** | `SharedAgentContext` persisted in StateStore | OpenAI stores thread state, LangChain memory backends |
| **Context window management** | Tiered: full → summary + recent → rolling summary | LangChain `ConversationSummaryBufferMemory`, GPT context window strategies |
| **Working memory** | Accumulated facts, entities, constraints across turns | LangChain `ConversationEntityMemory`, Autogen shared state |
| **Session resumption** | Named sessions with `--session` / `resume_session()` | ChatGPT conversation list, Claude project conversations |
| **REPL interface** | `starboard chat` interactive mode | GitHub Copilot Chat, `aider`, `claude` CLI |

---

## 10. Key Design Decisions

### Decision 1: In-Process vs HTTP for CLI

**Choice: In-process (current pattern)**

The CLI already runs the agent stack in-process. We keep this for:
- Zero deployment overhead for CLI users
- Lower latency (no HTTP roundtrip)
- Works offline with local models

The SDK supports both modes for flexibility.

### Decision 2: SQLite vs File-Based Session Storage

**Choice: SQLite (via existing `SQLiteStateStore`)**

- Already implemented and tested
- Handles concurrent access correctly
- Stores full conversation data (messages, working_memory, transitions)
- Location: `~/.starboard/sessions.db`

### Decision 3: Summarization Strategy

**Choice: LLM-based summarization with fallback**

- Primary: Use the same LLM to generate conversation summaries
- Fallback: Extractive summary (last N assistant messages, key entities)
- Trigger: When conversation depth exceeds threshold (configurable, default 5 turns)

### Decision 4: SDK Package Location

**Choice: New `packages/starboard-sdk/` package**

- Clean separation of concerns
- Depends on `starboard-core` only (for models)
- HTTP transport has no dependency on `starboard-server`
- In-process transport optionally depends on `starboard-server`

---

## 11. Testing Strategy

| Test Type | What | Coverage |
|---|---|---|
| **Unit** | SessionManager, ConversationContextStrategy, ChatDisplay | 100% |
| **Integration** | Multi-turn flow through CLI → Manager → StateStore | Key paths |
| **Golden** | Follow-up intent routing prompts | All follow-up patterns |
| **E2E** | Full REPL session with mock LLM | Happy path + edge cases |
| **Contract** | SDK ↔ API contract | All SDK methods |

### Key Test Scenarios

1. **Basic follow-up**: Turn 1 analyzes query → Turn 2 asks about optimization
2. **Cross-domain handoff**: Turn 1 analyzes query → Turn 2 asks about cluster
3. **Session resumption**: Start session, exit, resume, ask follow-up
4. **Long conversation**: 15+ turns with summarization kicking in
5. **New topic in session**: User changes topic entirely (context clearing)
6. **Concurrent sessions**: Multiple named sessions active simultaneously

---

## 12. Migration & Backward Compatibility

- **Existing `starboard --goal`** continues to work exactly as today (one-shot, no session).
- **Existing API clients** are unaffected (they already pass `conversation_id`).
- **No breaking changes** to any existing interface.
- **New features are additive**: `--session` flag, `chat` subcommand, SDK package.

# starboard-core Module Reference

**Package**: `starboard-core`  
**Purpose**: Module-level documentation for all components

---

## Overview

This document provides detailed information about each module in the starboard-core package.

---

## Models

### Conversation Models (`models/conversation.py`)

Core conversation data structures used throughout the platform.

#### Message

```python
@dataclass(frozen=True)
class Message:
    """Single message in a conversation."""
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    timestamp: datetime
    tool_calls: list[dict]
    metadata: dict[str, Any]
```

**Purpose**: Immutable message representation  
**Key Features**:
- Frozen dataclass (thread-safe)
- Automatic timestamp generation
- Serialization support (to_dict/from_dict)
- Support for tool calls

**Usage**:
```python
from starboard_core.models.conversation import Message

message = Message(
    role="user",
    content="Optimize my query",
    metadata={"query_id": "123"}
)
```

#### Episode

```python
class Episode(BaseModel):
    """A single conversation exchange (user message + agent response)."""
    id: str
    conversation_id: str
    user_message: Message
    agent_message: Message | None
    tool_calls: list[dict]
    created_at: datetime
```

**Purpose**: Represents one complete interaction cycle  
**Key Features**:
- Pydantic model with validation
- Links user input with agent response
- Tracks all tool calls in the episode

#### Conversation

```python
class Conversation(BaseModel):
    """Complete conversation with multiple episodes."""
    id: str
    user_id: str
    workspace_id: str | None
    title: str | None
    episodes: list[Episode]
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]
```

**Purpose**: Container for full conversation history  
**Key Features**:
- Tracks all episodes chronologically
- User and workspace association
- Extensible metadata

**Common Operations**:
```python
# Add episode
conversation.episodes.append(episode)

# Get latest episode
latest = conversation.episodes[-1]

# Count messages
total_messages = sum(2 for e in conversation.episodes)  # user + agent
```

---

### Memory Models (`models/memory.py`)

Long-term memory structures for facts, episodes, and user profiles.

#### Episode (Memory)

```python
@dataclass(frozen=True)
class Episode:
    """Memory episode - summary of past conversation."""
    id: str
    user_id: str
    summary: str
    key_points: list[str]
    timestamp: datetime
    embedding: list[float] | None
```

**Purpose**: Compressed representation of past conversations  
**Use Case**: Semantic search over conversation history

#### Fact

```python
@dataclass(frozen=True)
class Fact:
    """Extracted fact or knowledge."""
    id: str
    user_id: str
    fact_type: str
    content: str
    source: str
    confidence: float
    learned_at: datetime
    embedding: list[float] | None
```

**Purpose**: Store learned information about user or domain  
**Use Cases**:
- User preferences ("prefers cost over performance")
- Domain knowledge ("uses warehouse X for analytics")
- Context ("working on project Y")

#### UserProfile

```python
class UserProfile(BaseModel):
    """User preferences and settings."""
    user_id: str
    preferences: dict[str, Any]
    usage_stats: dict[str, Any]
    created_at: datetime
    updated_at: datetime
```

**Purpose**: Persistent user configuration and stats  
**Key Features**:
- Flexible preferences dict
- Usage tracking
- Automatic update timestamps

---

## Domain Models

### Context Types (`domain/models/context_types.py`)

Execution context structures for agents and tools.

**Key Types**:
- `AgentContext`: Context passed to agents
- `ToolContext`: Context passed to tools
- `ExecutionState`: State tracking during execution

**Purpose**: Provide consistent context across operations

---

### Databricks Models (`domain/models/databricks.py`)

Domain representations of Databricks entities.

**Key Models**:
- Warehouse configurations
- Cluster specifications
- Job definitions
- Query metadata

**Design Note**: These are domain models, not API DTOs. They represent business concepts, not API responses.

---

### LLM Schemas (`domain/models/llm_schemas.py`, `llm.py`)

Schemas for LLM interactions.

**Components**:
- Request/response schemas
- Function call definitions
- Tool schemas
- Prompt templates

**Validation**: All LLM I/O is validated with Pydantic

---

### Recommendations (`domain/models/recommendations.py`)

Types for optimization recommendations.

**Hierarchy**:
```
Recommendation (base)
├── QueryRecommendation
├── JobRecommendation
├── ResourceRecommendation
└── CostRecommendation
```

**Common Fields**:
- `title`: Short description
- `description`: Detailed explanation
- `impact`: Expected benefit
- `effort`: Implementation complexity
- `priority`: High/Medium/Low

---

### Report Types (`domain/models/report_types.py`)

Structures for generated reports.

**Components**:
- Report sections
- Formatting options
- Output types (Markdown, HTML, JSON)

---

## Ports (Protocols)

### StateStore (`ports/state_store.py`)

```python
class StateStore(Protocol):
    """Abstract interface for conversation state persistence."""
    
    async def save_conversation(self, conversation: Conversation) -> str:
        """Persist conversation."""
        ...
    
    async def load_conversation(self, conversation_id: str) -> Conversation:
        """Retrieve conversation by ID."""
        ...
```

**Purpose**: Define persistence interface without implementation  
**Implementations**: SQLiteStateStore, PostgresStateStore, InMemoryStateStore

**Design Pattern**: Protocol (structural subtyping, no inheritance required)

---

### MemoryStore (`ports/memory_store.py`)

```python
class MemoryStore(Protocol):
    """Abstract interface for long-term memory."""
    
    # Episodic Memory
    async def store_episode(self, episode: Episode) -> str: ...
    async def recall_episodes(self, user_id: str, query: str) -> list[Episode]: ...
    
    # Semantic Memory
    async def store_fact(self, fact: Fact) -> str: ...
    async def query_facts(self, user_id: str, query: SemanticQuery) -> list[Fact]: ...
    
    # Profile
    async def get_profile(self, user_id: str) -> UserProfile: ...
    async def update_profile(self, profile: UserProfile) -> None: ...
```

**Memory Types**:
- **Episodic**: Past conversation summaries (semantic search)
- **Semantic**: Extracted facts and knowledge
- **Profile**: User preferences and settings

---

### CacheStore (`ports/cache_store.py`)

```python
class CacheStore(Protocol):
    """Abstract interface for caching."""
    
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
```

**Purpose**: Simple caching interface  
**Implementations**: Redis, In-memory, Null (no-op)

---

## Repositories

### ConversationRepository (`repositories/conversation.py`)

```python
class ConversationRepository:
    """High-level conversation operations."""
    
    def __init__(self, state_store: StateStore):
        self._store = state_store
    
    async def get_or_create(self, user_id: str) -> Conversation:
        """Get active conversation or create new one."""
        ...
    
    async def add_episode(self, conversation_id: str, episode: Episode) -> None:
        """Add episode to conversation."""
        ...
```

**Purpose**: Provide rich, domain-focused API  
**Pattern**: Repository pattern built on protocols

**Benefits**:
- Hides storage complexity
- Returns domain objects
- Manages relationships

---

### MemoryRepository (`repositories/memory.py`)

```python
class MemoryRepository:
    """High-level memory operations."""
    
    def __init__(self, memory_store: MemoryStore):
        self._store = memory_store
    
    async def remember(self, user_id: str, content: str) -> None:
        """Store new memory."""
        ...
    
    async def recall(self, user_id: str, query: str) -> list[Episode]:
        """Retrieve relevant memories."""
        ...
```

**Purpose**: Simplify memory operations  
**Features**:
- Semantic search over memories
- Automatic embedding generation
- Confidence scoring

---

### CacheManager (`repositories/cache.py`)

```python
class CacheManager:
    """High-level cache operations."""
    
    async def cache_tool_result(
        self,
        tool_name: str,
        params: dict,
        result: Any,
        ttl: int = 300
    ) -> None:
        """Cache tool execution result."""
        ...
    
    async def get_cached_result(
        self,
        tool_name: str,
        params: dict
    ) -> Any | None:
        """Retrieve cached tool result."""
        ...
```

**Purpose**: Domain-specific caching utilities  
**Features**:
- Smart key generation
- TTL management
- Tool result caching

---

## Domain Services

### Admin Service (`domain/services/admin.py`)

Administrative operations for system management.

**Operations**:
- User management
- System configuration
- Data cleanup
- Health checks

**Design**: Pure business logic, no I/O

---

## Testing

All modules have corresponding test files in `tests/unit/`:

```
tests/unit/
├── models/
│   ├── test_conversation.py
│   └── test_memory.py
├── ports/
│   └── test_protocols.py
└── repositories/
    ├── test_conversation_repo.py
    ├── test_memory_repo.py
    └── test_cache.py
```

**Testing Strategy**:
- Unit tests only (no I/O)
- Fake implementations for protocols
- 100% coverage target
- Fast execution (<1ms per test)

---

## Import Guide

### Recommended Imports

```python
# Models
from starboard_core.models.conversation import Conversation, Episode, Message
from starboard_core.models.memory import Fact, UserProfile

# Ports
from starboard_core.ports.state_store import StateStore
from starboard_core.ports.memory_store import MemoryStore
from starboard_core.ports.cache_store import CacheStore

# Repositories
from starboard_core.repositories.conversation import ConversationRepository
from starboard_core.repositories.memory import MemoryRepository
from starboard_core.repositories.cache import CacheManager

# Domain models
from starboard_core.domain.models.recommendations import QueryRecommendation
```

### Anti-Patterns

❌ Don't import implementation details:
```python
# BAD - these are in other packages
from starboard.adapters.state.sqlite import SQLiteStateStore
```

✅ Use protocols instead:
```python
# GOOD - depend on protocol
def my_function(store: StateStore):
    ...
```

---

## Extension Guide

### Adding a New Model

1. Create in appropriate module (models/ or domain/models/)
2. Use Pydantic BaseModel or frozen dataclass
3. Add comprehensive docstring
4. Include serialization if needed
5. Write unit tests

### Adding a New Port

1. Create protocol in ports/
2. Define async methods
3. Document all parameters and return types
4. Keep methods focused and minimal

### Adding a New Repository

1. Create in repositories/
2. Depend on port(s), not implementations
3. Provide high-level, domain-focused API
4. Write tests with fake implementations

---

## Related Documentation

- [Architecture](./architecture.md) - Package architecture
- [System Architecture](../../architecture/SYSTEM_ARCHITECTURE.md) - Overall system design
- [Testing Guide](../../TESTING.md) - Testing strategies

---

## Quick Reference

| Component | Location | Purpose |
|-----------|----------|---------|
| Message | models/conversation.py | Single message |
| Episode | models/conversation.py | One interaction |
| Conversation | models/conversation.py | Full conversation |
| Fact | models/memory.py | Learned knowledge |
| StateStore | ports/state_store.py | Persistence interface |
| MemoryStore | ports/memory_store.py | Memory interface |
| ConversationRepository | repositories/conversation.py | Conversation operations |

---

**Last Updated**: 2025-12-02


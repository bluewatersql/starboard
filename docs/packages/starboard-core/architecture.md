# starboard-core Architecture

**Package**: `starboard-core`  
**Version**: 0.1.0  
**Purpose**: Pure domain logic, shared types, and abstractions  
**Last Updated**: 2025-12-02

---

## Overview

`starboard-core` is the foundation package of the Starboard AI Agent platform. It contains **pure domain logic with zero I/O dependencies**, making it the most stable and reusable component of the system.

### Design Philosophy

1. **Dependency Inversion**: Core depends on nothing; everything depends on core
2. **Pure Domain Logic**: No I/O operations, no side effects
3. **Immutability**: Frozen dataclasses and immutable structures
4. **Type Safety**: Comprehensive type hints on all public APIs
5. **Explicit Abstractions**: Protocol-based interfaces (ports)

---

## Package Structure

```
starboard-core/
├── starboard_core/
│   ├── domain/              # Domain models and business logic
│   │   ├── models/          # Domain DTOs and Pydantic models
│   │   │   ├── context_types.py    # Context and state types
│   │   │   ├── databricks.py       # Databricks domain models
│   │   │   ├── llm_schemas.py      # LLM request/response schemas
│   │   │   ├── llm.py              # LLM types and enums
│   │   │   ├── recommendations.py  # Recommendation types
│   │   │   └── report_types.py     # Report generation types
│   │   ├── analyzers/       # Domain analyzers
│   │   ├── transformers/    # Data transformers
│   │   ├── services/        # Domain services (pure logic, minimal)
│   │   └── utils/           # Domain utilities
│   ├── foundations/         # Core foundation types
│   │   ├── models.py               # Foundation model types
│   │   └── protocols.py            # Foundation protocols
│   ├── models/              # Shared data models
│   │   ├── conversation.py         # Conversation, Episode, Message
│   │   └── memory.py               # Facts, UserProfile, memory types
│   ├── ports/               # Abstract interfaces (hexagonal architecture)
│   │   ├── cache_store.py          # Cache abstraction
│   │   ├── memory_store.py         # Memory storage abstraction
│   │   └── state_store.py          # State persistence abstraction
│   ├── rag/                 # RAG utilities
│   └── repositories/        # Repository pattern implementations
│       ├── cache.py                # Cache manager
│       ├── conversation.py         # Conversation repository
│       └── memory.py               # Memory repository
└── tests/
    └── unit/                # Unit tests (no I/O)
```

---

## Architecture Diagram

![starboard-core Architecture](../../diagrams/generated/packages/starboard-core-architecture.png)

### Layer Responsibilities

| Layer | Purpose | Dependencies |
|-------|---------|--------------|
| **domain/models/** | Pure domain types, DTOs, enums | Pydantic only |
| **domain/services/** | Business logic, calculations | domain/models |
| **models/** | Shared data structures | Pydantic only |
| **ports/** | Abstract interfaces (protocols) | domain/models |
| **repositories/** | High-level data access patterns | ports, models |

---

## Key Components

### 1. Domain Models (`domain/models/`)

Pure domain types representing business concepts.

#### Context Types (`context_types.py`)

Defines context and state structures for agent operations:

- `AgentContext`: Execution context for agents
- `ToolContext`: Context passed to tools
- `ExecutionState`: State tracking for operations

**Key Characteristics**:
- Immutable (frozen dataclasses)
- No I/O operations
- Type-safe with strict validation

#### Databricks Models (`databricks.py`)

Domain representations of Databricks entities:

- Warehouse configurations
- Cluster specifications
- Job definitions
- Query metadata

**Purpose**: Provide type-safe, validated models for Databricks data without coupling to the Databricks SDK.

#### LLM Schemas (`llm_schemas.py`, `llm.py`)

Schemas for LLM interactions:

- Request/response schemas
- Function call definitions
- Tool schemas
- Prompt templates

**Design**: Pydantic models ensure LLM I/O is strictly validated.

#### Recommendations (`recommendations.py`)

Types for optimization recommendations:

- `Recommendation`: Base recommendation type
- `QueryRecommendation`: SQL optimization suggestions
- `JobRecommendation`: Job tuning suggestions
- `ResourceRecommendation`: Compute resource suggestions

#### Report Types (`report_types.py`)

Structures for generated reports:

- Report sections
- Formatting options
- Output types

---

### 2. Shared Models (`models/`)

Cross-cutting data models used throughout the system.

#### Conversation Model (`conversation.py`)

Core conversation data structures:

```python
@dataclass(frozen=True)
class Message:
    """Immutable message in a conversation."""
    role: str
    content: str
    metadata: dict
    timestamp: datetime

@dataclass(frozen=True)
class Episode:
    """A single conversation exchange (user + agent)."""
    id: str
    user_message: Message
    agent_message: Message
    tool_calls: tuple[ToolCall, ...]
    
class Conversation:
    """Complete conversation with multiple episodes."""
    id: str
    user_id: str
    episodes: list[Episode]
    created_at: datetime
```

**Design Pattern**: Immutable by default using frozen dataclasses.

#### Memory Model (`memory.py`)

Long-term memory structures:

- `Episode`: Conversation summaries
- `Fact`: Extracted knowledge
- `UserProfile`: User preferences and context
- `SemanticQuery`: Query structure for semantic search

---

### 3. Ports (`ports/`)

Abstract interfaces following the **Ports and Adapters** (Hexagonal Architecture) pattern.

#### StateStore Protocol (`state_store.py`)

```python
class StateStore(Protocol):
    """Abstract interface for conversation state persistence."""
    
    async def save_conversation(self, conversation: Conversation) -> str:
        """Persist conversation state."""
        ...
    
    async def load_conversation(self, conversation_id: str) -> Conversation:
        """Retrieve conversation by ID."""
        ...
```

**Purpose**: Define what the domain needs without dictating how it's implemented.

**Implementations** (in other packages):
- `SQLiteStateStore` (starboard)
- `PostgresStateStore` (starboard)
- `InMemoryStateStore` (starboard)

#### MemoryStore Protocol (`memory_store.py`)

```python
class MemoryStore(Protocol):
    """Abstract interface for long-term memory."""
    
    async def store_episode(self, episode: Episode) -> str: ...
    async def recall_episodes(self, user_id: str, query: str) -> list[Episode]: ...
    async def store_fact(self, fact: Fact) -> str: ...
    async def query_facts(self, user_id: str, query: SemanticQuery) -> list[Fact]: ...
```

**Memory Types**:
- **Episodic**: Past conversation summaries
- **Semantic**: Extracted facts and knowledge
- **Profile**: User preferences and settings

#### CacheStore Protocol (`cache_store.py`)

```python
class CacheStore(Protocol):
    """Abstract interface for caching."""
    
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
```

---

### 4. Repositories (`repositories/`)

High-level data access patterns built on top of ports.

#### ConversationRepository (`conversation.py`)

Provides rich conversation operations:

```python
class ConversationRepository:
    """Repository for conversation operations."""
    
    def __init__(self, state_store: StateStore):
        self._store = state_store
    
    async def get_or_create(self, user_id: str) -> Conversation:
        """Get active conversation or create new one."""
        ...
    
    async def add_episode(self, conversation_id: str, episode: Episode) -> None:
        """Add new episode to conversation."""
        ...
```

**Pattern**: Depends on `StateStore` protocol, not concrete implementations.

#### MemoryRepository (`memory.py`)

Manages long-term memory operations:

```python
class MemoryRepository:
    """Repository for memory operations."""
    
    def __init__(self, memory_store: MemoryStore):
        self._store = memory_store
    
    async def remember(self, user_id: str, content: str) -> None:
        """Store new memory."""
        ...
    
    async def recall(self, user_id: str, query: str) -> list[Episode]:
        """Retrieve relevant memories."""
        ...
```

#### CacheManager (`cache.py`)

Provides caching utilities:

```python
class CacheManager:
    """High-level cache operations."""
    
    async def cache_tool_result(self, tool_name: str, params: dict, result: Any) -> None: ...
    async def get_cached_result(self, tool_name: str, params: dict) -> Any | None: ...
```

---

## Data Flow

![Data Flow Diagram](../../diagrams/generated/packages/starboard-core-dataflow.png)

### Repository Pattern Flow

1. **Client** → `ConversationRepository.get_or_create(user_id)`
2. **Repository** → `StateStore.load_conversation(id)`
3. **StateStore** → Database/Storage (implementation-specific)
4. **Return** ← Domain models (type-safe)

**Key Benefit**: Client code works with domain types, completely isolated from storage details.

---

## Dependency Rules

### External Dependencies (Minimal)

From `pyproject.toml`:

```toml
dependencies = [
    "pydantic>=2.12.3",        # Data validation
    "typing-extensions>=4.14.1", # Type hints
    "orjson>=3.11.4",          # Fast JSON (no I/O)
    "pyyaml>=6.0.3",           # Config parsing (no I/O)
]
```

### Internal Dependencies

```
domain/services → domain/models
models → (none - pure data)
ports → models
repositories → ports + models
```

**Critical Rule**: NO dependencies on I/O libraries (httpx, aiohttp, databricks-sdk, etc.)

---

## Design Patterns

### 1. Hexagonal Architecture (Ports & Adapters)

```
┌─────────────────────────────────────┐
│         Domain (Core)               │
│  ┌─────────────────────────────┐   │
│  │  Models & Business Logic    │   │
│  └──────────┬──────────────────┘   │
│             │                       │
│  ┌──────────▼──────────────────┐   │
│  │  Ports (Protocols)          │   │
│  │  - StateStore               │   │
│  │  - MemoryStore              │   │
│  │  - CacheStore               │   │
│  └──────────┬──────────────────┘   │
└─────────────┼───────────────────────┘
              │
    ┌─────────┴─────────┐
    │    Adapters       │
    │  (Other Packages) │
    └───────────────────┘
```

### 2. Repository Pattern

Repositories provide high-level, domain-focused APIs:

- Hide storage complexity
- Return domain objects
- Handle data mapping
- Manage transactions (if needed)

### 3. Immutability

Prefer frozen dataclasses:

```python
@dataclass(frozen=True)
class Message:
    """Immutable - cannot be modified after creation."""
    role: str
    content: str
```

**Benefits**:
- Thread-safe by default
- Prevents accidental mutations
- Easier to reason about

### 4. Protocol-Based Abstraction

Use `Protocol` instead of ABC:

```python
from typing import Protocol

class StateStore(Protocol):
    """Interface definition without inheritance."""
    async def save(...) -> None: ...
```

**Benefits**:
- Structural subtyping (duck typing)
- No runtime overhead
- Better for testing (easy mocking)

---

## Testing Strategy

### Unit Tests Only

Since this package has no I/O:
- All tests are fast (<1ms each)
- No mocking of external services
- 100% coverage achievable

### Test Structure

```
tests/unit/
├── models/
│   ├── test_conversation.py
│   └── test_memory.py
├── repositories/
│   └── test_conversation_repo.py
└── ports/
    └── test_protocols.py
```

### Testing Repositories

Repositories are tested with **in-memory fake implementations**:

```python
class FakeStateStore:
    """In-memory implementation for testing."""
    def __init__(self):
        self._storage = {}
    
    async def save_conversation(self, conv: Conversation) -> str:
        self._storage[conv.id] = conv
        return conv.id

def test_conversation_repository():
    store = FakeStateStore()
    repo = ConversationRepository(store)
    # Test repository logic
```

---

## Usage Examples

### Creating Domain Models

```python
from starboard_core.models.conversation import Message, Episode, Conversation
from datetime import datetime

# Create immutable message
message = Message(
    role="user",
    content="How can I optimize this query?",
    metadata={"query_id": "123"},
    timestamp=datetime.now(),
)

# Message is frozen - this would raise error:
# message.content = "new content"  # FrozenInstanceError
```

### Using Repositories

```python
from starboard_core.repositories.conversation import ConversationRepository

# Inject storage implementation
repo = ConversationRepository(state_store)

# Get or create conversation
conversation = await repo.get_or_create(user_id="user123")

# Add episode
episode = Episode(...)
await repo.add_episode(conversation.id, episode)
```

### Implementing a Port

```python
from starboard_core.ports.state_store import StateStore
from starboard_core.models.conversation import Conversation

class PostgresStateStore:
    """Concrete implementation of StateStore protocol."""
    
    def __init__(self, connection_string: str):
        self.pool = create_pool(connection_string)
    
    async def save_conversation(self, conversation: Conversation) -> str:
        async with self.pool.acquire() as conn:
            # Database-specific logic
            await conn.execute(...)
        return conversation.id
    
    async def load_conversation(self, conversation_id: str) -> Conversation:
        # Implementation...
        pass
```

---

## Extension Points

### Adding New Domain Models

1. Create model in `domain/models/<category>.py`
2. Use Pydantic for validation
3. Keep immutable (frozen dataclasses)
4. Add comprehensive docstrings
5. Write unit tests

### Adding New Ports

1. Define protocol in `ports/<name>_store.py`
2. Document all methods thoroughly
3. Keep methods async-capable
4. Avoid implementation details

### Adding New Repositories

1. Create in `repositories/<name>.py`
2. Depend on ports, not implementations
3. Provide high-level, domain-focused API
4. Write tests with fake implementations

---

## Common Patterns

### Pattern 1: Validation at Boundaries

```python
from pydantic import BaseModel, Field, validator

class QueryRequest(BaseModel):
    """Validated query request."""
    query: str = Field(..., min_length=1)
    warehouse_id: str = Field(..., pattern=r'^[a-z0-9-]+$')
    
    @validator('query')
    def validate_query(cls, v):
        if 'DROP TABLE' in v.upper():
            raise ValueError("DROP statements not allowed")
        return v
```

### Pattern 2: Immutable Updates

```python
from dataclasses import replace

# Create new instance with changes
updated_conversation = replace(
    conversation,
    updated_at=datetime.now(),
)
```

### Pattern 3: Type-Safe Enums

```python
from enum import Enum

class OptimizationMode(str, Enum):
    """Optimization strategy."""
    ONLINE = "online"
    OFFLINE = "offline"
    HYBRID = "hybrid"
```

---

## Performance Considerations

### Memory Usage

- Frozen dataclasses have minimal overhead
- Use `tuple` instead of `list` where possible
- Pydantic models are memory-efficient

### Validation Overhead

- Pydantic validation happens once at creation
- Frozen dataclasses prevent re-validation
- Use `model_validate()` for performance-critical paths

---

## Troubleshooting

### Common Issues

**Issue**: `FrozenInstanceError` when trying to modify model

**Solution**: Use `replace()` to create new instance

```python
from dataclasses import replace
new_obj = replace(frozen_obj, field=new_value)
```

**Issue**: Protocol not recognized as implementing interface

**Solution**: Ensure all protocol methods are implemented

---

## Related Documentation

- [starboard Architecture](../starboard/architecture.md) - How this is used
- [System Architecture](../../architecture/SYSTEM_ARCHITECTURE.md) - Overall system design
- [Package Integration](../../integration/PACKAGE_INTEGRATION.md) - Cross-package patterns

---

## Changelog

### Version 0.1.0 (2025-12-02)

- Initial documentation
- Complete architecture overview
- Design patterns documented

---

**Next**: [Module Documentation](./modules.md)


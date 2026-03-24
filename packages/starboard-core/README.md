# Starboard Core

Core domain models and shared types for the Starboard AI Agent platform.

## Overview

`starboard-core` contains pure domain logic with no I/O dependencies:
- **Domain Models**: Pydantic DTOs, data classes
- **Type Definitions**: Protocols, type aliases
- **Shared Exceptions**: Common exception types

## Installation

```bash
pip install starboard-core
```

## Usage

```python
from starboard_core.domain.models import OptimizationMode

# Use domain models
mode = OptimizationMode.ONLINE
```

## Package Structure

```
starboard_core/
├── domain/              # Pure domain logic
│   ├── models/          # Domain DTOs (context, Databricks, LLM, recommendations)
│   ├── services/        # Domain services (admin operations)
│   └── utils/           # Domain utilities
├── models/              # Shared data models
│   ├── conversation.py  # Message, Episode, Conversation
│   └── memory.py        # Facts, UserProfile, memory types
├── ports/               # Abstract interfaces (protocols)
│   ├── state_store.py   # State persistence interface
│   ├── memory_store.py  # Memory storage interface
│   └── cache_store.py   # Caching interface
└── repositories/        # Repository pattern implementations
    ├── conversation.py  # Conversation operations
    ├── memory.py        # Memory operations
    └── cache.py         # Cache operations
```

See [complete architecture documentation](../../docs/packages/starboard-core/architecture.md) for detailed information.

## Design Principles

- **Pure Domain Logic**: No I/O operations
- **Immutable by Default**: Use frozen dataclasses
- **Explicit Types**: Full type hints

## Documentation

### Package Documentation

- **[Package Overview](../../docs/packages/starboard-core/index.md)** - Quick reference and links
- **[Architecture](../../docs/packages/starboard-core/architecture.md)** - Complete architecture guide (650+ lines)
- **[Module Reference](../../docs/packages/starboard-core/modules.md)** - Detailed module documentation

### Diagrams

- **[Architecture Diagram](../../docs/diagrams/generated/packages/starboard-core-architecture.png)** - Package structure
- **[Data Flow](../../docs/diagrams/generated/packages/starboard-core-dataflow.png)** - Repository pattern flow

### Project Documentation

- **[Main Project README](../../README.md)** - Overall project information
- **[System Architecture](../../docs/ARCHITECTURE.md)** - System design
- **[starboard-server README](../starboard-server/README.md)** - Backend server (uses this package)
- **[starboard-cli README](../starboard-cli/README.md)** - CLI tool (uses this package)

## Related Packages

This is the foundation package used by:
- **starboard-server**: Backend server and agents
- **starboard-cli**: Command-line interface

All packages in the monorepo depend on `starboard-core` for shared domain models and types.


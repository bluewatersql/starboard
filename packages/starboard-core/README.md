# Starboard Core

Core domain models and shared types for the Starboard AI Agent platform.

## Overview

`starboard-core` contains pure domain logic with no I/O dependencies:
- **Domain Models**: Pydantic DTOs, data classes
- **Type Definitions**: Protocols, type aliases
- **Shared Exceptions**: Common exception types

## Installation

```bash
pip install starboard-kernel
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

See [complete architecture documentation](../../docs/architecture.md) for detailed information.

## Design Principles

- **Pure Domain Logic**: No I/O operations
- **Immutable by Default**: Use frozen dataclasses
- **Explicit Types**: Full type hints

## Documentation

### Package Documentation

- **[Architecture](../../docs/architecture.md)** - Complete architecture guide

### Project Documentation

- **[Main Project README](../../README.md)** - Overall project information
- **[System Architecture](../../docs/architecture.md)** - System design
- **[starboard README](../starboard/README.md)** - Full experience package (CLI + MCP server + agents) that builds on this kernel

## Related Packages

This is the foundation package used by:
- **starboard-server**: Backend server and agents
- **starboard-cli**: Command-line interface

All packages in the monorepo depend on `starboard-core` for shared domain models and types.


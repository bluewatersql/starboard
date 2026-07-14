# starboard-core

Pure domain logic, prompts, shared types, and Spark log parsing with no external dependencies.

## Overview

`starboard-core` is the foundation package providing pure domain logic with **zero I/O dependencies**. It uses hexagonal architecture (ports & adapters) to define clean abstractions that other packages implement.

It also includes the Spark event log parser (previously a separate `starboard-log-parser` package), providing high-performance streaming parsing of Spark event logs from multiple sources (local, DBFS, Unity Catalog Volumes, HTTP/S, S3).

![Architecture Diagram](../../diagrams/generated/packages/starboard-core-architecture.png)

## Quick Links

- **[Architecture Documentation](./architecture.md)** - Complete architectural overview
- **[Data Flow](../../diagrams/generated/packages/starboard-core-dataflow.png)** - Repository pattern flow

## Key Components

### Log Parser (`log_parser/`)
- **SparkApplication**: Immutable parsed application model (jobs, stages, tasks, executors, DAG)
- **Event Parser**: Streaming parser for 30+ Spark event types (~50,000 events/second, O(1) memory)
- **Storage Loaders**: Local, DBFS, Unity Catalog Volumes, HTTP/S, S3
- **Credential Providers**: Protocol-based authentication (pluggable)

### Domain Models (`domain/models/`)
- **Context Types**: Agent and tool execution contexts
- **Databricks Models**: Domain representations of Databricks entities
- **LLM Schemas**: Request/response schemas for LLM interactions
- **Recommendations**: Optimization recommendation types
- **Report Types**: Report generation structures

### Shared Models (`models/`)
- **Conversation**: Message, Episode, Conversation structures
- **Memory**: Facts, UserProfile, Episodes for long-term memory

### Ports (`ports/`)
Protocol-based abstractions:
- **StateStore**: Conversation state persistence interface
- **MemoryStore**: Long-term memory storage interface
- **CacheStore**: Caching interface

### Repositories (`repositories/`)
High-level data access patterns:
- **ConversationRepository**: Rich conversation operations
- **MemoryRepository**: Memory management operations
- **CacheManager**: Caching utilities

## Design Principles

1. **Dependency Inversion**: Core depends on nothing
2. **Pure Domain Logic**: No I/O, no side effects
3. **Immutability**: Frozen dataclasses
4. **Type Safety**: Comprehensive type hints
5. **Explicit Abstractions**: Protocol-based interfaces

## Architecture

See [Complete Architecture Documentation](./architecture.md) for detailed information on:
- Package structure and layer responsibilities
- Design patterns (Hexagonal, Repository, Immutability)
- Data flow and dependency rules
- Testing strategy
- Usage examples and common patterns


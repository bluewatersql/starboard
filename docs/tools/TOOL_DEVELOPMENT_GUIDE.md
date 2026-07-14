# Tool Development Guide

**Version**: 1.0  
**Last Updated**: 2025-12-02  
**Target Audience**: Developers adding new tools

---

## Table of Contents

1. [Overview](#overview)
2. [Tool Architecture](#tool-architecture)
3. [Creating a New Tool](#creating-a-new-tool)
4. [Tool Interface Requirements](#tool-interface-requirements)
5. [Testing Strategy](#testing-strategy)
6. [Registration Process](#registration-process)
7. [Best Practices](#best-practices)
8. [Examples](#examples)

---

## Overview

This guide explains how to develop new tools for the Starboard AI Agent. Tools are the primary way agents interact with external systems (Databricks, databases, APIs).

### When to Create a New Tool

Create a new tool when you need to:
- Fetch data from an external system
- Perform a specific analysis or calculation
- Execute an action (create resource, update config, etc.)
- Provide domain-specific functionality

### When NOT to Create a Tool

Don't create a tool if:
- Functionality can be handled by existing tools
- It's purely domain logic (put in `domain/` layer)
- It's a one-off operation (use service layer)

---

## Tool Architecture

Tools follow a three-layer architecture:

```
┌─────────────────────────────────────┐
│    Adapter Layer (tools/adapters/)  │
│  - Clean interface for LLM agents   │
│  - Type validation (Pydantic)       │
│  - Returns structured dicts         │
└─────────────────┬───────────────────┘
                  ↓
┌─────────────────────────────────────┐
│    Service Layer (tools/services/)   │
│  - Orchestration & coordination     │
│  - Combines multiple operations     │
│  - Error handling & retries         │
└─────────────────┬───────────────────┘
                  ↓
┌─────────────────────────────────────┐
│    Domain Layer (tools/domain/)      │
│  - Pure business logic              │
│  - No I/O dependencies              │
│  - 100% testable                    │
└─────────────────────────────────────┘
```

---

## Creating a New Tool

### Step 1: Define Domain Logic

Create pure business logic in `tools/domain/`:

**File**: `packages/starboard-server/starboard/tools/domain/example/analyzer.py`

```python
"""Domain logic for example analysis."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisResult:
    """Result of example analysis."""
    
    score: float
    recommendations: list[str]
    metadata: dict[str, Any]


def analyze_example_data(data: dict[str, Any]) -> AnalysisResult:
    """
    Pure function to analyze example data.
    
    Args:
        data: Input data dictionary
    
    Returns:
        Analysis result with score and recommendations
    
    Examples:
        >>> result = analyze_example_data({"value": 42})
        >>> result.score
        0.85
    """
    # Pure logic - no I/O, no side effects
    score = calculate_score(data)
    recommendations = generate_recommendations(score)
    
    return AnalysisResult(
        score=score,
        recommendations=recommendations,
        metadata={"input_keys": list(data.keys())}
    )
```

**Key Points**:
- Pure functions (no I/O)
- Immutable data structures (`frozen=True`)
- Complete type hints
- Docstrings with examples
- 100% testable

---

### Step 2: Create Service Layer

Create service in `tools/services/`:

**File**: `packages/starboard-server/starboard/tools/services/example_service.py`

```python
"""Service layer for example tool operations."""

from typing import Any

from starboard.adapters.apis.databricks import DatabricksAPI
from starboard.tools.domain.example.analyzer import (
    analyze_example_data,
    AnalysisResult,
)


class ExampleService:
    """Service for example tool operations."""
    
    def __init__(
        self,
        api: DatabricksAPI,
        events: EventEmitter | None = None,
    ):
        """
        Initialize example service.
        
        Args:
            api: Databricks API client
            events: Optional event emitter for telemetry
        """
        self.api = api
        self.events = events
    
    async def analyze_resource(
        self,
        resource_id: str
    ) -> AnalysisResult:
        """
        Analyze a resource with complete error handling.
        
        Args:
            resource_id: Resource identifier
        
        Returns:
            Analysis result
        
        Raises:
            ResourceNotFoundError: Resource doesn't exist
            ToolExecutionError: API call failed
        """
        # Emit event (optional)
        if self.events:
            self.events.emit("tool_start", tool_name="analyze_resource")
        
        try:
            # Fetch data from external system
            data = await self.api.get_resource(resource_id)
            
            # Call domain logic (pure function)
            result = analyze_example_data(data)
            
            # Emit completion event
            if self.events:
                self.events.emit(
                    "tool_end",
                    tool_name="analyze_resource",
                    success=True
                )
            
            return result
            
        except Exception as e:
            if self.events:
                self.events.emit(
                    "tool_end",
                    tool_name="analyze_resource",
                    success=False,
                    error=str(e)
                )
            raise ToolExecutionError(f"Failed to analyze resource: {e}") from e
```

**Key Points**:
- Orchestrates external calls
- Calls domain logic
- Handles errors
- Emits telemetry events
- Retries with exponential backoff (if needed)

---

### Step 3: Create Adapter (Tool Interface)

Create adapter in `tools/adapters/`:

**File**: `packages/starboard-server/starboard/tools/adapters/example_tools.py`

```python
"""Adapter interface for example tools."""

from typing import Any

from starboard.adapters.apis.databricks import DatabricksAPI
from starboard.infra.observability.events import EventEmitter
from starboard.tools.services.example_service import ExampleService


class ExampleTools:
    """
    Tool adapter for example operations.
    
    Provides clean, parameter-based interface optimized for LLM reasoning.
    """
    
    def __init__(
        self,
        api: DatabricksAPI,
        events: EventEmitter | None = None,
    ):
        """
        Initialize example tools.
        
        Args:
            api: Databricks API client
            events: Optional event emitter
        """
        self.service = ExampleService(api=api, events=events)
    
    async def analyze_resource(
        self,
        resource_id: str,
        include_recommendations: bool = True,
    ) -> dict[str, Any]:
        """
        Analyze a resource and return structured results.
        
        Args:
            resource_id: Resource identifier to analyze
            include_recommendations: Include recommendations in output
        
        Returns:
            Dictionary with analysis results:
                - score: Analysis score (0.0-1.0)
                - recommendations: List of recommendation strings
                - metadata: Additional metadata
        
        Examples:
            >>> tools = ExampleTools(api)
            >>> result = await tools.analyze_resource("resource-123")
            >>> result["score"]
            0.85
        """
        # Call service layer
        analysis = await self.service.analyze_resource(resource_id)
        
        # Convert to dict for LLM consumption
        output = {
            "score": analysis.score,
            "metadata": analysis.metadata,
        }
        
        # Conditionally include recommendations
        if include_recommendations:
            output["recommendations"] = analysis.recommendations
        
        return output
```

**Key Points**:
- Clean signature: `async def tool(**kwargs) -> dict[str, Any]`
- No state/context parameters (injected at creation)
- Returns structured dictionaries
- Docstrings with examples
- Type hints on all parameters

---

## Tool Interface Requirements

### Signature

```python
async def tool_name(
    required_param: str,
    optional_param: int | None = None,
    flag: bool = False,
) -> dict[str, Any]:
    """Tool description."""
```

**Requirements**:
- Must be `async` (even if not doing I/O)
- Returns `dict[str, Any]` (JSON-serializable)
- All parameters have type hints
- Optional parameters have defaults

### Return Value

```python
return {
    "result_key": value,          # Primary results
    "metadata": {...},            # Optional metadata
    "warnings": [...]             # Optional warnings
}
```

**Requirements**:
- JSON-serializable (no custom objects)
- Flat structure preferred (avoid deep nesting)
- Consistent keys across similar tools
- Include metadata for debugging

### Error Handling

```python
try:
    result = await external_call()
    return {"result": result}
except ResourceNotFoundError:
    return {
        "error": "Resource not found",
        "error_type": "ResourceNotFoundError",
        "retryable": False
    }
except ToolExecutionError as e:
    raise  # Let framework handle retries
```

---

## Testing Strategy

### Unit Tests (Domain Layer)

**File**: `tests/unit/tools/domain/test_example_analyzer.py`

```python
"""Unit tests for example analyzer."""

import pytest

from starboard.tools.domain.example.analyzer import analyze_example_data


def test_analyze_example_data_basic():
    """Test basic analysis with valid data."""
    data = {"value": 42, "name": "test"}
    
    result = analyze_example_data(data)
    
    assert result.score >= 0.0
    assert result.score <= 1.0
    assert isinstance(result.recommendations, list)
    assert "input_keys" in result.metadata


def test_analyze_example_data_edge_cases():
    """Test edge cases."""
    # Empty data
    result = analyze_example_data({})
    assert result.score == 0.0
    
    # Large data
    result = analyze_example_data({"value": 10000})
    assert result.score <= 1.0


@pytest.mark.parametrize("value,expected_score", [
    (0, 0.0),
    (50, 0.5),
    (100, 1.0),
])
def test_analyze_example_data_parametrized(value, expected_score):
    """Test with various input values."""
    result = analyze_example_data({"value": value})
    assert result.score == pytest.approx(expected_score, rel=0.1)
```

**Coverage Target**: 100% for domain layer

---

### Integration Tests (Service Layer)

**File**: `tests/integration/tools/services/test_example_service.py`

```python
"""Integration tests for example service."""

import pytest

from starboard.tools.services.example_service import ExampleService


@pytest.mark.asyncio
async def test_analyze_resource_success(mock_api):
    """Test successful resource analysis."""
    # Setup mock
    mock_api.get_resource.return_value = {"value": 42}
    
    # Create service
    service = ExampleService(api=mock_api)
    
    # Execute
    result = await service.analyze_resource("resource-123")
    
    # Verify
    assert result.score > 0
    mock_api.get_resource.assert_called_once_with("resource-123")


@pytest.mark.asyncio
async def test_analyze_resource_not_found(mock_api):
    """Test resource not found error."""
    mock_api.get_resource.side_effect = ResourceNotFoundError()
    
    service = ExampleService(api=mock_api)
    
    with pytest.raises(ToolExecutionError):
        await service.analyze_resource("nonexistent")
```

**Coverage Target**: 80%+ for service layer

---

### Tool Tests (Adapter Layer)

**File**: `tests/unit/tools/adapters/test_example_tools.py`

```python
"""Tests for example tool adapter."""

import pytest

from starboard.tools.adapters.example_tools import ExampleTools


@pytest.mark.asyncio
async def test_analyze_resource_full_output(mock_service):
    """Test tool with full output."""
    # Setup mock service
    mock_service.analyze_resource.return_value = Mock(
        score=0.85,
        recommendations=["Optimize X", "Review Y"],
        metadata={"key": "value"}
    )
    
    # Create tools
    tools = ExampleTools(api=mock_api)
    tools.service = mock_service
    
    # Execute
    result = await tools.analyze_resource(
        "resource-123",
        include_recommendations=True
    )
    
    # Verify structure
    assert "score" in result
    assert "recommendations" in result
    assert "metadata" in result
    assert isinstance(result, dict)  # JSON-serializable


@pytest.mark.asyncio
async def test_analyze_resource_minimal_output(mock_service):
    """Test tool with minimal output."""
    mock_service.analyze_resource.return_value = Mock(score=0.85)
    
    tools = ExampleTools(api=mock_api)
    tools.service = mock_service
    
    result = await tools.analyze_resource(
        "resource-123",
        include_recommendations=False
    )
    
    assert "score" in result
    assert "recommendations" not in result  # Excluded
```

---

## Registration Process

### Step 1: Define Tool Metadata

**File**: `packages/starboard-server/starboard/agents/tools/registry.py`

```python
from starboard.agents.tools.tool_registry import ToolMetadata

ANALYZE_RESOURCE_METADATA = ToolMetadata(
    name="analyze_resource",
    description="Analyze a Databricks resource for optimization opportunities",
    parameters_schema={
        "type": "object",
        "properties": {
            "resource_id": {
                "type": "string",
                "description": "Resource identifier to analyze"
            },
            "include_recommendations": {
                "type": "boolean",
                "description": "Include recommendations in output",
                "default": True
            }
        },
        "required": ["resource_id"]
    },
    domains=["cluster", "query"],  # Which agents can use this
    category="analysis"
)
```

---

### Step 2: Register Tool

**File**: `packages/starboard-server/starboard/agents/tools/tool_factory.py`

```python
def create_tool_registry(...) -> ToolRegistry:
    """Create and populate tool registry."""
    
    # ... existing tool registration ...
    
    # Register new tool
    example_tools = ExampleTools(api=api, events=events)
    
    registry.register_native_tool(
        tool_callable=example_tools.analyze_resource,
        metadata=ANALYZE_RESOURCE_METADATA
    )
    
    return registry
```

---

### Step 3: Test Registration

```python
def test_tool_registered():
    """Verify tool is registered correctly."""
    registry = create_tool_registry(...)
    
    # Check tool exists
    assert registry.has_tool("analyze_resource")
    
    # Check metadata
    metadata = registry.get_metadata("analyze_resource")
    assert metadata.name == "analyze_resource"
    assert "cluster" in metadata.domains
```

---

## Best Practices

### 1. Naming Conventions

**Tools**:
- Use verb prefixes: `get_*`, `analyze_*`, `fetch_*`, `create_*`
- Be specific: `get_warehouse_config` not `get_config`
- Avoid abbreviations: `analyze_query_plan` not `analyze_qp`

**Parameters**:
- Use full words: `statement_id` not `stmt_id`
- Boolean flags: `include_*`, `enable_*`, `allow_*`
- Quantities: `max_*`, `limit`, `count`

---

### 2. Error Handling

**Always**:
- Catch specific exceptions
- Provide helpful error messages
- Include context (resource ID, parameters)
- Set `retryable` flag correctly

**Never**:
- Catch generic `Exception` without re-raising
- Swallow errors silently
- Return success with hidden errors

---

### 3. Performance

**Optimize**:
- Batch operations when possible
- Cache expensive calls (with TTL)
- Use connection pooling
- Implement timeouts

**Monitor**:
- Track execution duration
- Log slow operations (> 5s)
- Emit performance metrics
- Set SLOs (< 10s for most tools)

---

### 4. Documentation

**Required**:
- Docstring with description
- All parameters documented
- Return value structure described
- At least one example

**Recommended**:
- Use cases section
- Error conditions listed
- Performance characteristics
- Related tools mentioned

---

### 5. Versioning

When changing tool behavior:
- Create new tool for breaking changes: `analyze_resource_v2`
- Use optional parameters for backward compatibility
- Deprecate old tools (don't delete immediately)
- Update metadata with deprecation notice

---

## Examples

### Example 1: Simple Data Fetcher

```python
# Domain
def parse_cluster_config(raw_config: dict) -> ClusterConfig:
    """Pure parsing logic."""
    return ClusterConfig(
        cluster_id=raw_config["cluster_id"],
        node_count=raw_config["num_workers"],
        ...
    )

# Service
class ClusterService:
    async def get_cluster_config(self, cluster_id: str) -> ClusterConfig:
        raw = await self.api.get_cluster(cluster_id)
        return parse_cluster_config(raw)

# Adapter
class ComputeTools:
    async def get_cluster_config(self, cluster_id: str) -> dict[str, Any]:
        config = await self.service.get_cluster_config(cluster_id)
        return {
            "cluster_id": config.cluster_id,
            "node_count": config.node_count,
            ...
        }
```

---

### Example 2: Tool with Complex Logic

```python
# Domain
def calculate_cost_recommendations(
    usage_data: list[UsageRecord],
    threshold: float = 0.5
) -> list[Recommendation]:
    """Complex cost analysis logic."""
    # Pure function - testable without I/O
    ...

# Service
class CostService:
    async def analyze_costs(
        self,
        start_date: str,
        end_date: str,
        threshold: float
    ) -> list[Recommendation]:
        # Fetch data
        usage = await self.api.get_usage(start_date, end_date)
        
        # Transform
        records = [UsageRecord.from_api(u) for u in usage]
        
        # Analyze (domain logic)
        recommendations = calculate_cost_recommendations(records, threshold)
        
        return recommendations

# Adapter
class FinOpsTools:
    async def analyze_costs(
        self,
        start_date: str,
        end_date: str,
        threshold: float = 0.5
    ) -> dict[str, Any]:
        recs = await self.service.analyze_costs(
            start_date, end_date, threshold
        )
        
        return {
            "recommendations": [r.to_dict() for r in recs],
            "total_count": len(recs),
            "threshold_used": threshold
        }
```

---

## Checklist

Before submitting a new tool:

- [ ] Domain logic in `tools/domain/` (pure functions)
- [ ] Service layer in `tools/services/` (orchestration)
- [ ] Adapter in `tools/adapters/` (clean interface)
- [ ] Unit tests (100% coverage for domain)
- [ ] Integration tests (80%+ coverage for service)
- [ ] Tool metadata defined
- [ ] Tool registered in factory
- [ ] Docstrings complete with examples
- [ ] Type hints on all functions
- [ ] Error handling implemented
- [ ] Telemetry events emitted
- [ ] Performance tested (< 10s typical)
- [ ] Reviewed by team

---

## Related Documentation

- [Tool Catalog](./TOOL_CATALOG.md) - All available tools
- [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md) - Overall design
- [Testing Guide](../TESTING.md) - Testing strategies

---

**Last Updated**: 2025-12-02  
**Version**: 1.0


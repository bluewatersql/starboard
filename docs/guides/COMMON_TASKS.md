# Common Development Tasks

**Version**: 1.1  
**Last Updated**: 2025-12-06  
**Audience**: Contributors

---

## Table of Contents

1. [Adding a New Tool](#adding-a-new-tool)
2. [Adding a New Agent](#adding-a-new-agent)
3. [Modifying Prompts](#modifying-prompts)
4. [Adding an API Endpoint](#adding-an-api-endpoint)
5. [Updating Domain Models](#updating-domain-models)
6. [Debugging Agent Behavior](#debugging-agent-behavior)
7. [Writing Tests](#writing-tests)
8. [Updating Documentation](#updating-documentation)

---

## Adding a New Tool

**Time**: 1-2 hours  
**Difficulty**: ⭐⭐⭐ (Medium)

### Overview

Tools are how agents interact with external systems. Follow the three-layer architecture: Domain → Service → Adapter.

### Step 1: Define Domain Logic

Create pure business logic with no I/O dependencies.

**File**: `packages/starboard-server/starboard_server/tools/domain/compute/cost_analyzer.py`

```python
"""Domain logic for cost analysis."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CostAnalysis:
    """Cost analysis result."""
    
    total_cost: float
    period_start: datetime
    period_end: datetime
    top_consumers: list[dict[str, float]]
    recommendations: list[str]


def analyze_costs(
    usage_records: list[dict],
    threshold: float = 0.1
) -> CostAnalysis:
    """
    Analyze cost data and generate recommendations.
    
    Args:
        usage_records: List of usage records with cost data
        threshold: Threshold for identifying high consumers (0.0-1.0)
    
    Returns:
        Cost analysis with recommendations
    
    Examples:
        >>> records = [{"resource": "cluster-1", "cost": 100}]
        >>> result = analyze_costs(records)
        >>> result.total_cost
        100.0
    """
    # Pure logic - testable without I/O
    total = sum(r["cost"] for r in usage_records)
    
    # Identify top consumers
    sorted_records = sorted(
        usage_records,
        key=lambda r: r["cost"],
        reverse=True
    )
    top_consumers = sorted_records[:5]
    
    # Generate recommendations
    recommendations = []
    for record in top_consumers:
        if record["cost"] / total > threshold:
            recommendations.append(
                f"Consider optimizing {record['resource']} "
                f"(${record['cost']:.2f}, {record['cost']/total*100:.1f}%)"
            )
    
    return CostAnalysis(
        total_cost=total,
        period_start=datetime.now(),
        period_end=datetime.now(),
        top_consumers=[{r["resource"]: r["cost"]} for r in top_consumers],
        recommendations=recommendations
    )
```

### Step 2: Create Service Layer

Add orchestration and external I/O.

**File**: `packages/starboard-server/starboard_server/tools/services/cost_service.py`

```python
"""Service layer for cost analysis."""

from datetime import datetime

from starboard_server.adapters.apis.databricks import DatabricksAPI
from starboard_server.infra.observability.events import EventEmitter
from starboard_server.tools.domain.compute.cost_analyzer import (
    analyze_costs,
    CostAnalysis,
)


class CostService:
    """Service for cost analysis operations."""
    
    def __init__(
        self,
        api: DatabricksAPI,
        events: EventEmitter | None = None,
    ):
        """Initialize cost service."""
        self.api = api
        self.events = events
    
    async def analyze_cluster_costs(
        self,
        start_date: str,
        end_date: str,
        threshold: float = 0.1,
    ) -> CostAnalysis:
        """
        Analyze cluster costs for date range.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            threshold: Threshold for recommendations
        
        Returns:
            Cost analysis result
        
        Raises:
            ToolExecutionError: If API call fails
        """
        # Emit start event
        if self.events:
            self.events.emit("tool_start", tool_name="analyze_cluster_costs")
        
        try:
            # Fetch data from external system
            usage_data = await self.api.get_cluster_usage(
                start_date=start_date,
                end_date=end_date
            )
            
            # Call domain logic (pure function)
            result = analyze_costs(usage_data, threshold)
            
            # Emit success event
            if self.events:
                self.events.emit(
                    "tool_end",
                    tool_name="analyze_cluster_costs",
                    success=True,
                    total_cost=result.total_cost
                )
            
            return result
            
        except Exception as e:
            # Emit failure event
            if self.events:
                self.events.emit(
                    "tool_end",
                    tool_name="analyze_cluster_costs",
                    success=False,
                    error=str(e)
                )
            raise ToolExecutionError(f"Cost analysis failed: {e}") from e
```

### Step 3: Create Adapter (Tool Interface)

Create clean interface for LLM consumption.

**File**: `packages/starboard-server/starboard_server/tools/adapters/cost_tools.py`

```python
"""Adapter interface for cost analysis tools."""

from typing import Any

from starboard_server.adapters.apis.databricks import DatabricksAPI
from starboard_server.infra.observability.events import EventEmitter
from starboard_server.tools.services.cost_service import CostService


class CostTools:
    """Tool adapter for cost analysis."""
    
    def __init__(
        self,
        api: DatabricksAPI,
        events: EventEmitter | None = None,
    ):
        """Initialize cost tools."""
        self.service = CostService(api=api, events=events)
    
    async def analyze_cluster_costs(
        self,
        start_date: str,
        end_date: str,
        threshold: float = 0.1,
        include_recommendations: bool = True,
    ) -> dict[str, Any]:
        """
        Analyze cluster costs and return recommendations.
        
        Args:
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            threshold: Threshold for identifying high consumers (0.0-1.0)
            include_recommendations: Include cost optimization recommendations
        
        Returns:
            Dictionary with analysis results:
                - total_cost: Total cost for period
                - top_consumers: Top 5 cost consumers
                - recommendations: Optimization suggestions (if enabled)
        
        Examples:
            >>> tools = CostTools(api)
            >>> result = await tools.analyze_cluster_costs(
            ...     "2024-01-01", "2024-01-31"
            ... )
            >>> result["total_cost"]
            12345.67
        """
        # Call service layer
        analysis = await self.service.analyze_cluster_costs(
            start_date, end_date, threshold
        )
        
        # Convert to dict for LLM
        output = {
            "total_cost": analysis.total_cost,
            "top_consumers": analysis.top_consumers,
        }
        
        # Conditionally include recommendations
        if include_recommendations:
            output["recommendations"] = analysis.recommendations
        
        return output
```

### Step 4: Register Tool

Add to tool factory.

**File**: `packages/starboard-server/starboard_server/agents/tools/tool_factory.py`

```python
# ... existing imports ...
from starboard_server.tools.adapters.cost_tools import CostTools

def create_tool_registry(...) -> ToolRegistry:
    """Create and populate tool registry."""
    
    # ... existing tool creation ...
    
    # Create cost tools
    cost_tools = CostTools(api=api, events=events)
    
    # Register tool
    registry.register_native_tool(
        tool_callable=cost_tools.analyze_cluster_costs,
        metadata=ToolMetadata(
            name="analyze_cluster_costs",
            description="Analyze cluster costs and identify optimization opportunities",
            parameters_schema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD)"
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Threshold for high consumers (0.0-1.0)",
                        "default": 0.1
                    }
                },
                "required": ["start_date", "end_date"]
            },
            domains=["cluster", "analytics"],
            category="analytics"
        )
    )
    
    return registry
```

### Step 5: Write Tests

**Unit test (domain)**:

```python
# tests/unit/tools/domain/compute/test_cost_analyzer.py
"""Tests for cost analyzer."""

import pytest
from starboard_server.tools.domain.compute.cost_analyzer import analyze_costs


def test_analyze_costs_basic():
    """Test basic cost analysis."""
    records = [
        {"resource": "cluster-1", "cost": 100},
        {"resource": "cluster-2", "cost": 50},
    ]
    
    result = analyze_costs(records)
    
    assert result.total_cost == 150
    assert len(result.top_consumers) == 2
    assert len(result.recommendations) > 0


def test_analyze_costs_with_threshold():
    """Test with custom threshold."""
    records = [
        {"resource": "cluster-1", "cost": 90},
        {"resource": "cluster-2", "cost": 10},
    ]
    
    result = analyze_costs(records, threshold=0.5)
    
    # cluster-1 is 90% (> 50%), should have recommendation
    assert any("cluster-1" in r for r in result.recommendations)
    # cluster-2 is 10% (< 50%), should not
    assert not any("cluster-2" in r for r in result.recommendations)
```

**Integration test (service)**:

```python
# tests/integration/tools/services/test_cost_service.py
"""Integration tests for cost service."""

import pytest
from unittest.mock import AsyncMock

from starboard_server.tools.services.cost_service import CostService


@pytest.mark.asyncio
async def test_analyze_cluster_costs_success(mock_api):
    """Test successful cost analysis."""
    # Setup mock
    mock_api.get_cluster_usage.return_value = [
        {"resource": "cluster-1", "cost": 100}
    ]
    
    # Create service
    service = CostService(api=mock_api)
    
    # Execute
    result = await service.analyze_cluster_costs(
        "2024-01-01", "2024-01-31"
    )
    
    # Verify
    assert result.total_cost == 100
    mock_api.get_cluster_usage.assert_called_once()
```

### Step 6: Update Documentation

Add tool to [Tool Catalog](../tools/TOOL_CATALOG.md):

```markdown
### analyze_cluster_costs

**Purpose**: Analyze cluster costs and identify optimization opportunities

**Parameters**:
- `start_date` (str, required): Start date (YYYY-MM-DD)
- `end_date` (str, required): End date (YYYY-MM-DD)
- `threshold` (float, optional): Threshold for high consumers (default: 0.1)
- `include_recommendations` (bool, optional): Include recommendations (default: true)

**Returns**: Cost analysis with total, top consumers, and recommendations

**Example**:
```python
result = await tools.analyze_cluster_costs("2024-01-01", "2024-01-31")
```
```

### Step 7: Test End-to-End

```bash
# Run unit tests
pytest tests/unit/tools/domain/compute/test_cost_analyzer.py -v

# Run integration tests
pytest tests/integration/tools/services/test_cost_service.py -v

# Test in CLI
starboard --goal "Analyze cluster costs for January 2024" --mode online
```

✅ **Done!** Your new tool is ready to use.

---

## Adding a New Agent

**Time**: 2-4 hours  
**Difficulty**: ⭐⭐⭐⭐ (Hard)

### Overview

Agents are domain specialists. Follow this process to add a new agent.

### Step 1: Define Prompts

Create system prompts in the server package under the prompts directory.

**File**: `packages/starboard-server/starboard_server/prompts/security/v1.py`

```python
"""Prompts for security agent."""

PROMPT_VERSION = "1.0.0"

SECURITY_AGENT_SYSTEM_PROMPT = """
You are a Databricks security and governance specialist.

Your expertise:
- Access control (ACLs, groups, service principals)
- Data governance (Unity Catalog, lineage)
- Compliance (audit logs, data classification)
- Secret management
- Network security

Always:
- Verify current permissions before suggesting changes
- Follow principle of least privilege
- Cite specific policies and regulations
- Provide rollback steps for risky changes
- Use security best practices

Available tools:
{tool_descriptions}
"""

SECURITY_AGENT_USER_PROMPT_TEMPLATE = """
User request: {user_message}

Context:
{context}

Analyze the security implications and provide recommendations.
"""
```

### Step 2: Create Agent Class

**File**: `packages/starboard-server/starboard_server/agents/domain/security_agent.py`

```python
"""Security and governance agent."""

from starboard_server.agents.domain.domain_agent import DomainAgent
from starboard_server.prompts.security.v1 import (
    SECURITY_AGENT_SYSTEM_PROMPT,
    SECURITY_AGENT_USER_PROMPT_TEMPLATE,
)


class SecurityAgent(DomainAgent):
    """Agent for security and governance tasks."""
    
    def __init__(self, **kwargs):
        """Initialize security agent."""
        super().__init__(
            domain="security",
            system_prompt=SECURITY_AGENT_SYSTEM_PROMPT,
            user_prompt_template=SECURITY_AGENT_USER_PROMPT_TEMPLATE,
            **kwargs
        )
    
    def get_relevant_tools(self) -> list[str]:
        """Get tools relevant to security tasks."""
        return [
            "get_workspace_permissions",
            "list_service_principals",
            "get_audit_logs",
            "check_compliance_status",
        ]
```

### Step 3: Register in AgentFactory

**File**: `packages/starboard-server/starboard_server/agents/agent_factory.py`

```python
class AgentFactory:
    """Factory for creating domain agents."""
    
    def create_agent(self, domain: str) -> DomainAgent:
        """Create agent for domain."""
        if domain == "query":
            return QueryAgent(...)
        elif domain == "job":
            return JobAgent(...)
        # ... existing agents ...
        elif domain == "security":
            return SecurityAgent(
                llm_client=self.llm_client,
                tool_registry=self.tool_registry,
                shared_context=self.shared_context,
            )
        else:
            raise ValueError(f"Unknown domain: {domain}")
```

### Step 4: Update Intent Router

**File**: `packages/starboard-server/starboard_server/agents/routing/intent_router.py`

```python
# Update classification prompt to include security domain
INTENT_CLASSIFICATION_PROMPT = """
...
Available domains:
- query: SQL optimization
- job: Databricks job performance
- uc: Unity Catalog metadata, lineage, governance, storage optimization
- compute: Cluster and warehouse config
- diagnostic: Troubleshooting
- security: Access control, governance, compliance  # NEW
...
"""

# Update intent classification schema
intent_schema = {
    "type": "object",
    "properties": {
        "domain": {
            "type": "string",
            "enum": ["query", "job", "uc", "cluster", "diagnostic", "analytics", "warehouse"],
            ...
        },
        ...
    }
}
```

### Step 5: Add Security-Specific Tools

Create tools needed by the security agent (follow "Adding a New Tool" process).

### Step 6: Write Tests

```python
# tests/unit/agents/domain/test_security_agent.py
"""Tests for security agent."""

import pytest
from starboard_server.agents.domain.security_agent import SecurityAgent


@pytest.fixture
def security_agent(mock_llm_client, mock_tool_registry):
    """Create security agent for testing."""
    return SecurityAgent(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
    )


@pytest.mark.asyncio
async def test_security_agent_initialization(security_agent):
    """Test agent initializes correctly."""
    assert security_agent.domain == "security"
    assert "security" in security_agent.system_prompt.lower()


@pytest.mark.asyncio
async def test_security_agent_tool_selection(security_agent):
    """Test agent selects appropriate tools."""
    tools = security_agent.get_relevant_tools()
    assert "get_workspace_permissions" in tools
    assert "list_service_principals" in tools
```

### Step 7: Update Documentation

Update [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md) to list the new agent.

### Step 8: Test End-to-End

```bash
# Test via CLI
starboard --goal "Who has access to catalog.schema.table?" --mode online

# Test via API
curl -X POST http://localhost:8000/api/chat/conversations/{id}/messages \
  -d '{"message": "Show me service principals with admin access"}'
```

✅ **Done!** Your new agent is live.

---

## Modifying Prompts

**Time**: 30 minutes  
**Difficulty**: ⭐⭐ (Easy-Medium)

### ⚠️ Important: Always Version Prompts

**NEVER** modify prompts in place. Always create a new version.

### Step 1: Create New Version

**File**: `packages/starboard-core/starboard_core/prompts/query_agent.py`

```python
# OLD VERSION (keep unchanged)
QUERY_AGENT_SYSTEM_PROMPT_V2 = """
You are a SQL optimization expert...
"""

# NEW VERSION (create new)
QUERY_AGENT_SYSTEM_PROMPT_V3 = """
You are a SQL optimization expert...

NEW ADDITION: Always check for partitioning before suggesting indexes.
"""
```

### Step 2: Update Agent to Use New Version

**File**: `packages/starboard-server/starboard_server/agents/domain/query_agent.py`

```python
# Change import
from starboard_core.prompts.query_agent import (
    QUERY_AGENT_SYSTEM_PROMPT_V3,  # Changed from V2
    QUERY_AGENT_USER_PROMPT_TEMPLATE,
)

class QueryAgent(DomainAgent):
    def __init__(self, **kwargs):
        super().__init__(
            system_prompt=QUERY_AGENT_SYSTEM_PROMPT_V3,  # Use V3
            ...
        )
```

### Step 3: Update Golden Tests

```bash
# Update golden test snapshots
pytest tests/golden/test_prompts.py --update-snapshots
```

### Step 4: Document Changes

Create change log entry:

```markdown
# Prompt Changelog

## 2024-01-15 - Query Agent V3
- Added: Partitioning check before index suggestions
- Reason: Reduce false positive recommendations
- Impact: More accurate query optimization suggestions
```

### Step 5: A/B Test (Optional)

```python
# Run side-by-side comparison
async def compare_prompt_versions():
    query = "Optimize query abc123"
    
    # V2 result
    agent_v2 = QueryAgent(prompt_version="v2")
    result_v2 = await agent_v2.process(query)
    
    # V3 result
    agent_v3 = QueryAgent(prompt_version="v3")
    result_v3 = await agent_v3.process(query)
    
    # Compare
    print("V2:", result_v2)
    print("V3:", result_v3)
```

✅ **Done!** Prompt updated safely.

---

## Adding an API Endpoint

**Time**: 1 hour  
**Difficulty**: ⭐⭐ (Easy-Medium)

### Step 1: Define Request/Response Models

**File**: `packages/starboard-server/starboard_server/api/models/security.py`

```python
"""Security API models."""

from pydantic import BaseModel, Field


class CheckAccessRequest(BaseModel):
    """Request to check access permissions."""
    
    resource_type: str = Field(..., description="Type of resource (table, cluster, etc.)")
    resource_id: str = Field(..., description="Resource identifier")
    user_email: str | None = Field(None, description="User email (optional)")


class CheckAccessResponse(BaseModel):
    """Response with access permissions."""
    
    has_access: bool = Field(..., description="Whether user has access")
    permissions: list[str] = Field(..., description="List of permissions")
    inherited_from: str | None = Field(None, description="Source of permissions")
```

### Step 2: Create Route Handler

**File**: `packages/starboard-server/starboard_server/api/security.py`

```python
"""Security API endpoints."""

from fastapi import APIRouter, HTTPException, status

from starboard_server.api.dependencies import MultiAgentManagerDep
from starboard_server.api.models.security import (
    CheckAccessRequest,
    CheckAccessResponse,
)

router = APIRouter(prefix="/api/security", tags=["security"])


@router.post(
    "/check-access",
    response_model=CheckAccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Check Access Permissions",
    description="Check if user has access to a resource",
    responses={
        200: {"description": "Access check completed"},
        404: {"description": "Resource not found"},
        500: {"description": "Internal error"},
    },
)
async def check_access(
    request: CheckAccessRequest,
    manager: MultiAgentManagerDep,
) -> CheckAccessResponse:
    """
    Check user access permissions for a resource.
    
    Args:
        request: Access check request
        manager: Multi-agent manager (injected)
    
    Returns:
        Access permissions response
    """
    try:
        # Use security agent to check access
        result = await manager.check_resource_access(
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            user_email=request.user_email,
        )
        
        return CheckAccessResponse(
            has_access=result.get("has_access", False),
            permissions=result.get("permissions", []),
            inherited_from=result.get("inherited_from"),
        )
        
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
```

### Step 3: Register Router

**File**: `packages/starboard-server/starboard_server/api/__init__.py`

```python
"""API package."""

from starboard_server.api.chat import router as chat_router
from starboard_server.api.security import router as security_router  # NEW

__all__ = [
    "chat_router",
    "security_router",  # NEW
    ...
]
```

**File**: `packages/starboard-server/starboard_server/api/main.py`

```python
from starboard_server.api import chat_router, security_router

# Register routers
app.include_router(chat_router)
app.include_router(security_router)  # NEW
```

### Step 4: Write Contract Test

```typescript
// tests/contract/api/security.test.ts
import { z } from 'zod';

const CheckAccessResponseSchema = z.object({
  has_access: z.boolean(),
  permissions: z.array(z.string()),
  inherited_from: z.string().nullable(),
});

describe('Security API Contract', () => {
  it('POST /api/security/check-access returns valid response', async () => {
    const response = await fetch('/api/security/check-access', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resource_type: 'table',
        resource_id: 'catalog.schema.table',
      }),
    });
    
    const data = await response.json();
    
    // Validate against schema
    expect(() => CheckAccessResponseSchema.parse(data)).not.toThrow();
  });
});
```

### Step 5: Update API Documentation

Add to [API Reference](../api/API_REFERENCE.md).

### Step 6: Test

```bash
# Test endpoint
curl -X POST http://localhost:8000/api/security/check-access \
  -H "Content-Type: application/json" \
  -d '{
    "resource_type": "table",
    "resource_id": "catalog.schema.table"
  }'

# Check OpenAPI docs
open http://localhost:8000/docs
```

✅ **Done!** New endpoint is live.

---

## Updating Domain Models

**Time**: 30 minutes  
**Difficulty**: ⭐⭐ (Easy-Medium)

### Step 1: Update Model in Core

**File**: `packages/starboard-core/starboard_core/domain/models/conversation.py`

```python
# Add new field to existing model
@dataclass(frozen=True)
class Message:
    """Conversation message."""
    
    role: str
    content: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # NEW FIELD
    token_count: int | None = None  # Track token usage per message
```

### Step 2: Update Repository

**File**: `packages/starboard-server/starboard_server/repositories/conversation_repository.py`

```python
# Update save method to include new field
async def save_message(self, message: Message) -> None:
    """Save message with token count."""
    await self.db.execute(
        """
        INSERT INTO messages (role, content, timestamp, metadata, token_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            message.role,
            message.content,
            message.timestamp,
            json.dumps(message.metadata),
            message.token_count,  # NEW
        )
    )
```

### Step 3: Create Migration

**File**: `packages/starboard-server/starboard_server/infra/storage/migrations/007_add_token_count.sql`

```sql
-- Add token_count column to messages table
ALTER TABLE messages ADD COLUMN token_count INTEGER NULL;

-- Add index for performance
CREATE INDEX idx_messages_token_count ON messages(token_count);
```

### Step 4: Update Tests

```python
def test_message_with_token_count():
    """Test message with new token_count field."""
    message = Message(
        role="user",
        content="Hello",
        timestamp=datetime.now(),
        token_count=5,  # NEW
    )
    
    assert message.token_count == 5
```

### Step 5: Run Migration

```bash
# Run migration
make migrate

# Or manually
python3 scripts/run_migrations.py
```

✅ **Done!** Model updated across the system.

---

## Debugging Agent Behavior

**Time**: Variable  
**Difficulty**: ⭐⭐⭐⭐ (Hard)

### Enable Debug Logging

```bash
# Start server with debug logging
LOG_LEVEL=DEBUG make dev-server

# Or set in .env
echo "LOG_LEVEL=DEBUG" >> .env
make dev-server
```

### View Debug Logs

```bash
# Tail server logs
tail -f .debug/server/debug.log

# Search for specific agent
grep "QueryAgent" .debug/server/debug.log

# Search for tool executions
grep "tool_start\|tool_end" .debug/server/debug.log
```

### Add Debug Statements

```python
# In agent or tool
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

async def process_message(self, message: str):
    logger.debug(
        "Agent processing message",
        agent=self.domain,
        message=message,
        tool_count=len(self.available_tools),
    )
    
    # ... agent logic ...
    
    logger.debug(
        "Agent selected tool",
        agent=self.domain,
        tool_name=selected_tool,
        reasoning=tool_selection_reasoning,
    )
```

### Use Debugger

```python
# Add breakpoint
import pdb; pdb.set_trace()

# Or use IDE debugger
# Set breakpoint in IDE at desired line
```

### Inspect LLM Calls

```python
# Enable LLM call logging
from starboard_server.adapters.llm.openai.client import OpenAIProvider

# Add callback to log all calls
def log_llm_call(request, response):
    print(f"Prompt: {request.messages}")
    print(f"Response: {response.choices[0].message.content}")

provider = OpenAIProvider(cfg=config, callback=log_llm_call)
```

### Test Agent in Isolation

```python
# Test agent without full system
async def test_agent_isolation():
    agent = QueryAgent(
        llm_client=mock_llm,
        tool_registry=mock_tools,
    )
    
    result = await agent.process_message("Optimize query abc123")
    print(result)
```

✅ **Done!** Agent behavior debugged.

---

## Writing Tests

See [Testing Guide](../TESTING.md) for comprehensive testing strategies.

### Quick Test Templates

**Unit test**:
```python
def test_function_name():
    """Test description."""
    # Arrange
    input_data = ...
    
    # Act
    result = function_under_test(input_data)
    
    # Assert
    assert result == expected_value
```

**Async test**:
```python
@pytest.mark.asyncio
async def test_async_function():
    """Test async function."""
    result = await async_function()
    assert result is not None
```

**Parametrized test**:
```python
@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
])
def test_multiple_cases(input, expected):
    """Test multiple cases."""
    assert double(input) == expected
```

---

## Updating Documentation

### Update Existing Docs

1. Find relevant doc in `docs/`
2. Make changes
3. Regenerate diagrams if needed: `make diagrams`
4. Preview: `make docs-serve`
5. Commit changes

### Add New Doc

1. Create file in appropriate `docs/` subdirectory
2. Add to `mkdocs.yml` navigation
3. Add cross-references from related docs
4. Preview: `make docs-serve`
5. Commit changes

### Generate Diagrams

```bash
# Add .mmd file in docs/diagrams/source/
# Then generate
make diagrams

# Verify
ls docs/diagrams/generated/
```

✅ **Done!** Documentation updated.

---

## Next Steps

- **[Runbook](../RUNBOOK.md)** - Operational procedures
- **[FAQ](./FAQ.md)** - Quick answers
- **[Contributing Guide](./CONTRIBUTING.md)** - Contribution workflow

---

**Last Updated**: 2025-12-06  
**Version**: 1.1


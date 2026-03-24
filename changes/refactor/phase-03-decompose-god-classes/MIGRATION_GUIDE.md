# Phase 03: Migration Guide

## For Callers of DomainAgent

**No migration required.** DomainAgent's public API is unchanged. All existing code continues to work.

For new code, prefer importing from the focused modules:

```python
# Instead of relying on DomainAgent internals:
from starboard_server.agents.domain.reasoning_loop import FINALIZATION_BUDGET
from starboard_server.agents.domain.state_initializer import StateInitializer
from starboard_server.agents.domain.complete_tool import register_complete_tool
from starboard_server.agents.domain.partial_report import generate_partial_report
```

## For Callers of UCService

**No migration required.** The UCService facade preserves all existing method signatures.

For new code, prefer importing sub-services directly:

```python
# Direct sub-service usage (preferred for new code):
from starboard_server.tools.services.uc.catalog_browser import CatalogBrowserService
from starboard_server.tools.services.uc.table_metadata import TableMetadataService
from starboard_server.tools.services.uc.governance import GovernanceService
from starboard_server.tools.services.uc.lineage import LineageService
from starboard_server.tools.services.uc.schema_operations import SchemaOperationsService
from starboard_server.tools.services.uc.storage_analysis import StorageAnalysisService

# Still works (backward-compatible):
from starboard_server.tools.services.uc_service import UCService
```

## For Tests

Existing tests require no changes. New tests should target the focused modules directly for better isolation.

## InMemoryUserStore

No migration needed. The `container.user_store` property now caches the instance automatically (singleton per container). Callers continue using `container.user_store` as before.

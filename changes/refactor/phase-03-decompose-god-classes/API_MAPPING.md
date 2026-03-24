# Phase 03: API Mapping — Old Locations → New Locations

## DomainAgent Method Migration

| Old Location (DomainAgent) | New Location | Notes |
|---|---|---|
| `DomainAgent._reasoning_loop_stream()` | `reasoning_loop.reasoning_loop_stream()` | Main reasoning orchestration |
| `DomainAgent._should_continue_reasoning()` | `reasoning_loop.should_continue_reasoning()` | Budget/step checking |
| `DomainAgent._initialize_state()` | `state_initializer.StateInitializer.initialize()` | Facade shim retained |
| `DomainAgent._build_handoff_context()` | `state_initializer.build_handoff_context()` | Module-level function |
| `DomainAgent._register_complete_tool()` | `complete_tool.register_complete_tool()` | Module-level function |
| `DomainAgent.CompleteToolWrapper` | `complete_tool.CompleteToolWrapper` | Standalone class |
| `DomainAgent._generate_partial_report()` | `partial_report.generate_partial_report()` | Module-level function |
| `DomainAgent._build_context_summary()` | `partial_report.build_context_summary()` | Module-level function |
| `DomainAgent._add_assistant_message()` | `message_helpers.add_assistant_message()` | Module-level function |
| `DomainAgent._add_tool_message()` | `message_helpers.add_tool_message()` | Module-level function |
| `FINALIZATION_BUDGET` | `reasoning_loop.FINALIZATION_BUDGET` | Re-exported from `__init__.py` |

## UCService Method Migration

| Old Location (UCService) | New Sub-Service | Method |
|---|---|---|
| `enumerate_assets()` | `CatalogBrowserService` | `enumerate_assets()` |
| `discover_tables()` | `CatalogBrowserService` | `discover_tables()` |
| `enrich_table_references()` | `CatalogBrowserService` | `enrich_table_references()` |
| `fetch_table_metadata()` | `TableMetadataService` | `fetch_table_metadata()` |
| `fetch_table_fingerprint()` | `TableMetadataService` | `fetch_table_fingerprint()` |
| `fetch_table_lineage()` | `LineageService` | `fetch_table_lineage()` |
| `fetch_table_grants()` | `GovernanceService` | `fetch_table_grants()` |
| `analyze_access_patterns()` | `GovernanceService` | `analyze_access_patterns()` |
| `analyze_policy_coverage()` | `GovernanceService` | `analyze_policy_coverage()` |
| `analyze_table_schema()` | `SchemaOperationsService` | `analyze_table_schema()` |
| `detect_schema_drift()` | `SchemaOperationsService` | `detect_schema_drift()` |
| `generate_schema_diff()` | `SchemaOperationsService` | `generate_schema_diff()` |
| `fetch_delta_history()` | `StorageAnalysisService` | `fetch_delta_history()` |
| `recommend_storage_optimization()` | `StorageAnalysisService` | `recommend_storage_optimization()` |
| `analyze_query_impact()` | `StorageAnalysisService` | `analyze_query_impact()` |
| `attribute_table_costs()` | `StorageAnalysisService` | `attribute_table_costs()` |

## Backward Compatibility

Both `DomainAgent` and `UCService` remain fully backward-compatible:
- All existing imports continue to work
- All public API signatures are unchanged
- `FINALIZATION_BUDGET` is re-exported from `__init__.py`
- UCService protocols re-exported from `uc_service.py` (e.g., `SQLQueryProvider`, `UCCatalogProvider`)
- Shim methods on DomainAgent delegate to extracted modules transparently

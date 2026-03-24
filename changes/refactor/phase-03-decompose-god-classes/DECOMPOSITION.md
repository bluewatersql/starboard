# Phase 03: Decompose God Classes — Decomposition Report

## DomainAgent (Before: 1,448 lines → After: 324 lines)

### Before
Single monolithic class handling reasoning, tool execution, state init, output building, completion, and partial reports.

### After — 7 Focused Modules

| Module | Lines | Responsibility |
|--------|-------|---------------|
| `domain_agent.py` | 324 | Thin facade — creates components, delegates `run_stream()` |
| `reasoning_loop.py` | 484 | Step-by-step reasoning cycle, budget-aware continuation |
| `state_initializer.py` | 308 | State setup, system prompts, handoff context enrichment |
| `complete_tool.py` | 236 | Complete tool registration, LLM output normalization |
| `partial_report.py` | 343 | Budget-exhaustion partial report generation |
| `message_helpers.py` | 164 | Message building helpers (assistant/tool messages) |
| `output_builder.py` | 496 | Final output formatting (pre-existing, unchanged) |

### Class Diagram (After)
```
DomainAgent (facade, 324 lines)
├── ReasoningLoop          — orchestrates reasoning steps
│   ├── ReasoningEngine    — LLM calls (pre-existing)
│   ├── ToolExecutor       — tool execution (pre-existing)
│   ├── EventStreamer      — event creation (pre-existing)
│   └── OutputBuilder      — final output formatting
├── StateInitializer       — builds initial AgentState
├── CompleteToolWrapper    — registered via complete_tool module
├── PartialReport          — budget-exhausted report generation
└── MessageHelpers         — state message construction
```

## UCService (Before: 2,398 lines → After: 431-line facade + 6 sub-services)

### Before
Single monolithic service with 20+ methods spanning catalog browsing, metadata, lineage, governance, storage analysis, schema operations, and query analysis.

### After — 6 Focused Sub-Services + Facade

| Module | Lines | Responsibility |
|--------|-------|---------------|
| `uc_service.py` | 431 | Backward-compatible facade delegating to sub-services |
| `uc/base.py` | 196 | Shared protocols, base class, utility functions |
| `uc/catalog_browser.py` | 288 | Asset enumeration, table discovery, enrichment |
| `uc/table_metadata.py` | 342 | Table metadata and fingerprinting |
| `uc/lineage.py` | 102 | Lineage queries and graph transformation |
| `uc/governance.py` | 472 | Grants, access patterns, policy coverage |
| `uc/schema_operations.py` | 363 | Schema drift, diff generation, schema analysis |
| `uc/storage_analysis.py` | 328 | Delta history, storage optimization, query impact, costs |
| `uc/__init__.py` | 50 | Re-exports for convenience |

### Sub-Service Architecture
```
UCService (facade, 431 lines)
├── CatalogBrowserService  — enumerate_assets, discover_tables, enrich_table_references
├── TableMetadataService   — fetch_table_metadata, fetch_table_fingerprint
├── LineageService         — fetch_table_lineage
├── GovernanceService      — fetch_table_grants, analyze_access_patterns, analyze_policy_coverage
├── SchemaOperationsService— analyze_table_schema, detect_schema_drift, generate_schema_diff
└── StorageAnalysisService — fetch_delta_history, recommend_storage_optimization,
                             analyze_query_impact, attribute_table_costs
```

## InMemoryUserStore (Task 3.3)

Changed `container.py` `user_store` property to cache the instance using `_user_store` field, ensuring singleton-per-container behavior. Test added: `test_user_store_returns_same_instance`.

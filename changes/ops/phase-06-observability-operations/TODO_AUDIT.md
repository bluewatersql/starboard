# TODO Cleanup Audit — Phase 06

**Date:** 2026-03-02
**Branch:** `ops/phase-06-observability-operations`

## Summary

| Category | Before | After | Action |
|----------|--------|-------|--------|
| Unstandardized TODOs | 27 | 0 | All tagged with `TODO(PHASE-NN)` or `TODO(BACKLOG-NNN)` |
| False positives skipped | 3 | — | TEMPORAL, TEMPERATURE, DOMAIN_PROMPT_TEMPLATES references |
| Docstring "TODO" → "planned" | 4 | 0 | `conversation_patterns.py` pattern descriptions |

## Standardized TODOs by Package

### `starboard-server` (5 TODOs)

| ID | File | Description |
|----|------|-------------|
| `PHASE-07` | `services/clarification/clarification_service.py:113` | Context-aware disambiguation with conversation history |
| `PHASE-07` | `services/clarification/clarification_service.py:132` | Implement confidence-based auto-resolution |
| `BACKLOG-001` | `api/clarification.py:149` | Integrate clarification service into conversation flow |
| `BACKLOG-002` | `infra/cache/semantic_cache.py:259` | Add cache metrics for monitoring hit/miss rates |
| `BACKLOG-003` | `infra/core/container.py:201` | Make Redis optional — graceful degradation when unavailable |
| `BACKLOG-004` | `tools/services/uc/table_metadata.py:292` | Cache enriched metadata with TTL for repeated lookups |

### `frontend` (9 TODOs)

| ID | File | Description |
|----|------|-------------|
| `PHASE-03` | `lib/hooks/useSSE.ts:199` | Implement SSE reconnection with exponential backoff |
| `BACKLOG-005` | `components/chat/ReportBubble.tsx:211` | Add specialized bubble for diagnostic reports |
| `BACKLOG-006` | `components/chat/visualization/DataTableView.tsx:102,266` | Replace inline MUI styles with theme tokens |
| `BACKLOG-007` | `components/chat/reports/warehouse/index.ts:9` | Move warehouse components from compute/ to warehouse/ |
| `BACKLOG-008` | `components/chat/reports/AnalyticsReportBubble.tsx:94` | Implement client-side markdown formatter for analytics exports |
| `BACKLOG-009` | `components/chat/ChatErrorBoundary.tsx:86` | Integrate error tracking service (Sentry, etc.) |
| `BACKLOG-010` | `components/chat/reports/AdvisorReportBubble.tsx:323` | Implement recommendation apply handler |
| `BACKLOG-011` | `components/chat/reports/AdvisorReportBubble.tsx:364` | Implement finding action handlers (mark applied, explain more) |

### `starboard-log-parser` (10 TODOs)

| ID | File | Description |
|----|------|-------------|
| `BACKLOG-012` | `loaders/s3.py:115` | Implement true streaming with chunked reads |
| `BACKLOG-013` | `parsing_models/stage_model.py:195` | Account for failed tasks in stage event parsing |
| `BACKLOG-014` | `parsing_models/application/model.py:44` | Remove redundant boolean flags; use `is not None` checks |
| `BACKLOG-015` | `parsing_models/application/model.py:53` | Add docstrings for DataFrame fields |
| `BACKLOG-016` | `parsing_models/application/model.py:127` | Strengthen parsed-app detection beyond "jobData" key check |
| `BACKLOG-017` | `parsing_models/event_log_parser.py:416` | Implement task runtime distribution plotting and normality test |
| `BACKLOG-018` | `parsing_models/task_model.py:168` | Add utilization metrics to task JSON output |
| `BACKLOG-019` | `parsing_models/task_model.py:217` | Warn on non-zero disk spill and reconcile with shuffle metrics |
| `BACKLOG-020` | `parsing_models/task_model.py:227` | Populate once Spark exposes input read time |
| `BACKLOG-021` | `parsing_models/task_model.py:234` | Populate once Spark exposes output write time |

### `conversation_patterns.py` (docstring cleanup)

Changed 4 "— TODO" markers to "— planned" in module docstring (lines 5-8). These described future pattern implementations, not actionable code TODOs.

## FIXME / HACK / XXX / TEMP

No `FIXME`, `HACK`, `XXX`, or `TEMP` markers were found in the codebase.

## Methodology

1. Scanned with `rg 'TODO|FIXME|HACK|XXX|TEMP' packages/ frontend/ --type py --type ts -n`
2. Filtered false positives (variable names containing TODO-like substrings)
3. Assessed each TODO: implement if small, tag with `BACKLOG-NNN` if larger, tag with `PHASE-NN` if scheduled
4. Verified zero unstandardized TODOs remain after changes

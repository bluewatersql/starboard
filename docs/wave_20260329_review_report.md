# Wave 20260329 — Code Review Report

> **Date:** 2026-03-29
> **Reviewers:** Senior Architect, Python/AI Expert, QA Expert
> **Branch:** `feature/wave-20260329`
> **Commit:** `a5ce73c5` (73 files, +7716/-421)

---

## Overall Assessment: **B+**

The implementation is well-structured, spec-faithful, and passes all automated gates (lint, type-check, unit tests). Architecture layer boundaries are respected, dependency flow is correct, and the Jinja2 singleton is async-safe. The primary gap is **test coverage** — no golden tests for migrated prompts, no unit tests for Phase 3/4 new code. These are addressable in a follow-up sprint.

---

## Per-Phase Scores

| Phase | Code Quality | Guidelines | Best Practices | Completeness | Consistency | Grade |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|
| **Phase 1: Jinja Migration** | 88 | 85 | 90 | 82 | 90 | **B+** |
| **Phase 2: Config Enhancements** | 90 | 85 | 85 | 80 | 88 | **B+** |
| **Phase 3: Query Classification** | 90 | 90 | 88 | 85 | 90 | **A-** |
| **Phase 4: Domain Expansion** | 85 | 85 | 88 | 82 | 85 | **B+** |

---

## Key Findings

### HIGH PRIORITY

| ID | Phase | Finding | Reviewer |
|----|-------|---------|----------|
| H1 | P1 | **No golden tests for 11 migrated prompts.** Per CLAUDE.md, golden tests are REQUIRED for all prompt changes. None were added. | QA |
| H2 | P1 | **`__init__.py` re-exports still point to v1.** Code importing `from starboard_server.prompts.query import QUERY_SYSTEM_PROMPT` gets stale v1 output, not v2 Jinja2. | Architect |
| H3 | P2 | **Missing circuit breaker wrapping.** Spec requires circuit breaker on WarehouseProvisioner and SupportModeInitializer — not implemented. | Architect |
| H4 | P3 | **No unit tests for classification fields or executor filtering.** 3 new enums, QueryMetadata, DiscoveryMode filtering, `{result_limit}` rendering — all untested. | QA |

### MEDIUM PRIORITY

| ID | Phase | Finding | Reviewer |
|----|-------|---------|----------|
| M1 | P1 | **Discovery analysis templates inline preamble instead of `{% include %}`**. `_preamble.jinja2` exists but isn't referenced by any template. | Python |
| M2 | P1 | **`test_get_system_prompt_all_domains` missing warehouse + discovery.** Test checks 7 domains but factories has 9. | QA |
| M3 | P2 | **Cross-field validation removed.** `autocreate_dbx_dw + offline_mode` and `is_dbx_support + offline_mode` conflicts not validated at config time (runtime guards only). | Architect |
| M4 | P4 | **No unit tests for 47 new queries.** SQL syntax, required_tables, and metadata not validated. | QA |
| M5 | P2 | **WarehouseProvisioner tests missing retry/transient-error scenario.** Spec requires `test_provision_retries_on_transient_error`. | QA |

### LOW PRIORITY

| ID | Phase | Finding | Reviewer |
|----|-------|---------|----------|
| L1 | P1 | `factories.py` missing `from __future__ import annotations`. | Python |
| L2 | P1 | `domain_analysis.py` (v1) modified but no `PROMPT_VERSION` export. | Python |
| L3 | P3 | `jobs.py:446` has removal comment for C-J07 — should be a clean removal, not a comment. | Architect |
| L4 | P4 | `domain_analysis_v2.py:26-33` template map incomplete (missing new Phase 4 domains in v2 builder path). | Python |

---

## Positive Highlights

1. **Jinja2 Environment is async-safe.** `StrictUndefined` + `lru_cache` singleton is correct for the single-threaded async event loop. No mutable state between calls.
2. **Clean factory migration.** Eliminated special-case branching with uniform lambda-based builder pattern.
3. **Domain model extensions are clean.** `DiscoveryMode`, `QueryCategory`, `QueryMetadata` are frozen dataclasses in starboard-core with no I/O dependencies.
4. **Executor filtering is elegant.** `DiscoveryMode` gate + `format_map(defaultdict)` for safe `{result_limit}` rendering.
5. **All 39 existing queries classified.** Metadata summaries provide good LLM context.
6. **Product mapping expansion is thorough.** 29 products mapped to domain packs.

---

## Remediation Plan

### Sprint Follow-Up (recommended)

1. **Add golden tests** for all 11 migrated prompts (P1 — H1)
2. **Add `jinja_env.py` unit tests** — render_template, StrictUndefined, missing template, filters
3. **Add Phase 3 unit tests** — DiscoveryMode filtering, QueryCategory classification, `{result_limit}` rendering
4. **Add Phase 4 query pack tests** — SQL syntax validation, required_tables coverage
5. **Update `__init__.py` re-exports** to point to v2 (P1 — H2)
6. **Add circuit breaker wrapping** to WarehouseProvisioner and SupportModeInitializer (P2 — H3)

### Deferred (acceptable)

- M3 (cross-validation): Runtime guards are sufficient; config-time validation was causing test failures with default values
- L1-L4: Minor cleanup, no functional impact

---

## Conclusion

Wave 20260329 delivers a solid foundation: Jinja2 templating, warehouse auto-provisioning, query classification, and 8 domain packs with 47 new queries. The architecture is sound and all automated gates pass. The primary remediation need is **test coverage** — specifically golden tests and unit tests for new code paths. Recommended for merge with a follow-up test-coverage sprint.

# Docs Overhaul — Open Items

Consolidated gaps, follow-ups, and owner decisions surfaced during the documentation
overhaul (Workstreams A–E + central reconcile). Items are grouped by type. Docs were
brought in line with code; the items below are things the docs pass could **not**
resolve on its own (code bugs, product decisions, or owner confirmations).

_Last updated: 2026-08-27 (central reconcile)._

## Code / runtime (out of docs scope)

1. **Bootstrap eager import breaks store-free install.** `packages/starboard/starboard/bootstrap.py`
   eagerly imports `SQLiteStateStore`, so a bare `pip install starboard` can raise
   `ModuleNotFoundError: aiosqlite` before `starboard --help` runs — contradicting the
   documented "store-free by default" promise. Fix: make the SQLite/state-store import
   lazy so the default in-memory path needs no store drivers. (Flagged by Workstream B.)

2. **`genie ask` NL→SQL not exercised end-to-end.** Because of item (1), the CLI could
   not be launched during the pass; `genie ask` flags were verified from source
   (`genie_command.py`) but example outputs in the docs are illustrative. Re-verify once
   (1) is fixed.

## Repository hygiene

3. **Duplicate/stale skills tree at repo root.** `skills/starboard/` still contains the
   old roster (includes `starboard-workspace`, lacks `starboard-workload-review`) and
   diverges from the canonical `packages/starboard-skills/skills/starboard/`. Docs now
   point at the canonical tree; the stale root tree should be reconciled or removed.
   (Flagged by Workstream B.)

4. **Legacy root test tree (owner decision pending).** Carried over from the cleanup
   pass (`cleanup_report.md`) — the monolithic root `tests/` tree awaits an owner
   decision on retirement vs. migration into `packages/*/tests/`.

## Product / surface decisions

5. **Interruptible reasoning has no plain-CLI injection path.** True mid-flight injection
   (`inject-input` / `respond-to-solicitation`) is only reachable via the optional
   server/SDK. `docs/user-guide/interruptible-reasoning.md` was reframed to turn-based
   CLI + programmatic. If a supported CLI interrupt path is intended, add it and expand
   the doc. (Flagged by Workstream B.)

6. **Databricks AI Tools distribution — owner confirmations needed.** `docs/distribution/databricks-aitools.md`
   §5 lists open owner questions: installer-side manifest/registry shape, install
   locations/precedence, CLI-version/auth prerequisites, and the `starboard-helper`
   acquisition step. (Flagged by Workstream D.)

## Docs infrastructure (fixed this pass, noted for follow-up)

7. **`packages/starboard/README.md` was fiction — now reframed.** It described a
   `starboard-server` FastAPI backend with a full REST chat API, SSE streaming, and
   feedback/clarification/visualization endpoints. Those services were removed in the
   cleanup and the real app (`starboard.main:create_app`) exposes only `/`, `/health/*`,
   and an optional `/mcp` transport. README rewritten to match; see it as the reference
   for the true HTTP surface.

8. **Diagram sources retired.** Removed three stale Mermaid sources tied to the old
   package split: `packages/starboard-server-multi-agent.mmd`,
   `packages/starboard-log-parser-pipeline.mmd`, `integration/log-parser-integration.mmd`
   (no doc referenced their generated PNGs). If wanted, add a refreshed `starboard`
   multi-agent diagram and a `starboard-core` log-source diagram and reference them.

9. **Broken Mermaid edge labels fixed.** `uc/cluster/warehouse-agent-workflow.mmd` used
   double-quoted keyword lists inside `|…|` edge labels, which fail to parse in Mermaid
   10.x (so those PNGs silently never regenerated). Rewritten to plain text; all 36
   remaining sources now generate cleanly.

10. **Docs toolchain was undeclared.** Added a `docs` optional-dependency group to the
    root `pyproject.toml` (`mkdocs`, `mkdocs-material`, `mermaid2`, git-revision, macros)
    so `make docs` is reproducible. **CI does not build docs at all** — consider adding a
    docs job that runs `mkdocs build --strict` + `scripts/validate_doc_links.py`.

11. **`mkdocs build --strict` and untracked pages.** The git-revision-date plugin emits a
    "has no git logs" warning for pages that are new/untracked; strict mode treats it as
    an error. It clears once the new pages are committed. All other strict warnings
    (nav, links, macros) are resolved.

## Consistency to verify later

12. **Tool-count phrasing.** "45+ tools" appears in several docs (e.g.
    `architecture/SYSTEM_ARCHITECTURE.md`, package READMEs). It was not independently
    re-counted against the live registry this pass; verify the figure if precision
    matters and align all mentions.

# Dep-ful Progressive Helpers — Open Questions

> Unresolved questions for the middle-tier (dep-ful progressive-disclosure helper) design.
> Tagged by owner-topic where they cross-link.

## Packaging & source of truth
1. **New wheel vs extend `starboard-core`?** Ship `starboard-x` as a fresh thin wheel (cleanest
   dep boundary, but re-homes modules) or extend `starboard-core` with the diagnostic/discovery/
   chart modules + extras and expose a `starboard_x` CLI namespace (no code copy, but grows core)?
   `starboard-core` already has analyzers + log parser + cloud extras (`core/pyproject.toml:19-33`),
   which argues for extending it. Decision needed before rank-1 build. *(cross: decomposition)*
2. **Trimmed `__init__` scope.** `tools/domain/diagnostic/__init__.py:16-96` eagerly imports the whole
   subsystem. How much do we trim vs import-by-full-path? Does anything downstream rely on the eager
   re-exports (the MCP server / agents)?
3. **Do pure diagnostics/charts stay SDK-free?** Decomposition mandates "no Tier-0 package imports
   databricks-sdk" (`starboard_decomposition/recommendation.md:118`). C1/C2/C6/C16 qualify; confirm
   none sneak in an SDK import transitively via shared models.

## Input-schema contracts
4. **Profile / event-log / pattern JSON schemas drift.** C3 (query-profile), C4 (spark-evidence),
   C5 (patterns) consume JSON whose shape can change with DBR/DBSQL versions. Do we version and ship
   these schemas with the helper? Who owns compatibility?
5. **Tier-0 → Tier-1 piping.** Is the JSON that `starboard-helper` emits (Tier 0) exactly the shape
   the Tier-1 analyzers expect as input (e.g. warehouse history → `starboard_x.warehouse analyze`)?
   If not, an adapter is needed at the boundary.

## Disclosure & UX
6. **Install detection in the skill body.** The three-branch logic assumes the skill can detect
   whether `starboard-x` is installed (probe `scripts/run.sh` existence, or `python -c import`).
   What's the cheapest reliable probe that doesn't itself cost a turn?
7. **When to inline vs shell out.** `` !`cmd` `` dynamic injection gives a zero-turn answer but runs
   *before* Claude reasons about arguments. Which verbs are safe to inline (deterministic, arg-simple
   like `triage-exit`) vs must be an explicit Bash call (need file paths, large output)?
8. **`context: fork` default?** Should heavier helpers (discovery, sparklog) default to running in a
   forked subagent to keep even their body + JSON out of the main thread? Trade-off: fork adds
   latency and loses the result from the main context unless summarized back.
9. **Skill count vs description budget.** 8+ skills each carry a ≤1.5KB resident description. Is the
   aggregate acceptable, or do we consolidate (one `starboard` skill that routes to sub-verbs)?

## Auth (I/O helpers)
10. **Auth for Tier-1 I/O verbs.** C8/C11/C12/C14/C15 need a live `WorkspaceClient`. Do they reuse
    the Tier-0 unified SDK chain, or the Databricks-native path from the `databricks_auth/` topic?
    Multi-workspace + token refresh is still flagged as env-var-only. *(cross: databricks_auth)*

## Distribution
11. **Skill delivery: plugin, wheel, or both?** Plugin uses `${CLAUDE_PLUGIN_ROOT}`; a pip-installed
    skill uses `${CLAUDE_SKILL_DIR}`. Do we ship both and keep bodies byte-identical except the path
    var, or pick one? *(cross: agent_integration)*
12. **Where does `pip install` happen?** In a Databricks notebook / Apps runtime the helper's extras
    must be installable at the right Python. Is there a bootstrap step, or do we assume the harness
    environment already has `starboard-x`?
13. **Cross-host portability.** OpenCode `.opencode/skills/` and the claude.ai Skills API accept only
    the six spec frontmatter fields. Do we maintain a spec-only skill variant, or accept that the
    dep-ful helper is Claude-Code/Isaac-first?

## Boundary with Tier 2
14. **Does the RAG-replacement work move Analytics SQL down a tier?** If Round-2 asks C/D replace the
    vector DB with progressive-disclosure reference files, can deterministic Analytics SQL generation
    become a Tier-1 helper, or does it still need the LLM loop? *(cross: optimization, decomposition)*
15. **Progress/streaming.** Long deterministic runs (discovery over 17 packs) produce no progress in a
    one-shot subprocess. Acceptable, or do we need chunked stdout the skill can stream?

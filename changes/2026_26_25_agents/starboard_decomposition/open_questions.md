# Starboard Decomposition — Open Questions

Unresolved questions from the unbundling study. Grouped by theme; each notes who/what could
resolve it.

## A. Packaging format & ecosystem (coordinate with `agent_integration` topic)

1. **Skill frontmatter contract.** Current `skills/starboard/*/SKILL.md` open with a bare `name:`
   line and **no `---` fence**; the `packages/starboard-skills` copies have no frontmatter at all.
   What is the exact required frontmatter (fenced YAML? which fields — `name`, `description`,
   `allowed-tools`, `license`, `metadata`?) for the target runtime(s)? → agent_integration owns; verify against current docs.
2. **One skill set for two runtimes?** Claude Code and Isaac both consume skills — are their
   `SKILL.md` schemas identical enough to ship one canonical set, or do we need per-runtime
   frontmatter (or a build step that emits both)?
3. **Plugin vs marketplace granularity.** Do we ship one meta `starboard` plugin plus per-domain
   plugins, or a single plugin with all skills? What does install UX look like when a user wants
   *only* FinOps?
4. **MCP tool naming collisions.** If each Tier-1 package exposes its own MCP tools *and* the meta
   server re-exposes them, how do we prevent duplicate/ambiguous tool names in a combined session?
5. **Is there a supported Python API for building skills/plugins**, or is it file-convention only?
   Affects whether wheels can *generate* skill/plugin manifests at build time.

## B. Dependency & boundary decisions

6. **Can `starboard-kernel` truly avoid `databricks-sdk`?** Today `starboard-core` depends on it
   (`core/pyproject.toml:16`). Which analyzers/models actually need SDK *types* vs just plain
   DTOs? Requires an import audit before the kernel carve-out.
7. **Where do the log-parser loaders live?** `core/log_parser/loaders/{s3,dbfs,https}.py` do I/O.
   Do they stay in `starboard-sparklog` as optional extras, or move to `starboard-databricks`?
   This decides whether sparklog can be a zero-cloud-dep parse library.
8. **DBR-runtime pins.** The `packages/starboard/pyproject.toml` pins (cryptography, cffi,
   protobuf, fastapi/starlette CVEs) are tied to running on DBR 17.3. Do the *pure* tiers need any
   of these, or can they float freely? (Assumed: pure tiers are pin-free.)
9. **polars in the kernel.** Is polars acceptable in the dependency-light nucleus, or should the
   truly-minimal core be pydantic-only with polars pushed to a `[frames]` extra?

## C. Agent / LLM surface

10. **Discovery agent MCP exclusion** (`agent_bridge.py:63` `_MCP_EXCLUDED_AGENT_DOMAINS`). Was
    this deliberate (long-running, progress-notification gap) or incidental? Decides whether L8
    ships as an MCP `*_agent` tool or skill-only.
11. **Runtime coupling of agents.** Can L1-L8 run on a *generic* agent runtime (R1), or are they
    hard-bound to Starboard's event/streaming types? Determines if `starboard-agents` is reusable
    or Starboard-internal.
12. **Router as optional vs mandatory.** If units ship independently, is the `intent-router` (L9)
    an optional coordinator a user opts into, or does single-entry UX require it always present?
13. **Double-LLM cost.** Skills already warn that auto-pilot (server-side agent) doubles LLM cost
    vs direct orchestration (`skills/starboard/starboard-query/SKILL.md`). For decomposed units,
    what is the default — thin skill orchestrates libs directly, or delegates to an agent?

## D. Composition & migration

14. **Back-compat guarantee.** Must `pip install starboard[all]` reproduce today's behavior
    exactly during the transition, or is a major-version break acceptable?
15. **Chargeback/portfolio composition.** `warehouse-portfolio-service` (A3) composes A1 (I/O) +
    P2 (pure). Does it live in the databricks tier or the warehouse tier? (Cross-tier composition
    example that needs a rule.)
16. **service_catalog.yaml ownership.** The cross-domain handoff map (P14, v1.2.0) only matters
    when ≥2 agents are present. Does it ship with the meta bundle, or as its own data package that
    the router loads?
17. **Notebook helpers** (`notebooks.py`, uncommitted). Is notebook-native use a first-class
    surface we should design for, or an internal convenience? Affects whether A5 gets its own unit.

## E. Governance & release

18. **Release cadence.** Lockstep releases initially (simpler) vs independent SemVer per unit
    (more consumable)? When do we decouple a unit's version line?
19. **Test ownership.** Golden/prompt tests (`pytest.ini` markers) currently live centrally. Do
    they move into each unit package, or stay in a shared test suite that imports the units?
20. **Who owns the marketplace repo** and its trust/signing story for external consumers?

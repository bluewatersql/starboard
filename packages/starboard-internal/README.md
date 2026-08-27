# starboard-internal

**Internal distribution only.** Gated internal port adapters for Starboard.

This package is **not** a dependency of any public wheel (`starboard`,
`starboard-core`, `starboard-skills`) and must **never** be published to a
public index. `pip install starboard` from a public index never pulls this
code (Phase-3 exit criterion 5, UNIFIED_PLAN §7).

## What it is

Phase-3 D-3.1 ships the *seam*, not the real adapters: a single **no-op sample
adapter** registered through the public `starboard.port_adapters` entry-point
contract (see `starboard.ports.discovery`). The real internal adapters
(D6 logs/diagnostics, D7 fleet mode, D8 Genie curated rooms) land in later
Phase-3 tasks and register the same way.

## How the seam works

1. This package declares entry points in the `starboard.port_adapters` group.
   Each points at a `PortAdapterProvider` object (`port`, `tier`, `create()`).
2. The public registry calls `starboard.ports.install_entry_point_adapters(...)`,
   which discovers these providers and registers `internal`-tier adapters via
   `PortRegistry.register_internal`.
3. An internal adapter is selected **only** when the enablement gate is open
   (`select_adapter(port, gate_open=True)`). With the gate closed — or with this
   package absent — the public adapter remains the universal path
   (UNIFIED_PLAN §3.5 additive invariant).

## Governance

- No internal namespace, backend id, host, or internal shortlink appears in the sample
  adapter — it is a pure no-op.
- The import-linter contract *"Public packages import no `starboard_internal`"*
  (root `pyproject.toml`) enforces that the dependency edge only ever flows
  internal → public.

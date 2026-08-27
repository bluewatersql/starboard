# starboard-internal

**Internal distribution only.** Gated internal port adapters for Starboard.

This package is **not** a dependency of any public wheel (`starboard`,
`starboard-core`, `starboard-skills`) and must **never** be published to a
public index. `pip install starboard` from a public index never pulls this
code (Phase-3 exit criterion 5, UNIFIED_PLAN §7).

## What it is

The four gated internal adapters (D6/D7/D8), registered through the public
`starboard.port_adapters` entry-point contract (see `starboard.ports.discovery`).
Each is a **strict superset** of its public counterpart — it preserves every
public field and adds enrichment additively (UNIFIED_PLAN §3.5):

| Port | Public adapter | Internal adapter (this package) | Enrichment |
|------|----------------|---------------------------------|-----------|
| `LogRetrievalPort` | `SdkDbfsLogAdapter` (DBFS/Volumes parse) | `LogsSummariserAdapter` (D6) | indexed ClickHouse triage summary + severity |
| `DiagnosticBackendPort` | `NativeDiagnosticAdapter` | `DbrDoctorAdapter` (D6) | dbr-doctor semantic layer + trace-RCA + `hmr_stack_hash` |
| `FleetSqlPort` | `SingleWorkspaceFleetAdapter` (`system.*`) | `CentralizedFleetSqlAdapter` (D7) | `system.*` → centralized cross-account namespace rewrite |
| `NLQueryPort` | `AnalyticsSqlAdapter` (native NL→SQL) | `CuratedGenieRoomAdapter` (D8) | curated Genie rooms |

Real internal-tool/runtime access is external to this repo: each adapter is
driven by an injected backend (tests use stubs/fakes); the zero-arg entry-point
factory builds a default backend that raises unless a live client is wired.

The D7 rewrite (`_namespace_rewrite.py`) keeps the **public query packs
byte-for-byte unchanged** — `system.<schema>.<table>` becomes
`main.centralized_system_tables.<schema>_<table>` entirely inside the adapter.

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

- Internal namespaces, backend ids, hosts, and `go/` shortlinks appear **only**
  in this package (internal-index-only); they are never a dependency of a public
  wheel. A governance test (`tests/test_governance.py`) asserts the **public**
  adapters/packages contain none of them.
- The import-linter contract *"Public packages import no `starboard_internal`"*
  (root `pyproject.toml`) enforces that the dependency edge only ever flows
  internal → public.

# Internal-adapter deployment (Phase-3 O1)

**Internal-index-only.** This document lives inside `starboard-internal` and is
never part of a public wheel. It records the internal endpoints and credentials
that wire the four gated adapters to their real backends, and the guarded
integration run behind the **Internal-env** gate.

> **Additive-gate invariant.** None of this affects the public path. The
> enablement gate is **closed by default** (empty `internal_context_host_allowlist`);
> with the gate closed — or with `starboard-internal` absent — the public adapter
> remains the universal path. Wiring the env below only changes the *internal*
> deployment.

## How wiring works

Each adapter's zero-arg factory (`PortAdapterProvider.create()`) builds its
default backend from the env below:

- **env present** → the **real** backend is constructed (no I/O at construction).
- **env absent** → an *unwired* backend is used whose methods raise a clean,
  actionable `MissingInternalConfigError` naming the exact env vars to set. It is
  **never a silent stub** — an unwired adapter fails loudly with guidance.

`create()` itself never performs I/O and never raises, so the entry-point seam
registers cleanly even with the gate closed.

## Required env by adapter

### D6 — `LogsSummariserAdapter` (`LogRetrievalPort`, logs-summariser / ClickHouse triage)

| Env var | Required | Purpose |
|---|---|---|
| `STARBOARD_INTERNAL_LOGS_SUMMARISER_URL` | yes | Base URL of the logs-summariser triage service. |
| `STARBOARD_INTERNAL_LOGS_SUMMARISER_TOKEN` | yes | Bearer token for the service. |
| `STARBOARD_INTERNAL_LOGS_SUMMARISER_KUBE_CONTEXT` | no | Default `{env}-{cloud}-{region}` kube context. |
| `STARBOARD_INTERNAL_LOGS_SUMMARISER_TIMEOUT` | no | HTTP timeout seconds (default `30`). |

Wire contract: `POST {url}/triage` with the log reference JSON → an indexed-triage
JSON (`text`, `summary`, `severity`, `rows`, `kube_context`).

### D6 — `DbrDoctorAdapter` (`DiagnosticBackendPort`, dbr-doctor semantic layer + trace-RCA)

| Env var | Required | Purpose |
|---|---|---|
| `STARBOARD_INTERNAL_DBR_DOCTOR_URL` | yes | Base URL of the dbr-doctor service. |
| `STARBOARD_INTERNAL_DBR_DOCTOR_TOKEN` | yes | Bearer token for the service. |
| `STARBOARD_INTERNAL_DBR_DOCTOR_TIMEOUT` | no | HTTP timeout seconds (default `30`). |

Wire contract: `POST {url}/classify` → `{candidates: [...]}`; `POST {url}/diagnose`
→ diagnosis JSON (`summary`, `root_causes`, `recommendations`, `confidence`,
`evidence`, `trace_rca`, `hmr_stack_hash`, `analysis_url`).

### D7 — `CentralizedFleetSqlAdapter` (`FleetSqlPort`, centralized cross-account tables)

| Env var | Required | Purpose |
|---|---|---|
| `STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID` | yes | SQL warehouse id governing the centralized tables. |
| `STARBOARD_INTERNAL_FLEET_HOST` | no | Workspace host (else the SDK default credential chain). |
| `STARBOARD_INTERNAL_FLEET_TOKEN` | no | PAT (else the SDK default credential chain). |
| `STARBOARD_INTERNAL_FLEET_CATALOG` | no | Catalog override passed to statement execution. |

The adapter rewrites `system.<schema>.<table>` → the centralized cross-account
equivalent inside the adapter (public query packs stay byte-for-byte unchanged),
then runs the rewritten SQL via the Databricks SDK statement-execution API.

### D8 — `CuratedGenieRoomAdapter` (`NLQueryPort`, curated Genie rooms)

| Env var | Required | Purpose |
|---|---|---|
| `STARBOARD_INTERNAL_GENIE_SPACES` | yes | JSON object mapping curated-room key → Genie space id (e.g. `{"global_genie": "01ef…"}`). |
| `STARBOARD_INTERNAL_GENIE_HOST` | no | Workspace host (else the SDK default credential chain). |
| `STARBOARD_INTERNAL_GENIE_TOKEN` | no | PAT (else the SDK default credential chain). |

Room ids are **not** hard-coded in source; they are resolved from
`STARBOARD_INTERNAL_GENIE_SPACES` at runtime, keyed by the room selectors in
`starboard_internal._genie_rooms`.

## Internal-env integration run (gate: Internal-env)

The guarded integration tests live under
`packages/starboard-internal/tests/integration/`. They **skip** wherever the
`STARBOARD_INTERNAL_*` env is absent, and run only in the internal deployment.

```bash
export PATH="$PWD/.venv/bin:$PATH"
# ... export the STARBOARD_INTERNAL_* env for the adapters under test ...
# Optional live-input overrides:
#   STARBOARD_INTERNAL_LOGS_TARGET_ENTITY / _ID
#   STARBOARD_INTERNAL_DOCTOR_TARGET
#   STARBOARD_INTERNAL_FLEET_TARGET_SQL
#   STARBOARD_INTERNAL_GENIE_TARGET_ROOM / _QUESTION
pytest packages/starboard-internal/tests/integration -q
```

Each test asserts the real backend returns a strict **superset** of the public
port DTO (public-parity fields present + internal enrichment populated). Record
the parity result under the **Internal-env** gate in the phase `OWNER_RUNBOOK.md`.

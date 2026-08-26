# Phase 0 Code Review — Findings

Scope: `git diff 0e42d705 HEAD -- packages/` (A1–A5). Reviewed correctness-first,
with A5 SQL validated against current Databricks system-table docs
(docs.databricks.com / learn.microsoft.com, retrieved 2026-08).

**Verdict up front:** No merge-blockers (nothing crashes discovery or the CLI —
the broken queries are all `required=False` so they degrade per-query). But
**three of the four new A5 query packs reference columns that do not exist in the
real system tables and will fail or silently mislead at runtime**, and there is
one **high** auth-plumbing gap that breaks the REST/lineage paths under exactly
the token-less auth modes A1 introduces. These passed unit + ruff + mypy because
the tests only assert *table names*, never *column names* — no query is executed
against a real schema in CI.

Findings are ranked most-severe first.

---

## HIGH

### H1 — networking pack queries three non-existent columns; never returns data
`packages/starboard/starboard/discovery/query_packs/networking.py:23-35`

`NET_01_SQL` selects/filters on `event_date` and `access_result = 'DENIED'`, but
`system.access.outbound_network` has **no `event_date` column** (only
`event_time timestamp`) and **no `access_result` column** (denials are recorded
in `access_type`, and the value is `'DROP'`, not `'DENIED'`; dry-run rows use a
distinct value).

- Failure scenario: at runtime Databricks raises `UNRESOLVED_COLUMN` for
  `event_date` / `access_result`; the query errors on every workspace. Because
  it is `required=False` the domain is not marked failed, so the networking
  "security posture" signal silently never appears in any report — a permanent
  dead feature that looks healthy.
- Suggested fix:
  ```sql
  SELECT date(event_time) AS event_date,
         destination_type,
         COUNT(*) AS denied_connections,
         COUNT(DISTINCT workspace_id) AS affected_workspaces
  FROM system.access.outbound_network
  WHERE event_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
    AND access_type = 'DROP'
  GROUP BY ALL
  ORDER BY event_date DESC, denied_connections DESC
  LIMIT 200
  ```
  (Confirm the exact denial value for your cloud; docs show `DROP` for real
  denials and a `*_DRY_RUN`/`DRY_RUN_DENIAL` variant for dry-run.)

### H2 — data_classification pack queries two non-existent columns; hard runtime error
`packages/starboard/starboard/discovery/query_packs/data_classification.py:23-36`

`DC_01_SQL` uses `tag_name` (line 29) and `classified_at` (lines 30, 32).
`system.data_classification.results` has neither: the classification tag column
is **`class_tag`**, and the timestamp is **`latest_detected_time`** (with
`first_detected_time` also available). `catalog_name`, `schema_name`,
`table_name`, `column_name` are correct.

- Failure scenario: `UNRESOLVED_COLUMN` on `tag_name` / `classified_at` → query
  errors on every run; classification-coverage insight is never produced.
- Suggested fix: `COUNT(DISTINCT class_tag) AS distinct_classifications`,
  `MAX(latest_detected_time) AS last_classified_at`, and filter
  `WHERE latest_detected_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())`.

### H3 — data_quality pack: non-existent timestamp column + wrong status literal
`packages/starboard/starboard/discovery/query_packs/data_quality.py:23-37`

Two defects in `DQ_01_SQL`:
1. **`evaluated_at` does not exist** (lines 30, 32). The result timestamp is
   **`event_time`**. → hard `UNRESOLVED_COLUMN` error at runtime.
2. **`status = 'FAIL'` is the wrong literal** (line 29). The `status` column
   exists but its domain is `Healthy` / `Unhealthy` / `Unknown`. Even after
   fixing #1, `SUM(CASE WHEN status = 'FAIL' …)` is always 0, so
   `HAVING failed_checks > 0` filters out **every** row — the pack would silently
   report "no data-quality problems" regardless of reality (a false-negative
   landmine, worse than an error).

- Failure scenario: today the query errors (bad column); if only the column is
  fixed, it returns empty forever and masks real DQ incidents.
- Suggested fix: use `event_time` for the window/`MAX`, and
  `SUM(CASE WHEN status = 'Unhealthy' THEN 1 ELSE 0 END) AS unhealthy_snapshots`.
  Note the column is table-level health per snapshot, not a per-check failure
  count — rename the output column to avoid implying "# of failed checks", and
  consider taking the latest row per `table_id` (docs' pattern:
  `ROW_NUMBER() OVER (PARTITION BY table_id ORDER BY event_time DESC)`).

> Note: `predictive_optimization.py` (PO-01) was verified **correct** — every
> column (`operation_type`, `catalog_name`, `schema_name`, `table_name`,
> `start_time`) exists in
> `system.storage.predictive_optimization_operations_history`. 1 of 4 A5 packs is
> right.

### H4 — REST/lineage client still hardcodes host+token; breaks under A1 token-less auth
`packages/starboard/starboard/adapters/databricks/client.py:183-190` and `:344-352`

`_initialize()` now builds the SDK `WorkspaceClient` through the unified resolver
(good), so `host`/`token` are optional. But the raw `httpx.AsyncClient`
(`base_url=self._host or ""`, `Authorization: f"Bearer {self._token}"`) and the
lazily-built `_rest_client` (`HTTPClient(base_url=self._host or "", auth_header={"Authorization": f"Bearer {self._token}"})`)
still read `self._host` / `self._token` directly. Under profile / OAuth-M2M /
`.databrickscfg` / ambient-runtime auth — the very modes A1 exists to enable —
both are `None`, yielding `base_url=""` and a literal `Authorization: Bearer None`.

- Failure scenario: `AsyncDatabricksClient` authenticates fine and SDK-based calls
  (jobs, clusters, warehouses, `execute_sql` via `statement_execution`) work, but
  any REST-based path silently breaks: UC table lineage
  (`get_table_lineage` → `UCCatalogService` via `_rest_client`) and the
  `get_query_history` httpx fallback (`services/sql.py:632`) return 401 / connect
  errors. A user who runs `starboard --profile prod` (no inline token) loses
  lineage with a confusing auth error.
- Suggested fix: after building the SDK client, derive the effective host from
  `self._sdk_client.config.host` and obtain auth via the SDK's authenticated
  session (e.g. `config.authenticate()` headers) instead of a raw
  `Bearer {token}`; or route lineage/query-history through the SDK rather than a
  hand-rolled httpx client. At minimum, fall back to `w.config.host` for
  `base_url`.

---

## MEDIUM

### M1 — resolver precedence "profile > host/token" is documented but not enforced
`packages/starboard/starboard/infra/auth/resolver.py:73-111`

The module docstring promises `explicit --profile > --host/--token`. But
`resolve()` populates `profile` *and* `host`/`token` independently (host/token
come from `cfg`, i.e. `DATABRICKS_HOST`/`DATABRICKS_TOKEN` env), and
`build_config()` forwards **every** truthy field. When a user passes `--profile`
while `DATABRICKS_HOST`+`DATABRICKS_TOKEN` are exported (a very common Databricks
shell setup), `Config(host=…, token=…, profile=…)` receives all three.

- Failure scenario: the SDK either raises
  `ValueError: validate: more than one authorization method configured` (hard
  failure of the advertised `--profile` override), or lets host/token win —
  inverting the documented precedence so `--profile prod` silently keeps hitting
  the env workspace. No test exercises profile + host/token together
  (`test_resolver.py` only tests each in isolation).
- Suggested fix: enforce the stated precedence by subtraction — when `profile`
  (or client-id/secret) is set, drop `host`/`token` from the target before
  `build_config`; add a test for the "profile + ambient host/token" case.

---

## LOW / nits

### L1 — `sync_to_env` registers a new atexit handler on every call
`packages/starboard/starboard/infra/core/config.py:676-688`

`atexit.register(_cleanup_sensitive_env_vars)` runs each time `sync_to_env()` is
called (i.e. every `set_config(..., sync_to_env=True)`). Repeated calls
accumulate duplicate handlers (unbounded closures). Harmless but untidy.
Fix: register once at import/module scope, or guard with a module-level flag.

### L2 — `describe_auth` is dead code in production
`packages/starboard/starboard/infra/auth/resolver.py:133-144`

Only referenced by tests; neither the CLI nor `notebooks.py` calls it, despite
being the documented "safe to log/show" helper. Also `w.current_user.me()` is a
network round-trip, so it is not purely local. Either wire it into the CLI
auth-status output or drop it. (It does correctly redact secrets — no leak.)

### L3 — `--discovery-domains` targeting misses the new packs (pack_id != domain)
`packages/starboard/starboard/discovery/query_packs/registry.py:147-153` +
new packs

`get_packs_for_products` filters `target_domains` on `pack.domain`, but the four
new packs set `domain` to a broad bucket (`networking`/`predictive_optimization`/
`data_classification` → `"governance"`; `data_quality` → `"monitoring"`) while
their `pack_id` is the specific name. Product-route selection (by `pack_id`)
works, but `--discovery-domains networking` returns nothing for the networking
pack (its domain is `"governance"`). Minor UX inconsistency vs. the product route
names.

### L4 — `gating_products` on the new packs is dead metadata
`packages/starboard-core/.../discovery/query.py:119-121`; new packs set
`gating_products={"NETWORKING"}` etc.

`QueryPack.gating_products` is documented as the gate for running a pack, but the
registry routes purely via `PRODUCT_TO_DOMAIN_PACKS` and never reads
`gating_products`. The values set on the new packs are inert. Pre-existing
pattern (other packs do the same) — flagging for consistency only.

### L5 — dev + postgres/databricks backend silently falls back to in-memory
`packages/starboard/starboard/infra/core/state_factory.py:89-107, 228-246`

In `environment="dev"`, only `database_backend == "sqlite"` is special-cased;
`postgres`/`databricks` fall through to the `else` and return an in-memory store
with no warning. Likely pre-existing (not introduced by A3), but a developer
pointing dev at postgres gets memory silently. Also `create_state_store` uses the
`_uc_not_implemented()` helper while `create_memory_store` inlines the identical
message (minor duplication).

---

## What's solid

- **A3 (zero-store default):** correctly done. Only the driver-free in-memory
  adapters are imported at module top; every driver-backed backend lazy-imports
  inside its branch behind `_require`, which raises an actionable
  `pip install 'starboard[<extra>]'`. `memory`/`uc` handled, test-env behavior
  preserved, pyproject moves drivers to extras with an `all-stores` aggregate for
  CI/dev. `test_zero_store_default.py` covers defaults, missing-extra errors, UC
  Phase-2 guard, and packaging. No eager driver import remains.
- **A4 (helper CLI):** clean. Stable envelope, `contract_version`, typed errors
  mapping 1:1 to exit codes, and a custom `ArgumentParser` that funnels argparse
  failures through the same envelope + exit-4 path. Helper modules pull **no**
  heavy imports (stdlib + `starboard_skills` only) — the thin helper stays thin;
  `analyze snapshot` isolates per-domain failures under `errors`.
- **A2 (canonical skills):** frontmatter is valid fenced YAML with
  `name`/`description`/`allowed-tools`; `name == starboard-<domain>`; the richer
  dual-mode (MCP vs helper) body is preserved; duplicate tree removal and the
  9-domain set are enforced by tests. Skills packaged via hatch force-include.
- **A1 core:** `build_config` correctly forwards only set fields (verified by
  test), ambient/no-input resolves to an empty `Config` (SDK chain decides),
  host+token back-compat preserved, `describe_auth` redacts secrets, and
  `validate_config` no longer hard-requires host+token. The resolver is sound for
  the host/token, env-profile, and ambient paths — the gaps are the REST plumbing
  (H4) and the profile-vs-host/token precedence (M1).
- **A5 routing:** `registry.py` route re-pointing (e.g.
  `PREDICTIVE_OPTIMIZATION → predictive_optimization`) and pack registration are
  correct and well-tested; `predictive_optimization.py` SQL is schema-correct.
  The problem is confined to the SQL column names in the other three packs
  (H1–H3).

## Recommendation

Not a blocker for merge (graceful degradation holds), but **H1–H3 should be fixed
before these packs are relied on** — as written, the DQ pack can silently hide
real incidents (H3) and the networking/classification packs are permanently dead.
Add a lightweight schema-validation step (e.g. assert each query's referenced
columns against `information_schema` / a recorded column manifest, or run
`EXPLAIN`/`LIMIT 0` in an integration test) so column drift is caught in CI
rather than in production reports. H4 should be fixed to make A1's token-less auth
actually usable end-to-end (lineage + query history).

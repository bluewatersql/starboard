# Starboard — QA runbook (Phases 0–3 breadth)

Step-by-step QA to comprehensively exercise everything landed across Phases 0–3 (`main` @ `9bb1457f`).
Work top-to-bottom; each step lists the **command**, **expected result**, and a **[ ] pass** box.
Sections 1–2 need only a dev machine; sections 3+ need a Databricks workspace (a non-prod demo such as
`e2-demo-field-eng`) and a model endpoint. **All `$` figures are list-price DBU estimates.**

Legend: 🟢 automated (no workspace) · 🔵 functional (needs workspace) · 🟣 needs model/LLM · 🟠 internal-only.

---

## 0. Prerequisites

```bash
cd /path/to/job-agent
uv sync --all-packages                         # workspace deps (lighter; add --all-extras for heavy)
uv pip install -e packages/starboard-core -e packages/starboard \
               -e packages/starboard-skills -e packages/starboard-internal \
               -e packages/starboard-plugin-sample
```
- [X] `uv run python -c "import starboard, starboard_core, starboard_x, starboard_internal, starboard_skills; print('ok')"` → `ok`
- [X] Databricks auth available for functional steps: a `~/.databrickscfg` profile (e.g. `e2-demo-field-eng`) OR `DATABRICKS_HOST`+`DATABRICKS_TOKEN`. (Isaac/Claude Code inject this; a plain shell may need `databricks auth login`.)

## 1. 🟢 Automated gates (must all be green)

```bash
make lint            # ruff over all packages + tests
make type-check      # mypy packages/starboard/starboard (528 files)
make test-architecture   # import-linter — 4 contracts KEPT
```
- [X] `make lint` → **All checks passed**
- [X] `make type-check` → **Success: no issues found**
- [X] `make test-architecture` → **Contracts: 4 kept, 0 broken** (kernel SDK-free; starboard_x trio stdlib-only; starboard_x pure analyzers SDK-free; **public packages import no `starboard_internal`**)

Run unit suites **separately** (a combined run hits a cross-package basename collision):
```bash
uv run python -m pytest packages/starboard-core/tests/unit/ -q          # ~720 passed
uv run python -m pytest packages/starboard/tests/unit/ -q               # ~3201 passed
uv run python -m pytest packages/starboard-skills/tests/ -q             # ~28 passed
uv run python -m pytest packages/starboard-internal/tests/ -q           # ~39 passed
uv run python -m pytest packages/starboard-plugin-sample/tests/ -q      # ~3 passed
```
- [X] core green · [ ] starboard green · [X] skills green · [X] internal green · [X] plugin-sample green

## 2. 🟢 Governance grep (public artifacts stay clean)

```bash
grep -rniE "centralized_system_tables|fin_live_gold|gtm_|logfood|clickhouse|hmr_stack_hash|go/" \
  packages/starboard packages/starboard-core packages/starboard-skills plugin docs \
  --include=*.py --include=*.md --include=*.yaml --include=*.json | grep -v starboard-internal
```
- [X] **No matches** in public packages/docs/plugin (internal identifiers appear only under `packages/starboard-internal/`).
- [X] `python3 scripts/vendor_plugin_skills.py --check` → **in sync** (plugin skills == canonical tree).

## 3. 🔵 Auth (auth-by-subtraction)

```bash
starboard auth status                                   # resolved identity (redacted)
starboard auth status --profile e2-demo-field-eng
```
- [X] `auth status` prints host / auth_type / user with **no token/secret** shown.
- [ ] `--profile` overrides the resolved workspace; unset → falls through the SDK chain.

## 4. 🔵 Discovery + query packs (public `system.*`)

```bash
python -m starboard_x.discovery run --data-only --profile e2-demo-field-eng
python -m starboard_x.discovery run --data-only --packs finops_billing jobs
```
- [ ] Emits the JSON envelope `{ok, domain, command, data|error, meta}`; `ok=true`; exit 0.
- [ ] Registry has **27 packs** (`create_default_registry`); the 4 Phase-0 system-table packs
  (predictive_optimization, data_quality, data_classification, networking) + warehouse + compute_reliability
  + column_lineage resolve and Preview tables degrade gracefully (`required=False`).
- [ ] `--limit N` on `starboard-helper job list` / `query list` returns **exactly N** (SDK-pagination bug fixed).

## 5. 🔵🟣 Workload Review (flagship, D1b/D1c)

```bash
starboard review --domains jobs,sql,warehouse --profile e2-demo-field-eng
starboard review --domains warehouse --json                       # JSON envelope
starboard review --validate --min-severity medium                 # 🟣 validator council + severity gate
starboard review --snapshot-out /tmp/rev1.json                    # write snapshot
starboard review --since /tmp/rev1.json                           # Action-Rate delta (read-only)
python -m starboard_x.review score --rows rows.json --domains jobs,sql,warehouse   # offline pure scoring
```
- [ ] Produces a **ranked** Finding set: each finding has severity + impact/effort score + remediation +
  **evidence citation** (`query_id` + row); highest-priority first.
- [ ] `--domains` filters; the **jobs** domain returns rules (jobs seed ruleset present).
- [ ] Degraded/empty data → partial findings, **no crash**.
- [ ] 🟣 `--validate` gates findings through the council with a **bounded** pass count (no runaway spend);
  `--min-severity`/`--min-score` suppress sub-threshold findings.
- [ ] `--since` reports a resolved-rate delta and **never writes** the workspace.
- [ ] `$` values are labeled **list-price estimates**.

## 6. 🔵🟣 `genie ask` (NL→SQL, D8-public)

```bash
starboard genie ask "why is my Databricks bill so high?" --profile e2-demo-field-eng --json
```
- [ ] Returns generated SQL + explanation in the JSON envelope; `ok` reflects success; auth failure → exit 1.

## 7. 🔵 `starboard_x` helper trio + analyzers

```bash
python -m starboard_x.diagnostic triage-exit --exit-code 137
python -m starboard_x.diagnostic rca --text err.log --exit-code 137
python -m starboard_x.sparklog parse --text eventlog.json
python -m starboard_x.warehouse analyze --history wh.json
python -m starboard_x.uc analyze --data uc.json
```
- [ ] Each emits the envelope + exit codes (`0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error`).
- [ ] diagnostic/warehouse/uc/review run **out-of-context in pure Python** (no `databricks-sdk` import for the pure analyzers — import-linter enforces this).

## 8. 🟠 Internal-data enablement gate (closed-by-default, additive)

Default (gate closed / internal package absent):
- [ ] For each port (`LogRetrievalPort`, `DiagnosticBackendPort`, `FleetSqlPort`, `NLQueryPort`) the
  **public** adapter is selected and the capability works (parity test: `packages/starboard-internal/
  tests/test_parity.py`).

Gate open (`starboard-internal` installed + employee context + authorized):
- [ ] The **internal** adapter supersedes the public one; enrichment is **additive** (public fields still
  present). With real internal-tool access absent, this is stub-driven (see `open_items.md` O1).
- [ ] `detect_employee_context` is **closed** with an empty allowlist (no host hard-coded); it never
  inspects secrets (`describe_auth` host/user only).

## 9. 🔵 Native state + sessions

- [ ] `database_backend="memory"` is the default; server starts with **no external DB**.
- [ ] `database_backend="uc"` builds UC-native state/memory/user/feedback stores over the resolved
  `WorkspaceClient` (no new credentials); the Phase-0/1 `_uc_not_implemented` stubs are gone.
- [ ] CLI sessions persist as **JSON** (no `aiosqlite` on the hot path); resume by fixed `SESSION_NAME`.
- [ ] `deprecated` `database_backend="databricks"` still resolves (aliased → `lakebase`) with one warning.

## 10. 🔵 Reach & distribution

```bash
scripts/dev_plugin_local.sh add        # register ./plugin under isaac plugin dev + enable
isaac --claude                         # start a session; confirm skills are injected (no MCP)
scripts/dev_plugin_local.sh remove     # cleanup
```
- [ ] Plugin registers + skills inject under Isaac; a skill (`workload-review`, `starboard-discovery`)
  triggers and shells `python -m starboard_x.<cap>` **with no permission prompt**.
- [ ] Skills-only default: no MCP server is started (plugins are not MCP servers).
- [ ] Layered catalog: installing only the kernel tier works; a per-domain plugin registers a tool via the
  `starboard.*` entry point and is discovered (`packages/starboard-plugin-sample/tests`).
- [ ] `databricks aitools` format documented; canonical skills tree feeds both channels.

## 11. 🔵🟣 Example notebooks (in Databricks)

Import each into a Databricks workspace and Run All:
- `examples/Starboard AI Agent.ipynb` (query/job tuning)
- `examples/Starboard AI Agent - Workspace Discovery.ipynb`
- [ ] `%pip install` resolves from `github.com/databricks-field-eng/starboard` (canonical repo).
- [ ] Widgets render; `get_workspace`/`resolve_warehouse`/`start_warehouse`/`list_serving_endpoints`
  resolve; `StarboardClient.from_env()` + `create_session()` run; a review/discovery response renders;
  `client.close()` releases resources. Model dropdown defaults to `databricks-claude-opus-4-8`.

## 12. Sign-off

- [ ] §1 automated gates all green (lint / type-check / import-linter / 5 suites).
- [ ] §2 governance grep clean; plugin skills in sync.
- [ ] §3–§7 public-path functional checks pass on the demo workspace.
- [ ] §8 gate parity holds (closed-by-default; additive when open).
- [ ] §9–§10 state/sessions/reach verified.
- [ ] §11 both notebooks run end-to-end.
- [ ] Known non-blocking gaps acknowledged (see [`open_items.md`](./open_items.md): internal adapters
  stub-driven O1; managed-VS opt-in O2; council/OBO live-validation O3/O4).

**QA owner:** ________  **Date:** ________  **Build:** `9bb1457f`  **Result:** ☐ pass ☐ pass-with-notes ☐ fail

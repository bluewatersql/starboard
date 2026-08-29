# Wave 4 QA Runbook

End-to-end quality-assurance procedure for the **Wave 4 ("Agent Experience & Expansion")**
release of Starboard. Run it before promoting `main` to a customer-facing or internal
deployment, and again after any hotfix on top of Wave 4.

It is organised so that everything that can be verified **without a live Databricks
workspace runs first** (Parts A–B, fully reproducible in CI), followed by the three
**owner-gated live validations** (Part C) that require real environments, then the
**negative/regression** checks (Part D) and **rollback** procedure (Part E).

> **Cost labelling reminder.** Every `$` figure on the public path is a **list-price DBU
> estimate**. QA must confirm outputs carry that label (`LIST_PRICE_DISCLAIMER`) and never
> present list-price as finance-grade cost.

---

## How to use this runbook

- Work top to bottom. Each check states its **command**, **expected result**, **pass
  criterion**, and **on failure** action.
- Record each outcome in the [sign-off matrix](#sign-off-matrix) at the end.
- A `[GATE]` badge marks an owner-gated step that needs a live environment and cannot pass
  in CI — record it as `n/a (offline)` when running the offline pass.
- Stop and escalate on any **red-line** failure (governance leak, kernel-purity break,
  capability regression). These are release-blocking by definition.

---

## Preconditions

```bash
cd /path/to/job-agent
export PATH="$PWD/.venv/bin:$PATH"     # ruff / mypy / pytest / mkdocs live here
make setup                             # first-time only: uv venv + editable installs
```

Confirm you are on the release commit:

```bash
git rev-parse --abbrev-ref HEAD        # expect: main (post-merge) or wave4/phase0
git log --oneline -1                   # expect the Wave 4 tip
```

Databricks profile (Parts B–C only): **never auto-select**. Pass `--profile <name>`
explicitly, or set `STARBOARD_WORKSPACE` / `DATABRICKS_CONFIG_PROFILE`, and let the
operator choose the target workspace.

---

## Part A — Offline QA gates (no workspace required)

This is the CI-grade gate. All of Part A must be green before any live validation.

### A1 — The core gate

```bash
make check          # lint + type-check + test-unit + test-architecture
```

- **Expected:** ruff clean, mypy clean, unit suites pass (core + starboard), import-linter
  reports **4 contracts KEPT**.
- **Pass:** exit 0. Read the real result from the make output — do **not** trust a wrapper
  "exit 0" if the log shows failures; grep the tail for `FAILED`/`error:` before declaring green.
- **On failure:** triage by stage (`make lint`, `make type-check`, `make test-unit`,
  `make test-architecture`) and fix at the source; never suppress a contract.

### A2 — Extended test suites

```bash
make test-integration          # package + cross-package integration
make test-golden               # tests/golden/  (prompt/schema snapshots)
make test-contract             # tests/contract/ (output contracts)
make test-architecture-guidelines   # pytest tests/architecture/ (GUIDELINE-* suite)
make test-distribution         # skills mirror + OpenCode bundle drift
```

- **Expected:** all pass; golden snapshots match (no unreviewed prompt drift).
- **Pass:** each target exits 0.
- **On failure (golden):** if a prompt/schema change was intentional, review the diff and
  regenerate deliberately; otherwise it is a regression — fix the source.

### A3 — Documentation build (`--strict`)

```bash
python -m mkdocs build --strict
```

- **Expected:** builds with **zero warnings** (strict turns warnings into errors). Every
  page — including this runbook — is wired into `mkdocs.yml` nav.
- **Pass:** exit 0, `site/` produced.
- **On failure:** a new doc not in nav, a broken internal link, or a missing include. Wire
  it into nav or fix the link.

### A4 — Generator / drift `--check` guards

Every generated artifact ships with a drift guard. Each must report **in sync** (exit 0)
against the committed tree — proving the checked-in output matches what the generator would
produce now.

```bash
python scripts/vendor_plugin_skills.py --check   # plugin/ mirrors canonical skills
python scripts/skills.py --check                 # databricks aitools mirror
python scripts/port_to_opencode.py --check       # OpenCode bundle
python scripts/gen_rulesets.py --check           # per-domain rulesets
python scripts/gen_agents.py --check             # agent definitions
python scripts/gen_catalog.py --check            # docs/reference/CATALOG.md + INDEX pages
python scripts/validate_examples.py --check      # hero workflows / personas / validated examples
```

- **Expected:** each prints an in-sync / no-drift result and exits 0.
- **Pass:** all exit 0.
- **On failure:** the checked-in artifact is stale. Re-run the generator **without**
  `--check` to regenerate, review the diff, and commit. (A common cause: a canonical
  `SKILL.md` was edited but the plugin/aitools/opencode copies were not re-vendored.)

### A5 — Governance red-line grep (release-blocking)

No internal namespaces may appear anywhere in the **public** tree. These live only in
`packages/starboard-internal/**`.

```bash
grep -rnI -E \
  'centralized_system_tables|fin_live_gold|gtm_|eng_|logfood|hmr_stack_hash|clickhouse' \
  packages/starboard packages/starboard-core packages/starboard-skills docs plugin \
  --include='*.py' --include='*.md' --include='*.yaml' --include='*.yml' --include='*.json'
```

- **Expected:** the only hits are **guard-lists** in tests that assert these tokens are
  *absent* (e.g. `assert ns not in text`). No live reference in shipped code, docs, or
  skill/plugin bundles.
- **Pass:** zero substantive matches after excluding guard-list assertions.
- **On failure:** a real leak — **release-blocking**. Move the reference into
  `starboard-internal` and re-run.

### A6 — Import-linter contracts (explicit)

```bash
lint-imports        # equivalently: make test-architecture
```

- **Expected / Pass:** 4 contracts **KEPT**:
  1. Kernel free of `databricks-sdk` / `openai` / `fastapi` / `mcp`.
  2. `starboard_x` diagnostics-core trio is stdlib-only.
  3. `starboard_x` pure analyzers (`warehouse` / `uc` / `review` / `cluster` / `charts`) are SDK-free.
  4. Public packages import no `starboard_internal`.
- **On failure:** a purity/boundary break — **release-blocking**. Fix the offending import.

---

## Part B — Surface smoke tests

Prove each shipped surface loads and its help/entry points resolve. `--help` paths need no
workspace; the `starboard-internal` suite runs offline (guarded).

### B1 — CLI entry points

```bash
starboard --help
starboard review --help          # confirm --validate and --min-severity flags present
starboard genie ask --help
starboard auth --help
```

- **Pass:** each prints help and exits 0; `starboard review --help` shows the opt-in
  `--validate` (validator council) and `--min-severity` flags.

### B2 — Progressive helpers (`python -m starboard_x.<cap>`)

```bash
python -m starboard_x.review --help
python -m starboard_x.cluster --help
python -m starboard_x.charts --help
python -m starboard_x.warehouse --help
python -m starboard_x.uc --help
```

- **Pass:** each resolves and prints help (these are the dep-light kernel tiers; they must
  import without the SDK).

### B3 — MCP server

```bash
starboard-mcp --help
```

- **Pass:** the stdio MCP server entry point resolves.

### B4 — Tool registry invariant (DOC-12)

```bash
python -c "from starboard.agents.tools.registry import ALL_TOOL_METADATA as m; print(len(m)); assert len(m)==59, len(m); assert 'get_cluster_rightsizing' in m and 'get_workload_rightsizing' in m; print('OK')"
```

- **Pass:** prints `59` then `OK` (the Wave 4 tool count; both right-sizing tools present).
  If the tool set changed intentionally, update the invariant test **and** the DOC-12 count
  together, then adjust this step.

### B5 — Internal package (offline, guarded)

```bash
cd packages/starboard-internal && pytest -q ; cd -
```

- **Pass:** the gated-adapter parity suite passes (some tests skip when live backends are
  absent — skips are expected offline).

---

## Part C — Live gated validations (owner)

These require real environments and cannot pass in CI. Each landed **build-complete +
fake-tested**; the gate confirms the live behaviour. Record every result in the
owner runbook (`changes/2026_26_27_agents/plans/OWNER_RUNBOOK.md`) and here.

### C1 `[GATE]` Validator council — live model run (G5)

**What it validates:** the multi-model validator council resolves real model ids, votes,
and gates findings on a live review.

**Owner:** AI-platform. **Prereq:** model-serving/AI-gateway access to the council models.

**Steps.**

```bash
# Comma-separated list; ids come from the model-serving catalog / AI gateway (dynamic).
export STARBOARD_REVIEW_COUNCIL_MODELS="databricks-claude-opus-4-8m,databricks-claude-sonnet-4-6,databricks-claude-haiku-4-5"
# Optional tuning:
export STARBOARD_REVIEW_COUNCIL_MAX_PASSES=3    # bounded; ceiling enforced in code
# export STARBOARD_REVIEW_COUNCIL_SEED=42       # for reproducible ordering

starboard review --profile <name> --validate --min-severity medium <target>
```

- **Expected:** the review runs, the council convenes over the configured ids, each finding
  carries a verdict trail (`keep_ratio`, `passes_used`, per-model verdicts), and the
  severity gate filters below `--min-severity`.
- **Pass:** findings surface **with** council verdicts; no model-resolution error; if a
  model id is unavailable the run degrades gracefully (surfaces findings without council)
  rather than crashing.
- **Precedence to verify:** `STARBOARD_REVIEW_COUNCIL_MODELS` → `..._MODEL` →
  `config.llm_model` → built-in default.
- **Record:** chosen model ids, `max_passes`, and observed keep-ratios in the owner runbook
  §G5 and the workload-review docs.

### C2 `[GATE]` Databricks Apps OBO — multi-tenant (App-env / O4)

**What it validates:** per-request auth on behalf of the end user via the forwarded token.

**Owner:** App/platform. **Prereq:** a multi-tenant Databricks App deployment; App SP has
"Can Use" on the SQL Warehouse and "Can Browse" on Unity Catalog; `app.yaml` OBO scopes
declared; warehouse id in secrets.

**Steps.**

1. Deploy Starboard as a Databricks App (`app.yaml` command runs `starboard.main:create_app`).
2. Issue a request **as an end user** so the platform injects `X-Forwarded-Access-Token`.
3. Confirm the resolved client identity is the **end user**, not the App service principal:

```bash
# From the App logs (STARBOARD_LOG_JSON=true), find the per-request identity line:
#   event="obo_request_identity"  user="<end-user>"  auth_type=...  host=...
# It must show the calling user — and MUST NOT contain a token/secret field.
```

- **Expected:** `get_obo_client` reads the forwarded header and authenticates with the
  user's token directly (canonical Apps OBO); UC/Genie grants resolve per user; two
  concurrent users get **distinct** per-request clients (no identity bleed).
- **Pass:** identity logs show the end user; a request **without** the header (non-App path)
  still returns the ambient client unchanged; **no token value** appears in any log.
- **Record:** result in owner runbook §App and `docs/DEPLOYMENT.md` §"Databricks Apps OBO Auth".

### C3 `[GATE]` Internal adapters — live-backend parity (Int / O1)

**What it validates:** the gated internal adapters (`log_retrieval`, `diagnostic_backend`,
`fleet_sql`, `nl_query`) enrich — never reduce — their public counterparts, and the public
path stays fully functional with the gate **closed**.

**Owner:** internal deploy. **Prereq:** internal deployment with `starboard-internal`
installed and real backends reachable. See
`packages/starboard-internal/docs/INTERNAL_DEPLOYMENT.md`.

**Steps.**

1. In the internal env, populate `internal_context_host_allowlist` (config-driven, **empty
   by default**) with the internal workspace host(s), and provision the real backends.
2. Run the guarded internal integration tests against live backends:

```bash
cd packages/starboard-internal && pytest -q -m integration ; cd -
```

3. Confirm the **additive-gate invariant**: with the allowlist **empty**, the public
   adapter is selected and the full public path works; with it populated + authorized, the
   internal adapter is selected and returns a **superset** of the public result.

- **Expected:** internal adapters return live data; each is a strict enrichment of the
  public path; closing the gate (empty allowlist, or removing `starboard-internal`) leaves a
  fully-functional public deployment.
- **Pass:** integration tests pass live; gate-closed public path verified functional
  (re-run Part A A6 contract 4 to confirm public packages still import no `starboard_internal`).
- **Record:** result in owner runbook §Int.

---

## Part D — Negative & regression checks

Prove the safety defaults hold. These run offline.

- **D1 — OBO non-App path unchanged.** A request with no `X-Forwarded-Access-Token` returns
  `None` from `get_obo_client` and never calls `resolve_user_client`. Covered by
  `packages/starboard/tests/unit/infra/auth/test_app_obo_dependency.py::TestNonAppPathUnchanged`.
- **D2 — Internal gate closed by default.** With an empty `internal_context_host_allowlist`
  and no env markers, `detect_employee_context(...).gate_open` is `False` (public path).
- **D3 — Read-only advisory.** The cluster monitor and Workload Review **propose only** and
  never mutate workspace state (D-b write-back is deferred to the next wave). Confirmed by
  the report-only monitor tests.
- **D4 — DBU-only query packs.** Query packs emit DBU; the `$` list-price projection is
  applied only at the tool layer. No pack references a `cost_usd`/list-price column directly.
- **D5 — Secrets never logged.** `describe_auth` exposes only host/auth_type/profile/user —
  never a token. Covered by the OBO audit-log tests.

Run the focused regression set:

```bash
pytest packages/starboard/tests/unit/infra/auth/test_app_obo_dependency.py \
       packages/starboard/tests/unit/tools/services/test_validator_council.py \
       packages/starboard/tests/unit/tools/adapters/test_cluster_rightsizing_tools.py -q
```

- **Pass:** all pass.

---

## Part E — Rollback / abort

Wave 4 lands as a fast-forward from the previous `main` tip. If a release-blocking defect is
found **after** promotion:

```bash
# Identify the pre-Wave-4 baseline (the commit main pointed at before the merge).
git log --oneline --first-parent main | head -20

# Option 1 — move main back to the baseline (coordinate; force-push only with owner sign-off).
git checkout main
git reset --hard <pre-wave4-baseline>      # e.g. 05edb666
git push --force-with-lease origin main

# Option 2 — revert the merge/commits forward (preferred when others have pulled).
git revert --no-commit <wave4-range>
git commit -m "revert: roll back Wave 4 pending QA fix"
git push origin main
```

Prefer **Option 2** (revert-forward) once the branch is shared. See
`docs/runbooks/rollback_template.md` for the general procedure and comms steps.

Deployed surfaces:

- **CLI / MCP:** roll back the installed wheel/plugin version.
- **Databricks App:** redeploy the prior App revision.
- **Internal adapters:** setting `internal_context_host_allowlist` back to empty instantly
  reverts to the public path without a redeploy (the gate is additive and closed-by-default).

---

## Sign-off matrix

| # | Check | Command / evidence | Result | Owner | Notes |
|---|-------|--------------------|--------|-------|-------|
| A1 | Core gate | `make check` | ☐ | | 4 contracts KEPT |
| A2 | Extended suites | `make test-integration/golden/contract/architecture-guidelines/distribution` | ☐ | | |
| A3 | Docs `--strict` | `mkdocs build --strict` | ☐ | | zero warnings |
| A4 | Generator drift | 7× `--check` guards | ☐ | | all in sync |
| A5 | Governance grep | red-line grep | ☐ | | **release-blocking** |
| A6 | Import contracts | `lint-imports` | ☐ | | 4 KEPT |
| B1–B4 | Surface smoke | CLI / `python -m` / MCP / registry(=59) | ☐ | | |
| B5 | Internal pkg offline | `pytest` in `starboard-internal` | ☐ | | skips expected |
| C1 | `[GATE]` Council live | `starboard review --validate` | ☐ | AI-platform | record model ids |
| C2 | `[GATE]` Apps OBO | App identity logs | ☐ | App/platform | user, not SP |
| C3 | `[GATE]` Internal parity | `pytest -m integration` (internal) | ☐ | Internal deploy | additive invariant |
| D1–D5 | Negative/regression | focused pytest set | ☐ | | safety defaults |

**Release decision:** ☐ Go ☐ No-go — _signed_ ________________ _date_ __________

---

## References

- Owner gates & who owns them: `changes/2026_26_27_agents/plans/OWNER_RUNBOOK.md` (repo root)
- Testing structure & markers: [Testing Guide](../TESTING.md)
- Operational runbook & templates: [Runbook](../RUNBOOK.md), [Rollback template](rollback_template.md), [Incident template](incident_template.md)
- Deployment (incl. Apps OBO): [Deployment](../DEPLOYMENT.md)
- Internal deployment: `packages/starboard-internal/docs/INTERNAL_DEPLOYMENT.md`

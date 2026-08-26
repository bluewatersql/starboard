# Phase 0 — Foundations: Detailed Implementation Plan

> Execution-ready plan for the 5 foundation items (A1–A5) from
> [`../UNIFIED_PLAN.md`](../UNIFIED_PLAN.md) § Phase 0. Design detail is drawn from each topic's
> `technical.md`; this plan turns it into ordered tasks with file targets, TDD test plans,
> acceptance criteria, and back-compat rules. **Baseline: starboard 0.1.1 @ `b927dfaa`.**
>
> Anchors below were spot-verified against current code on 2026-08-26.

## 0. Goal & definition of done (phase-level)

**Goal:** ship the shared substrate everything else builds on, plus immediate customer-visible data
value — with **no capability regressions** and **no new required dependencies**.

**Phase-0 exit criteria (all must hold):**
1. `pip install starboard` (default, no extras) pulls **no** `redis`/`asyncpg`/`pgvector`/`aiosqlite`/`sqlite-vec`. *(A3)*
2. Auth resolves with **only** what's provided — PAT, profile, env, or ambient — and **no forced host+token**; existing `--databricks-host/--databricks-token` + env still work. *(A1)*
3. **One** canonical skill tree; every `SKILL.md` has valid fenced YAML frontmatter. *(A2)*
4. `starboard-helper` emits a **stable JSON envelope** with documented exit codes; all 9 skills map 1:1 to CLI verbs. *(A4)*
5. The 4 previously-empty product routes (Predictive Optimization, Data Quality, Data Classification, Networking) resolve to packs that **actually query their system table**. *(A5)*
6. Repo-wide gates green: `ruff`, `mypy`, `pytest` (see §8).

**Phase 0 is unblocked** — the one gating unknown (does Isaac inject auth onto the SDK chain?) is a Phase-1 concern.

## 1. Guardrails (apply to every task)

- **TDD:** write the failing test(s) first, then implement to green. Each task lists its tests.
- **Additive / back-compat:** nothing that works today may break. Old flags, env vars, and store
  backends keep working (backends move behind extras with an actionable error if missing).
- **No capability regression** — consistent with the UNIFIED_PLAN gate invariant.
- **Verification per task:** `ruff check`, `mypy`, and the task's pytest selection must pass before the task is "done".
- **Evidence:** cite `file:line`; reference the topic `technical.md` rather than re-deriving design.

## 2. Branch & PR strategy

Five small, independently reviewable PRs off `main`, in the dependency order of §7:

| PR | Item | Branch | Rough size |
|----|------|--------|-----------|
| 1 | A3 zero-store default | `phase0/zero-store-default` | S |
| 2 | A5 four query packs | `phase0/system-table-packs` | S |
| 3 | A1 auth resolver | `phase0/auth-resolver` | S–M |
| 4 | A2 skill de-dup + frontmatter | `phase0/canonical-skills` | S |
| 5 | A4 CLI helper hardening | `phase0/helper-cli-contract` | S–M |

PRs 1–2 and 4–5 are mutually independent; PR 3 (A1) and PR 1 (A3) both touch `infra/core/config.py`
— sequence PR 1 before PR 3 (or coordinate the two config edits). Each PR: reviewed with `/review`,
tests green, then merged.

## 3. Decisions to lock before coding (small)

| # | Decision | Recommendation |
|---|----------|----------------|
| D-0.1 | Canonical skills location | `packages/starboard-skills/skills/starboard/<domain>/SKILL.md` (the package that ships them); delete the `packages/starboard/skills/` copy; server references the package. |
| D-0.2 | `database_backend` default | `memory` (dev/default); `sqlite` still selectable via `starboard[sqlite]`. Add `uc` literal now (impl lands Phase 2 C2). |
| D-0.3 | `vector_backend` default | `inmemory` (no external store, keeps embeddings) — **not** `none`; the reference-file path (`none`) is Phase 2 C1. |
| D-0.4 | Genie verb in A4 | **Defer** `genie ask` to Phase 3 (D8). A4 adds `analyze` + `discovery` verbs only. |
| D-0.5 | Rename `databricks`→`lakebase` backend | **Defer** to Phase 2 (C2). Phase 0 leaves `databricks` untouched to avoid churn. |

---

## 4. Task A1 — Auth by subtraction

**Source design:** `databricks_auth/technical.md` §3–4. **Objective:** one resolver builds every
`WorkspaceClient`; host/token become optional; delegate to the SDK unified credential chain.

**Files:**
| File (anchor) | Change |
|---|---|
| `infra/auth/resolver.py` (new) | `WorkspaceTarget` dataclass + `resolve()` (precedence), `build_config()` (pass only set fields), `resolve_workspace_client()`, `describe_auth()` (redacted) |
| `adapters/databricks/client.py:157` | replace `WorkspaceClient(host=self._host, token=self._token)` with `resolve_workspace_client(WorkspaceTarget.resolve(host=…, token=…, cfg=…))`; keep `_verify_auth()` |
| `infra/core/config.py:320-334` | make host/token **optional**; validate only that *some* auth is resolvable; keep offline-mode exemption |
| `cli/cli/main.py` (~892, ~1338) | add `--profile/--client-id/--client-secret/--auth-type`; alias `--host`/`--token`; replace hard exit with resolver attempt + one actionable error |
| `notebooks.py:46-62` | make `host/token` optional (keyword `profile`); fall through to `resolve_workspace_client()`; keep positional back-compat |

> Scope note: the `starboard auth login` + `workspace list/use` subcommands are **Phase 2** (R2/R3), not A1.

**Back-compat:** `--databricks-host/--databricks-token` and `DATABRICKS_HOST/TOKEN` still resolve
(PAT is just first in the SDK chain). `mcp/config.py` `WorkspaceProfile` untouched in Phase 0.

**Tests (write first)** — `tests/unit/infra/auth/test_resolver.py`:
- precedence: `--profile` > inline host/token > `STARBOARD_WORKSPACE` > `DATABRICKS_CONFIG_PROFILE` > env host/token > ambient
- `build_config` omits unset fields (no empty host/token injected)
- `describe_auth` redacts secrets (only host/auth_type/profile/user)
- back-compat: host+token path still yields a client
- ambient: no inputs → `WorkspaceClient()` via chain (mock `Config`)
- config validation: missing host/token no longer errors when a profile/ambient path exists; still errors (actionable msg naming `--profile`) when nothing resolves

**Acceptance:** `starboard --profile X` and bare `starboard` (ambient) both build a client; PAT path
unchanged; validation no longer hard-requires token. **LOE: S–M.**

---

## 5. Task A2 — Collapse skill duplication + fenced frontmatter

**Source design:** `agent_integration/technical.md` §1.4; `starboard_decomposition/opportunities.md` §3.
**Objective:** one canonical, valid-frontmatter skill tree. Fixes the verified drift: top-level
`SKILL.md` open with a bare `name:` (no `---` fence); `packages/starboard-skills/.../skill.md` open
with `# Starboard: …` and **no frontmatter**.

**Files:**
| File | Change |
|---|---|
| `packages/starboard-skills/skills/starboard/<domain>/SKILL.md` (canonical, ×9) | rename `skill.md`→`SKILL.md`; add fenced YAML frontmatter: `name`, `description` (drives auto-invoke), `allowed-tools: Bash(starboard-helper:*), Read`; keep existing dual-mode body |
| `packages/starboard/skills/` | **delete** (duplicate); server references the skills package |
| build/packaging | ensure the wheel/plugin **vendors** the canonical tree (no hand copy) |

**Tests (write first)** — `tests/unit/skills/test_skill_frontmatter.py`:
- every `SKILL.md` parses as fenced YAML with required `name` + `description`
- exactly one skills tree exists (no `packages/starboard/skills/` copy)
- `allowed-tools` present on each
- (optional) `name` matches its directory

**Acceptance:** `find` shows one skill tree; all 9 parse; `diff` between any two vendored copies is
empty (built, not hand-copied). **LOE: S.**

---

## 6. Task A3 — Zero-store default

**Source design:** `native_simplification/technical.md` §1, §6. **Objective:** default install carries
no external-store drivers; Protocol layer preserved; backends become opt-in extras with actionable errors.

**Files:**
| File (anchor) | Change |
|---|---|
| `packages/starboard/pyproject.toml:51-57` | move `redis`, `asyncpg`, `pgvector`, `aiosqlite`, `sqlite-vec` out of `[project.dependencies]` into `[project.optional-dependencies]`: `sqlite`, `postgres`, `redis`, `memory`, `vectorsearch`, `all-stores` |
| `infra/core/config.py:128` | `database_backend`: add `"memory"`,`"uc"` literals; default → `"memory"` (D-0.2) |
| `infra/core/config.py:145` | `vector_backend`: default → `"inmemory"` (D-0.3); keep `sqlite` selectable |
| `infra/core/config.py:320-334` | don't require `DATABASE_URL` for `memory`/`uc`; keep redis guard |
| `infra/core/state_factory.py` | lazy-import guard `_require(mod, extra=…)` → actionable `pip install starboard[<extra>]` error when a backend's driver is absent |
| `infra/rag/services/vector_store_factory.py` | same guard for `sqlite`; `inmemory` is the driver-free default |

**Back-compat:** `database_backend=sqlite|postgres|databricks` all keep working **iff** the matching
extra is installed; otherwise a clear error. `databricks` backend literal untouched (D-0.5). Default
dev experience: in-memory (ephemeral) — durable UC state is Phase 2 (C2).

**Tests (write first)** — `tests/unit/infra/core/test_zero_store_default.py`:
- default `EnvConfig` → `database_backend=memory`, `vector_backend=inmemory`, `cache_backend=memory`
- `create_state_store(default)` returns `InMemoryStateStore` with **no** driver import
- selecting `sqlite` without the extra raises the actionable install error (simulate missing module)
- validation: default config validates with no `DATABASE_URL`/`REDIS_URL`
- packaging: assert the 5 store deps are absent from `[project.dependencies]` (parse pyproject)

**Acceptance:** fresh `pip install .` (no extras) imports and runs the CLI + in-memory server with no
store drivers; each backend still works behind its extra. **LOE: S.**

---

## 7. Task A4 — Harden `starboard-helper` CLI contract

**Source design:** `agent_integration/technical.md` §0; `progressive_helpers/technical.md` §3.
**Objective:** a stable JSON envelope + documented exit codes; add `analyze` + `discovery` verbs so
all 9 skills map 1:1 to CLI verbs.

**Files:**
| File | Change |
|---|---|
| `packages/starboard-skills/starboard_skills/helpers/__main__.py` | wrap every command's output in a stable envelope `{ "ok": bool, "domain","command","data"|"error","meta" }`; centralize exit codes `0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error`; add `--format json` (default) |
| `helpers/analyze.py` (new) | `analyze` verb: composes existing domain fetchers into a combined payload (maps the `starboard-analyze` skill) |
| `helpers/discovery.py` (new) | `discovery` verb: lists/summarizes available domains + entry points (maps the `starboard-discovery` skill) — data-only; the heavy discovery engine stays Tier-1/2 |

> `genie ask` is **deferred** (D-0.4). No starboard-package dep added here — helper stays thin (bare `WorkspaceClient()`).

**Tests (write first)** — `tests/unit/helpers/test_cli_contract.py`:
- every verb emits the envelope; `ok=true` + `data` on success
- exit codes: mock `WorkspaceClient` to raise → 1 (auth), 2 (not-found), 3 (api); bad args → 4
- `analyze` and `discovery` verbs exist and return valid envelopes
- the 9 skills' documented commands all resolve to a real verb (parse SKILL bodies)

**Acceptance:** `starboard-helper <domain> <cmd>` returns the envelope with correct exit codes;
`analyze`/`discovery` exist; skill→verb mapping is 1:1. **LOE: S–M.**

---

## 8. Task A5 — Four system-table query packs (fix mapped-but-empty routes)

**Source design:** `starboard_optimization/technical.md` §1. **Objective:** the 4 product routes that
resolve to a pack which never queries their table now query it. Verified routes in
`discovery/query_packs/registry.py`: `DATA_QUALITY_MONITORING→["monitoring"]` (:45),
`PREDICTIVE_OPTIMIZATION→["governance"]` (:47), `DATA_CLASSIFICATION→["governance"]` (:48),
`NETWORKING→["governance"]` (:51).

**Files:**
| File | Change |
|---|---|
| `discovery/query_packs/predictive_optimization.py` (new) | pack over `system.storage.predictive_optimization_operations_history` |
| `discovery/query_packs/data_quality.py` (new) | pack over `system.data_quality_monitoring.table_results` |
| `discovery/query_packs/data_classification.py` (new) | pack over `system.data_classification.results` |
| `discovery/query_packs/networking.py` (new) | pack over `system.access.{inbound,outbound}_network` |
| `discovery/query_packs/registry.py:17-51` | repoint the 4 routes to the new packs |
| `discovery/query_packs/registry.py:190` | register the 4 in `create_default_registry()` |

**Design rules:** use the `SystemQuery`/`QueryPack` model; set **`required=False`** for Preview/Beta
tables so a missing table degrades the *query*, not the domain. Follow the exact template in
`starboard_optimization/technical.md` §1.1.

**Tests (write first)** — `tests/unit/discovery/test_new_packs.py`:
- each pack imports and constructs; `required_tables` names the intended system table
- SQL templates render with test params (no `{unfilled}` placeholders); parse via the existing validator
- `create_default_registry()` includes the 4 packs
- each of the 4 products routes to a pack whose `required_tables` includes its target table (regression against the "empty route" bug)
- `required=False` on Preview/Beta queries

**Acceptance:** the 4 products produce real findings against their system tables; graceful degrade when
a Preview table is absent. **LOE: S.**

---

## 9. Task ordering & dependency graph (within Phase 0)

```
A3 zero-store ──(config.py first)──► A1 auth resolver     (both edit config.py; sequence A3→A1)
A5 packs        ─ independent ─► (ship anytime)
A2 skills       ─ independent ─► (ship anytime)
A4 helper CLI   ─ independent ─► (ship anytime)
```

Suggested execution order (fastest visible value first, minimize config.py collisions):
**A5 → A3 → A1 → A2 → A4** (A5/A2/A4 can also run in parallel with the A3→A1 line).

## 10. Verification & Definition of Done

Per PR and for the phase:
- `uv run ruff check .` — clean
- `uv run mypy packages/…` — clean (respect existing per-module ignores; `log_parser` stays excluded)
- `uv run pytest` for the touched package(s) — green, including the new TDD tests
- New/changed public behavior documented (help text, env example, skill bodies)
- Reviewed with `/review` before merge
- Phase-0 exit criteria §0 (1–6) all demonstrably met

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Moving store deps to extras breaks an install that silently relied on them | Actionable lazy-import error + `all-stores` extra; document in README/env example; test the missing-extra path |
| `config.py` edited by both A3 and A1 | Sequence A3→A1; small, reviewable diffs |
| Skill de-dup breaks a consumer importing the old path | Server references the skills package; grep for imports of `packages/starboard/skills` before deleting |
| New Preview/Beta tables absent in a target workspace | `required=False` degrade-gracefully; covered by tests |
| DBR 17.3 dep pins interact with new extras | Default wheel gets *smaller*; re-validate only the extras' transitive pins before release |

## 12. Explicitly out of scope for Phase 0 (deferred)

- `starboard auth login` / `workspace list|use` subcommands → Phase 2 (R2/R3)
- UC-native state adapter, `database_backend=uc` impl, `databricks`→`lakebase` rename → Phase 2 (C2)
- RAG → reference files (`vector_backend=none`) → Phase 2 (C1)
- `starboard-x` dep-ful helpers, kernel carve-out, plugin/marketplace → Phase 1 (B1–B4)
- `genie ask` verb → Phase 3 (D8)
- Internal-data enablement gate (C5) → Phase 2 interfaces / Phase 3 adapters

# Phase 1 — Packaging, Tiers & No-Server Distribution: Detailed Implementation Plan

> Execution-ready plan for the Phase-1 items (B1, B2, B3, B4, B6 + D2/D3 seed content) from
> [`../UNIFIED_PLAN.md`](../UNIFIED_PLAN.md) § Phase 1. Design detail is drawn from each topic's
> `technical.md`; this plan turns it into ordered tasks with file targets, TDD test plans, acceptance
> criteria, and back-compat rules. **Baseline: starboard 0.1.1 @ `b927dfaa`; builds on Phase 0
> branch `phase0/foundations` (zero-store default, canonical `SKILL.md` frontmatter, auth resolver,
> `starboard-helper` JSON envelope).**
>
> Anchors and the B1 import audit were verified against current code on 2026-08-26.
> Claude Code plugin / marketplace / Agent-Skills formats were re-verified against the live docs
> (URLs in §3) on 2026-08-26.

## 0. Goal & definition of done (phase-level)

**Goal:** ship the frictionless, server-free product to both audiences (Claude Code / Isaac users and
external Databricks customers) and prove the 3-tier model end-to-end with the diagnostic middle tier —
with **no capability regression** and the **public path free of internal data**.

**Phase-1 exit criteria (all must hold):**
1. A pure **kernel** import surface (see D-1.1) imports with **no `databricks-sdk`, `openai`, `fastapi`,
   `mcp`** — enforced by an import-linter (or AST) CI contract. *(B1)*
2. `pip install "starboard-x[diagnostics]"` pulls **only** pydantic (+ structlog + pyyaml) — **no heavy
   binaries, no `databricks-sdk`**. *(B1/B2)*
3. `python -m starboard_x.diagnostic {triage-exit|extract-evidence|rca}` emits the **stable JSON
   envelope** with the Phase-0 exit-code contract (`0 ok · 1 auth · 2 not-found · 3 api-error ·
   4 arg-error`). *(B2)*
4. `starboard-diagnostic/SKILL.md` shells to `${CLAUDE_SKILL_DIR}/scripts/run.sh` **with no permission
   prompt** (allowed-tools prefix match), 3-branch dual-mode (MCP agent → Tier-1 script → Tier-0
   helper). *(B2)*
5. The plugin installs in **Claude Code** (`/plugin marketplace add` → `/plugin install`) and **Isaac**;
   skills auto-discovered from convention dirs; only skill **descriptions** are resident (bounded
   context). *(B3)*
6. Optional-MCP toggle works: `userConfig.enable_mcp` + bundled `.mcp.json`; enabling exposes
   `mcp__starboard__*` agent tools, disabling falls back to `starboard-helper` — **same skill files**.
   *(B6)*
7. External-customer install path via **`databricks aitools`** documented and exercised (skills-only).
   *(B4)*
8. Shared **Finding** schema + N seed rules (from `databricks-elt-review`) land as pure pydantic + YAML
   with a `severity × impact / effort` scorer. *(D3)*
9. **LogFood framings** seed the warehouse/finops/compute packs (utilization bands, auto-stop waste,
   load buckets, client-app mix, trend windows); every `$` is a **list-price estimate**. *(D2)*
10. **Enabling smoke test (gate) passes:** Isaac-injected Databricks auth reaches `starboard-helper`'s
    SDK chain (`isaac --claude` + `starboard-helper …`) — gates the no-MCP "just works" UX.
11. **Governance grep** of all shipped public artifacts (wheel content, plugin, skills, packs, seed
    rules) finds **no** internal namespaces (`centralized_system_tables`, `fin_live_gold`, logfood
    workspace, ClickHouse, `go/…`, team keys).
12. Repo-wide gates green: `ruff`, `mypy`, `pytest`, **import-linter** (new).

**Phase 1 is unblocked by Phase 0** and gated only on two owner/process inputs: the Isaac-auth smoke
test (criterion 10) and Isaac plugin onboarding / review gates (see §3 D-1.4, D-1.6).

## 1. Guardrails (apply to every task)

- **TDD:** write the failing test(s) first, then implement to green. Each task lists its tests.
- **Additive / back-compat:** every existing import path stays alive via **re-export shims** (kernel
  carve-out and trio re-home must not break `from starboard.tools.domain.diagnostic import …` or
  `from starboard_core.domain.models import …`). Old `starboard-helper` verbs and exit codes keep
  working. Moving `databricks-sdk` to an extra keeps the SDK-using paths working *iff* the extra is
  installed, with an actionable error otherwise.
- **No capability regression** — consistent with the UNIFIED_PLAN gate invariant (§3.5).
- **Public path stays clean** — internal namespaces never enter shipped artifacts (governance §7);
  `$` labeled list-price estimate on the public adapter.
- **Verification per task:** `ruff check`, `mypy`, `import-linter`, and the task's pytest selection
  must pass before the task is "done".
- **Evidence:** cite `file:line`; reference the topic `technical.md` rather than re-deriving design.

## 2. Branch & PR strategy

Off the Phase-0 base. Seven reviewable PRs; sizes follow §9 ordering:

| PR | Item | Branch | Rough size |
|----|------|--------|-----------|
| 1 | B1 kernel carve-out + import-linter contract | `phase1/kernel-carveout` | M |
| 2 | B2 `starboard-x` diagnostic trio (`python -m`) + envelope | `phase1/starboard-x-diagnostic` | M |
| 3 | B2 `starboard-diagnostic` SKILL.md Tier-1 branch + `scripts/run.sh` + reference/examples | `phase1/diagnostic-skill-tier1` | S–M |
| 4 | B3 skills-only plugin (`plugin.json`) + `marketplace.json` | `phase1/plugin-marketplace` | M |
| 5 | B6 optional-MCP toggle (`userConfig` + `.mcp.json`) | `phase1/optional-mcp-toggle` | M |
| 6 | B4 `databricks aitools` distribution + docs | `phase1/aitools-distribution` | S–M |
| 7 | D3 Finding schema + seed rules · D2 LogFood pack framings | `phase1/seed-content` | S–M (×2, splittable) |

Dependency edges (see §9): PR1→PR2→PR3; PR4 needs Phase-0 canonical skills; PR5 extends PR4; PR6 needs
PR4; PR7 independent (parallelizable from day 1). Each PR: reviewed with `/review`, gates green, merged.

## 3. Decisions to lock before coding

Format facts below are **verified** against the live docs (fetched 2026-08-26):
- Skills / `SKILL.md`: <https://code.claude.com/docs/en/skills>
- Plugin & marketplace manifests: <https://code.claude.com/docs/en/plugins-reference>
- Agent Skills open standard: <https://agentskills.io>
- Genie Conversation API (for the deferred `genie ask`): docs.databricks.com Genie Conversation API

| # | Decision | Recommendation |
|---|----------|----------------|
| D-1.1 | **Kernel package name** (`starboard-kernel` new wheel vs. de-SDK'd `starboard-core`) | **Extend `starboard-core`** (decomposition doc + progressive_helpers §4 lean this way). Carve a pure surface *inside* `starboard-core`: move `databricks-sdk` to an optional extra (only the dbfs log loader needs it — see B1 audit) and add the import-linter contract. If a distinct name is required for external clarity, publish `starboard-kernel` as a **thin re-export** of the pure modules — no code copy. Avoid a hard fork of `starboard-core`. |
| D-1.2 | **`starboard-x` = new wheel or `starboard-core` CLI namespace?** | **Extend `starboard-core`**, expose `starboard_x` as its CLI/entry-point namespace (progressive_helpers §4 option (b); decomposition §5 migration). No third wheel to lock/publish; per-capability extras live on `starboard-core`. Re-home the diagnostic trio here behind re-export shims. |
| D-1.3 | **Per-capability extras taxonomy** | Lock the names now: `diagnostics-core` (`[]`, stdlib-only trio), `diagnostics` (`+pyyaml`, pattern registry), `discovery`, `sparklog` (+ `sparklog-aws/azure/gcp`), `warehouse`, `uc`, `cluster`, `charts`, and an `all` aggregate. Only `diagnostics*` ships in Phase 1; the rest are declared-but-empty stubs to fix the taxonomy early (progressive_helpers §4). |
| D-1.4 | **Plugin marketplace host** | Repo-root `.claude-plugin/marketplace.json` in this repo; plugin at `./plugin`, `source` = relative path. **Public GitHub org vs. internal Isaac (`vibe`-style) marketplace is an owner decision** — the manifest is identical either way; only the install command differs (`/plugin marketplace add <org>/repo` vs `isaac plugin add starboard@<marketplace>`). |
| D-1.5 | **Single skill source of truth** | Reuse the Phase-0 canonical tree `packages/starboard-skills/skills/starboard/<domain>/SKILL.md`. The plugin **vendors** it via a build-time copy/symlink (hatch build hook), not a hand copy. `${CLAUDE_SKILL_DIR}` (skill dir) resolves `scripts/run.sh` in both wheel and plugin installs. |
| D-1.6 | **`databricks aitools` install surface** | Distribution channel for external customers is **[C]** in `agent_integration/technical.md:156` but the exact CLI/format is **not publicly documented** (web verification returned nothing authoritative). **Confirm the real install command + manifest shape with the aitools owner before PR6.** Design the plugin so it is aitools-agnostic (skills-only bundle), so PR6 is packaging, not redesign. |
| D-1.7 | **Finding schema home** | Put the shared `Finding` model + scorer in **`starboard-core`** (pure pydantic, kernel-tier), so Phase-3 Workload Review (D1) and Phase-1 seed rules share one type. Not in the heavy `starboard` package. |
| D-1.8 | **Rules registry scope in Phase 1** | Ship **schema + seed YAML + scorer only** (no engine). The `RuleRegistry` (generalized from `PatternRegistry`) and the reviewer flow are **Phase 3 (D1)**. Phase 1 D3 proves the schema/scorer loads and validates. |
| D-1.9 | **Chart-renderer in B2** | UNIFIED_PLAN §4 lists "diagnostic 0-dep trio **+ chart-renderer**" under Phase 1, but §9 first slice and this task's scope emphasize the trio. **Lock: the trio + skill is the hard DoD; `starboard_x.charts` + `[charts]` extra is an optional B2 stretch** (same PR pattern) and is *not* a phase-gate. See §5b. |

---

## 4. Task B1 — Carve the pure kernel (import audit + de-SDK)

**Source design:** `starboard_decomposition/technical.md` §1–3, §5. **Objective:** a Tier-0 surface of
pure DTOs + analyzers depending on **pydantic (+polars)** only, with a CI contract that forbids
`databricks-sdk`/`openai`/`fastapi`/`mcp`.

**Import audit (done — the gating unknown from UNIFIED_PLAN §6 is resolved):**
- `starboard-core` today declares `databricks-sdk>=0.60.0` as a **hard** dep
  (`packages/starboard-core/pyproject.toml:15`).
- The **only** hard `databricks-sdk` import in the package is the DBFS log loader:
  `starboard_core/log_parser/loaders/dbfs.py:21` (`from databricks.sdk import WorkspaceClient`); the
  rest of `dbfs*` references are docstrings.
- `starboard_core/domain/**` (models, `analyzers/{uc_analyzer.py,warehouse_analyzer.py}`,
  `transformers/*`) is **SDK-free** — `uc_analyzer.py:15` imports only
  `starboard_core.domain.models.databricks.TableReference` (a pure DTO).
- **Conclusion: a kernel that excludes `databricks-sdk` is feasible** by moving the dbfs loader behind
  an extra + lazy import. `polars`/`numpy`/`httpx`/`stream-unzip` remain for the log-parser/analyzer
  slice (map to a `frames`/`logparse` extra per decomposition §3a).

**Files:**
| File (anchor) | Change |
|---|---|
| `packages/starboard-core/pyproject.toml:8-16` | move `databricks-sdk` out of `[project.dependencies]` into a new `dbfs` extra (`databricks = ["databricks-sdk>=0.73,<1"]`); add `frames`/`logparse` extras if separating polars/numpy from the pure DTO core (decomposition §3a); keep pydantic unconditional |
| `starboard_core/log_parser/loaders/dbfs.py:21` | make the `WorkspaceClient` import **lazy** (import inside the loader method) with an actionable `pip install starboard-core[databricks]` error when absent (mirror Phase-0 `_require` guard) |
| `starboard_core/log_parser/loaders/__init__.py` | guard the dbfs export so importing the loaders package doesn't eagerly pull the SDK |
| `pyproject.toml` (repo root) / new `importlinter` config | add an **import-linter** contract: kernel modules (`starboard_core.domain.models`, `.analyzers`, `.transformers`, new `Finding`) **must not** import `databricks-sdk`, `openai`, `fastapi`, `mcp` (decomposition §2 rules) |
| CI workflow | run `lint-imports` in the gate |
| (optional) `packages/starboard-kernel/` | if D-1.1 chooses a distinct name, a thin re-export wheel (`from starboard_core.domain.models import *`) — no logic |

**Back-compat:** all `from starboard_core.domain… import …` paths unchanged. The dbfs loader still
works with `starboard-core[databricks]`. `starboard` (meta) already depends on `databricks-sdk`
directly (`packages/starboard/pyproject.toml:24`), so the server is unaffected.

**Tests (write first)** — `packages/starboard-core/tests/unit/test_kernel_boundary.py`:
- importing `starboard_core.domain.models`, `.analyzers.uc_analyzer`, `.analyzers.warehouse_analyzer`
  does **not** import `databricks.sdk` (assert absent from `sys.modules` in a subprocess-clean import)
- `import-linter` contract passes (invoke `lint-imports` in a test or CI step)
- dbfs loader without the extra raises the actionable install error (simulate missing module)
- packaging: `databricks-sdk` absent from `[project.dependencies]`, present in the `databricks` extra
  (parse pyproject)

**Acceptance:** the pure surface imports SDK-free; `lint-imports` is green in CI; dbfs still works
behind its extra. **LOE: M.**

---

## 5. Task B2 — `starboard-x` middle tier: diagnostic 0-dep trio + `python -m`

**Source design:** `progressive_helpers/technical.md` §3, §4, §7; `starboard_decomposition/technical.md`
§3b. **Objective:** a dep-ful (here: dep-**light**) `python -m starboard_x.diagnostic` surface exposing
the diagnostic trio, JSON envelope + Phase-0 exit codes, installable via a per-capability extra.

**Import audit (done — trio is stdlib-only):**
- `exit_code_triager.py` → `dataclasses`, `enum.StrEnum` only (`:16-19`). **0-dep.**
- `evidence_extractor.py` → `hashlib`, `re`, `dataclasses`, `enum.StrEnum` (`:16-21`). **0-dep.**
- `root_cause_synthesizer.py` → stdlib + `starboard.tools.domain.diagnostic.models` (`:18`).
- `models.py` → `hashlib`, `uuid`, `dataclasses`, `enum.Enum`, `typing` (`:17-23`). **0-dep** (not even
  pydantic). Confirms `diagnostics-core = []` (stdlib-only) is achievable.
- Pattern layer (`pattern_matcher.py:25`, `patterns/registry.py:25-28`) needs `pyyaml` + `pydantic`
  **and** imports `starboard.infra.observability.logging.get_logger` — re-homing it requires swapping
  that logger for `structlog` directly (a kernel logging shim). Maps to the `diagnostics` extra
  (`+pyyaml`), separate from `diagnostics-core`.

**Files:**
| File | Change |
|---|---|
| `packages/starboard-core/starboard_core/x/diagnostic/` (new) OR re-home into `starboard_core` per D-1.2 | move (re-home) the 4 stdlib modules `models.py` (diagnostic subset), `exit_code_triager.py`, `evidence_extractor.py`, `root_cause_synthesizer.py`; carry a **trimmed `__init__`** so one verb doesn't pull the whole diagnostic tree (progressive_helpers §3 "re-homing note") |
| `packages/starboard/starboard/tools/domain/diagnostic/*.py` | leave **re-export shims** (`from starboard_core.x.diagnostic.exit_code_triager import *`) so `starboard.tools.domain.diagnostic` and the eager `__init__.py:16-96` keep working (decomposition §5 step 3) |
| `starboard_core/x/diagnostic/__main__.py` (new) | argparse verbs `triage-exit · extract-evidence · synthesize · match-patterns · rca`; thin wrappers over the re-homed classes (progressive_helpers §3 illustrative `_triage`); **reuse the Phase-0 JSON envelope** `{ok,domain,command,data|error,meta}` + exit codes `0/1/2/3/4`; `--format json` default |
| `starboard_core/x/__main__.py` (new) | `starboard-x` dispatcher to sub-modules |
| `packages/starboard-core/pyproject.toml` | add `[project.scripts] starboard-x = "starboard_core.x.__main__:main"`; add the D-1.3 extras (`diagnostics-core = []`, `diagnostics = ["pyyaml>=6.0.3"]`, plus declared stubs) |
| pattern registry re-home (`diagnostics` extra) | swap `starboard.infra.observability.logging.get_logger` → `structlog.get_logger` (kernel-safe) |

**Tests (write first)** — `packages/starboard-core/tests/unit/x/test_diagnostic_cli.py`:
- `python -m starboard_core.x.diagnostic triage-exit --exit-code 137` → envelope `ok=true`, `data`
  contains an OOM-family hypothesis; exit 0
- `extract-evidence` / `rca` emit valid envelopes over a fixture log
- bad args → exit 4; simulated auth failure in an I/O verb → exit 1 (contract parity with Phase-0 A4)
- **stdlib-only guarantee:** importing `starboard_core.x.diagnostic` (core trio) imports **no**
  `pyyaml`/`pydantic`/`databricks.sdk` (subprocess `sys.modules` assertion) — proves `diagnostics-core`
- re-export shim: `from starboard.tools.domain.diagnostic import ExitCodeTriager` still resolves

**Acceptance:** `pip install "starboard-core[diagnostics]"` gives the trio with only pydantic+structlog
+pyyaml; the three verbs emit the envelope with correct exit codes; back-compat imports intact.
**LOE: M** (the re-home + trimmed `__init__` is the main mechanical cost).

### 5b. B2 stretch (optional, per D-1.9) — `starboard_x.charts`

Add `starboard_core/x/charts/__main__.py` (`render --config c.json --out c.png`) wrapping the existing
altair/vl-convert path, behind the `charts` extra (`altair`, `vl-convert-python`, `polars`). Ship a
viz branch in `starboard-analyze`/a chart skill. **Not a phase gate**; include only if PR2 lands early.
**LOE: S–M.**

---

## 6. Task B2(skill) — `starboard-diagnostic` SKILL.md, three-branch dual-mode

**Source design:** `progressive_helpers/technical.md` §1, §2, §5. **Objective:** the canonical
diagnostic skill gains a Tier-1 branch that shells to the `starboard-x` script **with no permission
prompt**, keeping the existing Tier-0 (`starboard-helper`) and Tier-2 (MCP agent) branches.

**Verified skill mechanics (docs, 2026-08-26):** `description` + `when_to_use` are truncated at **1,536
characters** in the listing; keep `SKILL.md` **under 500 lines** (docs Tip); `${CLAUDE_SKILL_DIR}` and
`${CLAUDE_PLUGIN_ROOT}` are substituted in **both** the body **and** `allowed-tools` Bash rules, so a
bundled script "runs without prompting" when the rule prefix matches the command; scripts are
**executed, not loaded** into context. Portable frontmatter is the six-field spec set
(`name, description, license, compatibility, metadata, allowed-tools`).

**Files:**
| File | Change |
|---|---|
| `packages/starboard-skills/skills/starboard/starboard-diagnostic/SKILL.md` | (already `SKILL.md` + fenced frontmatter from Phase-0 A2) update `allowed-tools` to `Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *), Bash(starboard-helper:*), Read`; add the **3-branch path selection** (MCP `mcp__starboard__diagnostic_agent` → Tier-1 `scripts/run.sh` → Tier-0 `starboard-helper`) exactly per progressive_helpers §2 |
| `…/starboard-diagnostic/scripts/run.sh` (new) | `#!/usr/bin/env bash; set -euo pipefail; exec python -m starboard_core.x.diagnostic "$@"` |
| `…/starboard-diagnostic/reference.md` (new) | L3: exit-code table + evidence-window types (loaded on demand) |
| `…/starboard-diagnostic/examples.md` (new) | L3: sample invocations + expected JSON |
| build packaging | ensure `scripts/`, `reference.md`, `examples.md` are vendored into both the wheel skill tree and the plugin (D-1.5) |

**Tests (write first)** — `packages/starboard-skills/tests/test_diagnostic_skill_tier1.py`:
- `SKILL.md` frontmatter parses; `allowed-tools` contains the `${CLAUDE_SKILL_DIR}/scripts/run.sh *`
  prefix and the body invokes exactly that prefix (prompt-free contract)
- body ≤ 500 lines; `description`+`when_to_use` ≤ 1,536 chars
- `scripts/run.sh` is executable and execs `python -m starboard_core.x.diagnostic`
- end-to-end: run `scripts/run.sh triage-exit --exit-code 143` → valid envelope (uses B2 CLI)
- the three documented branches each name a resolvable target (MCP tool name, script path, helper verb)

**Acceptance:** invoking the skill on a failure runs the bundled script with no prompt and returns
compact JSON; degrades to `starboard-helper` when the script/module is absent; uses the MCP agent when
present. **LOE: S–M.**

---

## 7. Task B3 — Skills-only Claude Code plugin + marketplace

**Source design:** `agent_integration/technical.md` §1.1–1.2, §1.5–1.6; `starboard_decomposition`
§4a/4c/§6. **Objective:** one plugin that vendors the canonical skills tree, installable in Claude Code
and Isaac, with **no MCP** by default (skills auto-route to `starboard-helper`).

**Verified manifest facts (plugins-reference, 2026-08-26):** `plugin.json` lives at
`.claude-plugin/plugin.json`; **only `name` is required**; `skills/`, `commands/`, `agents/`,
`.mcp.json` are **auto-discovered from convention directories** (the `skills`/`commands`/… keys are
optional overrides; note `skills` *adds to* the default scan while `commands`/`agents` *replace* it).
`marketplace.json` lives at `.claude-plugin/marketplace.json` with `name`, `owner`, `plugins[]`; each
entry has `name`, `source`, `description` (+ optional `version`, `keywords`); `source` is a relative
path, a `{github:{owner,repo,ref,path}}` object, or a git URL.

**Files:**
| File | Change |
|---|---|
| `plugin/.claude-plugin/plugin.json` (new) | minimal manifest — `{name, displayName, version, description, author{name,url}, homepage, repository, license, keywords}`; rely on convention discovery for `skills/` (agent_integration §1.2, refined by decomposition §6 auto-discovery note) |
| `plugin/skills/` | build-time vendored copy/symlink of `packages/starboard-skills/skills/starboard/*` (D-1.5); includes the B2 `scripts/`, `reference.md`, `examples.md` |
| `plugin/commands/starboard-triage.md` (new, optional) | one-shot triage command (agent_integration §1.2 `commands` array) |
| `.claude-plugin/marketplace.json` (repo root, new) | `{name:"starboard-marketplace", owner:{…}, plugins:[{name:"starboard", source:"./plugin", description:…}]}` (agent_integration §1.5) |
| `plugin/README.md` (new) | documents `pip install "starboard-x[diagnostics]"` prerequisite + install flows |
| hatch build hook | vendor `skills/` into `plugin/skills/` (no hand copy) |

**Tests (write first)** — `tests/test_plugin_manifest.py`:
- `plugin.json` and `marketplace.json` are valid JSON; required fields present (`name`; marketplace
  `name`/`owner`/`plugins`)
- every skill referenced/vendored has a valid `SKILL.md` (fenced frontmatter, `name`+`description`)
- `marketplace.json` `source: "./plugin"` resolves to a dir containing `.claude-plugin/plugin.json`
- vendored `plugin/skills/**` is byte-identical to `packages/starboard-skills/skills/starboard/**`
  (built, not hand-copied)
- **no `mcpServers` key** in the skills-only manifest (B3 is pre-B6)

**Acceptance:** `/plugin marketplace add <path-or-repo>` then `/plugin install
starboard@starboard-marketplace` installs; skills appear and route to `starboard-helper`; Isaac install
path documented (`isaac plugin add starboard@<marketplace>`). **LOE: M.**

---

## 8. Task B4 — `databricks aitools` distribution (external customers)

**Source design:** `agent_integration/technical.md` §1.6, §6. **Objective:** the skills-only bundle is
installable by external Databricks customers via `databricks aitools install` (skills only, no server).

> **Blocked on D-1.6:** the exact `databricks aitools` CLI + manifest is not publicly documented;
> web verification (2026-08-26) returned nothing authoritative. Confirm the real surface with the
> aitools owner before implementing. The plugin from B3 is designed to be aitools-agnostic, so this
> task is packaging + docs, not redesign.

**Files:**
| File | Change |
|---|---|
| `plugin/` (reuse B3) | ensure the skills-only bundle satisfies whatever aitools manifest the owner confirms (likely the same `.claude-plugin/` layout) |
| distribution docs | add the `databricks aitools install` flow to `plugin/README.md` and the marketplace docs (three install rows: Claude Code, Isaac, Databricks customers — agent_integration §1.6 table) |
| CI/release | (if aitools requires a packaged artifact) add a release step producing it |

**Tests (write first):** a packaging smoke test that asserts the bundle contains exactly the public
skills tree + scripts and **no** server/MCP artifacts; governance grep (criterion 11) over the bundle.

**Acceptance:** documented, reproducible external-customer install producing the same skills UX.
**LOE: S–M** (mostly gated on the D-1.6 confirmation).

---

## 9b. Task B6 — Optional-MCP toggle in the same plugin

**Source design:** `agent_integration/technical.md` §1.3, §1.4, §6. **Objective:** raise the depth
ceiling to the full agent stack **without a second artifact** — a `userConfig` boolean + a bundled
`.mcp.json`; skills see `mcp__starboard__*_agent` tools when enabled, fall back to `starboard-helper`
otherwise.

**Verified facts (plugins-reference, 2026-08-26):** `userConfig` entries take
`{type, title, description, required?, default?, sensitive?}` (`type` ∈
`string|number|boolean|directory|file`); values substitute as `${user_config.KEY}` in MCP configs and
export as `CLAUDE_PLUGIN_OPTION_<KEY>`. `.mcp.json` stdio form is `{command, args, env, timeout}`;
`${CLAUDE_PLUGIN_ROOT}` resolves bundled paths.

**Files:**
| File | Change |
|---|---|
| `plugin/.claude-plugin/plugin.json` | add `mcpServers: "./.mcp.json"` (or rely on convention) + `userConfig.enable_mcp` (boolean, `title`/`description`, `required:false`, `default:false`) — agent_integration §1.3 |
| `plugin/.mcp.json` (new) | stdio server `{command:"starboard-mcp", args:["--transport","stdio"], timeout:900, env:{DATABRICKS_HOST, LLM_PROVIDER, LLM_API_KEY, LLM_MODEL}}` (agent_integration §1.3) |
| canonical skills bodies (all 9) | ensure each dual-mode body already prefers `mcp__starboard__*` when present, else Tier-1/Tier-0 (Phase-0 A2 shape) — verify, no rewrite |

**Tests (write first)** — `tests/test_optional_mcp_toggle.py`:
- `plugin.json` with `userConfig.enable_mcp` validates (type boolean, required false, has title+desc)
- `.mcp.json` valid; `command` = `starboard-mcp`; env keys present; no secrets hard-coded
- a skill body branch references `mcp__starboard__diagnostic_agent` (enabled path) **and** the
  `starboard-helper`/`scripts/run.sh` fallback (disabled path) — same file
- disabling (config false / server absent) still yields a working helper path (no regression)

**Acceptance:** toggling `enable_mcp` on exposes the agent tools; off falls back cleanly; one artifact,
two fidelity levels. **LOE: M.**

---

## 10. Task D3 — Shared Finding schema + seed rules (from `databricks-elt-review`)

**Source design:** `internal_harvest/technical.md` §4 (rule/finding correspondence), §5. **Objective:**
land the shared `Finding` model + `severity × impact / effort` scorer + a handful of **seed rule YAMLs**
paraphrased from `databricks-elt-review`, as **pure pydantic + YAML** (no engine — D-1.8). This is the
first rule set the Phase-3 Workload Review (D1) consumes.

**Files:**
| File | Change |
|---|---|
| `packages/starboard-core/starboard_core/domain/models/finding.py` (new) | `Finding` pydantic model — `current_state`, `recommended_fix`, `evidence`/target (job/query/warehouse id + metric), `severity`, `rationale`, `source` (nullable — strip internal `go/` links, governance §7) — mirroring `patterns/schema.py` fields (internal_harvest §4) |
| `starboard_core/domain/models/finding.py` | `score(severity, impact, effort) -> bucket` scorer (elt-review synthesizer formula, internal_harvest §4) |
| `packages/starboard/starboard/tools/domain/rules/<domain>/*.yaml` (new, seed only) | 3–5 seed rules paraphrased from elt-review sub-agents (e.g. `query/non_sargable_partition_filter.yaml` per internal_harvest §4), reusing existing query-pack queries as `evidence_query` |
| rules schema | reuse/generalize `patterns/schema.py` for validation of the seed YAML (fail-fast load), **without** wiring the reviewer flow |

**Tests (write first)** — `packages/starboard-core/tests/unit/domain/models/test_finding.py` +
`tests/test_seed_rules.py`:
- `Finding` validates; required fields enforced; `source` nullable
- scorer maps known `(severity, impact, effort)` triples to expected buckets (table-driven)
- every seed rule YAML loads + validates fail-fast; `evidence_query` names a real query-pack entry
- **governance:** no seed rule contains an internal namespace or `go/` link (grep in test)

**Acceptance:** the schema + scorer import from `starboard-core`; seed rules validate; Phase-3 D1 can
consume them unchanged. **LOE: S–M.**

---

## 11. Task D2 — LogFood metric framings → warehouse/finops/compute packs

**Source design:** `internal_harvest/technical.md` §1, §5; governance §7. **Objective:** encode
harvested LogFood *framings* (utilization bands, auto-stop waste, load buckets, client-app mix, trend
windows) as public `system.*` query-pack content + prompt "framings" sections — **list-price $ only**.

> **Note (repo grounding):** there is **no `warehouse.py`/`finops.py` pack today**
> (`packages/starboard/starboard/discovery/query_packs/` has `query_performance.py`, `compute.py`,
> `billing.py`, etc.). D2 **adds** `warehouse.py` (per internal_harvest §1) and enriches `compute.py`
> / `billing.py`; the warehouse route currently has no dedicated pack.

**Files:**
| File | Change |
|---|---|
| `discovery/query_packs/warehouse.py` (new) | `SystemQuery`/`QueryPack` over `system.compute.warehouse_events` + `system.query.history`: utilization bands (Offline / No util / Under <30% / Optimal 30–80% / Resource-starved >80%), auto-stop waste (RUNNING minutes with zero query activity), client-app mix, load buckets, T7/T28/T91 windows as pack params (internal_harvest §1) |
| `discovery/query_packs/compute.py`, `billing.py` | enrich with the same framings where they apply; cost via `system.billing.usage × system.billing.list_prices`, **labeled list-price estimate** |
| `discovery/query_packs/registry.py:17-51` | register the new `warehouse` pack; add a `WAREHOUSE`/DBSQL route if missing |
| `prompts/warehouse/v2.py`, `prompts/analytics/…` | add a "framings" section so the LLM narrates results in the harvested bands (internal_harvest §1) |

**Design rules:** set `required=False` on Preview/Beta system tables (Phase-0 A5 convention); paraphrase
harvested logic, **no internal namespaces** (namespace-swap `centralized_system_tables.*` → `system.*`,
governance §7); every $ is a list-price estimate.

**Tests (write first)** — `tests/unit/discovery/test_warehouse_pack.py`:
- pack imports/constructs; `required_tables` = the intended `system.*` tables
- SQL templates render with test params (no `{unfilled}` placeholders); pass the existing validator
- `create_default_registry()` includes the warehouse pack; the warehouse/DBSQL route resolves to it
- utilization-band CASE logic classifies fixture rows into the 5 bands correctly
- **governance:** no internal namespace/`go/` link in any new pack (grep in test)

**Acceptance:** warehouse/finops/compute packs produce banded, list-price-labeled findings on public
`system.*`; graceful degrade when a Preview table is absent. **LOE: S–M.**

---

## 12. Enabling smoke test (the Phase-1 gate)

**From UNIFIED_PLAN §4 Phase 1 + §6.** Independent of the build items; run once the plugin + helper are
installable:

- **Test:** under Isaac (`isaac --claude`), with **no** explicit `DATABRICKS_HOST/TOKEN`, run
  `starboard-helper job list` (and one diagnostic verb). It must authenticate via the SDK unified chain
  using Isaac-injected credentials — proving the no-MCP "just works" UX (open question I2/I5 in
  `agent_integration/technical.md:168`).
- **Owner input:** Isaac plugin onboarding + review gates (go/llmpolicy) for shipping a plugin/CLI
  internally (UNIFIED_PLAN §6 Phase-1 rows).
- **If it fails:** document the auth hand-off gap; skills still work with explicit env/profile (Phase-0
  auth resolver A1), so the public path is unaffected — this gate is about *frictionlessness*, not
  capability.

---

## 13. Note — Internal-data enablement gate (C5): **Phase 2, not Phase 1**

The task asked to include the Phase-1 slice of C5 **if UNIFIED_PLAN sequences the C5 interfaces here**.
It does **not**: UNIFIED_PLAN §3.5 says "Land the **port interfaces with public adapters** in Phase 2
(part of C5)"; Phase-2 workstream 2b explicitly lists "**C5 port interfaces + public adapters**"; the
Phase-1 exit criteria make no mention of C5. **Therefore Phase 1 defines no `LogRetrievalPort` /
`DiagnosticBackendPort` / `FleetSqlPort` / `NLQueryPort`.** Phase 1 stays focused on the B-pillar +
D2/D3. (The internal *adapters* are Phase 3, D6/D7.)

> This is the one place the task prompt and UNIFIED_PLAN could read differently — see the Report's
> "ambiguities" note. Recommendation: keep C5 in Phase 2 as the plan sequences it; D3's `Finding`
> schema (kernel-tier, D-1.7) is the shared type those ports will later produce, so nothing is lost.

---

## 14. Task ordering & dependency graph (within Phase 1)

```
B1 kernel carve-out ──► B2 starboard-x diagnostic ──► B2(skill) Tier-1 branch
        (import-linter)        (re-home + envelope)          (allowed-tools prompt-free)

A2 canonical skills (Phase 0) ──► B3 plugin + marketplace ──► B4 aitools distribution
                                          │
                                          └──► B6 optional-MCP toggle

D3 Finding schema + seed rules ─ independent ─► (feeds Phase-3 D1)
D2 LogFood framings            ─ independent ─► (ship anytime)

Enabling smoke test ── after plugin + helper installable (gates no-MCP UX)
```

Suggested execution order (longest pole first, content in parallel): **B1 → B2 → B2(skill) → B3 → B6 →
B4**, with **D3** and **D2** run in parallel from day 1, and the **smoke test** once B3 lands.

## 15. Verification & Definition of Done

Per PR and for the phase:
- `uv run ruff check .` — clean
- `uv run mypy packages/…` — clean (respect existing per-module ignores; `log_parser` stays excluded)
- `uv run lint-imports` — kernel boundary contract green (new gate, B1)
- `uv run pytest` for the touched package(s) — green, including the new TDD tests
- Manifests validated (`plugin.json`, `marketplace.json`, `.mcp.json`); skill frontmatter parses;
  `SKILL.md` ≤ 500 lines and description ≤ 1,536 chars
- **Governance grep** of shipped artifacts — no internal namespaces (criterion 11)
- Reviewed with `/review` before merge
- Phase-1 exit criteria §0 (1–12) all demonstrably met

## 16. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Re-homing the diagnostic trio breaks `starboard.tools.domain.diagnostic` consumers (eager `__init__.py:16-96`) | Re-export shims at every old path; golden import test; keep the trimmed `__init__` only in the `starboard_x` copy |
| Moving `databricks-sdk` to an extra breaks an install that relied on the dbfs loader | Lazy import + actionable `pip install starboard-core[databricks]` error; test the missing-extra path; `starboard` meta still declares the SDK directly |
| Pattern registry's `starboard.infra…logging` import drags the heavy package into `starboard-x` | Swap to `structlog.get_logger`; keep pattern layer in the `diagnostics` (not `diagnostics-core`) extra; assert stdlib-only import for the trio |
| `allowed-tools` prefix doesn't match the body command → permission prompt returns | Test asserts the exact `${CLAUDE_SKILL_DIR}/scripts/run.sh *` prefix equals the invoked command; verified against docs' pre-approval rule |
| `databricks aitools` surface differs from assumption (D-1.6) | Design plugin aitools-agnostic; gate PR6 on owner confirmation; treat as packaging not redesign |
| Isaac auth doesn't reach the helper's SDK chain (smoke test fails) | Public path unaffected (explicit env/profile via A1); document the gap; not a capability blocker |
| Internal methodology leaks into public packs/rules (D2/D3) | Paraphrase; namespace-swap to `system.*`; `source: null`; governance grep in tests + release gate |
| Plugin marketplace host undecided (D-1.4) | Manifest is host-independent; only the install command differs; defer host to owner without blocking the build |

## 17. Explicitly out of scope for Phase 1 (deferred)

- **C5 port interfaces + public adapters** (LogRetrieval/DiagnosticBackend/FleetSql/NLQuery) → **Phase 2**
  (UNIFIED_PLAN §3.5 / workstream 2b); internal adapters (D6/D7) → Phase 3.
- **C1 RAG → reference files**, **C2 UC-native state**, **C3 JSON CLI sessions** → Phase 2.
- **B5 full layered catalog / per-domain plugins** (single-domain `plugin-diagnostics`/`plugin-finops`,
  `starboard.mcp_tools` entry-point discovery replacing `ALL_TOOL_METADATA`) → Phase 3 (decomposition
  §3b/§4c is the target; Phase 1 ships one plugin only).
- **D1 Workload Review engine** (`RuleRegistry`, reviewer flow, verify-pass, adoption metric) → Phase 3;
  Phase 1 D3 seeds only the schema + scorer + seed YAML.
- **D4 progressive-helper depth** (discovery `data_only`, sparklog, warehouse/uc analyzer verbs,
  chart-renderer beyond the optional B2 stretch), **D5 new packs + caching** → Phase 2.
- **`genie ask` (D8)**, **Codex/OpenCode host wiring (D9)**, **Apps OBO (D10)** → Phase 3.
- **`starboard_x.{discovery,sparklog,warehouse,uc,cluster}` implementations** → Phase 2 (D-1.3 declares
  the extras taxonomy now; only `diagnostics*` is implemented in Phase 1).

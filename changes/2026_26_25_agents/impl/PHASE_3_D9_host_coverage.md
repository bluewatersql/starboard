# Phase 3 · D9 — Codex / OpenCode host coverage + `.isaac/rules/` (design note)

> Design note feeding PHASE_3.md §9 (Task D9). Resolves the host-invocation model
> and the **placement** of the `.isaac/rules/` baseline (flagged open during
> planning). Public path only — no internal namespaces.

## 1. The host-invocation model is already host-agnostic

The no-MCP path established in Phases 1–2 is a **stable Bash command** that any
host capable of running shell commands can invoke identically:

- Each skill's `scripts/run.sh` is a one-liner: `exec python -m starboard_x.<capability> "$@"`
  (e.g. `starboard-warehouse` → `python -m starboard_x.warehouse`). The stable path
  lets the `SKILL.md` `allowed-tools` prefix (`Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)`)
  match exactly, so it runs with **no permission prompt**.
- The `starboard_x` dispatcher (`python -m starboard_x <capability> …`) routes to
  `diagnostic | discovery | sparklog | warehouse | uc`, each emitting the compact
  **JSON envelope + exit codes** (`starboard_x/contract.py`).

**Consequence:** host coverage is mostly a *packaging + docs + auth* concern, not a
code concern. The same `python -m starboard_x …` invocation is valid under Claude
Code, Isaac (which wraps Claude Code), Codex, and OpenCode. D9 is therefore
lightweight: confirm discovery/permission conventions per host, document them, and
smoke-test where a host is available.

## 2. Per-host coverage matrix

| Host | Skill discovery | Invocation | Auth | D9 action |
|------|-----------------|-----------|------|-----------|
| **Claude Code** | plugin marketplace (`marketplace.json`) | `run.sh` → `python -m starboard_x …` | SDK credential chain (A1) | ✅ already covered (Phases 1–2) |
| **Isaac** | wraps Claude Code → same plugin | same | Isaac-injected identity → SDK chain (G1 verified) | ✅ covered; ships `.isaac/rules/` (see §3) |
| **Codex** | no plugin marketplace → point at the helper directly | `python -m starboard_x …` (or `starboard-helper`) | SDK chain / `--profile` | **document** invocation + a smoke test |
| **OpenCode** | agent config references the helper command | `python -m starboard_x …` | SDK chain / `--profile` | **document** invocation + a smoke test |

Codex/OpenCode lack a Claude-Code-style plugin loader, so the story is "install the
`starboard-x[…]` wheel, call `python -m starboard_x …`" — the thin/middle tier, not
the plugin. This is exactly the 3-tier model's purpose (tier-2 helpers usable
without any host-specific plugin machinery).

## 3. `.isaac/rules/` placement — DECISION

**Decision:** the baseline `.isaac/rules/` guidance ships **inside the distributed
plugin/skills bundle** (so a consumer who installs Starboard into an Isaac-enabled
workspace gets it), **not** committed to *this* development repo's root `.isaac/`.

- Rationale: a file at *this* repo's `/.isaac/rules/` would only shape Isaac
  sessions **in the Starboard dev repo**, which is not the goal. D9 wants end users
  of Starboard to get sane defaults. Ship it as **package data** in the plugin
  bundle (alongside `plugin/skills/`), materialized by the same
  `scripts/vendor_plugin_skills.py` vendoring step that already handles skills.
- Note: this repo already has `.isaac/config.json` (Isaac's own config) and the
  Isaac *review* rules path is a separate concern (`.isaac/review/rules/…`, which
  this repo intentionally does not define — the default `logical` reviewer runs).
  D9's `.isaac/rules/` (agent-session guidance) must not be confused with either.
- Content: paraphrased baseline guidance — "prefer `python -m starboard_x` helpers
  for workload analysis; results are list-price DBU **estimates**; single-workspace
  by default." **No internal namespaces, no `go/` links, no internal tool names.**

## 4. D9 acceptance (unchanged from PHASE_3.md §9)

- `python -m starboard_x …` runs under each host's invocation convention (smoke
  test where the host is available; otherwise a documented manual check).
- The shipped `.isaac/rules/` baseline passes the governance grep (no internal
  identifiers).
- Host-coverage docs land under the distribution docs (with B4 `databricks aitools`
  / plugin README), not scattered in package code.

## 5. Dependencies / sequencing

D9 is **independent of the D1 flagship and the D-3.1 seam** and can land any time in
workstream 3c. It reuses the Phase-1/2 `run.sh` + `starboard_x` machinery unchanged;
no new runtime code beyond docs + the `.isaac/rules/` data file + (optionally) a
tiny smoke-test harness per available host.

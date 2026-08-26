# Recommendations — Starboard Agent-Host Integration (no MCP required)

> Ranked plan derived from `opportunities.md` + `technical.md`. Evidence base: `_grounding_brief.md`, repo @ `b927dfaa`, internal Confluence (Isaac), official docs. Confidence: **[C]/[I]/[U]**.

## Executive stance

Starboard is one packaging step away from a strong no-MCP story: the **dual-mode skills** and the **`starboard-helper` CLI already exist**. The winning strategy is **skills-first, MCP-optional, CLI-as-substrate**, distributed through **marketplaces** — and the biggest, cheapest win is that **Isaac wraps Claude Code**, so a single Claude Code plugin reaches the entire internal engineering org (and, via `databricks aitools`, external customers) with no server to run. **[C]**

Guiding principle (matches Databricks' own framing): *skills teach the agent how to work; MCP servers let it do the work.* **[C]** Lead with skills; treat MCP as an opt-in ceiling for deep orchestration.

## Ranked recommendations

| Rank | Recommendation | Opp | LoE | Why now |
|------|----------------|-----|-----|---------|
| 1 | Ship the **skills-only Claude Code plugin** (no MCP) | O1 | M | Reuses existing assets; unlocks Claude Code + Isaac at once |
| 2 | **Marketplace distribution** — public GitHub + internal Isaac | O2 | S | Turns "exists" into "installed by many" |
| 3 | Harden the **`starboard-helper` CLI contract** (the substrate) | §0 | S–M | Every host depends on it |
| 4 | Add the **optional-MCP toggle** to the same plugin (dual-mode) | O3 | M | Raises the depth ceiling without a second artifact |
| 5 | **Codex** integration: AGENTS.md + prompts (+ skills) | O5 | S–M | Cheap reach into a second major host |
| 6 | **OpenCode** custom tool + agent | O6 | M | Native, typed integration; Isaac-launchable |
| 7 | **Consume Genie** via `starboard-helper genie ask` | O8 | M | New capability, pure SDK, fits the pattern |
| 8 | First-party **`databricks aitools`** distribution | O4 | S–M | External customer reach (needs Databricks process) |
| 9 | **Expose Starboard within Genie** (curated space) | O9 | L | Product bet; validate demand first |

Baselines O10 (PATH CLI + rules) and O11 (triage command/output style) are low-effort and fold into ranks 1–5 as they land.

## Rationale for the ordering

**Why #1 first.** The plugin is the smallest change with the largest blast radius: no runtime, no new auth, reuses the 9 skills verbatim, and — critically — **the same artifact runs under Isaac** because Isaac forwards to Claude Code and its plugin system delivers "skills, commands, MCP integrations, and apps." **[C]** One build, two audiences (Claude Code users + internal Isaac users).

**Why #2 immediately after.** A plugin nobody can find is inert. `marketplace.json` (public) + Isaac/vibe onboarding (internal) is a few files and an onboarding request. Distribution is the true unlock given the internal AI-tooling mandate (captive, incentivized user base). **[C]**

**Why #3 in parallel.** All four hosts wrap `starboard-helper`. A stable JSON contract, the missing `analyze`/`discovery`/`genie` verbs, and `--format json` are the highest-reuse investment; do it alongside #1.

**Why #4 (not sooner).** The optional MCP toggle is where server lifecycle, LLM keys, and the known `changes/mcp_claude/` wiring gaps re-enter. Ship the frictionless path first, then offer depth to those who ask — in the *same* plugin so there's no second install.
    -- **FEEDBACK NOTES**: The MCP path should be deprioritized as much as possible with the long term goal that eventually it can be completely retired. The goal should be to replicate as much of the functionality as possible natively or through other lightweight means without requiring the MCP connection.

**Why Codex (#5) before OpenCode (#6).** Codex needs only markdown (`AGENTS.md` + prompts) to reach a useful state — no new language surface. OpenCode's best integration is a TypeScript custom tool (higher fidelity but a new artifact type for a Python project).
    -- **FEEDBACK NOTES**: A project based build-time converter (even with LLM asistance) would be helpful rather than having to maintain two seperate artifacts.

**Why Genie consume (#7) before expose (#9).** `genie ask` is a contained SDK call that slots into the existing helper pattern and adds NL→SQL breadth. Exposing Starboard *inside* Genie (`create_space`) is a larger product commitment with an under-documented `serialized_space` schema **[U]** — validate demand before investing.
    -- **FEEDBACK NOTES**: I'd like to dig a big deeper on this, specifically for the `workspace discovery` slice of Starboard. Having a single place to surface end-to-end workspace health and observations has resonated with customers and would be highly impactful. 

## Sequencing (phased)

**Phase 0 — Decide & de-risk (days).**
- Resolve skill duplication; pick canonical source (open question XC2).
- Verify Isaac-injected Databricks auth reaches the CLI's SDK chain on a laptop (I5/XC1) — this gates the "just works" claim. Run one real `isaac --claude` + `starboard-helper` smoke test.

**Phase 1 — No-MCP flagship (rank 1–3).**
- Package skills-only plugin; add frontmatter; rename to `SKILL.md`.
- Harden CLI (add verbs, JSON contract).
- Publish public `marketplace.json`; dogfood via `/plugin install` and `isaac --claude`.

**Phase 2 — Distribution + depth (rank 2 internal, 4).**
- Onboard into internal Isaac/vibe marketplace (`isaac plugin add starboard@…`).
- Add optional-MCP `userConfig` toggle + `.mcp.json` to the plugin.

**Phase 3 — Multi-host breadth (rank 5–6).**
- Codex `AGENTS.md` + prompts; then OpenCode custom tool + agent.
- Wire `.isaac/rules/` guidance so all harnesses get baseline awareness.

**Phase 4 — Genie (rank 7, then 9).**
- `starboard-helper genie ask` (consume). Later, prototype curated Genie space (expose) if demand validates.

## What to do first (this week)

1. **Pick the canonical skills dir** and rename `skill.md` → `SKILL.md` with `description`/`allowed-tools` frontmatter (technical.md §1.4).
2. **Write `.claude-plugin/plugin.json` (skills-only)** and a `marketplace.json`; install locally and confirm the non-MCP branch fires (no `mcp__starboard__*` present).
3. **Smoke-test under Isaac** (`isaac --claude`) to confirm auth + CLI behavior end-to-end.
4. **Add the two missing CLI verbs** (`analyze`, `discovery`) so all 9 skills map cleanly.

These four steps deliver a working, installable, server-free Starboard in both Claude Code and Isaac — the highest-value slice — before any MCP or multi-host work.

## Risks & mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Isaac auth doesn't flow to CLI's SDK chain (I5) | No-MCP UX needs manual creds | Phase 0 smoke test; document `databricks auth login` fallback |
| CLI-path analysis shallower than agent stack | Under-delivers on deep RCA | Set expectations; offer O3 MCP toggle for depth |
| Internal marketplace onboarding gated (I4) | Slower internal rollout | Start public/dogfood; run go/llmpolicy review early |
| Codex skills format unverified (X1) | Rework | Verify docs before building; AGENTS.md path works regardless |
| Genie `serialized_space` opaque (G3) | O9 slips | Keep O9 last; prototype behind a flag |

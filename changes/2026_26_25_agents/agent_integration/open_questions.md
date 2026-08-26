# Open Questions — Agent-Host Integration (no-MCP path)

> Companion to `opportunities.md`, `recommendation.md`, `technical.md`.
> Evidence base: `changes/2026_26_25_agents/_grounding_brief.md` + repo (commit `b927dfaa`, starboard 0.1.1) + internal Confluence (Isaac) + official docs.
> Confidence tags: **[confirmed]** doc/repo-verified · **[inferred]** reasoned, not directly verified · **[unverified]** could not confirm this session.

## 1. Isaac internals (highest uncertainty — internal, Glean-sourced)

| # | Question | What we know | Confidence |
|---|----------|--------------|------------|
| I1 | Does Isaac's plugin marketplace accept an externally-authored Claude Code plugin as-is, or must plugins be onboarded into the `vibe`/internal marketplace repo? | `isaac plugin add PLUGIN@MARKETPLACE`; the FE `vibe` marketplace is a git-repo snapshot at `~/.vibe/marketplace/`; plugins named `PLUGIN@MARKETPLACE` (e.g. `fe-ai-tools@fe-vibe`). Isaac forwards `isaac -- plugin install …` to the underlying Claude CLI. | [confirmed] commands; [inferred] onboarding path |
| I2 | Is the Isaac plugin format byte-identical to Anthropic's Claude Code plugin format (`.claude-plugin/plugin.json` + bundled skills/agents/commands/hooks/MCP)? | Isaac "is a CLI wrapper for tools like Claude Code"; plugins "add reusable skills, commands, MCP integrations, and apps to supported agents"; plugin-delivered MCP shows as `plugin:NAME:server`. Strongly implies Claude Code plugin format. | [inferred] |
| I3 | For non-Claude harnesses under Isaac (Codex, OpenCode, Cursor, Omnigent), do bundled Claude Code **skills** carry over, or only MCP + `.isaac/rules/`-compiled guidance? | `.isaac/rules/` compiles to Claude rules, Cursor rules, and Codex `AGENTS.md`. Skills appear Claude-Code-specific. | [inferred] |
| I4 | What are the security/review gates to publish a plugin that ships a `starboard-helper` CLI or an MCP server to the internal marketplace? | `go/llmpolicy` governs approved MCP servers / data handling; internal PyPI proxy used for plugin deps. | [unverified] specifics |
| I5 | Does Isaac inject Databricks workspace auth (OAuth) into the agent env such that a bare `WorkspaceClient()` in `starboard-helper` "just works" without PAT env vars? | Isaac "provides Databricks authentication" and manages OAuth token mgmt for Codex/OpenCode. Whether that auth is on the default SDK chain the helper reads is unconfirmed. | [unverified] — **critical for no-MCP path UX** |
| I6 | Is "Omnigent" (planned default Isaac harness) extensible the same way, and does it honor Claude Code skills/plugins? | Omnigent named as future default; args forwarded to it. Extension model unknown. | [unverified] |
| I7 | Distribution: is `databricks aitools install` (public skills installer) the right channel for Databricks-external users, and can it co-exist with the internal `vibe`/Isaac marketplace? | Public doc confirms `databricks aitools install` installs skills for detected agents (Claude, Copilot, Cursor). Overlap/precedence with Isaac plugins unconfirmed. | [confirmed] command; [unverified] interaction |

## 2. Claude Code plugin/skill format — RESOLVED this session

| # | Question | Status |
|---|----------|--------|
| C1 | Exact required vs optional fields in `.claude-plugin/plugin.json` and `marketplace.json`. | **[resolved/confirmed]** Full schema verified (code.claude.com/docs/en/plugins-reference): `name` required; `skills`/`commands`/`agents`/`hooks`/`mcpServers`/`outputStyles`/`userConfig`/`defaultEnabled` optional. `marketplace.json`: `name`, `owner`, `plugins[]`. See `technical.md` §1. |
| C2 | Can one plugin bundle skills AND an optional MCP server the user toggles? | **[resolved/confirmed]** Yes — plugin declares `mcpServers`+`userConfig`; plugin-delivered MCP is real (Isaac `plugin:NAME:server`). See `technical.md` §1.3. |
| C3 | Can a skill pre-authorize `Bash(starboard-helper:*)` via `allowed-tools`? | **[resolved/confirmed]** `allowed-tools` is a supported SKILL.md frontmatter field (code.claude.com/docs/en/skills). |

## 3. Codex

| # | Question | Status |
|---|----------|--------|
| X1 | Does Codex support a skill mechanism beyond MCP + `AGENTS.md` + prompts? | **[partly resolved]** Codex CLI docs confirm skills exist ("package repeatable instructions as skills", /codex/skills-and-plugins). Exact SKILL.md location/frontmatter for Codex still **[unverified]** (skills-and-plugins page 404'd this session) — verify before building. |
| X2 | Can Codex prompts/skills reliably invoke a PATH CLI under Codex's sandbox/approval model? | **[unverified]** — `AGENTS.md` guidance path works regardless; test the approval prompts. |

## 4. OpenCode

| # | Question | Status |
|---|----------|--------|
| O1 | Custom-tool file API and CLI shell-out. | **[resolved/confirmed]** `import { tool } from "@opencode-ai/plugin"`, zod args, Bun `$` shell-out (opencode.ai/docs/custom-tools + repo example). See `technical.md` §4.1. |
| O2 | Does OpenCode under Isaac inherit only AI-Gateway model config, or also workspace data auth? | **[unverified]** Isaac configures OpenCode "default AI Gateway model"; whether Databricks data auth flows to `starboard-helper` unconfirmed (ties to I5/XC1). |

## 5. Genie

| # | Question | Status |
|---|----------|--------|
| G1 | GA vs Preview + rate/message limits in 2026. | **[partly resolved]** Endpoints appear GA; visualization retrieval marked Beta (docs updated 2026-08-20). Explicit rate/message limits **[unverified]**. |
| G2 | Auth model + required permissions. | **[resolved/confirmed]** OAuth U2M/M2M; `CAN USE` on a pro/serverless SQL warehouse + `CAN RUN` on the space; `include_all` needs `CAN MANAGE`. |
| G3 | Register discovery packs as a curated Genie space (expose Starboard *within* Genie)? | **[partly resolved]** `w.genie.create_space(warehouse_id, serialized_space, …)` exists; `serialized_space` schema is under-documented **[unverified]** — prototype needed. |

## 6. Cross-cutting

| # | Question | Notes |
|---|----------|-------|
| XC1 | Auth parity: the MCP server assumes deployment inside Databricks Apps (`validate_session()` no-op); the helper relies on the SDK unified auth chain. In a laptop/Isaac context, which auth actually flows? | Grounding brief §Auth. Determines whether no-MCP path needs any user credential setup. |
| XC2 | Duplication: skills exist in BOTH `starboard-skills/skills/` and `starboard/skills/`. Which is canonical for packaging? | Grounding brief §Skills. Must resolve before publishing a plugin. |
| XC3 | `starboard-helper` currently registers 7 domains (job, query, warehouse, uc, cluster, finops, diagnostic) but 9 skills exist (adds analyze, discovery). Analyze/discovery skills compose other helper subcommands rather than having their own. Confirm this is intended. | Repo: `starboard_skills/helpers/__main__.py`. |

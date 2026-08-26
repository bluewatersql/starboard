# Integration Opportunities — Starboard into Existing Agent Hosts (no MCP required)

> Envisioning study, 2026-08-26. Evidence base: `_grounding_brief.md`, repo @ `b927dfaa` (starboard 0.1.1), internal Confluence (Isaac), official docs (Claude Code, Codex, OpenCode, Databricks Genie).
> Confidence tags: **[C]** confirmed by doc/repo · **[I]** inferred from confirmed facts · **[U]** unverified.
> LoE = level of effort (T-shirt), assuming the existing `starboard-skills` package and `starboard-helper` CLI as the substrate.

## The core thesis

Starboard **already** ships the two ingredients needed to go MCP-free:

1. **9 dual-mode `skill.md` files** that branch: *if `mcp__starboard__*` tools present → MCP path; else → shell out to `starboard-helper <domain> <cmd>`* (repo: `packages/starboard-skills/skills/starboard/*/skill.md`).
2. A **thin `starboard-helper` CLI** (entry point in `packages/starboard-skills/pyproject.toml`) that uses a bare `databricks.sdk.WorkspaceClient()` (unified auth chain) and prints JSON with clean exit codes 0–4 (`starboard_skills/helpers/__main__.py`).

Every host below can consume that same CLI substrate. The strategic move is to **package the skills + CLI once** and surface them natively in each host's own extension format. The single highest-leverage fact discovered this session:

> **Isaac — Databricks' internal coding agent — is a CLI wrapper/router over Claude Code, Codex, OpenCode, Cursor, and Omnigent, and it has a plugin marketplace** (`isaac plugin add PLUGIN@MARKETPLACE`). Plugins "add reusable skills, commands, MCP integrations, and apps to supported agents." **[C]** (Confluence *Isaac CLI, go/isaac-cli*, updated 2026-08-18). So a single Claude Code plugin published to the internal marketplace reaches every internal engineer with **no MCP server**.

---

## Opportunity map (summary)

| # | Opportunity | Host(s) | MCP needed? | LoE | Priority signal |
|---|-------------|---------|-------------|-----|-----------------|
| O1 | Package skills + `starboard-helper` as a **Claude Code plugin** (skills-only, no MCP) | Claude Code, **Isaac** | No | **M** | Highest leverage |
| O2 | Publish plugin to a **marketplace** (public GitHub + internal Isaac/vibe) | Claude Code, Isaac | No | **S** | Distribution unlock |
| O3 | **Dual-mode plugin**: same artifact optionally ships the MCP server, toggled by `userConfig` | Claude Code, Isaac | Optional | **M** | Best of both |
| O4 | Distribute skills via first-party **`databricks aitools install`** | Claude, Copilot, Cursor | No | **S–M** | External reach |
| O5 | **Codex** integration: `AGENTS.md` + `~/.codex/prompts/*.md` + skills, all calling `starboard-helper` | Codex | No | **S–M** | |
| O6 | **OpenCode** integration: custom `tool()` wrapping `starboard-helper` + agent + skills | OpenCode | No | **M** | |
| O7 | Optional **Codex/OpenCode MCP** registration (`[mcp_servers.*]` / `mcp` block) | Codex, OpenCode | Yes | **S** | Superset path |
| O8 | **Consume Genie** as an NL→SQL source via `starboard-helper genie ask` | all (via CLI) | No | **M** | New capability |
| O9 | **Expose Starboard within Genie**: provision a curated Genie space from discovery packs | Genie | No (uses Genie API) | **L** | Product bet |
| O10 | `.isaac/rules/`-style guidance + `starboard-helper` on PATH as a zero-plugin baseline | Isaac, Codex, Cursor | No | **S** | Fallback |
| O11 | Slash commands / output style for a "workspace triage" one-shot | Claude Code, Isaac | No | **S** | Polish |

---

## O1 — Claude Code plugin (skills-only, NO MCP) — the flagship no-MCP path

**Description.** Wrap the existing 9 skills and the `starboard-helper` CLI into an installable Claude Code plugin. `.claude-plugin/plugin.json` points `skills` at the bundled skill directory and **declares no `mcpServers`**. On install, the skills become `/starboard-query`, `/starboard-finops`, etc.; because no `mcp__starboard__*` tools exist, each skill's dual-mode logic automatically takes the `starboard-helper` branch. The CLI ships either as a bundled `bin/` script or as a `pip install starboard-skills` dependency documented in the plugin README. **[C]** plugin.json supports a `skills` path field and bundled `bin/`/`scripts/` (code.claude.com/docs/en/plugins-reference).

**Strengths.**
- Zero server to run, deploy, or authenticate; no long-lived process. Skills load lazily (progressive disclosure) so they cost ~nothing until invoked. **[C]**
- Reuses 100% of existing dual-mode skills — no skill rewrite. **[C repo]**
- Auth is the databricks-sdk unified chain the user already has (`~/.databrickscfg`, env, OAuth). **[C repo]**
- Works verbatim under Isaac (`isaac --claude`), since Isaac forwards to Claude Code. **[C]**

**Weaknesses.**
- No server-side agent orchestration: analysis is the host model reasoning over JSON the CLI returns, not Starboard's 7-agent stack / IntentRouter. Depth is lower than MCP path.
- Skills currently reference MCP tool names loosely ("or similar MCP tool"); the non-MCP branch is the real workhorse and must be hardened.
- `starboard-helper` only registers 7 domains; the `analyze`/`discovery` skills compose other subcommands. **[C repo]** Fine, but must be documented.

**Trade-offs.** Simplicity and portability vs. analytical depth. For most triage/discovery tasks the CLI+reasoning path is sufficient; deep RCA benefits from the MCP agent stack (see O3).

**Considerations.** Resolve the skill duplication (`starboard-skills/skills/` vs `starboard/skills/`) and pick one canonical source before packaging (open question XC2). Pre-authorize `Bash(starboard-helper:*)` via skill `allowed-tools` to avoid per-call prompts.

**LoE: M** — manifest + directory restructure + skill hardening + README; no new runtime.

## O2 — Marketplace distribution (public + internal Isaac/vibe)

**Description.** Ship a `.claude-plugin/marketplace.json` from a GitHub repo so users run `/plugin marketplace add <org>/starboard` then `/plugin install starboard`. Internally, onboard the same plugin into the Isaac/vibe marketplace so engineers run `isaac plugin add starboard@<marketplace>`. **[C]** marketplace.json schema (`name`, `owner`, `plugins[]`) verified; Isaac plugin commands verified.

**Strengths.** One-command install; versioned; the internal marketplace reaches every Isaac user (the org mandate is >$400/mo AI-tool usage per engineer — large captive audience). **[C]** Distribution is the difference between "a tool exists" and "a tool is used."

**Weaknesses/Considerations.** Internal onboarding likely requires review/gates (go/llmpolicy) and the internal PyPI proxy for deps **[U]** (open question I4). Marketplace `source` can be git/GitHub-release/npm **[C]**.

**LoE: S** (public) / **S–M** (internal onboarding, gated by review).

## O3 — Dual-mode plugin: skills default, MCP optional (single artifact)

**Description.** The *same* plugin ships both the skills (default) and the `starboard-mcp` server, declared under `mcpServers` in `.mcp.json`, gated behind a `userConfig` toggle (`enable_mcp`). Users who want the full agent stack flip it on; everyone else gets the CLI path. Confirmed feasible: Claude Code plugins can bundle an MCP server, and Isaac renders plugin-delivered MCP as `plugin:NAME:server`. **[C]**

**Strengths.** One install, two fidelity levels; graceful upgrade path from CLI reasoning → server-side 7-agent orchestration (`query_agent`, `job_agent`, … `discovery_agent` — real tool names, `mcp/agent_bridge.py`). The skills' existing dual-mode branch means no skill changes needed to support both. **[C repo]**

**Weaknesses.** MCP path reintroduces server lifecycle, config (LLM keys per `examples/cursor-mcp.json`), and the known wiring gaps flagged in `changes/mcp_claude/`. Requires `userConfig` plumbing and clear docs on when to enable.

**Trade-offs.** Slightly more complex manifest for a much better ceiling.

**LoE: M.**

## O4 — First-party distribution via `databricks aitools install`

**Description.** Databricks ships a public skills installer: `databricks aitools install` installs Agent-Skills-standard skill files into detected AI assistants (Claude, Copilot, Cursor), scoped global or per-project. **[C]** (docs.databricks.com/aws/en/agent-skills, "Skills teach the agent how to work; MCP servers let it do the work"). Starboard's skills could be contributed to / distributed through this channel for Databricks *customers* (not just internal).

**Strengths.** Official, trusted, multi-assistant channel with automatic discovery; aligns with Databricks' own "skills, not servers" positioning. Reaches the external customer base Starboard ultimately targets.

**Weaknesses/Considerations.** Requires conforming to the exact Agent Skills standard fields (subset of Claude Code's) and likely a Databricks-side inclusion process **[U]**. Overlap/precedence with the Isaac plugin path is unconfirmed (open question I7).

**LoE: S–M.**

## O5 — Codex (OpenAI Codex CLI/IDE)

**Description.** Surface Starboard in Codex three complementary ways, all MCP-free: (1) an `AGENTS.md` section (repo root and/or `~/.codex/AGENTS.md`) teaching Codex that `starboard-helper <domain> <cmd>` exists and when to use it; (2) `~/.codex/prompts/*.md` custom prompts invoked as `/starboard-*` slash commands with `$ARGUMENTS` substitution; (3) Codex **skills** — Codex now supports packaging "repeatable instructions as skills." **[C]** (learn.chatgpt.com/docs/codex/cli). All three drive the same CLI.

**Strengths.** No server; Codex's `codex exec` also enables scripted/CI Starboard runs. Under Isaac, `.isaac/rules/` already compiles into Codex `AGENTS.md` **[C]** — a natural injection point.

**Weaknesses.** Codex's skills format/location is less documented than Claude Code's (page 404'd this session) — treat exact frontmatter as **[U]**, verify before build. Sandbox/approval model may prompt on each `starboard-helper` shell-out; needs config guidance.

**Trade-offs.** Lighter integration than Claude Code plugins (no unified bundle), but Codex's config.toml `[mcp_servers.*]` is available if MCP is later desired (O7).

**LoE: S–M.**

## O6 — OpenCode

**Description.** OpenCode's richest no-MCP surface is a **custom tool**: a TypeScript file at `.opencode/tool/starboard.ts` using `import { tool } from "@opencode-ai/plugin"` that shells out to `starboard-helper` (via Bun `$`) and returns JSON. Pair with a subagent (`.opencode/agent/databricks-expert.md`, `mode: subagent`), `SKILL.md` skills (OpenCode supports the same skill concept), and an `AGENTS.md` section. **[C]** (opencode.ai/docs/custom-tools, /agents, /skills, /rules; verified with repo examples). Isaac can launch OpenCode (`isaac opencode`). **[C]**

**Strengths.** The custom tool gives a *typed, first-class tool* (not just a Bash blob) with zod-validated args and native permission control (`"starboard": "allow"`), while remaining a thin CLI wrapper — no MCP server. Lower latency than MCP (subprocess vs IPC).

**Weaknesses.** Requires a TS/JS artifact (new language surface for a Python project); must be maintained per OpenCode tool-API changes. Skills carryover from a Claude Code plugin is not automatic — OpenCode reads its own `.opencode/skills/`.

**Trade-offs.** More native than Codex, but bespoke to OpenCode's file layout.

**LoE: M.**

## O7 — Optional MCP registration in Codex / OpenCode

**Description.** For teams wanting the full agent stack, register `starboard-mcp` in Codex `~/.codex/config.toml` `[mcp_servers.starboard]` (command/args/env, stdio) or OpenCode `mcp.starboard` (`type: local`). **[C]** Both hosts support stdio and HTTP MCP.

**Strengths.** Unlocks server-side orchestration in non-Claude hosts; reuses the existing `starboard-mcp` entry point and streamable-HTTP transport.

**Weaknesses.** Same server-lifecycle/LLM-key burden as O3; per-user config edits (no unified plugin bundle in Codex).

**LoE: S** (config snippets + docs).

## O8 — Consume Genie as an NL→SQL source

**Description.** Add a `starboard-helper genie ask --space-id <id> --question "<nl>"` subcommand that calls `w.genie.start_conversation_and_wait(...)` / `create_message_and_wait(...)`, then `get_message_attachment_query_result(...)` to retrieve generated SQL + result rows, returning JSON. Starboard then reasons over / optimizes the Genie-produced SQL, or uses Genie to resolve fuzzy NL questions into concrete queries feeding its analyzers. **[C]** SDK methods verified (databricks-sdk-py GenieAPI).

**Strengths.** Lets Starboard answer NL data questions it doesn't have a hard-coded query pack for; complements the ~17 discovery packs. Pure SDK call — fits the existing helper pattern; no MCP.

**Weaknesses/Considerations.** Requires a Genie space to exist and `CAN USE` on a warehouse + `CAN RUN` on the space; async poll model (statuses `EXECUTING_QUERY`/`COMPLETED`/`FAILED`) must be handled. **[C]** Auth is OAuth U2M/M2M. GA-vs-preview and limits unconfirmed (open question G1).

**Trade-offs.** Adds a Databricks-feature dependency; Genie SQL still needs Starboard's validation.

**LoE: M.**

## O9 — Expose Starboard within/alongside Genie spaces

**Description.** Provision a curated "Starboard" Genie space via `w.genie.create_space(warehouse_id, serialized_space=...)` seeded with the discovery query-packs (billing, jobs, query_performance, compute, governance, …) as sample queries/instructions, so Genie users get Starboard's curated system-table analytics through the Genie UI/API. **[C]** `create_space`/`update_space` exist in the SDK.

**Strengths.** Meets analysts where they already are (Genie UI in the Databricks workspace); turns Starboard's query IP into a governed, shareable NL surface; no coding-agent host required at all.

**Weaknesses.** `serialized_space` schema is opaque/under-documented **[U]**; Genie's curation model may not map cleanly to Starboard's parameterized multi-step packs; larger product commitment.

**Trade-offs.** Broadest reach, highest uncertainty and effort.

**LoE: L.**

## O10 — Zero-plugin baseline: PATH CLI + rules guidance

**Description.** Simplest possible: put `starboard-helper` on PATH and add a short guidance block (CLAUDE.md / AGENTS.md / `.isaac/rules/`) telling any agent it exists. Works in every host immediately, no packaging. **[C]** `.isaac/rules/` compiles to Claude/Cursor/Codex guidance.

**Strengths.** Instant, universal, trivial. Good for pilots and for hosts without a plugin concept.

**Weaknesses.** No discovery UX, no versioning, no lazy loading; relies on the model noticing the guidance.

**LoE: S.**

## O11 — One-shot "workspace triage" command / output style

**Description.** A slash-command skill (`/starboard-triage`) that runs a fixed discovery+diagnostic sequence and formats a prioritized report; optionally a Claude Code output style for consistent report layout. **[C]** plugin.json supports `commands` and `outputStyles`.

**Strengths.** High-value canned workflow; showcases the tool. **Weaknesses.** Narrow. **LoE: S.**

---

## Cross-cutting considerations

- **One CLI, four hosts.** `starboard-helper` is the universal substrate. Investing in its breadth/robustness (more domains, stable JSON contract, `--format json`) pays off across every host. This is the single most reusable asset for the no-MCP strategy.
- **Auth reality check.** The MCP server assumes deployment inside Databricks Apps (`validate_session()` no-op); the CLI relies on the SDK unified chain. On a laptop/Isaac, whether Isaac-injected Databricks OAuth lands on the SDK chain the helper reads is **[U]** and gates the "just works" UX (open questions I5, XC1).
- **Skills vs MCP is not either/or.** Databricks' own framing — "skills teach the agent how to work; MCP servers let it do the work" — matches Starboard's dual-mode design. Ship skills-first; offer MCP as an opt-in ceiling.
- **Depth ceiling.** The CLI path exposes *data*; the MCP path exposes *the 7-agent analytical stack*. Be explicit with users about which they're getting.

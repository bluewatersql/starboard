# Agent-skills distribution

> **Moved.** The agent-skills distribution story (the `databricks aitools` channel, the
> Agent Skills standard, and how the canonical skills tree reaches external customers) now
> lives in one canonical page:
>
> **→ [Distribution via `databricks aitools`](distribution/databricks-aitools.md)**

## In one paragraph

Starboard's skills come from a **single canonical tree** at
`packages/starboard-skills/skills/starboard/` (10 skills). That tree is vendored into the
Claude Code / Isaac plugin (`plugin/` + `marketplace.json`) by
`scripts/vendor_plugin_skills.py` and drift-checked with `make vendor-skills-check`. Each
skill is a self-contained Agent Skill (`SKILL.md` + optional `scripts/`/`references/`), and
the diagnostic skill's Tier-1 helper shells out to `python -m starboard_x.diagnostic`
(the `starboard_x` helpers ship in the `starboard-core` wheel).

The **`databricks aitools`** mirror (agent-skills layout + a generated `manifest.json`) is
**format-documented but not yet materialized** — today only the plugin channel ships. See
the canonical page for the confirmed command surface, the portable-frontmatter spec, and
the open owner questions.

For per-host reach (Claude Code, Isaac, Codex, OpenCode) see
[Host coverage & integration](HOST_COVERAGE.md).

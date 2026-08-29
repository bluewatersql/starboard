# How to choose: skill vs tool vs agent vs helper

Starboard ships the same Databricks-analysis kernel behind several **surfaces**.
This guide explains how they relate and how to pick the right one. For the
generated, always-current inventory of every surface, see the
[Capability Catalog](../reference/CATALOG.md).

> Dollar figures on the public path are **list-price DBU estimates** — always
> labelled as such.

## The tier model

Starboard is layered into three tiers, mirroring the `uv` workspace packages:

| Tier | Package | What lives here | Dependencies |
|------|---------|-----------------|--------------|
| **Kernel** | `starboard-core` (`starboard_core`) | Pure DTOs, ports, analyzers | stdlib + `pydantic` (no SDK / FastAPI / MCP) |
| **Capability** | `starboard-core` (`starboard_x`) | Progressive helpers (`python -m starboard_x.<cap>`) | dependency-light; per-capability extras |
| **Experience** | `starboard` | FastAPI server, MCP tools, agents, CLI | full stack (SDK + FastAPI + MCP) |

Skills and agent definitions ship in `starboard-skills`; per-domain plugins are
opt-in thin wheels discovered through an entry-point group.

## The five surfaces

- **Skill** — a natural-language capability packaged as a `SKILL.md` prompt for
  a skill-aware host (Claude Code, Cursor, Claude Desktop). It routes to a
  domain agent when MCP tools are available and degrades to the
  `starboard-helper` CLI otherwise. *Choose when* you are working inside a chat
  host and want intent-based invocation.
- **MCP tool** — one focused operation callable over MCP by name (e.g.
  `resolve_query`). Tools are **shared across agents**; the authoritative count
  is the registry size (`len(ALL_TOOL_METADATA)`), never a per-agent sum.
  *Choose when* you are orchestrating steps yourself and want a single, typed
  operation.
- **Agent** — a canonical definition (subagent, orchestrator, or autonomous)
  that owns a domain workflow end-to-end and returns a prioritized,
  evidence-cited report. Subagents are reached through their
  `mcp__starboard__*` tool. *Choose when* you want server-side reasoning over a
  whole domain, not a single tool call.
- **CLI command** — the `starboard` command surface: the NL goal agent
  (`--goal` / `--chat`), workspace discovery (`--discover`), and the routed
  `review`, `genie`, and `auth` groups. *Choose when* you are at a terminal or
  scripting a pipeline.
- **Progressive helper** — a dependency-light `python -m starboard_x.<cap>`
  module that runs a pure analyzer without the full experience wheel and emits a
  JSON envelope. *Choose when* you want offline/embedded analysis or a
  lightweight install.
- **Plugin** — an opt-in per-domain tool wheel discovered through the
  `starboard.mcp_tools` entry-point group. *Choose when* you are extending
  Starboard with your own domain tools; absent plugins leave the built-in
  catalog fully functional.

## Decision guide

1. **Inside a chat host (Claude Code / Cursor / Claude Desktop)?** Use the
   **skill** for the domain — it picks the best available path for you.
2. **At a terminal or in a pipeline?** Use a **CLI command**
   (`starboard review`, `starboard genie ask`, `starboard --goal …`).
3. **Want a whole-domain report with server-side reasoning?** Invoke the
   domain **agent** (`mcp__starboard__<domain>_agent`).
4. **Orchestrating steps yourself?** Call individual **MCP tools** by name.
5. **Offline / embedded / minimal install?** Run a **progressive helper**
   (`python -m starboard_x.<cap>`).
6. **Extending Starboard?** Ship a **plugin** on the `starboard.mcp_tools`
   entry-point group.

## See also

- [Capability Catalog](../reference/CATALOG.md) — generated index of every surface
- [Skills index](../reference/skills/INDEX.md)
- [MCP tools index](../reference/mcp-tools/INDEX.md)
- [Agents index](../reference/agents/INDEX.md)
- [CLI commands index](../reference/cli-commands/INDEX.md)
- [Progressive helpers index](../reference/progressive-helpers/INDEX.md)
- [Plugins index](../reference/plugins/INDEX.md)
- [Install Tiers](../reference/INSTALL_TIERS.md)

---
title: "Package: starboard-plugin-sample"
description: Reference per-domain tool-plugin scaffold for the layered-catalog plugin contract.
last_reviewed: 2026-08-27
status: current
---

# starboard-plugin-sample

> **Docs** > **Packages** > **starboard-plugin-sample**

A **reference scaffold** (import package `starboard_plugin_sample`), not a shipped
capability. It demonstrates the layered-catalog **tool-plugin contract** end-to-end: a
thin wheel that registers a per-domain tool through the public `starboard.mcp_tools`
entry-point group and is discovered at runtime.

> **Plugins are not MCP servers.** They are thin wheels discovered via entry points; MCP
> is a separate, optional transport (`starboard-mcp`).

---

## The contract

A plugin registers a `ToolPlugin` object (contract in `starboard.tools.plugins`) under
the entry-point group (`packages/starboard-plugin-sample/pyproject.toml`):

```toml
[project.entry-points."starboard.mcp_tools"]
sample_jobs_health = "starboard_plugin_sample.plugin:sample_plugin"
```

Discovery loads these entry points and registers them into a `ToolCatalog`, keyed by the
plugin's `name`. Because a plugin is **never a dependency of a Starboard wheel**, the
catalog is opt-in: with no plugin installed, discovery returns an **empty catalog** and
every built-in tool keeps working.

## Using it as a starting point

Copy this directory as the starting point for a real per-domain plugin. A real plugin
depends on whatever tier its tool needs — a kernel-only tool depends on `starboard-core`;
a tool that needs the server surface depends on `starboard`.

It is a uv-workspace member for local linting, type-checking, and contract tests, but is
excluded from the public wheels.

---

## Related documentation

- [Tool Architecture → entry-point seams](../../TOOL_ARCHITECTURE.md)
- [Package Integration](../../integration/PACKAGE_INTEGRATION.md)
- [Tool Development Guide](../../tools/TOOL_DEVELOPMENT_GUIDE.md)

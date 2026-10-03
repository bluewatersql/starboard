# starboard-plugin-sample

A **reference per-domain tool plugin** for Starboard's layered catalog
(Phase-3 B5). Copy this directory as the starting point for a real plugin.

## What it demonstrates

Starboard ships a fixed, universal tool surface across its three tiers
(kernel → capability → experience). Optional **per-domain plugins** — their own
thin wheels — extend that surface at runtime by registering tools/analyzers
through the `starboard.mcp_tools` Python entry-point group. No plugin is
required: with none installed, discovery returns an empty catalog and every
built-in tool keeps working.

## The contract (`starboard.mcp_tools`)

Each entry point resolves to a `ToolPlugin`
(`starboard.tools.plugins.ToolPlugin`) exposing:

| member     | meaning                                                             |
|------------|---------------------------------------------------------------------|
| `name`     | unique, stable registration key (the catalog key)                   |
| `domain`   | capability domain the tool belongs to (e.g. `"jobs"`, `"warehouse"`)|
| `create()` | zero-arg factory returning the tool/analyzer instance               |

`SimpleToolPlugin(name=..., domain=..., factory=...)` is the easy path — expose
a module-level instance and point the entry point at it:

```toml
[project.entry-points."starboard.mcp_tools"]
sample_jobs_health = "starboard_plugin_sample.plugin:sample_plugin"
```

## How a host discovers it

```python
from starboard.tools.plugins import install_entry_point_tools

catalog = install_entry_point_tools()      # reads installed distributions
tool = catalog.create("sample_jobs_health")  # instantiate on demand
catalog.by_domain("jobs")                   # or enable a whole domain
```

With this package **absent**, `install_entry_point_tools()` returns an empty
`ToolCatalog` — nothing breaks. One malformed plugin is skipped (non-strict)
rather than breaking discovery for the rest.

## Install (opt-in)

```bash
pip install starboard-plugin-sample   # layers the `jobs` sample tool on top
```

This package is intentionally **not** a uv workspace member and **not** a
dependency of any Starboard wheel: the layered catalog is opt-in.

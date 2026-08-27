# Phase 3 · B5 — Layered catalog / per-domain plugins (design + impl note)

> Implements PHASE_3.md §11 (Task B5). Builds on the D-3.1 entry-point seam.
> Public path only — additive packaging, no internal namespaces, no breaking
> split of the existing single-wheel install.

## 1. Two additive mechanisms

B5 delivers the layered catalog as **two additive mechanisms**, neither of which
changes the existing `pip install starboard` (full) or any existing extra:

1. **Named tier extras** — the 3-tier model (kernel → capability → experience)
   made explicit as install targets on the `starboard-meta` root package.
2. **Per-domain tool plugins** — an entry-point discovery contract
   (`starboard.mcp_tools`) that layers optional per-domain tools onto the
   built-in surface at runtime; absent plugins degrade cleanly.

## 2. Tier extras (kernel → capability → experience)

The three tiers are already three separately-installable thin wheels
(`starboard-core`, its `starboard_x` middle tier, and `starboard`). B5 names the
composition as additive extras in the root `pyproject.toml`:

| Extra | Installs | Tier |
|-------|----------|------|
| `starboard-meta[kernel]`     | `starboard-core`        | pure DTOs + analyzers (no `databricks-sdk`) |
| `starboard-meta[capability]` | `starboard-core[all]`   | + `python -m starboard_x.<domain>` progressive-disclosure helpers |
| `starboard-meta[experience]` | `starboard`             | full MCP server + CLI + agents |

Independent installability is enforced by test: the kernel surface (and the
`starboard_x` capability analyzers) import in a subprocess with the `starboard`
experience package **blocked** — proving a kernel-only install resolves without
any experience-tier import (`packages/starboard-core/tests/unit/test_layered_catalog_tiers.py`).

Back-compat: the pre-existing extras (`core`, `server`, `cli`, `sdk`, `all`,
`dev`) are untouched, and `pip install starboard` still pulls the full stack via
`starboard`'s hard dependency on `starboard-core`.

## 3. Per-domain plugin contract (`starboard.mcp_tools`)

A NEW entry-point group, distinct from D-3.1's `starboard.port_adapters` (which
is bound to the four data-enablement `Port` values). Per-domain **tools** are not
ports, so they get their own kernel-light contract in
`starboard/tools/plugins.py` (re-exported from `starboard.tools`).

**Group:** `starboard.mcp_tools`. Each entry point resolves to a `ToolPlugin`:

| member     | meaning |
|------------|---------|
| `name`     | unique, stable registration key (the catalog key) |
| `domain`   | capability domain (`"jobs"`, `"warehouse"`, …) — enable tools by domain |
| `create()` | zero-arg factory returning the tool/analyzer instance |

`SimpleToolPlugin(name, domain, factory)` is the easy path. A distributing
package declares:

```toml
[project.entry-points."starboard.mcp_tools"]
my_domain_tool = "my_pkg.plugin:my_plugin"   # -> a ToolPlugin object
```

**Host integration is a single call** (mirrors D-3.1's `install_entry_point_adapters`):

```python
from starboard.tools.plugins import install_entry_point_tools

catalog = install_entry_point_tools()          # reads installed distributions
tool = catalog.create("my_domain_tool")         # instantiate on demand
catalog.by_domain("jobs")                        # or a whole domain
```

Like the D-3.1 discovery module, `plugins.py` depends only on the stdlib
(`importlib.metadata`) — it never imports the MCP/SDK/model stack, so the catalog
is usable from any tier and the *shape* of a tool object is left to the host.

## 4. Degrade-cleanly invariant

- **No plugin installed** → `discover_tool_plugins()` returns `[]`,
  `install_entry_point_tools()` returns an empty `ToolCatalog`, every built-in
  tool keeps working. (UNIFIED_PLAN §3.5 applied to the catalog.)
- **One bad plugin** (fails to load, wrong shape, empty name/domain) → skipped in
  non-strict mode so it cannot break discovery for the rest; raises under
  `strict=True`.
- **Name collision** → first registration wins in non-strict mode; raises under
  `strict=True`; `register(..., replace=True)` overrides explicitly.

## 5. Reference scaffold

`packages/starboard-plugin-sample/` is a complete, copy-me plugin: a thin wheel
in the `jobs` domain that declares the entry point and ships a trivial,
side-effect-free tool. It is deliberately **not** a uv workspace member and
**not** a dependency of any Starboard wheel — the catalog is opt-in. It keeps the
layered wheels compatible with a skills-bundle distribution (cf.
`databricks/databricks-agent-skills`): a domain team ships its tools as an
independent wheel discovered at runtime, never vendored into the core wheels.

## 6. Files

- `packages/starboard/starboard/tools/plugins.py` — the `starboard.mcp_tools`
  contract + `ToolPlugin` / `SimpleToolPlugin` / `ToolCatalog` + discovery.
- `packages/starboard/starboard/tools/__init__.py` — re-exports the contract.
- `packages/starboard-plugin-sample/**` — reference per-domain plugin scaffold.
- root `pyproject.toml` — `kernel` / `capability` / `experience` tier extras +
  the `starboard.mcp_tools` contract documentation.
- Tests: `packages/starboard/tests/unit/tools/test_tool_plugins.py`,
  `packages/starboard-core/tests/unit/test_layered_catalog_tiers.py`,
  `packages/starboard-plugin-sample/tests/test_plugin.py`.

## 7. Guardrails held

- **Additive / back-compat** — no existing extra or import changed; the full
  single-wheel install is unchanged.
- **import-linter** — all four existing contracts KEPT; `plugins.py` lives in the
  experience package and imports only the stdlib, so no kernel boundary is
  crossed and no `starboard_internal` edge is introduced.
- **No internal namespaces** — contract, scaffold, and docs name nothing internal.

# starboard-capability

Capability tier of the [Starboard](https://github.com/databricks/starboard) layered
catalog, published as an independently installable wheel.

`starboard-capability` is a thin meta-package. It ships no import package of its own;
it pulls the kernel wheel plus every per-capability `starboard_x` extra so that

```bash
pip install starboard-capability
```

gives you the full progressive-helper surface (`python -m starboard_x.<domain>`)
without the FastAPI/MCP experience tier.

## Tiers

| Install | You get |
|---|---|
| `pip install starboard-kernel` | Pure DTOs + analyzers (`starboard_core`) |
| `pip install starboard-capability` | Kernel + `starboard_x` progressive helpers (all domains) |
| `pip install starboard` | Full MCP server + CLI + agents |

To install only the domains you need, depend on the kernel extras directly, e.g.
`pip install "starboard-kernel[warehouse,uc]"`.

See [`docs/reference/INSTALL_TIERS.md`](../../docs/reference/INSTALL_TIERS.md).

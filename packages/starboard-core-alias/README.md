# starboard-core (deprecated alias)

> **Deprecated.** Install [`starboard-kernel`](../starboard-core) instead.

The kernel distribution was renamed `starboard-core` -> `starboard-kernel` in
Phase 1. The **import package is unchanged** — `import starboard_core` (and
`starboard_x`) still work exactly as before; only the published wheel name changed.

This package is a thin, code-free alias that keeps `pip install starboard-core`
working for **one release** by depending on `starboard-kernel`. It will be removed
in the next release.

## Migrate

```bash
# Old (still works this release, via this alias):
pip install starboard-core

# New (do this):
pip install starboard-kernel
```

No code changes are required: `import starboard_core` continues to work either way.

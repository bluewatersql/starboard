# Host coverage — Claude Code, Isaac, Codex, OpenCode

Starboard's no-MCP path is a **stable shell invocation** that any host able to run a
Bash command can use identically:

```bash
python -m starboard_x.<capability> [args]      # discovery | warehouse | uc | sparklog | diagnostic | review
```

Each capability emits the compact JSON envelope (`{ok, domain, command, data|error, meta}`)
and the standard exit codes (`0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error`).
Because the invocation is host-agnostic, host coverage is a packaging + auth concern,
not a code concern. **Plugins are not MCP servers** — the plugin injects skills; nothing
starts an MCP server.

## Per-host

| Host | Discovery | Invocation | Auth |
|------|-----------|-----------|------|
| **Claude Code** | plugin marketplace (`marketplace.json`) | skill `run.sh` → `python -m starboard_x.…` | SDK credential chain |
| **Isaac** (wraps Claude Code) | same plugin; register locally with `scripts/dev_plugin_local.sh` | same | Isaac-injected identity → SDK chain |
| **Codex** | no plugin loader → call the helper directly | `python -m starboard_x.…` or `starboard-helper …` | SDK chain / `--profile` |
| **OpenCode** | agent config references the helper command | `python -m starboard_x.…` | SDK chain / `--profile` |

Codex/OpenCode lack a Claude-Code-style plugin loader, so the story is: install the
`starboard-x[…]` wheel (the tier-2 helper) and call `python -m starboard_x.…` — no
host-specific plugin machinery required.

## Local Isaac plugin dev/test (G3)

```bash
scripts/dev_plugin_local.sh add      # vendor skills, register ./plugin, enable
isaac --claude                       # start a session; confirm skills are injected
scripts/dev_plugin_local.sh remove   # clean up the dev entry
```

## Baseline agent rules (`.isaac/rules`)

`plugin/rules/starboard.md` ships a paraphrased, public baseline (helper-first,
list-price $, single-workspace, read-only). Copy it into a workspace's `.isaac/rules/`
to activate sane defaults for Isaac sessions.

# Databricks Auth — Recommendation

> Ranked recommendation for the **simplest unified auth UX** for Starboard.
> Grounded in databricks-sdk 0.73.0 (verified) + current docs. See `opportunities.md` for the option catalog and `technical.md` for the design.

## The one-sentence thesis

**Stop constructing `WorkspaceClient(host=, token=)`. Build a `Config` from only the
inputs the user gave, hand it to the SDK, and let the SDK's unified credential chain do
the rest — then make "target a workspace" a single `--profile`/`STARBOARD_WORKSPACE` flag.**

Everything else is polish on top of that subtraction.

## Why this is *simpler*, not just different

- The SDK 0.73.0 already resolves **PAT, OAuth U2M, OAuth M2M, Azure, Google, OIDC,
  notebook-native, and model-serving OBO** with a documented precedence
  (`credentials_provider.py:1059`). Starboard re-implements a worse, PAT-only slice of this.
- Two of Starboard's own subsystems (**skills helper** `helpers/uc.py:34`, **state/uc
  stores** `state/databricks/*.py`) already call bare `WorkspaceClient()` and work. The
  recommendation is to make the *rest* of the codebase consistent with the parts that are
  already right.
- Net effect: **less code** (delete forced-credential validation), **more auth methods**,
  one mental model.

---

## Ranked recommendation

### Rank 1 — Adopt SDK unified auth as the default resolution path  *(O1 + O7)*  — do first
Introduce one `resolve_workspace_client()` helper (see `technical.md`) that:
- passes `host`/`token`/`client_id`/`client_secret`/`profile` to `Config` **only when set**,
- otherwise lets `DefaultCredentials` resolve (env → `.databrickscfg` → ambient),
- and **removes** the hard requirement that `DATABRICKS_TOKEN` be present.

PAT keeps working unchanged (it's just the `pat` strategy, first in the chain). This is the
keystone; ranks 2–5 build on it. **LOE: S–M.**

### Rank 2 — First-class workspace targeting via `profile`  *(O2)*
`--profile NAME`, env `STARBOARD_WORKSPACE` (aliased to `DATABRICKS_CONFIG_PROFILE`), and a
`starboard workspace {list,use,current}` command reading `.databrickscfg`. One flag switches
workspaces across external, internal, and Genie contexts. **LOE: M.**

### Rank 3 — `starboard auth login` for interactive OAuth U2M  *(O3)*
Wrap `databricks auth login --host <url> --profile <name>` (fallback: drive the SDK
`external-browser` strategy in-process when the CLI is absent). Gives browser SSO with
auto-refresh, no PAT paste, and works for **internal Okta** and external customer SSO alike.
**LOE: M.**

### Rank 4 — Zero-config ambient auth for notebooks/Apps/jobs  *(O4 + O5)*
Make `notebooks.get_workspace(host=None, token=None)` fall through to `WorkspaceClient()`
inside Databricks. Stop clobbering App-injected `DATABRICKS_CLIENT_ID/SECRET`. **LOE: S.**

### Rank 5 — Unify MCP registry & `workspace_manager` on the same resolver  *(O8)*
Extend `WorkspaceProfile` so an entry may name a `.databrickscfg` `profile` (preferred), an
env `token_env` (compat), or neither (ambient). One resolution model everywhere; closes the
"multi-workspace is env-var-only, no OAuth/refresh" gap from the grounding brief. **LOE: M–L.**
  -- **FEEDBACK NOTES**: Remove multi-workspace all together. The `--profile` option removes the
  requirment for multi-workspace, the workpsace manager and the complexity of the config/setup. 
  Raise priority for refactoring and removal to to Rank 2.

### Rank 6 (defer) — Apps On-Behalf-Of-User (OBO)  *(O6)*
Per-request `WorkspaceClient` from `x-forwarded-access-token` so queries honor each user's UC
grants and Genie space access. Only needed for **multi-user App hosting**; genuinely complex
because Starboard uses a singleton client today. Defer until multi-tenant App hosting is a
committed requirement. **LOE: L.**

---

## Target UX

### CLI — workspace targeting (precedence, highest wins)
```
1. --profile NAME                     (explicit flag)
2. --host / --token / --client-id ... (explicit inline overrides)
3. STARBOARD_WORKSPACE  → profile     (Starboard's friendly alias)
4. DATABRICKS_CONFIG_PROFILE          (SDK-native)
5. DATABRICKS_HOST (+ TOKEN | CLIENT_ID/SECRET)   (SDK env auth)
6. .databrickscfg DEFAULT profile     (SDK default)
7. ambient (notebook / App / job / model-serving)  (SDK runtime auth)
→ if none resolve: one clear error naming `starboard auth login` and `--profile`
```

### Commands
```bash
# Interactive login (browser SSO; works for external + internal Okta)
starboard auth login --host https://e2-demo-field-eng.cloud.databricks.com --profile fe
starboard auth login --host https://acme.cloud.databricks.com --profile acme

# Target a workspace for a single run
starboard --profile acme --goal "Analyze query abc123"

# Or set once for the session
export STARBOARD_WORKSPACE=fe
starboard --goal "Workspace health check"

# Token path still works (external customer with only a PAT)
starboard --host https://acme.cloud.databricks.com --token dapi... --goal "..."
# or: export DATABRICKS_HOST=... DATABRICKS_TOKEN=...

# Inspect / switch
starboard auth status          # shows resolved host, auth_type (pat|databricks-cli|oauth-m2m), user
starboard workspace list       # lists .databrickscfg profiles + starboard registry
starboard workspace use fe     # sets default profile
```

### Inside Databricks (notebook / job / App)
```python
from starboard.notebooks import get_workspace
w = get_workspace()            # ambient identity — no host/token needed
```

### Flag / env rename map (keep old ones as aliases for one release)
| Today | Add | Note |
|-------|-----|------|
| `--databricks-host` | `--host` (alias) | shorter; keep old |
| `--databricks-token` | `--token` (alias) | shorter; keep old |
| — | `--profile` | new primary targeting |
| — | `--client-id` / `--client-secret` | M2M inline |
| — | `--auth-type` | force a strategy for debugging |
| — | `STARBOARD_WORKSPACE` | friendly alias for `DATABRICKS_CONFIG_PROFILE` |

---

## Sequencing (delivery plan)

| Phase | Scope | Ranks | LOE | Unblocks |
|-------|-------|-------|-----|----------|
| **P1** | `resolve_workspace_client()` helper; `AsyncDatabricksClient` + `notebooks.get_workspace` use it; drop forced-token validation; keep PAT | R1, R4 | **S–M** | OAuth, M2M, ambient, notebooks — immediately |
| **P2** | `--profile` / `STARBOARD_WORKSPACE`; `starboard auth status`; `workspace list/use` | R2 | **M** | easy workspace switching |
| **P3** | `starboard auth login` (CLI wrapper / external-browser fallback) | R3 | **M** | interactive SSO incl. internal Okta |
| **P4** | Extend `WorkspaceProfile` (profile\|token_env\|ambient); migrate `workspace_manager`; MCP registry resolves via P1 helper | R5 | **M–L** | unified multi-workspace, OAuth in MCP |
| **P5** *(defer)* | Apps OBO via `x-forwarded-access-token`; per-request client; declare `genie`/`sql` scopes | R6 | **L** | safe multi-user App hosting + per-user Genie |

**Critical path:** P1 must land first — it is the shared resolver every later phase reuses.
P2/P3 can proceed in parallel after P1. P4 depends on P1's resolver. P5 is independent and
optional.

## Risks & mitigations
- **"Magic" resolution / confusing failures** → `starboard auth status` + a single explicit
  error message that names `--profile` and `starboard auth login`; log the winning
  `w.config.auth_type`.
- **Headless OAuth** (no browser) → document PAT / M2M for those hosts; `external-browser`
  needs a reachable browser.
- **CLI dependency for `auth login`** → fall back to SDK `external-browser` in-process.
- **Back-compat** → keep `--databricks-host/--databricks-token` and the host+token env
  fallback; `WorkspaceProfile.token_env` stays valid.
- **Internal VPN/Okta** → out of Starboard's control; `auth login` surfaces the browser flow,
  document the VPN prerequisite (*confidence: high, Glean-sourced*).

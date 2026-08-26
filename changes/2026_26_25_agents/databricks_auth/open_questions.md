# Databricks Auth — Open Questions

> Unresolved items and anything not fully verified. Confidence tags: **[verified]** (SDK read / official docs), **[high]** (internal Glean sources), **[medium]**, **[low/unverified]**.

## Internal Databricks employee auth (internal-only)

1. **In-process `external-browser` behind Okta + VPN.** [medium] Glean confirms FE
   workspaces (`e2-demo-field-eng`) use OAuth U2M via `databricks auth login` + Okta SSO,
   VPN-required, `auth_type = databricks-cli`. **Unverified:** whether the SDK's in-process
   `external-browser` strategy (our CLI-absent fallback) completes the Okta flow cleanly, or
   whether the installed `databricks` CLI is effectively mandatory internally. *Test on a real
   FE laptop before relying on the fallback.*
2. **Token cache location vs. OS keyring.** [medium] Docs say U2M caches at
   `~/.databricks/token-cache.json`; Glean says "CLI 1.x stores U2M secrets in OS-native
   secure storage by default." Need to confirm which applies for our target CLI version, since
   it affects whether the SDK (`databricks-cli` strategy) can read the cache headlessly.
3. **FE PAT policy.** [high] PATs kept enabled for automation, **90-day max** in demo
   workspaces. Confirm rotation expectations if Starboard server runs long-lived in an FE
   workspace (argues for M2M over PAT there).
4. **Account-level auth.** [verified API] `AccountClient` exists and does *not* support
   notebook-native auth. **Open:** does Starboard need any account-level calls (it appears
   workspace-scoped today)? If not, we can ignore `AccountClient` entirely.

## OBO / Apps (deferred phase)

5. **Singleton → per-request client.** [verified problem] `AsyncDatabricksClient` is built
   once (`client.py`). OBO needs a client per user request. Open design question: request-scoped
   client factory + caching strategy, and its blast radius across the tools/agents layers.
6. **Token lifetime / refresh for forwarded tokens.** [low] `x-forwarded-access-token` is a
   short-lived user token; behavior for long-running agent tasks that outlive it is unverified.
   Does Apps refresh the header mid-session, or must we re-auth per request only?
7. **Scope declaration mechanics.** [medium] Apps auth docs list scopes (`sql`, `files`,
   `genie`, `model-serving`) and an admin "restrict OAuth scopes" setting. Exact `app.yaml`
   syntax and whether admins in target workspaces permit `genie` scope is unverified.
8. **`ModelServingUserCredentials` applicability.** [verified exists] Strategy is present
   (`credentials_provider.py:~1140`) but only activates in the model-serving environment. Open:
   is Starboard ever deployed *as* a serving endpoint (vs. an App), which would make this the
   right OBO primitive instead of the header approach?

## Genie

9. **Genie authorization granularity.** [medium] Docs confirm CAN USE on a Pro/Serverless
   warehouse + Assistant enabled, and space access; the readthedocs page did **not** confirm a
   distinct "CAN RUN" space permission or a Genie-specific API scope beyond the Apps `genie`
   OBO scope. Verify the minimal grant for programmatic `w.genie.*` under a plain PAT/OAuth user
   (vs. under OBO).
10. **Genie space discovery.** [low] Whether `w.genie.list_spaces()` returns only
    user-accessible spaces under OBO vs. app-SP identity — affects the "internal customer
    workspace Genie access" UX.

## Resolver / precedence design

11. **`STARBOARD_WORKSPACE` vs `DATABRICKS_CONFIG_PROFILE` collision.** [design] If both are
    set and differ, which wins? Proposed: `STARBOARD_WORKSPACE` (Starboard's own alias) wins,
    but confirm this won't surprise users who set the SDK-native var expecting it to dominate.
12. **`sync_to_env` clobbering.** [verified risk] Today `sync_to_env` (`config.py:466-468`)
    writes `DATABRICKS_HOST/TOKEN` whenever config has them. If a user relies on a *profile*,
    stale config values could override it via env. Need explicit rule: don't write host/token
    env when a profile is the chosen target.
13. **`auth_type` forcing for diagnostics.** [verified capability] `--auth-type` maps to
    `DATABRICKS_AUTH_TYPE`, which makes the SDK skip all other strategies
    (`credentials_provider.py:1085`). Good for debugging; open question whether to expose it in
    the default help or keep it hidden/advanced.
14. **`.databrickscfg` parsing for `workspace list`.** [design] Read via `configparser`
    directly, or shell out to `databricks auth profiles`? The latter adds a CLI dependency but
    is authoritative (handles OS-keyring-stored tokens). Leaning shell-with-configparser-fallback.

## Migration / compatibility

15. **`WorkspaceProfile` schema migration.** [design] Model is `frozen`; adding optional
    `profile`/`auth_type` and making `host`/`token_env` optional is back-compatible, but existing
    `~/.starboard/config.json` files and any serialized configs must still validate. Need a
    migration/validation pass + test with a real old config file.
16. **Do we keep Starboard's registry at all?** [strategy] Once `profile` targeting lands,
    `~/.starboard/config.json` + `workspace_manager` overlaps heavily with `.databrickscfg`.
    Open product decision: thin wrapper over `.databrickscfg`, or keep a separate registry for
    per-workspace Starboard metadata (warehouse_id, catalog, cost_attribution) that
    `.databrickscfg` can't hold? (Leaning: keep registry for *metadata*, delegate *auth* to
    profiles.)

## Verification still owed
- Confirm `from databricks.sdk.core import Config` is the stable public import in 0.73.0 (used
  `databricks.sdk.config.Config` for introspection; both observed — pin the public one).
- End-to-end smoke test of each strategy against a live workspace (PAT, U2M profile, M2M) —
  this study verified APIs/signatures statically, not a live handshake.

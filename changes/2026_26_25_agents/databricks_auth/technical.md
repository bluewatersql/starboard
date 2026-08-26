# Databricks Auth — Technical Design

> Proposed architecture for a unified auth/credential-resolution component in Starboard.
> Pseudocode is grounded in **verified** databricks-sdk 0.73.0 APIs (read from `.venv`). File:line refs are current repo state (commit `b927dfaa`).

## 1. Design goals

1. **One resolver** builds every `WorkspaceClient` in the codebase (server adapter, CLI,
   notebooks, MCP multi-workspace, skills helper, state/uc stores).
2. **Delegate to the SDK's `DefaultCredentials` chain** — pass through only the inputs that
   are set; never force PAT.
3. **Workspace targeting = `profile`** (SDK-native), with a friendly `STARBOARD_WORKSPACE`
   alias.
4. **No secrets exposed to the AI** — profile *names* and env-var *names* are safe; token
   *values* stay in `~/.starboard/.env` / `.databrickscfg` / OS keyring.
5. Back-compatible: existing host+token env, `--databricks-*` flags, and MCP `token_env`
   keep working.

## 2. Verified SDK building blocks (databricks-sdk 0.73.0)

```python
# .venv/.../databricks/sdk/__init__.py:192  — WorkspaceClient accepts a prebuilt Config:
WorkspaceClient(config=Config(...))
# or discrete kwargs: host, token, profile, config_file, client_id, client_secret,
#                      auth_type, azure_*, google_*, credentials_strategy, ...

# .venv/.../databricks/sdk/config.py  — Config attributes (env var in parens):
#   host(DATABRICKS_HOST) token(DATABRICKS_TOKEN) profile(DATABRICKS_CONFIG_PROFILE)
#   config_file(DATABRICKS_CONFIG_FILE) client_id(DATABRICKS_CLIENT_ID)
#   client_secret(DATABRICKS_CLIENT_SECRET) auth_type(DATABRICKS_AUTH_TYPE)
#   warehouse_id(DATABRICKS_WAREHOUSE_ID)

# .venv/.../databricks/sdk/credentials_provider.py:1059 — default chain ORDER:
#   pat, basic, metadata_service, oauth_service_principal(=oauth-m2m), env_oidc, file_oidc,
#   github_oidc, azure_service_principal, github_oidc_azure, azure_cli, azure_devops_oidc,
#   external_browser, databricks_cli(=OAuth U2M cache), runtime_native_auth, google_*, model_serving
# credentials_provider.py:1085 — cfg.auth_type forces one strategy, skips others.

# credentials_provider.py:~1140 — OBO in model serving / Apps:
from databricks.sdk.credentials_provider import ModelServingUserCredentials
WorkspaceClient(credentials_strategy=ModelServingUserCredentials())

# After construction, the winning method is observable:
w.config.auth_type      # "pat" | "databricks-cli" | "oauth-m2m" | "runtime" | ...
w.current_user.me()     # identity check (already used at client.py verify + notebooks.py:59)
```

## 3. The unified resolver (new component)

New module: `packages/starboard/starboard/infra/auth/resolver.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config          # verified import path in 0.73.0

@dataclass(frozen=True)
class WorkspaceTarget:
    """Everything needed to point the SDK at a workspace. All optional —
    absence means 'let the SDK unified auth chain decide'."""
    host: str | None = None
    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    profile: str | None = None
    config_file: str | None = None
    auth_type: str | None = None          # force a strategy: "pat"|"databricks-cli"|"oauth-m2m"|...
    warehouse_id: str | None = None

    @classmethod
    def resolve(cls, *, profile=None, host=None, token=None, cfg=None) -> "WorkspaceTarget":
        """Apply Starboard precedence (see recommendation.md) into a target.
        Only fields that are explicitly set are populated; the rest fall to the SDK."""
        profile = (
            profile
            or os.environ.get("STARBOARD_WORKSPACE")     # friendly alias
            or os.environ.get("DATABRICKS_CONFIG_PROFILE")
        )
        return cls(
            profile=profile,
            host=host or (cfg.databricks_host if cfg else None),   # None if unset
            token=token or (cfg.databricks_token if cfg else None),
            client_id=os.environ.get("DATABRICKS_CLIENT_ID"),
            client_secret=os.environ.get("DATABRICKS_CLIENT_SECRET"),
            auth_type=os.environ.get("DATABRICKS_AUTH_TYPE"),
            warehouse_id=(cfg.databricks_warehouse_id if cfg else None),
        )

def build_config(target: WorkspaceTarget) -> Config:
    """Pass ONLY set fields to Config; unset → SDK chain resolves them.
    Key difference from today: we never inject empty host/token."""
    kwargs = {k: v for k, v in {
        "host": target.host,
        "token": target.token,
        "client_id": target.client_id,
        "client_secret": target.client_secret,
        "profile": target.profile,
        "config_file": target.config_file,
        "auth_type": target.auth_type,
        "warehouse_id": target.warehouse_id,
    }.items() if v}
    return Config(**kwargs)                 # DefaultCredentials attaches automatically

def resolve_workspace_client(target: WorkspaceTarget | None = None,
                             *, credentials_strategy=None) -> WorkspaceClient:
    target = target or WorkspaceTarget.resolve()
    cfg = build_config(target)
    if credentials_strategy is not None:                 # e.g. ModelServingUserCredentials()
        return WorkspaceClient(config=cfg, credentials_strategy=credentials_strategy)
    return WorkspaceClient(config=cfg)

def describe_auth(w: WorkspaceClient) -> dict:
    """Backs `starboard auth status` — no secrets, safe to log/show the AI."""
    return {"host": w.config.host, "auth_type": w.config.auth_type,
            "profile": w.config.profile, "user": w.current_user.me().user_name}
```

### Config precedence (implemented by `WorkspaceTarget.resolve` + SDK chain)
```
explicit --profile
  > explicit --host/--token/--client-id/...            (inline overrides)
    > STARBOARD_WORKSPACE → profile
      > DATABRICKS_CONFIG_PROFILE
        > DATABRICKS_HOST (+ TOKEN | CLIENT_ID/SECRET)  [SDK env layer]
          > .databrickscfg DEFAULT profile             [SDK file layer]
            > ambient runtime/model-serving            [SDK runtime layer]
```
Starboard's `resolve()` decides layers 1–4; the SDK's `DefaultCredentials`
(`credentials_provider.py:1059`) transparently handles 5–7.

## 4. Wiring into existing call sites

### 4a. Server adapter — `adapters/databricks/client.py:157`
```python
# BEFORE
self._sdk_client = WorkspaceClient(host=self._host, token=self._token)
# AFTER
target = WorkspaceTarget.resolve(host=self._host, token=self._token, cfg=self._cfg)
self._sdk_client = resolve_workspace_client(target)
# _verify_auth() at client.py:163 stays (current_user.me()); error text now names
#   `starboard auth login` / `--profile` instead of only host+token.
```

### 4b. Config validation — `infra/core/config.py:310-314`
```python
# BEFORE: errors if DATABRICKS_HOST or DATABRICKS_TOKEN missing (offline exempt)
# AFTER: host/token become OPTIONAL. Validate only that *some* auth is resolvable:
if not offline_mode:
    if not _auth_resolvable():   # any of: host+token, profile set, client creds,
                                 #         .databrickscfg exists, ambient runtime
        errors.append(
            "No Databricks auth resolved. Run `starboard auth login --host <url> "
            "--profile <name>`, set DATABRICKS_CONFIG_PROFILE, or provide "
            "DATABRICKS_HOST + (DATABRICKS_TOKEN | DATABRICKS_CLIENT_ID/SECRET)."
        )
# sync_to_env (config.py:466-468) unchanged for host/token; ADD passthrough (not clobber)
# of DATABRICKS_CONFIG_PROFILE / DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET.
```

### 4c. CLI — `cli/cli/main.py`
- Add args: `--profile`, `--client-id`, `--client-secret`, `--auth-type`; alias
  `--host`/`--token` to the existing `--databricks-host/--databricks-token`
  (`main.py:892-901`).
- Replace the hard exit at `main.py:1338-1345` with: attempt `resolve_workspace_client`,
  and only error (with the message above) if resolution/`current_user.me()` fails.
- New subcommands (argparse subparser, mirrors `starboard-helper` structure):
  `auth login`, `auth status`, `workspace list|use|current`.

```python
# starboard auth login  — prefer the Databricks CLI, fall back to in-process U2M
def cmd_auth_login(host, profile):
    if shutil.which("databricks"):
        subprocess.run(["databricks","auth","login","--host",host,"--profile",profile], check=True)
    else:  # SDK external-browser strategy (verified: credentials_provider.py:207)
        w = WorkspaceClient(config=Config(host=host, auth_type="external-browser"))
        w.current_user.me()   # triggers browser; token cached at ~/.databricks/token-cache.json
    print(describe_auth(WorkspaceClient(profile=profile)))
```

### 4d. Notebooks — `notebooks.py:46-62`
```python
# Make host/token OPTIONAL so ambient/profile auth works in-notebook.
def get_workspace(host: str | None = None, token: str | None = None,
                  *, profile: str | None = None) -> WorkspaceClient:
    client = resolve_workspace_client(
        WorkspaceTarget.resolve(host=host, token=token, profile=profile))
    user = client.current_user.me().user_name
    print(f"Authenticated to {client.config.host} as {user} "
          f"(auth={client.config.auth_type})")
    return client
# Back-compat: get_workspace(host, token) positional call still valid.
```

### 4e. MCP workspace registry — `mcp/config.py:45-66`, `mcp/workspace_registry.py`
Extend `WorkspaceProfile` (currently `host` + `token_env`, frozen) with optional fields;
resolve through the shared component:
```python
class WorkspaceProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
    host: str | None = None            # now optional (profile may carry it)
    token_env: str | None = None       # was required-ish; now optional (compat path)
    profile: str | None = None         # NEW: .databrickscfg profile name (preferred)
    auth_type: str | None = None       # NEW
    warehouse_id: str | None = None
    # ... existing default_catalog/schema/token_budget/cost_attribution ...
    @model_validator(mode="after")
    def _validate(self):
        if not (self.profile or self.host):
            raise ValueError("workspace needs either `profile` or `host`")
        return self

def profile_to_target(p: WorkspaceProfile) -> WorkspaceTarget:
    return WorkspaceTarget(
        host=p.host, profile=p.profile, auth_type=p.auth_type,
        token=os.environ.get(p.token_env) if p.token_env else None,
        warehouse_id=p.warehouse_id,
    )
# DefaultWorkspaceRegistry.resolve(ws_id) -> profile_to_target -> resolve_workspace_client
# registry.validate() (workspace_registry.py:77-98): warn only for token_env-based entries
#   whose env is unset; profile/ambient entries are always considered valid.
```
MCP config precedence (`mcp/config.py:122-190`) is unchanged; only `WorkspaceProfile`
gains fields, and the DATABRICKS_HOST+TOKEN fallback (`config.py:169-182`) still applies.

### 4f. `workspace_manager` — `mcp/workspace_manager.py:72-116`
`add_workspace` gains a profile mode: when the caller passes a `.databrickscfg` profile
name, store `{"profile": name, "host": host}` in `~/.starboard/config.json` and write
**nothing** to `~/.starboard/.env` (no secret at rest in Starboard's files). PAT mode
(token → `token_env` + `.env`) stays for external customers who only have a PAT.

### 4g. Apps OBO (deferred, P5) — new server path
```python
# FastAPI dependency — per request, honor the end-user's UC/Genie grants.
def user_workspace(request: Request) -> WorkspaceClient:
    fwd = request.headers.get("x-forwarded-access-token")   # verified header name
    if fwd:
        return WorkspaceClient(config=Config(host=APP_HOST, token=fwd))
    # fallback: app service principal (DATABRICKS_CLIENT_ID/SECRET injected by Apps)
    return resolve_workspace_client()
# app.yaml must declare scopes: sql, genie, model-serving (per Apps auth docs).
# Requires threading per-request identity through the adapter layer, which today assumes a
# singleton AsyncDatabricksClient (client.py) — the main cost of this phase.
```

## 5. Genie specifics

- `w.genie` is present (`__init__.py:613`); methods incl. `start_conversation`,
  `create_message`, `execute_message_query`, `get_message_query_result`.
- **No special SDK auth** beyond a valid `WorkspaceClient` — Genie rides the same resolved
  credentials. Requirements are *authorization*, not *authentication*:
  - user needs **CAN USE** on a Pro/Serverless SQL warehouse + Databricks Assistant enabled
    (docs), and access to the Genie space;
  - under **Apps OBO**, the app must declare the **`genie`** OAuth scope (Apps auth docs) so
    the forwarded user token can call Genie.
- Implication: internal-customer Genie access "just works" once O1 lands and the caller's
  profile/OBO identity has the space grant — no Genie-specific auth code.

## 6. Skills helper & state stores
`helpers/*.py` already call `WorkspaceClient()` (full chain) — leave as-is, OR route through
`resolve_workspace_client()` so `STARBOARD_WORKSPACE`/`--profile` also steer the helper. Same
for `state/databricks/*.py:117,111` and `infra/storage/uc_adapter.py:96`. Low-priority
consistency cleanup, not required for correctness.

## 7. Test surface
- Unit: `WorkspaceTarget.resolve` precedence table; `build_config` drops empty fields;
  `describe_auth` redaction.
- Integration (mock `Config`): env-only, profile-only, host+token, client_id/secret,
  ambient (no inputs) all yield a client without raising.
- Regression: existing `--databricks-host/--databricks-token` and `token_env` MCP entries
  still resolve (back-compat).
- `notebooks.get_workspace()` with no args resolves under a faked runtime env.

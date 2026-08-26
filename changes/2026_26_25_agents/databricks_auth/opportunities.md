# Databricks Auth — Opportunities

> Envisioning study, topic: **Simplify databricks-sdk-py authentication for Starboard.**
> Evidence base: grounding brief + code read (commit `b927dfaa`, starboard 0.1.1) + **databricks-sdk 0.73.0 verified locally** + current docs (Aug 2026).
> Reason from first principles; every claim is cited. Confidence marked where unverified.

## TL;DR of the core finding

Starboard **fights the SDK**. Everywhere except the skills helper it constructs
`WorkspaceClient(host=..., token=...)` — a PAT-only path — and even *requires* both
values or it exits. Meanwhile databricks-sdk 0.73.0 already ships a full **unified
authentication** chain (PAT, OAuth U2M, OAuth M2M, Azure, Google, OIDC, notebook-native,
model-serving OBO) selected automatically from args → env → `.databrickscfg` profile.
The simplest possible auth is therefore mostly **subtraction**: stop forcing host+token,
delegate to the SDK's credential chain, and make "target a workspace" a thin wrapper over
the SDK `profile` concept.

### Verified SDK facts (databricks-sdk 0.73.0, read from `.venv`)

| Fact | Evidence |
|------|----------|
| `WorkspaceClient(*, host, account_id, username, password, client_id, client_secret, token, profile, config_file, azure_*, auth_type, google_*, credentials_strategy, config, ...)` | `.venv/.../databricks/sdk/__init__.py:192` |
| Config attrs + env vars: `host`(`DATABRICKS_HOST`), `token`(`DATABRICKS_TOKEN`), `profile`(`DATABRICKS_CONFIG_PROFILE`), `config_file`(`DATABRICKS_CONFIG_FILE`), `client_id`(`DATABRICKS_CLIENT_ID`), `client_secret`(`DATABRICKS_CLIENT_SECRET`), `auth_type`(`DATABRICKS_AUTH_TYPE`), `warehouse_id`(`DATABRICKS_WAREHOUSE_ID`) | `.venv/.../databricks/sdk/config.py` |
| Registered credential strategies: `pat`, `basic`, `oauth-m2m`, `external-browser`, `databricks-cli`, `metadata-service`, `env-oidc`, `file-oidc`, `github-oidc`, `azure-cli`, `azure-client-secret`, `model-serving`, `runtime` | `.venv/.../databricks/sdk/credentials_provider.py:127-1045` |
| Default chain order: `pat → basic → metadata_service → oauth_service_principal → env_oidc → file_oidc → github_oidc → azure_service_principal → github_oidc_azure → azure_cli → azure_devops_oidc → external_browser → databricks_cli → runtime_native_auth → google_* → model_serving` | `credentials_provider.py:1059` |
| `auth_type=` forces one method (skips the rest) | `credentials_provider.py:1085` |
| `ModelServingUserCredentials()` strategy = OBO user token in model-serving/Apps | `credentials_provider.py:~1140` |
| `w.genie` GenieAPI exists | `__init__.py:613` |

### Verified docs facts

| Fact | Source |
|------|--------|
| Default chain searches args → env vars → `.databrickscfg` (DEFAULT profile) | https://databricks-sdk-py.readthedocs.io/en/latest/authentication.html |
| OAuth U2M: `databricks auth login --host <url> [--profile <name>]`; token cached at `~/.databricks/token-cache.json`; ~1h token, **auto-refreshed**; `databricks auth token --host <url>` to inspect; SDK picks it up via `databricks-cli` auth type | https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m |
| OAuth M2M: service principal `client_id`/`client_secret`, `databricks auth token` | https://docs.databricks.com/aws/en/dev-tools/auth/oauth-m2m |
| Apps: app service principal via injected `DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET`; OBO user token via **`x-forwarded-access-token`** header; scopes incl. `sql`, `files`, `genie`, `model-serving` | https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth |
| Genie API needs: user **CAN USE** on a Pro/Serverless SQL warehouse + Assistant enabled; for Apps OBO the `genie` scope | https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth ; readthedocs genie API |
| **Internal (FE) workspaces** e.g. `e2-demo-field-eng`: OAuth U2M + **Okta SSO**, **VPN required**, profile with `auth_type = databricks-cli`; PATs legacy-but-enabled (90-day max) for automation. *Confidence: high (Glean-sourced, internal wiki + FE policy).* | Glean: FE Workspaces wiki `databricks.atlassian.net/wiki/spaces/FE/pages/1657504546`; FE Workspace Use Policy |

### Current Starboard state (what we'd change)

| Location | Current behavior | Evidence |
|----------|------------------|----------|
| Server client | `WorkspaceClient(host=self._host, token=self._token)` — **PAT only** | `adapters/databricks/client.py:157` |
| Config | `databricks_host`/`databricks_token`; `sync_to_env` writes `DATABRICKS_HOST`/`DATABRICKS_TOKEN`; validate requires both | `infra/core/config.py:40-42,312-314,466-468` |
| CLI | only `--databricks-host` / `--databricks-token`; **exits** if either missing | `cli/cli/main.py:892-901,1338-1345` |
| Skills helper | bare `WorkspaceClient()` — **already uses full chain** ✅ | `starboard-skills/.../helpers/uc.py:34` |
| MCP profile | `WorkspaceProfile{host, token_env}` — **PAT only**; validator warns if token env unset | `mcp/config.py:45-66`; `mcp/workspace_registry.py:88` |
| MCP config precedence | `--config` → `STARBOARD_MCP_CONFIG` → `~/.starboard/config.json` → `DATABRICKS_HOST`+`TOKEN` | `mcp/config.py:122-190` |
| workspace_manager | writes `~/.starboard/config.json` + `~/.starboard/.env` (PAT values) | `mcp/workspace_manager.py:72-116` |
| notebooks | `get_workspace(host, token)` → `WorkspaceClient(host, token)` | `notebooks.py:46-62` |
| state/uc stores | bare `WorkspaceClient()` (full chain) ✅ but inconsistent with above | `adapters/state/databricks/*.py:117,111`; `infra/storage/uc_adapter.py:96` |
| Server auth provider | Apps reverse-proxy identity; `validate_session` no-op | `infra/auth/providers/databricks.py:141-166` |

**Inconsistency worth flagging:** the codebase uses *two* incompatible auth idioms — forced host+token (client/CLI/notebooks/MCP) vs. bare-chain (`WorkspaceClient()`) in helper/state/uc stores. Unifying them is itself a simplification.

---

## Opportunity catalog

Each approach below is scored for **complexity** (conceptual load on the user) and
**LOE** (engineering effort: S ≤ 0.5d, M ≈ 1-2d, L ≈ 3-5d, XL > 1wk).

### O1 — Delegate to SDK unified auth chain (make host/token *optional*)

Replace `WorkspaceClient(host=, token=)` with a call that passes **only what is set**,
letting the SDK's `DefaultCredentials` chain resolve PAT / OAuth / profile / ambient.
Concretely: build a `databricks.sdk.core.Config` from optional inputs and pass `config=`.

| | |
|---|---|
| **Strengths** | One code path covers *all* auth methods (PAT, U2M, M2M, notebook, Apps). Deletes the forced-credential validation. Immediately unblocks OAuth + profiles with near-zero new surface. Matches what helper/state stores already do. |
| **Weaknesses** | Behavior becomes "magic" (chain order matters); harder to give a crisp error when nothing resolves. Must preserve today's explicit-override ergonomics. |
| **Trade-offs** | Less explicit, far less code. Error messages must be improved to compensate. |
| **Considerations** | Keep `host`/`token` as *optional* overrides; only pass them to Config when present. Surface `w.config.auth_type` in logs so users know which method won. |
| **Complexity** | **Low** (mostly subtraction) |
| **LOE** | **S–M** (touch `client.py`, config validation, notebooks) |

### O2 — First-class `profile` targeting (SDK-native workspace switching)

Adopt the SDK `profile` concept as Starboard's primary "target a workspace" mechanism:
`--profile NAME` / `STARBOARD_WORKSPACE` / `DATABRICKS_CONFIG_PROFILE`, resolved into
`WorkspaceClient(profile=NAME)`. A profile in `~/.databrickscfg` already carries host +
whatever auth (PAT or `databricks-cli` OAuth) the user set up via `databricks auth login`.

| | |
|---|---|
| **Strengths** | "Switch workspace" becomes one flag. Reuses the artifact `databricks auth login` already produces — zero secret handling by Starboard. Works identically for internal FE workspaces (Okta OAuth profiles) and external customer workspaces (PAT or OAuth profiles). |
| **Weaknesses** | Requires the user to have run the Databricks CLI once. Starboard's *own* `~/.starboard/config.json` registry (workspace_manager) becomes partly redundant. |
| **Trade-offs** | Leans on an external file; but that file is the ecosystem standard. |
| **Considerations** | Provide `starboard workspace list` that reads `.databrickscfg` profiles (parse via `configparser`, or shell `databricks auth profiles`). Decide whether Starboard's registry *wraps* or *replaces* `.databrickscfg`. |
| **Complexity** | **Low** |
| **LOE** | **M** |

### O3 — `starboard auth login` wrapper over the Databricks CLI (OAuth U2M)

A thin command that shells to `databricks auth login --host <url> --profile <name>` (or
drives the SDK `external-browser` strategy directly), so a human at a terminal/notebook
gets browser SSO with auto-refreshing tokens and no PAT to paste.

| | |
|---|---|
| **Strengths** | Best interactive UX; no long-lived secret on disk in Starboard's files; tokens auto-refresh (~1h). Same command works for internal (Okta) and external customer SSO. Directly satisfies the "interactive auth" requirement. |
| **Weaknesses** | Depends on the Databricks CLI being installed (or on driving `external-browser` in-process). Browser flow is awkward on headless/remote hosts (mitigation: PAT or M2M there). |
| **Trade-offs** | Small dependency vs. large UX win. |
| **Considerations** | If CLI absent, the SDK `external-browser` auth_type can do U2M in-process (verified strategy `external-browser`, `credentials_provider.py:207`). Cache lives at `~/.databricks/token-cache.json`. |
| **Complexity** | **Low–Med** |
| **LOE** | **M** |

### O4 — In-workspace / ambient auth (notebooks, Apps, jobs) — zero-config

Inside Databricks (notebook, job, Model Serving, App) the SDK's chain
(`runtime_native_auth`, `model_serving_auth`) makes `WorkspaceClient()` "just work" with
the ambient identity. Starboard's forced host+token *defeats* this today (notebooks call
`get_workspace(host, token)`).

| | |
|---|---|
| **Strengths** | Zero credentials to manage inside the platform. Notebook users drop two required args. Aligns with the server auth provider's Apps assumption. |
| **Weaknesses** | Only applies inside Databricks; must detect and not force host/token there. `notebooks.get_workspace` signature change (keep back-compat overload). |
| **Trade-offs** | Slightly more branching to detect ambient context (or just: don't pass host/token → chain handles it). |
| **Considerations** | Make `get_workspace(host=None, token=None)` → fall through to `WorkspaceClient()` when both omitted. |
| **Complexity** | **Low** |
| **LOE** | **S** |

### O5 — OAuth M2M service principal (unattended / server / CI)

For headless server deployments and automation: OAuth M2M via `client_id`/`client_secret`
(`DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET`) or a profile with those set. Already in
the SDK chain (`oauth_service_principal`).

| | |
|---|---|
| **Strengths** | Correct primitive for servers/CI (no human, no expiring PAT). Same env vars Apps inject — so App-hosted Starboard is already M2M-capable if we stop overriding. Auto-refreshing OAuth tokens. |
| **Weaknesses** | Requires SP provisioning + secret management by the operator. |
| **Trade-offs** | More setup than PAT, but the right long-term default for automation. |
| **Considerations** | If we adopt O1, this works with **no new code** — just don't clobber `DATABRICKS_CLIENT_ID/SECRET` with host+token. Today `sync_to_env` never sets these, but validation forces token, blocking M2M-only. |
| **Complexity** | **Low** (given O1) |
| **LOE** | **S** (given O1) |

### O6 — Apps On-Behalf-Of-User (OBO) auth (per-request user identity)

Server/App path: build a per-request `WorkspaceClient` from the `x-forwarded-access-token`
header so queries run under the *end user's* UC permissions (row/column masks), not the
app SP. Complements the existing `DatabricksAuthProvider`.

| | |
|---|---|
| **Strengths** | Correct security model for multi-user Apps: honors per-user UC grants, Genie space access, etc. Enables safe multi-tenant Starboard. |
| **Weaknesses** | Per-request client construction (can't cache one global client); App must declare scopes (`sql`, `genie`, `model-serving`); more moving parts. |
| **Trade-offs** | Higher complexity, but unlocks the "internal customer workspace Genie access" context safely. |
| **Considerations** | Use `WorkspaceClient(host=<app host>, token=<forwarded token>)` per request, or `ModelServingUserCredentials()` in serving. Declare scopes incl. `genie` in `app.yaml`. Requires threading request context into the adapter layer — non-trivial given the singleton client. |
| **Complexity** | **High** |
| **LOE** | **L** |

### O7 — Keep PAT, but as one strategy among many (not the forced one)

PAT stays fully supported (customers without OAuth, quick demos, CI) — via
`--token`/`DATABRICKS_TOKEN` or a `.databrickscfg` PAT profile — but is **no longer
required**. This is the compatibility guarantee that makes O1 safe.

| | |
|---|---|
| **Strengths** | Backwards compatible; nothing breaks for current token users; simplest for external customers who only have a PAT. |
| **Weaknesses** | Long-lived secret; 90-day rotation in FE; encourages secret sprawl if it stays the default. |
| **Trade-offs** | Keep it, demote it. |
| **Complexity** | **Low** |
| **LOE** | **S** |

### O8 — Unify the two MCP/registry stores onto profiles + token_env fallback

Today MCP `WorkspaceProfile` is host+`token_env` only. Extend it so a workspace entry can
reference a **`.databrickscfg` profile** *or* an env-var token *or* nothing (ambient/chain),
resolved through the same O1 resolver. `workspace_manager` writes profile refs instead of
PAT values where possible.

| | |
|---|---|
| **Strengths** | One resolution model across CLI, MCP multi-workspace, skills, notebooks. Removes the "no OAuth/no refresh" multi-workspace gap called out in the grounding brief. Keeps the "don't expose secrets to the AI" property (profile name is not a secret). |
| **Weaknesses** | Schema migration for `WorkspaceProfile` (add optional `profile`, make `token_env` optional); back-compat for existing `~/.starboard/config.json`. |
| **Trade-offs** | Some migration work for a much cleaner model. |
| **Considerations** | `WorkspaceProfile` is `frozen`; add fields as optional with validators. Registry `validate()` must accept profile-backed entries (no token_env). |
| **Complexity** | **Med** |
| **LOE** | **M–L** |

### O9 — Do nothing / status quo (baseline)

| | |
|---|---|
| **Strengths** | No work. |
| **Weaknesses** | Forces PAT; blocks interactive OAuth, internal Okta SSO, ambient in-workspace auth, M2M; multi-workspace is env-var-only with no refresh (grounding brief). Fights the SDK. |
| **Complexity** | n/a |
| **LOE** | — |

---

## Approach × Context coverage matrix

Legend: ✅ works well · ⚠️ works with caveats · ❌ does not address · — n/a

| Approach | External customer | Internal DBX (e2-demo-field-eng) | Genie access | Interactive | Token (PAT) | Notebook | App |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **O1** Delegate to SDK chain | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **O2** Profile targeting | ✅ | ✅ (Okta profile) | ✅ | ✅ | ✅ (PAT profile) | ⚠️ (ambient better) | ⚠️ (SP better) |
| **O3** `starboard auth login` (U2M) | ✅ | ✅ (Okta SSO) | ✅ | ✅ | — | ⚠️ (headless) | ❌ |
| **O4** Ambient in-workspace | ⚠️ (only if running inside) | ⚠️ | ✅ | — | — | ✅ | ✅ |
| **O5** OAuth M2M (SP) | ✅ | ✅ | ⚠️ (SP needs Genie grant) | ❌ | — | ⚠️ | ✅ (app SP) |
| **O6** Apps OBO | ⚠️ | ⚠️ | ✅ (user's grants) | — | — | — | ✅ |
| **O7** PAT (demoted) | ✅ | ⚠️ (legacy, 90d) | ✅ | ⚠️ | ✅ | ✅ | ⚠️ |
| **O8** Unified registry/profiles | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **O9** Status quo | ⚠️ (PAT only) | ❌ (no OAuth/SSO) | ⚠️ | ❌ | ✅ | ⚠️ (forces token) | ⚠️ |

**Reading:** O1 (+O7 for compat) is the keystone — it single-handedly turns most ❌/⚠️ into ✅
because it hands resolution to the SDK. O2/O3 make workspace switching and interactive login
*ergonomic*. O6 is the only genuinely hard piece and only matters for multi-user App hosting.

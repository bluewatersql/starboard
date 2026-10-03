# Primitive: capability-bind — deliver to whatever tool is present

The plan asks for **logical capabilities**, never provider names. Bind each to whatever tool is
actually available in this session — the host's own **MCP** tools first, plus any Starboard
`starboard-helper` surface that provides it.

## Artifact selection vs. delivery destination

These are separate decisions:
- **Artifact selection** (made in the `present` beat): which deliverables to produce — exec-summary
  Doc, evidence pack + notebooks, customer deck, Slack message, CRM draft.
- **Delivery destination**: where each deliverable is built — the real tool first (Google Doc via
  **Google MCP Docs** (`mcp__google__docs_*`)); the customer deck is a **local Markdown outline**
  (there is no Slides deck-build path). A local Markdown working copy is **always** written first
  regardless of remote success.

**For a selected exec-summary Doc, local Markdown is never the default** — build the actual Google
Doc (Docs have no shared-template dependency); local Markdown is the fallback only when the Docs
tools are genuinely unavailable.

**For a selected customer deck**, the deliverable is the **local Markdown outline** (per
[`../templates/deck.md`](../templates/deck.md)) plus chart PNGs under `deliverables/charts/`. There
is **no Slides/Drive deck-build path**: the outline is what ships, and the operator adapts it into
their own presentation tool with their own branding.

| Logical capability | Bind to (by availability) | Fallback (tool genuinely unavailable — state visibly) |
|---|---|---|
| `publish.doc` / `publish.sheet` | **Google MCP Docs/Sheets** (`mcp__google__docs_*` / `mcp__google__sheets_*`) · Office/M365 MCP | local Markdown |
| `present.deck` | **Local Markdown outline** (per [`../templates/deck.md`](../templates/deck.md)) + chart PNGs under `deliverables/charts/`. No Slides/Drive deck-build path — the outline is the deliverable. | (none — the outline is local) |
| `message.post` | Slack MCP · Teams MCP | local Markdown / content-only |
| `ticket.open` | Salesforce MCP (draft only) | (none — skip) |

> **Byte-upload ceiling — state it up front, before you build.** The Google MCP creates native
> Docs/Sheets and folders, but it **cannot upload file bytes** (notebook `.py`, chart PNGs as Drive
> files, evidence files). Those need an authenticated gcloud **user** token (`gcloud auth
> print-access-token` succeeds) and the gcloud/curl multipart upload. When you tell the user what
> will be delivered (the `present` beat, or the first line of an unattended run's delivery), say
> which files will reach Drive and which stay local, e.g. "Docs via MCP; notebooks + PNGs local —
> no gcloud user token". Don't promise files in Drive you can't upload.

> **File & image upload.** **Chart-render precondition:** rendering chart PNGs requires the
> `starboard-skills[render]` extra (`vl-convert-python`); if it is not installed, `charts render`
> produces no output and charts cannot be embedded regardless of the upload path. Check this
> **before** attempting chart embed — if unavailable, degrade visibly: deliver the doc with
> the chart callouts in place and attach any pre-rendered charts from `deliverables/charts/` (or
> state that charts are unavailable). (The deck is a local Markdown outline — its charts are always
> local PNGs under `deliverables/charts/`, never embedded via an API.)
>
> **Docs MCP image embedding.** `docs_document_create_from_markdown` can inline local images
> given **absolute file paths** — this works without gcloud/curl. Prefer MCP-first for
> creating Docs and embedding images into them. gcloud/curl is only required for **raw binary
> uploads to Drive** (chart PNGs as Drive files, notebook `.py` files, evidence files) and for
> obtaining a hosted Drive URL for `insertInlineImage` in the structured Docs API. If gcloud/curl
> is unavailable, keep binary artifacts **local** under `deliverables/` and note the local path
> in the delivery confirmation.
>
> **Quota-project 403s.** A router probe reporting the CLI as "OK" can still produce a `403
> Forbidden` on the actual API call if a quota project is misconfigured. Prefer MCP-first for
> all Docs and Drive operations; fall back to gcloud/curl only for byte uploads. If MCP returns
> 403, tell the user the quota project may need updating (not just that auth is down) and offer
> fix-and-retry / local-only.
>
> The Google MCP handles **native-doc creation** (Docs, Sheets) — use it for that.
> `drive_file_create` is metadata-only (creates empty native files; no content parameter):
> binary uploads require gcloud/curl or the Docs MCP's markdown import path.

## Links inside a delivered Doc

The local Markdown links its siblings relatively (`[evidence pack](evidence-pack.md)`,
`[opp-wh-queue.py](notebooks/opp-wh-queue.py)`, `charts/*.png`). Those links are dead in a Google
Doc. **Before** `docs_document_create_from_markdown`, rewrite every relative link in the payload:

- to the **Drive link** of the uploaded file or Doc (`https://drive.google.com/file/d/<id>/view`,
  `https://docs.google.com/document/d/<id>/edit`) when it was delivered to the folder; or
- to **plain text** naming the file and where it is, e.g. `opp-wh-queue.py (notebook, delivered
  alongside this doc)` or `opp-wh-queue.py (local copy: deliverables/notebooks/)`, when it wasn't.

Images you embed via absolute local paths are not links and stay as they are. Leave the local
`.md` file unchanged; rewrite only the payload you send. Check the created Doc for leftover
`](` relative targets before you report it delivered.

## Explicit destination

An **explicit destination** is any path, folder name, or workspace named in the prompt or user
message — including a permission constraint ("only upload to `starboard/_prompt-tests/…`"). A Drive
folder path counts as a destination even when phrased as a constraint. If no destination appears in
the prompt, the run is local-only.

## Unattended / no-user-present path

When no interactive user is present (scheduled run, unattended agent, prompt test), Rule 3's
STOP-and-ask is replaced by **per-artifact degrade-and-record**:
- Try each bound tool.
- If a tool is absent or fails, mark that artifact `local: <reason>` in `README.md ## Delivery`
  (e.g. `byte uploads: local — gcloud not authenticated (run gcloud auth login)`), keep the
  local file, and continue to the next artifact. Name the fix in the reason when there is one.
- Never pause an unattended run waiting for a confirmation — degrade and record instead.
- A host with no Google or Slack MCP tools records all artifacts as `local: no Google/Slack MCP`
  and continues normally.

**Standard local-only `## Delivery` block** (copy it when no Google/Slack tool is present; list
every artifact that exists, and keep the reason specific):

```markdown
## Delivery

All artifacts are local only — no Google or Slack tools in this session.

- deliverables/exec-summary.md — local: no Google Docs MCP
- deliverables/evidence-pack.md — local: no Google Docs MCP
- deliverables/action-plan.md — local: no Google Docs MCP
- deliverables/slack-post.md — local: no Slack MCP (draft, not posted)
- deliverables/notebooks/*.py — local: no byte uploader
- deliverables/charts/*.png — local: no byte uploader
```

When Docs work but bytes can't be uploaded, keep the same shape: `Docs via MCP: <link>` lines for
the Docs, `local: no gcloud user token` lines for the files.

## Rules

0. **Deliver the plan — do not re-summarize it.** The delivered artifact carries the **same substance**
   as the plan you wrote: the native-remediation **code snippets** (the exact SQL / CLI / diff), the
   **evidence citations** (`query_id` + number), the confidence, and the technical-review outcome.
   "Sanitize" means **redact** PII/secrets/internal names (see
   [`scope-sanitize.md`](scope-sanitize.md)) — it does **not** mean drop the code, the evidence, or the
   review. A customer doc with no snippets and no citations is claims with no backup; that is a failed
   delivery, not a polished one. If you find yourself writing a thinner second version, stop and deliver
   the real one with redactions applied in place.
1. **Render native to the destination.** A Doc gets styled headings, **real code blocks** (not fenced
   text), real tables — use `docs_document_create_from_markdown` or the Docs API structurally, **not** a
   verbatim Markdown paste (which leaks `\~`, `\+`, `\#`, `\=` escapes and renders code as flat text).
   A deck gets one idea per slide, never a pasted Markdown table (see
   [`../templates/deck.md`](../templates/deck.md)). **Never emit `~` for "approximately"** in a Doc or
   Slack payload — `~x` / `~~x~~` become strikethrough; write "approx." or use a real rendered value.
2. **Preview + confirm before every external write.** Show the final destination-specific payload, not
   the raw plan. Email and CRM are **content-only / draft-only** unless the user explicitly confirms a
   send, and only if a write path exists.
3. **Preflight the binding before you build.** For each selected artifact, first confirm its
   primary tool is present AND authenticated before building anything. Use a cheap read call —
   `mcp__google__drive_file_list` or `mcp__google__docs_document_list` for Google MCP, a
   `channels.list` for Slack MCP.

   **Also preflight the byte uploader** if the artifact set includes files (evidence pack files,
   notebooks, chart PNGs): the Google MCP cannot upload bytes, so confirm the gcloud/curl uploader
   is authenticated (e.g. `gcloud auth print-access-token` succeeds) **before promising files in
   Drive**. If it is not, tell the user up front that those files will be **local only** under
   `deliverables/`, and offer fix-and-retry (`gcloud auth login`) / proceed local-only.
   **gcloud has an account but no token.** When `gcloud auth list` shows an active account but
   `gcloud auth print-access-token` fails (expired or revoked credentials), the fix is
   re-authentication, not install. On an unattended run, record it in `## Delivery` with the fix,
   e.g. `deliverables/notebooks/*.py — local: gcloud account <account> has no valid token (run
   gcloud auth login)`, so the operator knows the one command that unblocks byte uploads.

   If the call is absent or returns an auth/unauthenticated error:
   - **STOP** (attended runs only — for unattended runs, apply the per-artifact degrade-and-record
     path above instead) — do not begin building the artifact.
   - Tell the user **exactly what to fix and how**, naming the tool and the concrete step:
     Google MCP → the workspace connections page for that connector; gcloud/curl path →
     `gcloud auth login` or refresh the access token; Slack MCP → connect the Slack app
     in workspace connections.
   - Ask: **fix-and-retry / skip this artifact / local-Markdown fallback**.
   - Degrade **only after the user has chosen** — never silently degrade a selected Doc
     to Markdown because auth was down. (The deck is always a local Markdown outline.)

4. **Build the real artifact first; degrade visibly only when the tool is genuinely unavailable.**
   When "exec-summary doc" is selected, invoke the Google Docs MCP
   (`mcp__google__docs_document_create_from_markdown` or the Docs API structurally) immediately —
   do not default to a Markdown outline (Docs have no shared-template dependency). A capability can
   have more than one binding, and they don't share auth. For `present.deck`, the deliverable is the
   **local Markdown outline** (per [`../templates/deck.md`](../templates/deck.md)) plus chart PNGs —
   there is no Slides/Drive deck-build path, so there is nothing to preflight for the deck; the
   operator brands it downstream. For all other capabilities, if a bound tool fails, say **which** binding
   failed and **why** (auth / workspace-identity mismatch / not installed) — never a bare "tool
   failed" — then **ask**: fix-and-retry (log in) / skip / fall back to local Markdown. Never
   silently drop to the floor and never claim you delivered.
   If a binding you did not preflight fails mid-write, apply the same STOP-and-ask from Rule 3
   — never a bare "tool failed", never a silent floor.
5. **Read-only to the customer's Databricks workspace** — deliver only to the operator's own
   destinations. Run [`scope-sanitize.md`](scope-sanitize.md) on the payload first.
   **Delivery destinations are the operator's own tools (Google Docs/Slides/Sheets/Drive, Slack,
   Jira/CRM by availability) plus local files under the run directory** — never an external hosting
   surface the operator did not choose. Do **not** publish deliverables to any external or shareable
   hosting surface: it is not a Starboard delivery destination. An HTML deck, if you build one, is a
   **local working file** under `deliverables/`, not something to publish.
6. **Drive delivery contract.** When Google Drive is available, deliver all selected artifacts to a
   consistent folder path:

   ```
   My Drive/starboard/<Workspace Name>/<YYYY_MM_DD>/
   ```

   - **Find-or-create each path segment — never blind-create.** Google Drive allows
     multiple folders with the same name under the same parent, so an unconditional
     "create folder `starboard`" makes a **second** `starboard` folder on every run
     (the observed duplication bug). Resolve the path one segment at a time, top-down,
     reusing any existing folder. **Don't trust a name query.** A `name = '<segment>'` search (with
     or without `'root' in parents`) has returned **no items** for a `starboard` folder that
     existed, so a run that creates on an empty name search makes the duplicate this rule exists
     to prevent. List the parent's children and match the name yourself:
     1. **Find the root parent id.** My Drive's root id is not reliably the literal `root`. Read it
        from an item you know is at the top level: `drive_file_get` on a known `starboard` (or
        `_prompt-tests`, or any top-level) item with `fields=parents`, and use that parent id. Use
        `root` only when you have no such item; if the `root` listing then shows no `starboard`
        folder, also search by name for a **known child** (for example `_prompt-tests`, or the
        workspace folder) and read its parent before you conclude `starboard` is absent.
     2. For each segment (`starboard` → `<Workspace Name>` → `<YYYY_MM_DD>`), **list the current
        parent's child folders**:
        `drive_file_list` with
        `q = "'<parentId>' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"`
        (`fields=files(id,name,parents,createdTime)`; page through every result), then match the
        segment name **client-side** (exact string match on `name`).
     3. If exactly one child matches, **reuse its id** as the parent for the next segment. If
        **more than one** matches (a pre-existing duplicate), reuse the **oldest** (earliest
        `createdTime`) and note the duplicate in the delivery confirmation rather than creating yet
        another. `drive_file_list` may ignore `fields` and return no `createdTime`; then call
        `drive_file_get` on **each** duplicate id to read its `createdTime` and pick the earliest
        (never guess from list order).
     4. **Create only after the parent-scoped listing confirms the name is absent**
        (`drive_file_create` with `mimeType=application/vnd.google-apps.folder` and
        `parents=[<parentId>]`), then use the new id. An empty name search is not that
        confirmation.
     5. Only then upload artifacts into the final `<YYYY_MM_DD>` folder id.
     - Always resolve the folder path this way; do not rely on a hardcoded folder id. When the
       prompt hands you a pre-created destination folder id, use it as given (no lookup needed).
   - **Which name for the middle segment.** Customer name vs. workspace name is ambiguous, so
     apply find-or-create here too: first list `starboard/`'s child folders for an existing
     customer/account folder for this engagement and **reuse it**; only if none exists, create
     `<Workspace Name>`. Likewise **reuse an existing same-day `<YYYY_MM_DD>` folder — even if
     empty** — rather than creating a duplicate.
   - **Every created Doc is a two-step delivery: create, then move.**
     `docs_document_create_from_markdown` takes **no parent-folder argument**, so the Doc lands in
     My Drive root (or another default parent, which is **not** reliably the literal `root`: one
     import returned a fixed folder id). A run that skips the move silently delivers outside the
     target folder. For each Doc:
     1. **Create** it (`docs_document_create_from_markdown`) and keep the returned document id.
     2. **Read its actual parent**: `drive_file_get` on that id with `fields=parents`.
     3. **Move it**: `drive_file_update` with `add_parents=<final folder id>` and
        `remove_parents=<the parent id you just read>`. Never hard-code `remove_parents=root`.
     4. **Verify a single parent**: `drive_file_get` again; `parents` must be exactly
        `[<final folder id>]`. Two parents means the update added the folder without removing the
        old one: repeat step 3 with the remaining old parent.
     Do not report the Doc as delivered to the folder until step 4 passes.
   - **Doc titles carry the run id in prompt tests.** When the prompt supplies a `RUN_ID`, put it in
     every created Doc's title (e.g. `Starboard exec summary — <MODEL> <RUN_ID>`), so a reconciliation
     can tell this run's Docs from any other.
   - Do not drop files into the Drive root or an ad-hoc folder.
   - Upload every artifact the user confirmed in the `present` beat (deck, exec summary, evidence pack,
     notebooks) to this folder in one session. **Upload path by artifact type:** native Docs/Sheets/Slides
     are created directly by the Google MCP tools; binary files (chart PNGs, notebook `.py`, evidence
     files) require the **fe-google-tools google-drive skill (gcloud/curl) multipart upload** — the
     Google MCP cannot upload binary content. If gcloud/curl is unavailable, keep those binary
     artifacts local under `deliverables/` (charts under `deliverables/charts/`) and note the local
     path in the delivery confirmation.
   - Mirror all artifacts locally under `starboard-reports/<workspace>-<YYYY-MM-DD>/deliverables/` regardless of whether Drive
     upload succeeds — the local copy is always written first.
   - The user may override the root path; if they do, use their path verbatim and note it in the
     delivery confirmation.

6a. **The orchestrator owns the shared surfaces.** In a run split across subagents (forks,
   parallel workers), only the orchestrating agent writes `deliverables/`, `README.md` and the Drive
   folder, and only it creates or deletes Docs. A subagent writes only the files it was assigned
   (for example `discovery/domains/<domain>.md` or a draft under `analysis/`) and returns its
   result; it never creates Docs, edits the README, or touches the Drive folder, even to "fix" what
   looks like a stray file. Say this explicitly in every subagent's instructions.

7. **Notebooks are files — never workspace imports.** Notebooks and scripts generated from
   [`../templates/notebook.py`](../templates/notebook.py) are delivered as **files** (Drive folder +
   local `starboard-reports/<workspace>-<YYYY-MM-DD>/deliverables/`). Uploading `.py` files to the
   Drive folder requires the **fe-google-tools google-drive skill (gcloud/curl)** — the Google MCP
   cannot upload file content. They are **never** imported into, written to, or executed inside the
   customer's Databricks workspace. The operator downloads the file and runs it themselves if and
   when they choose to act.

8. **Logo asset for branding (exec-summary Doc only).** The source of truth is
   `assets/starboard_logo.png`, bundled at the plugin root. The exec-summary **Google Doc** may
   insert it via the Docs API (`insertInlineImage`, which needs a hosted URL) using the pre-uploaded
   public Drive copy (id `1XUFmeZSJn0h9UZoSGfpbLkgD_I0GNT1I`, the hosted copy of the bundled file).
   The asset is a **1:1 square emblem** (1254×1254) — insert it with **equal width and height**
   (e.g. ~0.5"×0.5"), never a 3:1/wordmark box (that stretches the square source). The hosted Drive
   copy must be the **same 1254×1254 square source** as the bundled file. If the hosted copy is
   unavailable, omit the image rather than substituting a placeholder. (The deck is a local Markdown
   outline — no Slides logo insert; the operator applies branding when they build the deck.)

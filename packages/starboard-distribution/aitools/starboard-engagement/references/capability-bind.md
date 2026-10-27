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
  (there is no Slides deck-build path). The Markdown working copy is **always** written first,
  regardless of remote success: on a Drive run put into the run folder with `starboard-helper
  engagement put --run-folder $RUN_FOLDER --path deliverables/<file>` (nothing is written locally),
  under `<run-dir>/deliverables/` on a local run.

**For a selected exec-summary Doc, local Markdown is never the default** — build the actual Google
Doc (Docs have no shared-template dependency). On a local run, local Markdown is the fallback only
when the Docs tools are genuinely unavailable; on a Drive run there is no local fallback (see
[No local fallback on a Drive run](#no-local-fallback-on-a-drive-run)).

**For a selected customer deck**, the deliverable is the **local Markdown outline** (per
[`../templates/deck.md`](../templates/deck.md)) plus chart PNGs under `deliverables/charts/`. There
is **no Slides/Drive deck-build path**: the outline is what ships, and the operator adapts it into
their own presentation tool with their own branding.

| Logical capability | Bind to (by availability) | Fallback (tool genuinely unavailable — state visibly) |
|---|---|---|
| `publish.doc` / `publish.sheet` | **Google MCP Docs/Sheets** (`mcp__google__docs_*` / `mcp__google__sheets_*`) · Office/M365 MCP | local run: local Markdown · Drive run: `not delivered: <reason>` |
| `present.deck` | **Local Markdown outline** (per [`../templates/deck.md`](../templates/deck.md)) + chart PNGs under `deliverables/charts/`. No Slides/Drive deck-build path — the outline is the deliverable. | (none — the outline is the deliverable) |
| `message.post` | Slack MCP · Teams MCP | local run: local Markdown / content-only · Drive run: `not delivered: <reason>` |
| `ticket.open` | Salesforce MCP (draft only) | (none — skip) |

> **Files reach the run folder through the writers, not an upload step.** On a Drive run
> (`storage_decision` `drive_required`, `drive_default` or `drive_optional`), every Starboard writer streams its file
> straight into the run folder with `--run-folder $RUN_FOLDER` (notebooks, chart PNGs, JSON, verify
> pairs, the manifest), and `engagement commit` records each one with its size and MD5. There is
> no upload command and no gcloud byte uploader. The Google MCP still creates the native Docs and
> Sheets. On a local run (`local`, `internal_only_local`) the files stay under
> `<run-dir>/deliverables/`; when you tell the user what will be delivered, say which files stay
> local, e.g. "Docs via MCP; notebooks + PNGs local". Don't promise files in Drive that no writer
> put there.

> **File & image upload.** **Chart-render precondition:** rendering chart PNGs requires the
> `starboard-skills[render]` extra (`vl-convert-python`); if it is not installed, `charts render`
> produces no output and charts cannot be embedded regardless of the upload path. Check this
> **before** attempting chart embed — if unavailable, degrade visibly: deliver the doc with
> the chart callouts in place and attach any pre-rendered charts from `deliverables/charts/` (or
> state that charts are unavailable). (The deck is a local Markdown outline — its charts are always
> local PNGs under `deliverables/charts/`, never embedded via an API.)
>
> **Docs MCP image embedding.** On a local run, `docs_document_create_from_markdown` can inline
> local images given **absolute file paths** (`<run-dir>/deliverables/charts/<name>.png`). On a
> Drive run there is no local copy: the chart PNG is already in the run folder, so link it from the
> Doc by its run-folder link (`https://drive.google.com/file/d/<id>/view`), never by a local path.
> Prefer MCP-first for creating Docs.
>
> **Quota-project 403s.** A router probe reporting the CLI as "OK" can still produce a `403
> Forbidden` on the actual API call if a quota project is misconfigured. If MCP returns 403, tell
> the user the quota project may need updating (not just that auth is down) and offer
> fix-and-retry / local-only.
>
> The Google MCP handles **native-doc creation** (Docs, Sheets) — use it for that.
> `drive_file_create` is metadata-only (creates empty native files; no content parameter): binary
> files reach a Drive run folder only through the Starboard writers (`--run-folder`).

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
- If a tool is absent or fails on a local run, mark that artifact `local: <reason>` in
  `README.md ## Delivery` (e.g. `exec summary: local — Google Docs MCP not connected`), keep the
  file, and continue to the next artifact. On a Drive run mark it `not delivered: <reason>`
  instead and leave its revision pending (see
  [No local fallback on a Drive run](#no-local-fallback-on-a-drive-run)). Name the fix in the
  reason when there is one.
- **An unattended run can't approve.** On a Drive run, register every report (`engagement report`),
  deliver or record the `internal` ones, and leave each `customer` report pending
  (`can_approve` is false): the run ends `publication_pending`, and the operator approves and
  delivers it later.
- Never pause an unattended run waiting for a confirmation — degrade and record instead.
- On a local run, a host with no Google or Slack MCP tools records all artifacts as
  `local: no Google/Slack MCP` and continues normally.

**Standard local-run `## Delivery` block** (copy it on a local run when no Google/Slack tool is
present; list every artifact that exists, and keep the reason specific):

```markdown
## Delivery

All artifacts are local only — no Google or Slack tools in this session.

- deliverables/exec-summary.md — local: no Google Docs MCP
- deliverables/evidence-pack.md — local: no Google Docs MCP
- deliverables/action-plan.md — local: no Google Docs MCP
- deliverables/slack-post.md — local: no Slack MCP (draft, not posted)
- deliverables/notebooks/*.py — local: public run, no Drive run folder
- deliverables/charts/*.png — local: public run, no Drive run folder
```

When Docs work on a local run, keep the same shape: `Docs via MCP: <link>` lines for the Docs,
`local: <reason>` lines for the files. On a Drive run every file is already in the run folder:
list its run-folder link instead.

## No local fallback on a Drive run

On a Drive run (`storage_decision` `drive_required`, `drive_default`, or `drive_optional` — a
public install where the operator chose `--storage drive`) nothing is ever written to a local folder in place of a delivery. When a
destination tool is missing, fails auth, or the operator skips an artifact:

- write `not delivered: <reason>` for that artifact in README `## Delivery` (e.g.
  `- exec summary — not delivered: Google Docs MCP not connected`);
- leave its revision as it is (`ready`, `approved` or `pending_delivery`); never mark it
  delivered and never record a receipt for it;
- quote the run's publication state, `data.states.publication` of `starboard-helper engagement
  status` (`pending` until every revision that needs delivery has a verified receipt, `complete`
  after, `skipped` when none is due). The manifest is a versioned record, not a run file.

**Audience follows the destination.** An internal destination (an internal Drive folder, an
internal channel) is `--audience internal`; a customer-facing destination is
`--audience customer`. `engagement report` returns `allowed_audiences`: offer a customer version
only when `allowed_audiences` includes `customer`, and then only as a derivative of the internal
report (Rule 6, step 1). When it does not, the customer leg is `not delivered:` with
the block reason (`internal_only_run`, `derivative_required` or
`derivative_source_not_internal`).

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

   **Drive storage was preflighted at setup.** On a Drive run, `engagement preflight` and
   `engagement route` already proved the helper can reach Google Drive; a writer that later fails
   on storage exits 7 (an `engagement` command exits 4); `run_status` and a `resume` block then say
   where to continue: fix the access and re-run that stage
   (see the scaffold's resume rule), never fall back to a local copy.

   If the call is absent or returns an auth/unauthenticated error:
   - **STOP** (attended runs only — for unattended runs, apply the per-artifact degrade-and-record
     path above instead) — do not begin building the artifact.
   - Tell the user **exactly what to fix and how**, naming the tool and the concrete step:
     Google MCP → the workspace connections page for that connector; Starboard Drive storage →
     the `error` text the helper printed (it names the sign-in step); Slack MCP → connect the Slack app
     in workspace connections.
   - Ask: **fix-and-retry / skip this artifact / local-Markdown fallback** on a local run; on a
     Drive run offer only **fix-and-retry / skip this artifact** (`not delivered: <reason>`).
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
   failed" — then **ask**: fix-and-retry (log in) / skip / (local run only) fall back to local
   Markdown; a skip on a Drive run is `not delivered: <reason>`. Never
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
6. **Drive delivery contract.** A Drive run already has its folder: `engagement route` resolved it
   before gather and returned `run_folder_id`. Every artifact lives there, nowhere else:

   ```
   My Drive/starboard/<ACCOUNT>/<TASK>/<TASK NAME>/<RUN ID>/
   <ticket root>/<ACCOUNT>/AR-NNNNNNNNN: <TITLE>/starboard/<TASK>/<TASK NAME>/<RUN ID>/   # internal overlay, validated ticket
   ```

   - **The writers already put the files there.** Each Starboard writer took `--run-folder
     $RUN_FOLDER` and streamed its output to its relpath; `engagement commit --stage <stage>`
     recorded them. Files you author yourself (README, `analysis/backlog.json`,
     `analysis/analysis.md`, `action-plan.md`, chart rows, focused reports, the delta narrative,
     the deliverable Markdown) go in with `starboard-helper engagement put --run-folder
     $RUN_FOLDER --path <relpath>`, the bytes on stdin (`<<'EOF'`), each before the commit of its
     stage, so that commit records them; put `analysis/backlog.json` before `notebook render` and
     `run check` read it. Never create a run file with the host's own Drive tool: a file the
     helper did not write is not in the manifest. Google Docs and Slides deliverables are the
     exception: they are built with the host's Docs/Slides tools and published through report →
     approve → deliver | receipt. Nothing is written locally, and an input outside the run is passed
     as `drive:<object_id>`. Repeat any `fallback_warning` / `ticket_warning` from the route in
     `## Delivery`.
   - **Publish in this order: report → approve → deliver | receipt.** Run it after
     `starboard-helper run check --run-folder $RUN_FOLDER --out analysis/run-check.json` and
     `starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check`, so every report
     points at final files:
     1. `starboard-helper engagement report --run-folder $RUN_FOLDER --report-id <report-id>
        --audience <internal|customer> --path deliverables/<file>` registers a revision. A
        `customer` report citing internal-only evidence comes back `blocked_audience`: rewrite it
        from customer-shareable evidence and register it as a derivative of the internal report:
        `starboard-helper engagement report --run-folder $RUN_FOLDER --report-id <customer-report-id> --audience customer --path deliverables/<file> --derived-from <internal-report-id>@<n> --cite-evidence <evidence_id>`
        (or `--cite-observation <observation_id>`; both repeat). The output carries `allowed_audiences` and `derived_from_revision`.
        It refuses (`REPORT_REFUSED`, exit 2) a body under `raw/` or `evidence/`, a `customer`
        report with no citations, a `customer` body that is internal-sourced evidence, and a
        `--derived-from` that names the report itself or a revision that does not exist, and
        (`UNCOMMITTED_ARTIFACT`) a body not yet committed.
     2. `starboard-helper engagement approve --run-folder $RUN_FOLDER --report-id <report-id>
        --revision <n>` records the operator's approval of that exact revision (customer audience).
        Ask first and show the revision. An unattended run can't approve (`can_approve` is false):
        leave the report pending. An `internal` report needs no approval.
     3. Either `starboard-helper engagement deliver --run-folder $RUN_FOLDER --report-id
        <report-id> --revision <n> --destination-folder-id <folder_id>` (copies it to an
        internal-only Drive destination and reads it back; any other folder is
        `DELIVERY_REFUSED`), or publish it yourself through a host tool and record it
        with `starboard-helper engagement receipt --run-folder $RUN_FOLDER --report-id <report-id>
        --revision <n> --external-object-id <object_id> --channel <google_doc|slides|slack>
        --destination-id <folder_or_channel_id>` (`--destination-id` is required unless a
        verified `deliver` of that revision is recorded).
   - **Only a verified receipt completes the run.** A Doc or Slides receipt is verified only when
     the object sits directly in the destination, outside the run folder and staging, is not a
     run artifact, matches the revision's md5 when Drive reports one, and was created after the
     approval; otherwise `receipt` returns `warnings`. **A Slack receipt never completes** a customer delivery (it is recorded
     unverified): pair it with a Drive, Doc or Slides receipt. Until every report that needs
     delivery has a verified receipt, the run is `publication_pending`; say so in the delivery
     confirmation instead of reporting it delivered.
   - **Docs: create, then move into the delivery destination, then record the receipt.**
     `docs_document_create_from_markdown` takes **no parent-folder argument**, so the Doc lands in
     My Drive root (or another default parent, which is **not** reliably the literal `root`: one
     import returned a fixed folder id). A run that skips the move silently delivers to an
     unrecorded place. The destination is a folder outside the run folder and staging (a Doc
     inside the run folder doesn't verify). For each Doc:
     1. **Create** it (`docs_document_create_from_markdown`) and keep the returned document id.
     2. **Read its actual parent**: `drive_file_get` on that id with `fields=parents`.
     3. **Move it**: `drive_file_update` with `add_parents=<destination_folder_id>` and
        `remove_parents=<the parent id you just read>`. Never hard-code `remove_parents=root`.
     4. **Verify a single parent**: `drive_file_get` again; `parents` must be exactly
        `[<destination_folder_id>]`. Two parents means the update added the folder without
        removing the old one: repeat step 3 with the remaining old parent.
     5. **Record it**: `engagement receipt … --external-object-id <document_id> --channel google_doc
        --destination-id <destination_folder_id>`.
     Do not report the Doc as delivered until steps 4 and 5 pass.
   - **Never create the route folders by hand** on a Drive run, and never write a test file to
     check access: `engagement route` finds or creates each segment by ID, refuses duplicate
     same-name folders (reconcile them in Drive, then retry), and reads folder capabilities instead
     of probing.
   - **A sharing change stops the run.** Writers and `engagement commit` re-check the run folder's
     sharing against the run descriptor. If it changed since route, they stop with
     `blocked_access`: restore the folder's previous sharing and re-run the stage, or start a new
     run with preflight.
   - **Doc titles carry the run id in prompt tests.** When the prompt supplies a `RUN_ID`, put it in
     every created Doc's title (e.g. `Starboard exec summary — <MODEL> <RUN_ID>`), so a reconciliation
     can tell this run's Docs from any other.
   - Do not drop files into the Drive root or an ad-hoc folder.
   - **A pre-created destination folder** handed to you by the prompt is either the run's route
     override (`engagement route --override-folder-id <folder_id>`, the run folder is created
     inside it) or a delivery destination (`engagement deliver --destination-folder-id
     <folder_id>`). Note the override in the delivery confirmation.
   - **Public install, local run.** Without the internal overlay the default stays local
     (`local`; `drive_optional` is the public Drive choice and a Drive run): artifacts stay
     under `<run-dir>/deliverables/`, there is no
     report chain, and README `## Delivery` records each artifact's outcome (a Doc URL, or
     `local: <reason>`). With no Google MCP either, record `local: no Google/Slack MCP`.

6a. **The orchestrator owns the shared surfaces.** In a run split across subagents (forks,
   parallel workers), only the orchestrating agent writes `deliverables/`, `README.md` and the Drive
   folder, and only it creates or deletes Docs. A subagent writes only the files it was assigned
   (for example `discovery/domains/<domain>.md` or a draft under `analysis/`) and returns its
   result; it never creates Docs, edits the README, or touches the Drive folder, even to "fix" what
   looks like a stray file. Say this explicitly in every subagent's instructions.

7. **Notebooks are files — never workspace imports.** Notebooks and scripts generated from
   [`../templates/notebook.py`](../templates/notebook.py) are delivered as **files**: `notebook
   render --run-folder $RUN_FOLDER` streams them into the run folder's `deliverables/notebooks/` on
   a Drive run; on a local run they stay under `<run-dir>/deliverables/notebooks/`. They are
   **never** imported into, written to, or executed inside the
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
9. **Carry the health read unchanged.** When the run has `analysis/health.json`, every delivered
   report keeps its `## Unknowns` section (one `- <family>: unknown` line per unknown family) and,
   on an `insufficient_evidence` verdict, the line `Insufficient evidence`. Redaction never drops
   them, and a channel that can't hold the full report (a Slack post) links to it instead of
   summarizing unknowns away.

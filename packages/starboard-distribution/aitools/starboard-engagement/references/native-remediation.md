# Primitive: native-remediation

For each action, produce the **concrete, native remediation artifact as a preview the operator
applies** — never a vague "review your config". Match the artifact to the fix:

- **CLI / API** — the exact command for settings that have no SQL statement, e.g. a warehouse
  auto-stop: `databricks warehouses edit <warehouse-id> --auto-stop-mins 10` (or the SQL Warehouses
  API, `POST /api/2.0/sql/warehouses/{id}/edit` with `{"auto_stop_mins": 10}`). There is no
  `ALTER WAREHOUSE` statement — do not invent one.
- **SQL** — the exact statement where SQL is the real mechanism, e.g.
  `OPTIMIZE main.sales.orders ZORDER BY (customer_id);`
- **Bundle / DAB diff** — the `databricks.yml` fragment to change (autoscale bounds, `serverless: true`),
  as a preview diff.
- **Query reference / rewrite** — the specific `query_id` + the rewritten SQL (project columns instead
  of `SELECT *`; add the partition/clustering predicate).
- **json_patch / terraform** — where config is declarative (e.g. a cluster-policy fragment).

Rules:

- **Syntax-valid** and **names the exact target resource** — never a `<placeholder>` in a customer-facing
  doc (that fails the technical-review artifact-validity check).
- **Preview-only.** The operator applies it. Starboard is **read-only to the customer workspace** and
  ships **no custom apply/rollback harness**.
- If you can't produce a safe concrete artifact, say what's needed to produce one — don't hand-wave.
- **Notebooks.** Put the artifact in the backlog item's optional `lever_command`
  (`{"kind": "cli" | "sql" | "json" | "bundle_yaml", "text": "…"}`); `notebook render` emits `text`
  verbatim in the remediation cell, so the notebook carries the exact command, not just the lever
  prose. A **bundle-deployed** job (vt-job-settings-history `deployment_kind` = `BUNDLE`) always
  gets the bundle YAML change plus a redeploy (render translates a `jobs update` / `json` command),
  because a `jobs update` is overwritten by the next deploy. A warehouse resize sets the
  **proposed** value in Apply and restores the **current** one in Rollback.

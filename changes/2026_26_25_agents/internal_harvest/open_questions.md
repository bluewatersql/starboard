# Open Questions — Internal-Tool IP Harvest

> Unresolved technical + governance/IP-shipping questions from the harvest study.
> **[U]** uncertain · **[I]** inferred, needs confirmation · **[C]** confirmed but with a decision to make.

## Governance / IP-shipping (must resolve before shipping)

1. **[U] Which internal thresholds are safe to ship?** Internal dashboards encode specific numeric bands
   (utilization <30% / 30–80% / >80%, auto-stop waste windows, SAFEr config-exposure checks). Are these
   defensible public heuristics, or non-public product knowledge? Default position: ship *generic, rationale-
   documented* thresholds; get product/legal sign-off on any borrowed from internal tools.

2. **[U] Prompt-text provenance.** How much reauthoring is required for harvested prompts (triage question,
   review `additional_instructions`) to be shippable? We plan to paraphrase, not copy — is paraphrase
   sufficient, or is a clean-room reauthoring policy needed?

3. **[C→decide] Leakage guard in CI.** We recommend grepping shipped artifacts for internal tokens
   (`eng_`, `centralized_system_tables`, `fin_live_gold`, `logfood`, `adb-2548836972759138`, internal `go/`
   links, `eng-*-team` keys). Should this be a **blocking CI check** on the Starboard repo? Recommend yes.

4. **[U] Finance-grade $ labeling.** Public `system.billing` = list-price × usage, not contract net rates.
   Confirmed we must label all $ as "list-price estimate". Is even list-price estimation commercially
   acceptable to surface to customers, or should Starboard show DBUs and let the customer apply their rate?

5. **[I] hmr_stack_hash / cross-account corpus.** Confirmed internal-only (relies on private runtime stack
   normalization + multi-tenant corpus). The public analog (log4j-stack fingerprinting from delivered logs)
   is built fresh — but does even the *fingerprinting approach* carry any internal-only IP concern?

## Data-availability / fidelity (validate against real customer workspaces)

6. **[I] Log delivery prevalence.** The log-triage harvest (#2) and trace-RCA log evidence (#1) assume the
   customer configured **cluster log delivery** to DBFS/Volumes. How common is this in practice? If rare,
   these capabilities degrade or need a "turn on log delivery first" onboarding step.

7. **[I] Query-profile availability.** dbr-doctor's query-plan/operator-tree richness — how much is
   reproducible from the public query-profile API + `system.query.history` vs the internal
   `main.eng_qpl` / `main.eng_dp_debug_tools` semantic views? Needs a side-by-side on a real query.

8. **[U] `system.compute.node_timeline` granularity.** Is public node-timeline granular enough to substitute
   for even coarse Cluster-360 CPU/mem framings, given the JVM/GC/Hydra detail is unavailable? Determines
   whether a public "cluster health" capability is worth building at all.

9. **[I] system-table schema drift.** Column names harvested from internal mirrors
   (`compute_warehouses.event_type`, `query_history.read_io_cache_percent`, etc.) — confirm each exists with
   the same name/semantics in the *public* `system.*` schema and pin to a schema version.

## Workload-Review engine design

10. **[U] RuleRegistry: generalize `PatternRegistry` or sibling?** Schemas overlap heavily
    (`severity/rationale/evidence`). Recommend generalizing the existing loader to two domains
    (`diagnostic patterns`, `workload rules`); confirm no coupling issues.

11. **[U] Verify-pass (validator council) cost model.** One+ extra model call per candidate finding. Batch
    per rule set? Only validate `high/critical`? What false-positive-rate target justifies the cost?

12. **[I] Adoption metric without GitHub.** `/review`'s Action Rate reads GitHub PR behavior. A workload
    review has no PR — adoption = "did the finding clear on the next scheduled re-scan?". This needs
    cross-run state (recommend the Databricks-native state adapter, per Round-2 Ask C). Confirm the re-scan
    signal is a reliable proxy for "customer acted".

13. **[U] Output modality.** For a running workload there is no diff to comment on. Should findings surface as
    a report, as **DABs/Terraform change suggestions**, as inline Databricks-workspace annotations, or all
    three? Affects how "actionable" the review feels.

14. **[U] Trigger model.** Is Workload Review on-demand (user asks), scheduled (nightly/weekly), or
    event-driven (after a job failure / cost spike)? The action-rate loop assumes recurring runs.

15. **[I] Selector grammar scope.** Isaac's filters target files (paths/diff). Workload selectors target
    entities (job/warehouse/query by tag, size, cost, failure). How rich must selectors be at launch — is
    "statement_type + min_read_gb" style enough, or do we need tag/owner/schedule filters day one?

## Cross-topic dependencies

16. **[I] Overlap with Round-1 Topic 3 (I1–I4).** That topic wired internal tools as backends; this harvests
    IP to public data. Where they coincide (e.g. a customer *is* internal), do we offer both the live-backend
    path and the harvested-IP path, or does harvested-IP supersede it? Needs a product call.

17. **[I] RAG-corpus retirement (Ask C/D).** The variable glossary / knowledge-pack harvest (#1, #6) is the
    proposed replacement for the Analytics agent's curated RAG corpus + embeddings. Confirm the reference-
    file + query-pack approach fully covers what the RAG corpus provides before deleting the vector store.

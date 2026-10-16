# The pattern — ingredients of a deployment that reached parity across its surfaces

Condensed from mr-load (Drive library → BigQuery/dbt → HubSpot, passes 1–2, 2026-09) and re-read
for CloudBQ (HubSpot deals → BigQuery → weekly report, three candidate scenarios, 2026-10). Each
ingredient is stated with the failure it prevents, because that is how to recognise when one is
missing in a new project. The second illustration shows the same ingredient when the "surfaces"
are scenarios rather than terminals.

## Execution

1. **One script is the execution surface.** mr-load: every cell and terminal line runs
   `scripts/run_pass1.sh <step>`. CloudBQ: every scenario must call the same arithmetic — the
   hot-score constants exist once per runtime and an equality check pins them to the same output for
   one `deal_id`. Failure prevented: three procedures that drift apart.
2. **Gates opened inline, per live step, after a dry run.** mr-load: `MRLOAD_APPROVE_X=1 runner …`,
   never exported. CloudBQ: `?dry_run=1` on both entities before any scheduler is enabled; the live
   write is the absence of that flag, and the Scheduler jobs are created last.
3. **Live steps checkpoint their dry counterpart first.** The dry payload is the plan the operator
   reads; the record keeps both.
4. **Checkpoints read back from a state machine.** mr-load: `pipeline_state.sh` (done / stale /
   failed / pending). CloudBQ: `hubspot.report_state.watermark` per entity, advanced only after a
   successful MERGE; the window `[watermark − overlap, run_ts)` is the state.
5. **A local ledger makes live steps idempotent — and is the one Conditional.** mr-load: SQLite on
   the clone that ran the live steps. CloudBQ: there is no clone — the MERGE on `deal_id` plus the
   `report_state` row *is* the ledger, and the Conditional becomes "same `report_state` row, same
   identity, one instance at a time (`--max-instances 1 --concurrency 1`)".
6. **Shared truth versus local state, decided per artefact.** Anything another surface must read
   lives in the warehouse (`hubspot.new_deals`, `new_deals_last_7d`); an orchestrator's private
   state (an n8n static variable, a JS runtime cache) is local by definition and must not hold
   the watermark.
7. **Strict pass boundaries.** A new scenario never rewrites what a running one wrote; it MERGEs
   into the same table under the same key or it is not the same pipeline.
8. **Enrich, never create, when reconciling with an external system.** The write-back lane PATCHes a
   score onto deals that exist; it never creates deals, and it skips rows already holding the value.

## Evidence

9. **A rehearsal harness with numbered checks is the regression net.** mr-load: 48 → 50 checks.
   CloudBQ: offline test vectors for `hot_score()` and for the window arithmetic, run before deploy.
10. **The probe closes a reconciliation.** `bq query` from the least-equipped surface, pasted
    verbatim with date and project; read column by column.
11. **Equality checks after each stage.** Payload counts after dry run; rows per entity and both
    watermarks after the first live run; identical counts after the second (idempotent) run; the
    same score for one deal across Python, JS and SQL.

## Operator experience

12. **Look and edit affordances are part of the sequence.** After every step the command that shows
    its result (`gcloud run services describe`, `gcloud logging read`, `bq query`, `python3 -m json.tool`).
13. **Branch points are documented, not tooled away.** Delivery by the function's webhook POST
    versus delivery owned by n8n; write-back by remote JS versus none. Both routes with one
    prerequisite each; no second loader.
14. **The sandbox is the only target until told otherwise.** Portal id pinned (`PORTAL_ID`),
    private service (`--no-allow-unauthenticated`), scheduler identity scoped to the service.

## Documentation

15. **Distinct documents with distinct roles**: sequence page = recipe; README = reference;
    surfaces record = history; workbook = audit; run sheet or bash block = motion. Pointers, no
    duplicated procedure.
16. **Docs-only changes touch no code.** Fixes the operator has described but not committed are
    recorded as "not implemented, awaiting consent" until a commit hash can be cited.
17. **Commits are cited.** Every "closed by" names a hash checkable with `git show`.
18. **Side branch per feature, fast-forward when the operator says merge.**

## Safety and consent

19. **Secrets never reach git.** `.env` ignored, `.env.example` carries names only, Secret Manager
    for runtime tokens.
20. **Guardrails that could impede the operator are proposed, not implemented, until consent.**
    "Not implemented, awaiting consent" is a first-class status in the record.

# Recipe — scenario C write-back: Node 22 Cloud Run job that PATCHes hot_score_v1 / hot_flag_v1 onto deals

/add writeback/package.json writeback/index.mjs writeback/Dockerfile writeback/deploy_job.sh writeback/bootstrap_property.sh
/read-only sql/hot_deals_v1.sql sql/audit_tables.sql CONVENTIONS.md

- index.mjs: read hubspot.hot_deals_v1_writeback (only rows whose value differs), POST /crm/v3/objects/deals/batch/update in
  slices of 100, honour 429/5xx with the X-HubSpot-RateLimit-Interval-Milliseconds header (bounded backoff), parse 207 partial
  results per id, log one writeback_log row per deal (OK | ERROR | DRY), exit 1 when any error so the task is retried; gate:
  WRITEBACK_APPROVE unset → DRY (no HubSpot call). Never send a NULL score. A 403 names the missing scope.
- bootstrap_property.sh: create hot_score_v1 (number) and hot_flag_v1 (booleancheckbox) once with a schema-write token (GET first).
- deploy_job.sh: SAs new-deals-writeback (jobUser + dataset dataEditor + accessor on hubspot-token-write pinned version) and
  new-deals-scheduler (run.invoker on the job); `gcloud run jobs deploy --source`; Cloud Scheduler → jobs.run at 05:30
  Europe/Zurich Monday (after the 04:00 UTC scheduled query, before A's 07:00); `execute` and `live` sub-commands; DRYRUN=1.
Verify: node --check, bash -n, DRYRUN=1 deploy prints the sequence.

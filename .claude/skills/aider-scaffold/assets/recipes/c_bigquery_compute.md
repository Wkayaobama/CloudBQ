# Recipe — scenario C compute lane: BigQuery views, transactional weekly script, audit tables, registration scripts

/add sql/deals_synced_v1.sql sql/hot_deals_v1.sql sql/new_deals_weekly.sql sql/audit_tables.sql sql/apply.sh sql/scheduled_query.sh sql/sync_transfer.sh sql/refresh_pipeline_labels.sh
/read-only scoring/hot_score_v1.sql cloud_function_new_deals/bigquery_schema.sql cloud_function_new_deals/main.py CONVENTIONS.md

Build the hybrid lane's compute half over a HubSpot → BigQuery sync (Google DTS HubSpot connector by default):
- deals_synced_v1.sql: adapter views (deals, owners) with SAFE_CAST over ${SYNC_DATASET}.${SYNC_DEALS_TABLE}; pipeline_labels table
  + views (labels are not a sync asset; refresh_pipeline_labels.sh loads GET /crm/v3/pipelines/deals with WRITE_TRUNCATE).
- hot_deals_v1.sql: scored view calling hubspot.hot_score_v1 (argument order of scoring/hot_score_v1.sql), per-region top-5 with
  window functions, and hot_deals_v1_writeback (rows whose value differs from the last OK write-back or the synced property;
  never a NULL score).
- new_deals_weekly.sql: one transaction per entity run: 14-day lookback window → name_key/duplicates (90 days, whole portal) →
  MERGE into new_deals with the same frozen columns as main.py → new_deals_history slice → new_deals_runs row → report_state
  row NEW_DEALS_<entity>_C (never A's key). Freshness guard aborts when the sync is older than 36 h and records the abort.
- audit_tables.sql: new_deals_history (partitioned, 730-day expiry) and writeback_log.
- apply.sh renders ${PROJECT} ${DATASET} ${BQ_LOCATION} ${PORTAL_ID} ${SYNC_*} and applies in dependency order; DRYRUN=1 renders only.
- scheduled_query.sh registers/updates one scheduled query per entity ("every monday 04:00" UTC, before the write-back and A);
  DISABLE_SCHEDULE=1 registers without auto-scheduling (the gate); DRYRUN=1 runs bq --dry_run on the rendered scripts.
- sync_transfer.sh creates the DTS transfer config (assets Deals + Owners, daily 02:00 UTC) if missing.
All scripts: bash -n clean, placeholders refused, create-or-update everywhere.

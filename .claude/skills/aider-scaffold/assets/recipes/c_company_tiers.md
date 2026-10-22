# Recipe — pass 2b: the company object by foreign-key resolution (one SQL body; notebook dry run → ship → scheduled refresh)

/add sql/company_tiers_body.sql sql/company_tiers_v1.sql sql/company_tiers_apply.sql sql/company_tiers_schedule.sh sql/apply.sh .env.example notebooks/company_tiers.ipynb tests/test_company_tiers.py
/read-only sql/deal_tiers_v1.sql sql/deal_tiers_apply.sql sql/deals_synced_v1.sql scoring/deal_tiers_v1.constants.json notebooks/l2_deal_tiers.ipynb sql/scheduled_query.sh CONVENTIONS.md

The operator's notebook cell altered the synced Deals table (ALTER … ADD COLUMN unified_probability / tier / … then MERGE a CSV into
it) and built vw_company_tiers_v1 / mv_company_tiers_v1 on top; the second cell computed the same thing read-only over the API
snapshot passed as @deals_payload. Keep the second cell's discipline (nothing written until the result is read), move the rule out of
the notebook into the repository, never write into a sync table (the transfer overwrites it; derived columns live in the dataset).

1. sql/company_tiers_body.sql — the rule once, as a CTE chain over a `deal_source` the including statement defines (14 documented
   columns, in order): labelled (pipeline / stage labels, region default, dealstatus_norm) → arr (${ARR_PROJECT}.${ARR_DATASET}.stg_deals:
   entity, company_ids, the 2026–2029 pipeline / weighted figures, one row per deal) → in_status (the icalps_dealstatus rule: Icalps
   needs 'in progress' after `[_-]` → space; the other pipelines '' or the same word) → three resolvers in precedence (1 the deal's
   primary company association = SPLIT(company_ids, ';')[0]; 2 the ARR clinic map rec_three_layer final customer → company; 3 an exact
   name match on companies_synced_v1) → resolved (one row per deal: company_id, company_name, resolver 1…5, entity_key with the
   'fc:' / 'deal:' fallbacks) → rollup (sales_region × entity_key × tier; the deals nested; years nested; totals). No DDL in the body.
2. sql/company_tiers_v1.sql — companies_synced_v1 (CAST(${SYNC_COMPANY_ID_COLUMN}) AS company_id, name); company_deal_input_v1 =
   deal_tiers_v1 ⋈ deals_synced_v1 (one row per deal); company_deals_v1 and company_tiers_v1 = `WITH deal_source AS (…),` + the body
   spliced at `-- @include company_tiers_body.sql` + SELECT * FROM resolved / rollup; the snapshot table company_tiers (refresh_ts,
   orchestrator + the 21 rollup columns; clustered), company_tiers_history (partitioned by DATE(refresh_ts), 730 d), company_tiers_refreshes,
   company_tiers_summary_v1. sql/apply.sh splices the include, substitutes SYNC_COMPANIES_TABLE / SYNC_COMPANY_ID_COLUMN / ARR_PROJECT /
   ARR_DATASET, and applies the file only when SYNC_COMPANIES_TABLE is set (a notice otherwise).
3. sql/company_tiers_apply.sql — the refresh as a scheduled query (@run_time): 36 h freshness guard on the sync; TEMP batch from the
   live view; row-count guard (batch < current / 2 → RAISE); ONE transaction: replace company_tiers, replace this run's history slice,
   replace this run's refreshes row (OK, counts, duration); EXCEPTION → ROLLBACK if open, a FAILED refreshes row with @@error.message,
   RAISE. sql/company_tiers_schedule.sh registers it (display_name company-tiers-refresh, SCHEDULE_UTC_COMPANY_TIERS off the hour —
   refused on :00 —, DISABLE_SCHEDULE=1 → --no_auto_scheduling, grants for new-deals-sql@ on the dataset, the sync dataset and the ARR
   dataset, prechecks that the view and the table exist; DRYRUN renders and runs bq --dry_run).
4. notebooks/company_tiers.ipynb (Vertex AI Workbench / Colab Enterprise) — §1 the snapshot through main.HubSpot, tiered as
   deal_tiers_v1 would; §2 the dry run: the same body over UNNEST(@deals_payload) (ARRAY<STRUCT> in the 14-column order), deal-level and
   company-level CSVs, resolver counts, "0 BigQuery tables written"; §3 ship = sql/company_tiers_v1.sql rendered as apply.sh renders it;
   §4 equality (dry-run rollup vs live view per sales_region × entity_key × tier); §5 register paused (DISABLE_SCHEDULE=1) + one manual
   refresh; §6 probe (refreshes, summary, snapshot CSV); §7 enable. Both write gates are flags that ship False.
5. tests/test_company_tiers.py — body is a CTE chain and both assemblies render; view input columns == documented deal_source columns
   == notebook payload fields, in order; resolver precedence, the status rule, the grain, nested deals, no DDL/DML on a sync table;
   INSERT lists == DDL columns, one transaction, both guards, the exception path; the schedule script renders in DRYRUN and refuses an
   on-the-hour schedule; apply.sh wiring; .env variables; the notebook dry-runs before it ships before it schedules, flags False, token
   handled as in pass 2, no outputs.

Behaviour change: none for pass 1–3 and lane Q of pass 2 (deal_tiers untouched); new objects only, created when SYNC_COMPANIES_TABLE is set.
Rollback: `bq rm` the six objects and the transfer config company-tiers-refresh; sql/apply.sh without SYNC_COMPANIES_TABLE skips the file.
Run `python3 tests/test_company_tiers.py`, `DRYRUN=1 sql/apply.sh` (with and without SYNC_COMPANIES_TABLE), `DRYRUN=1 sql/company_tiers_schedule.sh`.

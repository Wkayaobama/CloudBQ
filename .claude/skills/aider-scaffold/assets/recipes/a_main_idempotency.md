# Recipe — scenario A function: make dry mode a true rehearsal and the live path race-free

/add cloud_function_new_deals/main.py tests/test_main_offline.py
/read-only cloud_function_new_deals/bigquery_schema.sql CONVENTIONS.md

Fix the confirmed gaps of discovery/scenario_A.md without changing the payload contract or hot_score():
- G05 dry mode: always build the BigQuery client; read the watermark and the 90-day warehouse twins exactly like a live run;
  skip only MERGE, watermark advance, audit rows and the delivery POST. Add `dry_run` and `orchestrator` to the payload.
- G03 per-run staging: load into `new_deals_staging_<entity>_<run_ts>` and DROP it in a finally block after the MERGE.
- G06 frozen columns: the MERGE update list excludes deal_id, first_seen_run, day1_hot_score, day1_hot_flag.
- G07 recent_names: drop the unused parameter, return name_key → [deal_ids], exclude the deal itself, log failures at ERROR
  and continue; duplicate_of lists batch twins then warehouse twins.
- G04 lease (defence in depth): report_state.lock_until taken by one atomic UPDATE per entity (create the row first);
  an overlapping run answers 409 and writes nothing; the watermark UPDATE releases the lease; failure releases it too.
- G13 audit: one row per run in new_deals_runs (also on failure) and the run's rows in new_deals_history (append; a replayed
  run_ts replaces its slice) — layer L13 shared with scenario C.
- G14 logs: one JSON object per line with severity and fields.
- B-G03/B-G04 delivery: X-Delivery-Token header from DELIVERY_WEBHOOK_TOKEN; three attempts with backoff; failure recorded.
- G16: compute `others` with an id set.
Write tests/test_main_offline.py with a fake HubSpot and a recording fake BigQuery client (real SchemaField objects) proving:
row contract == schema columns, dry reads but writes nothing, per-run staging created and dropped, frozen update list, watermark
after MERGE, 409 on an overlapping run, event mode never touches the watermark. Run `python3 tests/test_main_offline.py`.

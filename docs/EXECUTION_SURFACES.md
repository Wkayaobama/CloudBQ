# Execution surfaces — how the three lanes were brought to one idempotent outcome (record)

Companion to `docs/EXECUTION_SURFACES.xlsx` (Overview, Layers L0–L17, Pipeline steps, Remediation, Equality checks), built
from `docs/execution_surfaces.yaml` with the `pass-sequence` skill. This page is the narrative: what diverges between the lanes,
how each divergence was observed, what closed it (commit), and what stays open. The recipe is `docs/PASS1_SEQUENCE.md`;
the lanes themselves are condensed in `docs/SCENARIOS.md`.

Written 2026-10-05 before any run against Google Cloud. Every observation below comes from reading the code, from the skeptic-
verified discovery reports, or from offline tests; the "verified" cells of the workbook say which. The first live probe will be
pasted into §5 verbatim.

## 1. The motions and the vocabulary

| Lane | Acquire | Runtime | Driver | State lives in |
|---|---|---|---|---|
| **A** · Cloud Run function | `git clone`; `deploy.sh deploy` (source build) | Cloud Run gen2 service, python312, 1 instance × 1 request, scale to zero | Cloud Scheduler → `GET ?entity=…` with OIDC; `deploy.sh dry/run` by hand | `hubspot.report_state`, `hubspot.new_deals`, `new_deals_runs`, `new_deals_history` |
| **B** · n8n on Cloud Run | pinned `n8nio/n8n` image; `deploy/n8n/*.sh`; workflow JSON imported by id | n8n on Cloud Run + Cloud SQL Postgres, minScale 0 | Cloud Scheduler → webhook with `X-Delivery-Token`; manual execution = rehearsal | the same BigQuery tables; n8n credentials + executions in Cloud SQL |
| **C** · Hybrid | `sql/apply.sh`, `sql/scheduled_query.sh`, `writeback/deploy_job.sh` | BigQuery scheduled queries (UTC) + Node 22 Cloud Run job | DTS sync 02:00 UTC → scheduled query Mon 04:00 UTC → Scheduler → `jobs.run` 05:30 Zurich | the same BigQuery tables (`report_state` row `…_C`), `writeback_log`; HubSpot properties `hot_score_v1`/`hot_flag_v1` |

Parity of a layer or a step is one of three words. **Parallel**: same artefact and same result on every lane whatever runtime
produces it, pinned by a test or an equality check (outcome parity — the columns are scenarios, not terminals, so "same mechanism"
would make nothing Parallel). **Conditional**: same result when a stated condition holds. **Divergent**: a different mechanism, with
a remediation that makes it equivalent.

## 2. The principle that made reconciliation possible

The lanes were not made equal by sharing an orchestrator; they were made equal by sharing the **arithmetic** (`scoring/`: one
constants file, three ports, one vector set), the **target** (`hubspot.new_deals` MERGEd on `deal_id` with the same frozen
columns), the **state semantics** (`hubspot.report_state`, advance only after a successful MERGE, each lane its own row) and the
**audit tables** (`new_deals_runs`, `new_deals_history`). Everything that could not be shared — identity, secrets, trigger
clock, the ingestion route, the write-back — was either stated as a condition or given a remediation in the Layers sheet.

What the workbook shows today (`build_surfaces_xlsx.py --verify`, the values the Overview formulas display):

```
Layers: {'Parallel': 4, 'Conditional': 4, 'Divergent': 10}  rows=18  (what the Overview formulas will show)
Pipeline steps: {'Parallel': 2, 'Conditional': 5, 'Divergent': 6}  rows=13  (what the Overview formulas will show)
```

The four **Parallel** layers — L5 scoring, L7 MERGE, L8 watermark, L13 audit — are the parallel lane: the idempotent outcome that
holds whichever orchestrator runs. Parity here is *outcome* parity (stated in the workbook's legend and `parity_meanings`): three code
paths that must produce the same tables, keys, constants and audit rows, pinned by `tests/` for Python == JS and by the equality checks
for SQL once credentials exist. The four **Conditional** layers (L3 trigger clock, L6 duplicate horizon, L11 rehearsal, L12 replay window)
name their condition; the ten **Divergent** layers name the file that makes the lanes equivalent. Remediation rows R01–R46 are the user's
risk table plus every skeptic-confirmed gap of the three discovery reports, each with the commit or the open item that answers it.

## 3. Timeline — divergence, observation, fix

| When | Divergence | Observed how | Closed by |
|---|---|---|---|
| 2026-10-05 | `deploy.sh` piped a schema with a literal `your_project`; GRANT before the dataset existed (the quoting was never the failure) | reading `deploy.sh:4,18` and `bigquery_schema.sql`; skeptic confirmed (G01, G12) | `b5c37ab` — envsubst placeholders, `CREATE SCHEMA IF NOT EXISTS`, GRANT after |
| 2026-10-05 | the Scheduler SA was never granted `roles/run.invoker` (every Monday would 403) | `deploy.sh:7–31` vs Cloud Scheduler docs; G02 confirmed | `b5c37ab` — `deploy.sh invoker` |
| 2026-10-05 | compatibility deploy path (`gcloud functions deploy --gen2`) with a `cloudfunctions.net` URL as Scheduler audience | Google docs: canonical is `gcloud run deploy --function --base-image`; G10 contested (either works, mixing breaks) | `b5c37ab` — canonical path; URL from `status.url` |
| 2026-10-05 | both entities scheduled in the same minute sharing one `WRITE_TRUNCATE` staging table; retry could overlap a slow attempt | `main.py:123–130`, `deploy.sh:29`; G03 confirmed, G04 contested (`--max-instances 1 --concurrency 1` alone makes the second job 429) | `b5c37ab` (07:00 / 07:20) + `c6a7cc9` (per-run staging, lease) |
| 2026-10-05 | `dry_run=1` skipped every BigQuery read, so the gate rehearsed a different window with no warehouse de-dup | `main.py:176–184`; G05 confirmed | `c6a7cc9` — dry mode reads, writes nothing |
| 2026-10-05 | `day1_*` overwritten on re-observation and replay | `main.py:126`; G06 confirmed | `c6a7cc9` — frozen columns (also in `new_deals_weekly.sql` and the generated MERGE) |
| 2026-10-05 | warehouse de-dup kept one id per key and hid errors at WARNING | `main.py:133–136`; G07 contested (dead parameter, real defect is the dict) | `c6a7cc9` — key → [ids], ERROR log, continue |
| 2026-10-05 | no per-run audit; plain-text logs | G13, G14 confirmed | `c6a7cc9` (`new_deals_runs`, `new_deals_history`, JSON lines) |
| 2026-10-05 | the JS scorer named in `main.py` does not exist in any repository | `discovery/scorer_repos.md` (two repos cloned, GitHub code search) | `15c926b` — `scoring/` with vectors; JS == Python at 1e-9 |
| 2026-10-05 | n8n delivery webhook unauthenticated; watermark advanced before a fire-and-forget POST; zero-row week sent nothing | `n8n_NewDeals_Delivery.json:5–10`, `main.py:196–203`; B-G03/04/05 confirmed | `c6a7cc9` (token header, 3 attempts) + `9e7e18a` (`NEW_DEALS_DELIVERY.json` hardened) |
| 2026-10-05 | n8n on Cloud Run with SQLite / `:latest` / Schedule Trigger at minScale 0 / `/healthz` | n8n docs and Google codelab; B-G01/02/13/14 confirmed | `9e7e18a` — `deploy/n8n/service.yaml` (Cloud SQL, pinned image, Scheduler → webhook, `/health`) |
| 2026-10-05 | C sharing A's `report_state` key would rewind A; the sync is never real-time; write-back blocked by read-only scopes | `discovery/scenario_C.md`; C-G2/G4/G10 confirmed | `913f63a` — `NEW_DEALS_<entity>_C`, 36 h freshness guard; **`hubspot-token-write` app — awaiting the operator** |
| 2026-10-05 | HubSQL cannot compute the score or a per-region rank; the user's matrix said "BigQuery sync cannot write to HubSpot" | HubSpot docs (C-G12, C-G1 contested: true only without Data Hub Enterprise) | `913f63a` — `hot_deals_v1` views + Node job write-back; reverse sync noted as the Enterprise alternative |
| 2026-10-14 | the committed `tree /f` renders listed an empty directory and named the root after the checkout folder, so CI's `tree_f --check` failed on every runner; the ledger check needed full history | the first PR run (`verify` job) | `8d14e0d` — walker drops empty dirs, root = project name, `fetch-depth: 0` |
| 2026-10-16 | pre-run adversarial review (3 critics, 6 confirmed): `secret_version()` returned the Secret Manager resource path, not the number (R47); service-account ID tokens without the URL audience (R48); `enable` not idempotent (R49); `run` passed JSON error bodies as payloads (R50); bare NULLs in the vector SQL (R51) | reading `deploy.sh`, gcloud's formatter, google-auth source | `574e954` — `value(name.basename())`, `--audiences`, state-checked enable/pause, `curl -sSf`, typed NULLs |
| 2026-10-21 | both lanes reconstruct their outputs per run but never persist their inputs: the search result is consumed by `shape()` and discarded, six hot-score inputs are columns of no table, lane C's batch is a TEMP table over a full-refresh sync — a past run's score, duplicates, labels and report cannot be recomputed from BigQuery (R54) | the operator's DAG proposal, answered by reading `main.py`, `new_deals_weekly.sql`, `deals_synced_v1.sql`, `sync_transfer.sh`; plan reviewed by three critics | `docs/PASS3_RAW_ROOT.md` — phase 1 (this commit): `deals_raw` / `labels_raw` keyed like `new_deals_history`, landed by both lanes before anything is computed, `data_gaps` on the runs row, `sql/backfill_raw.sh`; phases 2–3 pending |
| 2026-10-16 | the operator runbook tied `BQ_LOCATION` to the Cloud Run region, used a second `run` as the idempotency check, blamed a `dry` 403 on `invoker`, carried portal 49610528; its offline tests would have failed on import in Cloud Shell (R52, R53) | review of the draft against `deploy.sh`, mir-load `run_pass1.sh` (mrload in EU), the connected HubSpot account (hub 9201667) | `docs/RUNBOOK_CLOUD_SHELL.md` (this commit), `e88c27a` (PASS1 corrections, notebook) |

(Append-only. Never rewrite a past row; add a new one when the situation changes.)

## 4. Pass 1 on each lane, after the reconciliation

| Operation | A | B | C | Parity |
|---|---|---|---|---|
| Score a deal | `main.hot_score()` | generated Code node | `hubspot.hot_score_v1` UDF | **Parallel** (vectors: Python == JS; SQL check ready) |
| Write the rows | per-run staging → MERGE | inline-JSON MERGE | TEMP table → MERGE in a transaction | **Parallel** in outcome (same table, key, frozen columns) |
| Advance state | `report_state` after MERGE (lease) | `report_state` after MERGE node | `report_state …_C` in the same transaction | Conditional: distinct rows per lane |
| Rehearse | `deploy.sh dry` | `?dry_run=1` on the webhook / manual execution | `DISABLE_SCHEDULE=1` + one `bq mk --transfer_run`; job with `WRITEBACK_APPROVE` unset | Conditional: C's SQL rehearsal writes to real tables (use a dev dataset) |
| Probe | `deploy.sh probe` | same `bq query` | same `bq query` + `writeback_log` | **Parallel** |
| Deliver | POST to `NEW_DEALS_DELIVERY` | native tail | Breeze/BI read the views; optional POST | Divergent |
| Write back | — | optional HubSpot node | `writeback/index.mjs` | Divergent (only C and B2 can) |

## 5. The probe that closes the reconciliation ({date}, {project}, {lane})

```
(paste `deploy.sh probe` / `deploy.sh status` output verbatim after the first live run — not composed)
```

## 6. What stays open (none of it blocks pass 1 on lane A)

- **Pass 1 on `wisekeybq`** — runbook `docs/RUNBOOK_CLOUD_SHELL.md` ready (dataset `mrload`, EU); evidence section still empty.
- **First authenticated run** of everything: `bq query < tests/hot_score_vectors.sql` (UDF parity), `deploy.sh dry`, the DTS transfer.
- **`hubspot-token-write` private app** (`crm.objects.deals.write`) and a one-off `crm.schemas.deals.write` token for `bootstrap_property.sh` — **awaiting the operator**.
- **Synced table and column names** for lane C (`SYNC_DATASET`, `SYNC_DEALS_TABLE`, `SYNC_OWNERS_TABLE`) — known after the first transfer run.
- **n8n HTTP Request pagination parameters** in `NEW_DEALS_FULL.json` are best-effort: validate once in the editor on import.
- **Event mode** (HubSpot workflow → function) — code kept, not deployed; a relay through n8n is **not implemented, awaiting consent**.
- **`amount_kusd` unit** — confirm from the first dry-run payload.
- **LibreOffice recalculation** of the workbook is unavailable in the build sandbox; `--verify` prints the values the formulas show, and
  the file recalculates on open.

## 7. Keeping the parity

After each stage compare what the *Equality checks* sheet names: dry-run counts per entity across lanes, rows per entity in
`hubspot.new_deals`, both state rows, unchanged counts after a second identical run, one deal's score across the three runtimes,
and an empty `hot_deals_v1_writeback` after a write-back. Two lanes on the same constants, the same tables and the same window
produce the same numbers; any difference points at one of the 18 layers.

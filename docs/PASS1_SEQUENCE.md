# Pass 1 — the sequence, on any lane (scenario A shown)

The ordered recipe from the working branch to the first weekly report, with the place to *look* at every stage.
`cloud_function_new_deals/README.md` explains the function; `docs/SCENARIOS.md` the three lanes; `docs/EXECUTION_SURFACES.md`
records how the lanes are brought to the same result and `docs/EXECUTION_SURFACES.xlsx` audits it layer by layer.
Nothing below is specific to Cloud Shell except that `gcloud`, `bq` and `curl` are already there; from a laptop the same
commands run after `gcloud auth login` and `gcloud auth application-default login`.

Pass 1 has not run against Google Cloud yet. Every command below was rehearsed offline (`bash -n`, `DRYRUN=1`,
`python3 tests/*.py`); the **Evidence** section is empty until the operator pastes the first dry-run payloads.

The same sequence runs cell by cell from `notebooks/cloudbq_deploy_and_witness.ipynb` on a Vertex AI Workbench instance in the
project, followed by the SQL witnessed from Python (`notebooks/README.md`).

## Preconditions on the clone you run from

- `git fetch origin && git checkout claude/cloud-run-bigquery-pipeline-e94ziy && git pull`
- `.env` filled from `.env.example` (`PROJECT`, `REGION`, `DATASET`, `FN`, `SA_NAME`, `PORTAL_ID`; `deploy.sh check-env` refuses placeholders).
- The operator is Owner (or has Cloud Run Admin, Cloud Run Source Developer, Service Account Admin, Service Account User, Project IAM Admin,
  Service Usage Admin, Secret Manager Admin, BigQuery Admin, Cloud Scheduler Admin, Cloud Build Editor — `enable-apis`, `iam` and the
  `--source` deploy need more than the Cloud Run and BigQuery roles).
- The HubSpot private app has `crm.objects.deals.read`, `crm.schemas.deals.read`, `crm.objects.owners.read`; its token is in the
  shell as `HUBSPOT_TOKEN` for the `secret` step only (never in `.env`, never in git).
- Offline checks are green: `python3 tests/test_hot_score.py && python3 tests/test_main_offline.py && python3 tests/test_n8n_code.py`.

## The sequence

```bash
D=cloud_function_new_deals/deploy.sh
set -a; . .env; set +a            # deploy.sh reads .env by itself; the hand-typed look commands below need $PROJECT $DATASET $FN $REGION
DRYRUN=1 $D all                   # rehearsal: prints every gcloud/bq command, runs nothing
$D check-env                      # .env complete, no placeholders
$D enable-apis                    # run, cloudbuild, artifactregistry, secretmanager, cloudscheduler, bigquery
$D iam                            # SA new-deals-fn, bigquery.jobUser, run.builder for the Cloud Build SA
$D tables                         # CREATE SCHEMA IF NOT EXISTS; report_state (+lock_until), new_deals, new_deals_runs, view; dataEditor GRANT

# ── look ──────────────────────────────────────────────────────────────────────────────────────────
bq ls --project_id=$PROJECT $DATASET                                     # four tables, one view
bq show --schema --format=prettyjson $PROJECT:$DATASET.new_deals | python3 -m json.tool | head -40

IFS= read -rsp 'HUBSPOT_TOKEN: ' HUBSPOT_TOKEN; echo
HUBSPOT_TOKEN="$HUBSPOT_TOKEN" $D secret; unset HUBSPOT_TOKEN   # typed, not in history; creates hubspot-token or adds a version; prints the
                                  # version NUMBER (optional to pin in .env SECRET_VERSION; `deploy` uses the latest enabled one)
$D deploy                         # gcloud run deploy $FN --source … --function new_deals_report --base-image python312 …
$D invoker                        # run.invoker for the SA; two Scheduler jobs created PAUSED (SEALSQ 07:00, ICALPS 07:20 Zurich)

# ── look ──────────────────────────────────────────────────────────────────────────────────────────
gcloud run services describe $FN --region $REGION --format 'value(status.url,spec.template.spec.containers[0].image)'
gcloud scheduler jobs list --location $REGION                            # both jobs PAUSED

$D dry                            # THE GATE: ?dry_run=1 for both entities — reads watermark + warehouse twins, writes nothing;
                                  #           asserts rows_written == 0 and dry_run == true

# ── look ──────────────────────────────────────────────────────────────────────────────────────────
URL=$($D url | tail -1)           # `url` prints the check-env lines first; the service URL is the last line
curl -sSf -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL?entity=SEALSQ&dry_run=1" | python3 -m json.tool | less
$D logs                           # JSON lines: {"severity","message","entity","dry_run","rows","window"}

$D run SEALSQ                     # first LIVE window run (one entity, by hand): per-run staging → MERGE → history → watermark;
$D run ICALPS                     # an HTTP 403 (caller lacks run.invoker) or 409 (lease held) fails the step instead of printing a payload

# ── look, from the warehouse ─────────────────────────────────────────────────────────────────────
$D probe                          # rows per entity, hot and duplicate counts; last 10 new_deals_runs rows
$D status                         # watermarks, leases, Scheduler job states

$D replay SEALSQ "$FROM"          # the idempotency check: FROM = watermark_in printed by the first run; the same window again —
                                  # MERGE on deal_id leaves the `probe` counts unchanged (`run` would open the next window instead)
$D enable                         # resume the two Scheduler jobs — only after the gate passed and the probe looks right
```

Facts that affect an edit: `deploy.sh` reads `../.env` with `set -a`, so values with spaces need quotes (`SCHEDULE_SEALSQ="0 7 * * 1"`);
the schema is rendered with `envsubst` (falls back to `sed` where gettext is absent, e.g. stock macOS).

## The branch points

**Delivery after the run — route 1, the function posts to n8n (B1).** Set `DELIVERY_WEBHOOK_URL` (and `DELIVERY_WEBHOOK_TOKEN_SECRET`)
in `.env`, deploy `workflows/NEW_DEALS_DELIVERY.json` (hardened: Header Auth, zero-row email) on the n8n service from
`deploy/n8n/`, redeploy the function. The function retries the POST three times; BigQuery stays the truth if n8n is down
(`new_deals_last_7d` is the fallback source).

**Delivery after the run — route 2, no n8n.** Breeze and BI read `hubspot.new_deals_last_7d`; nothing sends email. One
prerequisite: `roles/bigquery.dataViewer` on the dataset for the readers.

**Write-back to HubSpot (only scenario C does it).** `writeback/bootstrap_property.sh` once with a `crm.schemas.deals.write` token,
`sql/apply.sh`, `writeback/deploy_job.sh` (dry executions until `deploy_job.sh live`). Prerequisite: a second private app with
`crm.objects.deals.write` stored as `hubspot-token-write`. The read-only token of scenario A cannot write.

**Why no second loader.** Scenario B2 (`workflows/NEW_DEALS_FULL.json`) and scenario C (`sql/new_deals_weekly.sql`) MERGE into the
*same* `hubspot.new_deals` on `deal_id` with the *same* frozen columns and the *same* arithmetic (`scoring/`), and keep their own
`report_state` rows (`NEW_DEALS_<entity>` for A and B2, `NEW_DEALS_<entity>_C` for C). Running two lanes in the same week is safe
on the data side; it only doubles the compute. Pick one orchestrator per entity and pause the others' schedulers.

## What each stage produces, and where to look

| Stage | Produces | Look with |
|---|---|---|
| `tables` | dataset, `report_state`, `new_deals`, `new_deals_runs`, `new_deals_last_7d` | `bq ls`, `bq show --schema` |
| `secret` | Secret Manager `hubspot-token` version | `gcloud secrets versions list hubspot-token` |
| `deploy` | Cloud Run service revision at `https://<fn>-<hash>-<region>.run.app` | `gcloud run services describe`, `gcloud run revisions list` |
| `invoker` | IAM binding, two paused Scheduler jobs | `gcloud scheduler jobs list` |
| `dry` | two payloads (`rows_written: 0`, `dry_run: true`) | the command's own summary line; `$D logs` |
| `run` | rows in `new_deals`, slice in `new_deals_history`, one `new_deals_runs` row, watermark advanced | `$D probe`, `$D status` |
| any time | position in the sequence | `$D status` (watermark present → tables + first run done; jobs ENABLED → gate passed) |

The state the function keeps is `report_state`: a missing row means "never ran"; `lock_until` in the future means "running"
(or a crash less than `LEASE_MINUTES` ago — the next run proceeds once it expires).

## Evidence — the probe of {date} ({project}, {surface})

```
(paste the two dry-run summary lines and the `probe` output verbatim here after the first run; not composed)
```

## Pitfalls

- **Dry mode writes nothing — including the audit row.** `new_deals_runs` shows live runs only; dry runs are visible in `$D logs`.
- **Generated files are never edited.** `workflows/NEW_DEALS_*.json` come from `workflows/src/build_workflow.py`; `tests/hot_score_vectors.*`
  from `tests/test_hot_score.py`; the tree from `docs/architecture.yaml`; the workbook from `docs/execution_surfaces.yaml`.
- **Event mode is not deployed in A.** The code path exists (`mode: event`), but a HubSpot workflow webhook cannot present a Google
  OIDC token to a private service; a relay belongs to scenario B if wanted.
- **`amount_kusd` holds `amount_in_home_currency` as stored.** Confirm the unit from the first dry-run payload before the README promises kUSD.
- **Both schedulers in the same minute was a bug** (shared staging + 429s); they are 20 minutes apart now and the staging table is per run.

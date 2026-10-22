# notebooks/ — the Pass-1 sequence as a Jupyter notebook (Vertex AI Workbench)

`cloudbq_deploy_and_witness.ipynb` runs the same sequence as the Cloud Shell runbook in `docs/PASS1_SEQUENCE.md`, one cell per
`deploy.sh` step, and then **witnesses** the SQL from Python: the schema, the `hot_score_v1` UDF on the golden vectors, the audit
tables and the function's dry payload, each statement with its BigQuery job id, bytes processed and slot time next to its text.
Nothing is re-implemented: every step cell calls `bash cloud_function_new_deals/deploy.sh <step>`. The `enable` step sits after
the witness section: look, then schedule.

## Run it on a Workbench instance in the same project

```bash
gcloud workbench instances create cloudbq-nb --location=europe-west6-a --machine-type=e2-standard-4 --project=YOUR_PROJECT
# optional: --service-account-email=SA@YOUR_PROJECT.iam.gserviceaccount.com  (default: the Compute Engine default service account)
```

Console → Vertex AI → Workbench → Instances → **Open JupyterLab**. In a JupyterLab **Terminal**:

```bash
git clone --branch claude/cloud-run-bigquery-pipeline-e94ziy https://github.com/Wkayaobama/CloudBQ.git ~/CloudBQ
```

Open `CloudBQ/notebooks/cloudbq_deploy_and_witness.ipynb` with the default Python 3 kernel and run the cells top to bottom. The
notebook detects that it was opened from inside the clone and works in it; `.env` is written from the `SETTINGS` cell (keys left as
placeholders do not overwrite a hand-edited `.env`) and stays gitignored.

**Identity — two credential stores.** `gcloud` and `bq`, hence every `deploy.sh` step, act as gcloud's active account; the BigQuery
and Secret Manager Python clients act as Application Default Credentials. On a Workbench instance both are the instance's service
account by default, which usually cannot enable APIs, create service accounts or deploy Cloud Run. Pick one route before step 3:

- **act as yourself**: in the Terminal run `gcloud auth login --no-launch-browser --update-adc` once (`--update-adc` couples the two
  stores; `gcloud auth application-default login` alone would leave `deploy.sh` acting as the service account);
- **act as the instance's service account**: grant it what the Cloud Shell operator has — Owner on a sandbox project, or Cloud Run
  Admin, Cloud Run Source Developer, Service Account Admin, Service Account User, Project IAM Admin, Service Usage Admin, Secret
  Manager Admin, BigQuery Admin, Cloud Scheduler Admin, Cloud Build Editor. `deploy.sh` mints the service's ID token with the service
  URL as audience when the active account is a service account, so `dry` and `run` work on this route.

The identity cell prints both stores. The HubSpot token is typed into a masked prompt in step 3.5 and handed to `deploy.sh secret`
as an environment variable; it never touches the notebook file or `.env` (`check-env` refuses a token in `.env`).

Colab Enterprise (Vertex AI → Colab Enterprise) runs the same notebook; the first cell's clone falls back to `~/CloudBQ` there.

## What you see

| Section | Cells | Evidence |
|---|---|---|
| 3. Sequence | `DRYRUN=1 all`, `check-env` … `invoker`, `dry` (gate), `run SEALSQ`, `run ICALPS`, `probe` | the script's own output; a failing step stops Run-All |
| 4.1 | `INFORMATION_SCHEMA` | the four tables and the view `tables` created |
| 4.2 | `scoring/hot_score_v1.sql`, `tests/hot_score_vectors.sql` | the UDF's DDL job, 15 rows `ok = TRUE` |
| 4.3 | `main.hot_score` on the same vectors | Python and SQL side by side |
| 4.4 | `report_state`, `new_deals_runs`, `new_deals_history`, `new_deals_last_7d` | what the live runs wrote |
| 4.5 | `deploy.sh probe` vs the same SQL from Python | the equality check across surfaces |
| 4.6 | `GET ?entity=…&dry_run=1` with an ID token chosen by credential type | the function's own payload: window, per-deal scores |
| 4.7 | optional: HubSpot deals of the last 7 days → `main.hot_score` and the UDF | live parity, via `test_hot_score.emit_sql` |
| 5. Enable | `enable` (flag-guarded), `status` | the two jobs resumed; idempotent on re-run |

`tests/test_notebook.py` keeps the notebook valid (nbformat), its code cells compilable, every `deploy.sh` step mirrored in the
runbook order, `enable` flag-guarded, the token prompted, and no outputs committed. Offline rehearsal: the notebook was executed with
a real kernel in a clone without Google credentials; every cell that needs none ran (repository, settings, identity, `DRYRUN=1 all`,
`check-env`, the Python scorer), and every other cell stopped at the credential boundary, as intended. The SQL text of the witness
cells was reviewed against the BigQuery `INFORMATION_SCHEMA` and function signatures; it has not yet run against a project.

## `l2_deal_tiers.ipynb` — pass 2, the lab for the L2 likelihood tiers

Lane N of `docs/PASS2_L2_TIERS.md`. It installs the function's requirements into the kernel, takes a snapshot of every deal through the
function's `HubSpot` client (token from Secret Manager `hubspot-token` or a masked prompt), measures fill rates and distributions of the
certainty candidates, bins with `numpy.digitize` on the edges of `scoring/deal_tiers_v1.constants.json`, calibrates the bins against the
stage-entry dates (`hs_v2_date_entered_<stage>`, with each stage's configured probability), loads the snapshot into `deal_tiers_lab` and
proves per deal that BigQuery's `RANGE_BUCKET` returns the same bin, compares the lab with the gold table when it exists, and prints the
`deal_tier_v1` property definition and the StackSync mapping rows. It never writes the gold table `deal_tiers`; that is the scheduled
MERGE `sql/deal_tiers_apply.sql` (lane Q). Same identity notes as above.

## `company_tiers.ipynb` — pass 2b, the company object by foreign-key resolution (Vertex AI Workbench / Colab Enterprise)

§7 of `docs/PASS2_L2_TIERS.md`. The kernel is the probe of a lane-Q object the repository defines once (`sql/company_tiers_body.sql`):
§1 takes the snapshot through the function's `HubSpot` client and tiers it as `deal_tiers_v1` would (same constants, `numpy.digitize`);
§2 runs the repository's body over `UNNEST(@deals_payload)` — the snapshot as an `ARRAY<STRUCT>` query parameter — and writes two CSVs
(deal level with the resolver that fired, company level: `sales_region × company × tier` with the deals nested) and **no table**
(`statement_type = SELECT` is asserted); §3 ships `sql/company_tiers_v1.sql` rendered exactly as `sql/apply.sh` renders it (the views,
the snapshot tables, the refreshes log); §4 compares the dry run's rollup with the live view; §5 registers the refresh paused
(`DISABLE_SCHEDULE=1 sql/company_tiers_schedule.sh`) and runs it once by hand; §6 probes `company_tiers_refreshes`, the summary view and
the snapshot; §7 enables the daily schedule. The two write gates (§5, §7) are flags that ship `False`. On Colab Enterprise the first cell
clones the branch into `/content` when no clone is present; `.env` must hold `SYNC_COMPANIES_TABLE` (the Companies asset of the sync) and
`ARR_DATASET` (the ARR dashboard staging with `stg_deals` and `rec_three_layer`). Same identity notes as above; nothing is written into a
sync table.

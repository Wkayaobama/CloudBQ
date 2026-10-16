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

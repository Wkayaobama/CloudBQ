# Cloud Shell runbook — CloudBQ lane A on `wisekeybq`

Run the phases in order. Each ends with a check; do not continue when a check fails. The canonical sequence with the look
commands is `docs/PASS1_SEQUENCE.md`; this page is the operator's phased version for one project, with the values filled in.
The same sequence runs from a Vertex AI Workbench notebook (`notebooks/cloudbq_deploy_and_witness.ipynb`, see `notebooks/README.md`).

Settled before the first run:

- **Portal ID is 9201667.** It is the hub ID of the HubSpot account this project is connected to (ayaobama@wisekey.com), and the
  default in `.env.example`; 49610528 was a mistake in an earlier draft. It only builds `deal_url`.
- **`BQ_LOCATION=EU` because `mrload` lives in EU**, not because Cloud Run runs in europe-west6. The BigQuery location is independent of
  the Cloud Run region; what matters is the location of the dataset the tables go into. mir-load created `mrload` with `--location=EU`
  (`scripts/run_pass1.sh`), and Phase 2 checks it.
- **`DATASET=mrload` puts lane A's tables next to the warehouse tables.** `deploy.sh tables` grants `roles/bigquery.dataEditor` on that whole
  dataset to `new-deals-fn@`, so the function can edit every table in `mrload`. Acceptable for a first pass; a dedicated dataset
  (`DATASET=hubspot`) narrows the grant and costs nothing, since `new_deals_last_7d` is read by name either way.
- **The repo is private**, so Phase 1 authenticates `gh` first.

## Phase 0: shell and project

```bash
# variables in $HOME (persists across Cloud Shell restarts; contains no secrets)
cat > ~/cloudbq_vars.sh <<'EOF2'
MY_PROJECT=wisekeybq
MY_REGION=europe-west6
MY_DATASET=mrload
MY_FN=new-deals-report
MY_SA=new-deals-fn
MY_PORTAL=9201667
D=cloud_function_new_deals/deploy.sh
EOF2
source ~/cloudbq_vars.sh

gcloud config set project "$MY_PROJECT"
gcloud config list project                                                        # check: project = wisekeybq
gcloud auth list                                                                  # check: your account is ACTIVE
gcloud billing projects describe "$MY_PROJECT" --format='value(billingEnabled)'   # check: True
```

In every new Cloud Shell session: `source ~/cloudbq_vars.sh && cd ~/CloudBQ && source ~/.venvs/cloudbq/bin/activate`
(`D` is a relative path, valid inside the clone).

## Phase 1: get the code

```bash
gh auth login                  # GitHub.com → HTTPS → browser; gh is preinstalled in Cloud Shell
gh auth setup-git
git clone https://github.com/Wkayaobama/CloudBQ.git ~/CloudBQ && cd ~/CloudBQ
git checkout claude/cloud-run-bigquery-pipeline-e94ziy && git pull
git branch --show-current      # check: claude/cloud-run-bigquery-pipeline-e94ziy
ls -a | grep env               # check: .env.example is listed
```

## Phase 2: create `.env`

```bash
source ~/cloudbq_vars.sh
cp .env.example .env
sed -i.bak -E \
  -e "s|^PROJECT=[^ #]*|PROJECT=${MY_PROJECT}|" \
  -e "s|^REGION=[^ #]*|REGION=${MY_REGION}|" \
  -e "s|^DATASET=[^ #]*|DATASET=${MY_DATASET}|" \
  -e "s|^FN=[^ #]*|FN=${MY_FN}|" \
  -e "s|^SA_NAME=[^ #]*|SA_NAME=${MY_SA}|" \
  -e "s|^PORTAL_ID=[^ #]*|PORTAL_ID=${MY_PORTAL}|" \
  .env && rm .env.bak

grep -E '^(PROJECT|REGION|BQ_LOCATION|DATASET|FN|SA_NAME|PORTAL_ID)=' .env       # check: seven lines, your values, BQ_LOCATION=EU
bq show --format=prettyjson "${MY_PROJECT}:${MY_DATASET}" | grep '"location"'      # check: "EU" — must equal BQ_LOCATION in .env
```

If the dataset does not exist yet, the second check prints "Not found"; `tables` will create it in `BQ_LOCATION`. If it exists in another
location, set `BQ_LOCATION` to that value: `CREATE SCHEMA IF NOT EXISTS` never moves a dataset, and every `bq` call passes the location.

## Phase 3: offline rehearsal (no cloud changes)

The tests import the function module, which needs `functions-framework`, `requests` and `google-cloud-bigquery`; Cloud Shell's Python
does not ship them, so install them once into a virtualenv in `$HOME` (it persists).

```bash
python3 -m venv ~/.venvs/cloudbq && source ~/.venvs/cloudbq/bin/activate
pip install -q -r cloud_function_new_deals/requirements.txt pyyaml pytest
python3 tests/test_hot_score.py && python3 tests/test_main_offline.py && python3 tests/test_n8n_code.py
$D check-env                   # check: project=wisekeybq region=europe-west6 dataset=mrload fn=new-deals-report sa=new-deals-fn@wisekeybq.iam.gserviceaccount.com …
DRYRUN=1 $D all                # prints every gcloud/bq command, runs nothing
```

Read the printed commands once: your project, region, dataset and `new-deals-fn@wisekeybq.iam.gserviceaccount.com` must appear in them.
`deploy.sh` is executable in git; no `chmod` needed.

## Phase 4: infrastructure, in this order

`secret` comes after `iam`: it grants `secretAccessor` to the service account, which must already exist.

```bash
$D enable-apis
$D iam
$D tables

# look
gcloud iam service-accounts list --project "$MY_PROJECT"                         # check: new-deals-fn
bq ls --project_id="$MY_PROJECT" "$MY_DATASET"                                   # check: report_state, new_deals, new_deals_runs, new_deals_history, deals_raw, labels_raw, new_deals_last_7d (view)
```

## Phase 5: the HubSpot token

Use the silent prompt only; the inline form `HUBSPOT_TOKEN=… $D secret` leaves the token in your shell history. `check-env` refuses a
token placed in `.env`.

```bash
IFS= read -rsp "HubSpot token: " HUBSPOT_TOKEN; echo
HUBSPOT_TOKEN="$HUBSPOT_TOKEN" $D secret     # creates hubspot-token or adds a version; prints the version NUMBER
unset HUBSPOT_TOKEN

gcloud secrets versions list hubspot-token --project "$MY_PROJECT"                # check: one enabled version
```

Pinning is optional: with `SECRET_VERSION` empty, `deploy` uses the latest enabled version number. To pin:

```bash
sed -i -E "s|^SECRET_VERSION=[^ #]*|SECRET_VERSION=1|" .env                       # replace 1 with the printed number
```

Every re-run of `secret` adds a new version (the previous ones stay enabled); that is rotation, not a no-op.

## Phase 6: deploy

```bash
$D deploy                      # first source build takes several minutes; the first one asks to create the cloud-run-source-deploy repository → Y
$D invoker

# look
gcloud run services describe "$MY_FN" --region "$MY_REGION" --format 'value(status.url)'
gcloud scheduler jobs list --location "$MY_REGION"                                # check: both jobs PAUSED
```

If `deploy` fails on a permission right after `iam`, wait two minutes and run `$D deploy` again: IAM bindings propagate with delay.

## Phase 7: the gate, then the live runs

```bash
$D dry                         # must end with "dry run passed for both entities"
```

If `dry` fails, run `$D logs` and do not continue. `invoke` uses `curl -sSf`, so an HTTP error fails the step with its status:

- **403**: *your* account lacks `run.invoker` on the service. `dry` calls the service with your identity token, not the service account's;
  Owner and Editor have the permission, otherwise `gcloud run services add-iam-policy-binding "$MY_FN" --region "$MY_REGION"
  --member "user:you@wisekey.com" --role roles/run.invoker`. (`invoker` grants the service account, for Cloud Scheduler.)
- **500 with a HubSpot 401 in the logs**: the token is wrong or lacks `crm.objects.deals.read`, `crm.schemas.deals.read`, `crm.objects.owners.read`.
- **500 with "Not found: Table"**: `tables` did not finish, or `BQ_LOCATION` does not match the dataset.
- **409**: a lease is held (a run is in progress); wait `LEASE_MINUTES` (12) and retry.

```bash
$D run SEALSQ                  # first live window: no watermark yet → the last FIRST_RUN_DAYS (7) days; prints window.query_start
$D run ICALPS
$D probe                       # rows per entity, hot and duplicate counts; last runs
$D status                      # watermarks, leases, scheduler states

FROM=2026-10-09T07:00:00Z      # ← window.query_start printed by the first `run SEALSQ`
$D replay SEALSQ "$FROM"       # idempotency check: the SAME window again — MERGE on deal_id, probe counts must not change
$D probe
```

A second `run` would not test idempotency: each `run` moves the watermark, so it opens the next window. Only `replay` repeats one.

## Phase 8: turn on the schedule

```bash
$D enable                      # resumes the two PAUSED jobs; a second call reports "already enabled"
gcloud scheduler jobs list --location "$MY_REGION"                                # check: ENABLED
```

Only after the gate passed and the probe looks right.

## Summary of the order

| # | Step | Needs |
|---|---|---|
| 0 | vars file, `gcloud config set project` | nothing |
| 1 | `gh auth`, clone, checkout | GitHub login (private repo) |
| 2 | `.env` via sed, dataset location check | nothing |
| 3 | venv, offline tests, `check-env`, `DRYRUN=1 all` | nothing |
| 4 | `enable-apis`, `iam`, `tables` | Owner (or the roles in `docs/PASS1_SEQUENCE.md`) |
| 5 | `secret` | the HubSpot token, once, typed |
| 6 | `deploy`, `invoker` | nothing |
| 7 | `dry`, `run`, `probe`, `status`, `replay` | `run.invoker` for your account |
| 8 | `enable` | nothing |

Reminders:

- **Re-running.** `enable-apis`, `iam`, `tables`, `deploy`, `invoker`, `enable`, `pause` are create-or-update: safe to repeat after a dropped
  session. `secret` adds a version each time; `run` moves the watermark each time (`replay` repeats a window).
- **Evidence.** `docs/PASS1_SEQUENCE.md` has an empty Evidence section: paste the two `dry` lines and the `probe` output there after Phase 7.
- **`amount_kusd`.** Confirm its unit from the first dry payload: the column holds HubSpot's `amount_in_home_currency` as stored, not a
  computed kUSD figure (`main.py shape()`); rename or divide in a later pass if the stored unit is not thousands.

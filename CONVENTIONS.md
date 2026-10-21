# Conventions for scaffolded code in CloudBQ (read by aider on every run)

- **Idempotent by construction.** Every step may be re-run with the same inputs and must leave the same state:
  rows MERGE into `hubspot.new_deals` on `deal_id`; the watermark in `hubspot.report_state` advances only after a
  successful MERGE; HubSpot write-backs PATCH values and skip rows that already hold them.
- **Gate before live.** `?dry_run=1` (function), `--dry-run` (scripts) or an unset `*_APPROVE_*` variable computes
  everything and writes nothing to the sink or the state (a dry run of the function lands its root slice with `mode = 'dry'`
  and leaves one `new_deals_runs` row with `dry_run = TRUE`; nothing else). One explicit flag opens the live path; schedulers
  are enabled only after a dry run.
- **Shared truth in BigQuery, local state in the clone.** Anything two orchestrators (Cloud Run function, n8n,
  remote JS) must agree on lives in the `hubspot` dataset — never in a local file or an n8n static variable.
- **No secrets, no project ids in git.** `HUBSPOT_TOKEN` comes from Secret Manager; `PROJECT`, `REGION`, `DATASET`
  come from `.env` (gitignored) via `.env.example`; scripts fail loudly on a missing or placeholder value.
- **Same arithmetic everywhere — one implementation since pass 3.** The batch (window, labels, duplicates, `hot_score_v1`,
  MERGE, history, runs row) is `sql/new_deals_batch.sql` over the raw root (`deals_raw` / `labels_raw`); every lane lands its
  inputs and CALLs it. `main.py` keeps `hot_score()` / `shape()` as test oracles pinned to `tests/hot_score_vectors.json`; the
  constants (`W`, `BIAS`, `THRESHOLD`, `CR`, `MAXC`) live in `scoring/hot_score_v1.constants.json` and the UDF.
- **Inputs land before anything is computed from them.** A run's root slice (run_ts, entity, orchestrator) is written first,
  load-then-delete-older, so a failed batch leaves its inputs queryable and a past run is recomputable: `SELECT * FROM
  new_deals_batch_rows(run_ts, entity, orchestrator, query_start)`.
- **One block, one commit.** Do not refactor neighbouring code in a scaffold step; keep the trailer
  `Recipe: <recipe path>` in the commit body so `docs/diffs/INDEX.md` can name it.
- **Python 3.12 (functions-framework), Node 22 (write-back job), standard SQL (BigQuery).** Standard libraries first.

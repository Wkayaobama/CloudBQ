# Conventions for scaffolded code in CloudBQ (read by aider on every run)

- **Idempotent by construction.** Every step may be re-run with the same inputs and must leave the same state:
  rows MERGE into `hubspot.new_deals` on `deal_id`; the watermark in `hubspot.report_state` advances only after a
  successful MERGE; HubSpot write-backs PATCH values and skip rows that already hold them.
- **Gate before live.** `?dry_run=1` (function), `--dry-run` (scripts) or an unset `*_APPROVE_*` variable computes
  everything and writes nothing. One explicit flag opens the live path; schedulers are enabled only after a dry run.
- **Shared truth in BigQuery, local state in the clone.** Anything two orchestrators (Cloud Run function, n8n,
  remote JS) must agree on lives in the `hubspot` dataset — never in a local file or an n8n static variable.
- **No secrets, no project ids in git.** `HUBSPOT_TOKEN` comes from Secret Manager; `PROJECT`, `REGION`, `DATASET`
  come from `.env` (gitignored) via `.env.example`; scripts fail loudly on a missing or placeholder value.
- **Same arithmetic everywhere.** The hot-score constants (`W`, `BIAS`, `THRESHOLD`, `CR`, `MAXC`) are defined once per
  surface and covered by the offline test vectors in `tests/`; a change to one copy is a change to all.
- **One block, one commit.** Do not refactor neighbouring code in a scaffold step; keep the trailer
  `Recipe: <recipe path>` in the commit body so `docs/diffs/INDEX.md` can name it.
- **Python 3.12 (functions-framework), Node 22 (write-back job), standard SQL (BigQuery).** Standard libraries first.

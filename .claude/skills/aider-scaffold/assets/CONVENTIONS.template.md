# Conventions for scaffolded code (read by aider on every run)

- **Idempotent by construction.** Every pipeline step may be re-run with the same inputs and must produce
  the same state: loads MERGE on a natural key, watermarks advance only after the write succeeds,
  write-backs PATCH values and skip rows already equal.
- **Gate before live.** A dry-run mode (`dry_run=1`, `--dry-run`, an unset `*_APPROVE_*` variable) computes
  everything and writes nothing; the live mode is opened by one explicit flag.
- **Shared truth in the warehouse, local state in the clone.** Anything two surfaces must agree on lives in
  BigQuery (or the system of record), never in a local file.
- **No secrets in git.** Tokens come from Secret Manager or `.env` (gitignored); scripts read `.env.example`
  for the variable names and fail loudly when one is missing or still a placeholder.
- **One block, one commit.** Do not refactor neighbouring code in a scaffold step; name the recipe in the
  commit trailer `Recipe: <path>`.
- **Small, typed, logged.** Prefer standard libraries; log one structured line per step with counts.

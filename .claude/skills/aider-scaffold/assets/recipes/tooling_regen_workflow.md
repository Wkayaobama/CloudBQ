/add .claude/skills/regen-workflow/SKILL.md .claude/skills/regen-workflow/scripts/new_regen_workflow.py .claude/skills/regen-workflow/assets/commit_if_changed.sh .claude/skills/regen-workflow/assets/update_readme_index.py .github/workflows/regenerate.yml .github/workflows/update-readme-index.yml tests/test_regen_workflow.py
/read-only .claude/skills/aider-scaffold/scripts/diff_ledger.py CONVENTIONS.md

A reusable skill that writes "run a generator, commit what changed" GitHub Actions workflows for any repository.

Rules:
- One commit step (assets/commit_if_changed.sh) embedded by the generator into the reusable workflow and into inline workflows: stage paths, "No changes to commit" → exit 0, mode check → exit 1 with the diff, else commit as github-actions[bot] with a Regenerated-by trailer and push with rebase retries.
- Three modes: inline (self-contained), local (uses ./.github/workflows/regenerate.yml), Owner/Repo@ref. Triggers push / pull_request (forces check) / schedule / workflow_dispatch. permissions contents: write on the job; concurrency per workflow+ref; fetch-depth input; optional REGEN_TOKEN secret.
- assets/update_readme_index.py keeps a marker-delimited index of markdown files in README (idempotent, --check).
- diff_ledger.py skips commits carrying the Regenerated-by trailer.
- The generated YAML is parsed before it is written; tests cover the generator shapes, the commit step in a temporary repository, the index idempotency and the ledger skip.

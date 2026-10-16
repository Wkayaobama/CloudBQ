# Facts the skill relies on (GitHub Actions)

- A commit pushed with the workflow's `GITHUB_TOKEN` does not trigger `push`/`pull_request` workflows — so a push-triggered regeneration
  cannot loop on itself, and the bot commit does not run CI unless a PAT (`REGEN_TOKEN`) is used for the checkout. A PAT push *does*
  start runs, the regeneration workflow included: the generated jobs therefore carry
  `if: github.event_name != 'push' || !contains(github.event.head_commit.message, 'Regenerated-by:')`, which skips the run the bot's own
  commit would start. Independently of that guard, a generator whose output is not idempotent (timestamps, unordered output) would commit
  on every run — the `--check` mode on pull requests is the test for it.
- `workflow_dispatch` runs appear in the Actions tab only once the workflow file exists on the default branch; the branch to run on is then selectable.
- A reusable workflow (`on: workflow_call`) in the same repository is referenced as `./.github/workflows/<file>.yml`; in another repository as
  `owner/repo/.github/workflows/<file>.yml@ref`. A private host repository must allow access under Settings → Actions → General → Access.
- The caller job sets `permissions:`; the called workflow cannot exceed them. `secrets: inherit` passes the caller's secrets.
- On `pull_request`, the default checkout is the merge ref `refs/pull/<n>/merge`, which exists for fork PRs too; `github.head_ref` is a bare
  branch name that `actions/checkout` would look for in the base repository, so the generated checkouts set no `ref:`. The merge ref cannot
  be pushed to — the skill forces mode `check` on `pull_request`. On `push`, `workflow_dispatch` and `schedule` the default checkout is a
  local branch named after `github.ref_name`; `github.ref_type` tells a tag run apart (nothing to push to → exit 2).
- `concurrency.group` at workflow level serialises runs per ref; `cancel-in-progress: false` lets a queued regeneration run after the current one.
- Action majors in the generated files: `actions/checkout@v7`, `actions/setup-python@v7`, `actions/setup-node@v7` (node24 runtime; the
  inputs used — `fetch-depth`, `token`, `persist-credentials`, `python-version`, `node-version` — are unchanged since the v4/v5 majors, checked
  against each action.yml on 2026-10-16). `persist-credentials: true` is the default but is set explicitly because the commit step pushes with it.

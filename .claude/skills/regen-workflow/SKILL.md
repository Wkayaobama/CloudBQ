---
name: regen-workflow
description: Create GitHub Actions workflows of the "run a generator, commit what changed" family (update a README index, regenerate trees, rebuild a workbook) from one command, in any repository. Emits a self-contained workflow, or a thin caller of a reusable `regenerate.yml` kept in the same or a shared repository; one shared commit step with a change check, a PR check mode, push retries and a `Regenerated-by:` trailer. Use when someone wants "a GitHub Action like Update README" or asks to automate a regenerated file. Project-agnostic: nothing in the skill names a repository.
---

# regen-workflow

One generator, one commit step, three shapes of the same job: checkout → toolchains → run the generator → commit what changed
(or fail when something changed, on a pull request).

```bash
S=.claude/skills/regen-workflow/scripts
python3 $S/new_regen_workflow.py --emit-reusable                                   # once per repo: .github/workflows/regenerate.yml
python3 $S/new_regen_workflow.py --name "Update README index" --paths README.md \
    --run "python3 .claude/skills/regen-workflow/assets/update_readme_index.py --readme README.md --dir docs --dir notebooks --exclude 'docs/diffs/*'" \
    --on push:main --on workflow_dispatch --mode local                             # thin caller of ./.github/workflows/regenerate.yml
python3 $S/new_regen_workflow.py --name "Update README" --paths README.md --run "python3 update_readme.py"    # self-contained (inline)
python3 $S/new_regen_workflow.py --name "Trees" --paths "docs/*.txt docs/*.json" --run "python3 tree.py" --mode Owner/Repo@v1
```

Prerequisites: Python 3.10+ and git. PyYAML is optional — when installed, the generated file is parsed before it is written.

## In another repository

1. Copy the folder `.claude/skills/regen-workflow/` (the generator reads `assets/commit_if_changed.sh` next to it, so copy the folder,
   not the one script). `git subtree` or a plain `cp -r` both work; nothing in it names a repository.
2. From that repository's root, run the inline command above — the generated file is self-contained and needs only your `--run`
   program. `--out other/repo/.github/workflows/x.yml` writes it elsewhere without copying anything there.
3. `--mode local` also writes `regenerate.yml` the first time (a caller without its callee fails on GitHub at parse time).
4. `--mode Owner/Repo@ref` needs the host's `regenerate.yml` at that ref; a private host must allow access (Settings → Actions →
   General → Access) and that setting admits private callers only — a public caller needs a public host.
5. Triggers default to `main`; the generator prints a note when the clone's `origin/HEAD` says otherwise (`--on push:master`).

| `--mode` | What is written | When |
|---|---|---|
| `inline` (default) | the whole job in the file; the commit step embedded | any repository, no dependency, nothing to configure |
| `local` | `uses: ./.github/workflows/regenerate.yml` with `with:` inputs; `regenerate.yml` is written too when missing | several regenerations in one repository share one implementation |
| `Owner/Repo@ref` | `uses: Owner/Repo/.github/workflows/regenerate.yml@ref` | a shared copy — pin `@ref` to a tag or SHA; a private host needs Settings → Actions → General → Access → "Accessible from repositories owned by …" (private callers only) |

Both callers pass exactly one secret, `REGEN_TOKEN` (never `secrets: inherit`): it is the only one the reusable workflow reads.

Triggers: `--on push[:branch,branch]`, `--on pull_request[:branch]`, `--on schedule:"0 6 * * 1"`, `--on workflow_dispatch`
(default `push:main` + `workflow_dispatch`, like the Update README original; a repeated kind merges, so `--on push:main --on push:dev` is one `push:`). `--check` makes the job fail when regeneration changes
anything instead of committing; on `pull_request` that mode is forced because a PR checkout cannot be pushed to.

## The commit step (`assets/commit_if_changed.sh`)

The same script is embedded in the reusable workflow and in every inline workflow, so a fix lands in one place and `--emit-reusable`
/ regeneration propagates it. It stages the given paths (deletions included), prints "No changes to commit" and exits 0 when nothing
changed, otherwise commits as `github-actions[bot]` with a `Regenerated-by: <workflow> (<run url>)` trailer and pushes with three
rebase-and-retry attempts (a rejection that is not a race, or a rebase conflict, stops at once with the reason). Globs in `--paths` reach git
unexpanded, so `docs/*.txt` also stages the files the generator deleted. Pushes made with `GITHUB_TOKEN` do not start new workflow runs;
when the regenerated commit must run CI, store a PAT as the `REGEN_TOKEN` secret — the checkout uses it when present. A PAT push *would*
re-run a `push`-triggered regeneration, so every generated job is guarded with
`if: github.event_name != 'push' || !contains(github.event.head_commit.message, 'Regenerated-by:')`; the generator itself must still be
idempotent (the pull-request `check` run proves it). The guard skips *every* regen workflow for a bot commit, so a regeneration that
depends on another's output belongs in the same workflow (repeat `--run`) or on a schedule.

`permissions: contents: write` is on the job. `concurrency` (group = workflow + ref) serialises runs of one workflow per branch; two
different regen workflows writing to the same branch are reconciled by the rebase-and-retry push. `fetch-depth` is an input for
generators that read history (`0` = full). On a protected branch the bot's push is refused ("the branch did not move: not a race"):
add the GitHub Actions app (or the PAT's user) to the ruleset's bypass list, or regenerate on a branch and let `pull_request` run in
check mode.

## The first consumer: a README index (`assets/update_readme_index.py`)

```bash
python3 .claude/skills/regen-workflow/assets/update_readme_index.py --readme README.md --dir docs --dir notebooks --exclude 'docs/diffs/*'          # write
python3 .claude/skills/regen-workflow/assets/update_readme_index.py --readme README.md --dir docs --dir notebooks --exclude 'docs/diffs/*' --check  # exit 1 if stale (CI)
```
Keeps `- [first H1 title](path)` lines for every `*.md` under the directories between `<!-- regen:docs-index start/end -->` markers
(appended once as a "## Documents" section): the files of each directory first, then its sub-directories, case-insensitive; titles
are read outside fenced code (setext and BOM handled); hidden directories are skipped; CRLF is preserved. Idempotent; several blocks can
coexist (`--name`). The `--check` form belongs in CI next to the other generated-artefact checks.

## Generated commits and the diff ledger

`diff_ledger.py` (aider-scaffold skill) skips commits that carry the `Regenerated-by:` trailer: a regenerated file is not an AI
suggestion, and the ledger's `--check` must stay green after the bot commits.

## Verify

```bash
python3 -m pytest tests/test_regen_workflow.py -q      # generator shapes, commit step in a temporary repository, index idempotency, ledger skip
python3 tests/test_regen_workflow.py                   # the same without pytest
```

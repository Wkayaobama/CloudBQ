# UNIVERSAL_WORKFLOW — how a building block travels from idea to green CI, and how a team keeps it that way

This page is for anyone who will add, review or regenerate something in a repository that carries the four skills under
`.claude/skills/` — `aider-scaffold` (recipes and the diff ledger), `tree-f-visualizer`, `pass-sequence` and `regen-workflow`.
It is written for a team: every command is copy-pasteable from the repository root, every expected output is quoted, and every
claim about what the tools did in CloudBQ is checked against the git history (branch `claude/cloud-run-bigquery-pipeline-e94ziy`
at d18a95f: 42 commits between 2026-10-05 and 2026-10-16; every count below is as of that commit). The same files are installed unchanged in IC-DBT-BQ.

**How to read it.** Five minutes: §1 and §2 (the idea and the loop). Thirty minutes: §4 (one tool at a time) and §5 (a worked
example with outputs). Reference: §6 (bootstrapping a new repository), §8 (verify cheat-sheet), §10 (FAQ), §11 (glossary).

---

## 1 · The idea in four sentences

1. **The suggestion is the commit.** Every change — a person's, aider's, or a bot's — is one commit whose body says where it came
   from (`Recipe:`, `Scaffolded-by:`, `Regenerated-by:` trailers). Review happens on `git diff`, never on a chat transcript.
2. **The record is derived, never typed twice.** The patch trail (`docs/diffs/`), the architecture tree (`docs/ARCHITECTURE_TREE.txt`,
   `docs/architecture_tree.html`), the lane workbook (`docs/EXECUTION_SURFACES*.xlsx`) and the README's Documents index are all
   generated from a source file you edit (`git log`, `docs/architecture.yaml`, `docs/execution_surfaces*.yaml`, the `docs/` folder).
3. **The check is automated.** CI re-runs every generator in check mode and refuses a push that skipped a regeneration. A bot runs the
   same generators in commit mode when a human should not have to.
4. **Nothing in the tools names a project.** The project's words — scenario ids, layer ids, roles, parity — live in two YAML files.
   The skills are copied between repositories without edits (CloudBQ → IC-DBT-BQ was the probe).

---

## 2 · The loop

```
 1 recipe ─► 2 apply ─► 3 verify ─► 4 commit ─► 5 ledger ─► 6 tree ─► 7 workbook ─► 8 index ─► 9 review ─► 10 replay ─► 11 push
   U1          U2          U3          U4          U5          U6          U7           U8          U10          U3           U11
 recipe .md  aider or   pytest,     trailers   diff_       tree_f.py   build_       update_     critics +   fresh clone  git push;
 + proposed  by hand    --check                ledger.py   (3 files)   surfaces_    readme_     skeptics    runs the     CI verify;
 tree node                                                            xlsx.py      index.py                whole §8     bot regen
```

`U0…U11` are the layer ids of `docs/EXECUTION_SURFACES_TOOLING.xlsx`, where each stage is rated across the three surfaces of §3.
Steps 6, 7 and 8 run only when their source changed (an annotation, a surfaces YAML, a document); step 9 runs for a block, not for
a regenerated artefact. Steps 3, 5, 6, 7 and 8 are exactly what CI repeats, so a developer who runs them before pushing never sees a
red check for a reason they could not have seen locally.

---

## 3 · Three execution surfaces

The same loop is executed by three actors. Knowing which one you are tells you what you may write.

| Surface | Who | Runs | Writes | Never does |
|---|---|---|---|---|
| **D** developer shell | a person on a clone (aider when an LLM key is present) | every step of §2 | the recipe, the block, the annotations, the specs, the commits | push to another branch; commit a secret |
| **C** CI check | `.github/workflows/ci.yml`, job `verify`, on every push and pull request | steps 3, 5, 6, 7, 8 in `--check` / `--verify` mode, the test suite | nothing (builds to `/tmp`) | fix, commit, push |
| **B** bot commit | a regen workflow (`.github/workflows/regenerate.yml` and its callers) | one generator, then `assets/commit_if_changed.sh` | one commit as `github-actions[bot]` with a `Regenerated-by:` trailer | apply a block; run the test suite; retry a push that was refused for a non-race reason |

`docs/execution_surfaces_tooling.yaml` lays the twelve layers out per surface with the parity vocabulary of the `pass-sequence` skill
(the workbook `docs/EXECUTION_SURFACES_TOOLING.xlsx` is built from it). Reading the verdict: **one** layer is Parallel — the README
index, the same script with the same arguments on all three surfaces; **six** are Conditional on "same commit, regeneration run before
the push, a PAT if the bot's commit must run CI"; **five** are Divergent because only the developer creates, only a person or an agent
reviews, and only the bot commits unattended. Divergent is not a defect here: it names the stages where a surface has nothing to do.

---

## 4 · The tools, one at a time

Each section answers the same six questions: what problem it solves, when you reach for it, the commands, what it writes, how to read
the output, and what it did (or would have done) in CloudBQ.

### 4.1 Recipes and the aider scaffolder — `.claude/skills/aider-scaffold/`

**Problem.** A building block proposed by an assistant arrives as prose in a chat; nobody can `git diff` it, and the next block
quietly refactors the previous one. **Solution.** One markdown *recipe* per block states the purpose, the files to add, the contract
(inputs, outputs, idempotency rule, gate) and what not to touch; a wrapper feeds it to aider, which edits and commits each step
itself; without an LLM key the same recipe is applied by hand and the commit says so.

**When.** Every new building block (a script, a view, a notebook, a doc set). Not for a one-line fix.

```bash
S=.claude/skills/aider-scaffold/scripts
# 1. write the recipe (copy an existing one and keep its shape)
$EDITOR .claude/skills/aider-scaffold/assets/recipes/<block>.md
# 2. run it — aider edits the listed files and auto-commits; the tree must be clean first
python3 $S/aider_scaffold.py .claude/skills/aider-scaffold/assets/recipes/<block>.md path/to/file.py path/to/other.sql
python3 $S/aider_scaffold.py <recipe> <files> --dry-run        # show the edits, write nothing
```

**What it writes.** With a key: one commit per aider edit, author `<you> (aider)`, trailer `Recipe: <recipe path>` (added by the
`--commit-prompt` the wrapper builds from `.aider.conf.yml`); then the ledger (§4.2) runs. Without a key — the exact output is:

```
aider_scaffold: cannot run aider (no LLM API key in the environment).

Recipe .claude/skills/aider-scaffold/assets/recipes/<block>.md:
------------------------------------------------------------------------
<the recipe, verbatim>
```

and the exit code is 2. You then apply the recipe yourself and commit with the two trailers, so the ledger row is the same either way:

```bash
git commit -m "<block>: <what it does>" -m "Recipe: .claude/skills/aider-scaffold/assets/recipes/<block>.md" -m "Scaffolded-by: hand (no LLM key)"
```

**Pitfalls.** The wrapper refuses a dirty tree (`--allow-dirty` exists but defeats "one commit, one suggestion"). A recipe must be
self-contained: aider sees only the recipe, the `/add` files and `CONVENTIONS.md`. Keys are read from `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY` or `--model`.

**In CloudBQ.** aider never answered: no key was present in the build environment. Twelve recipes exist (this page adds a
thirteenth); 17 commits carry
`Scaffolded-by: hand (no LLM key)` and a `Recipe:` trailer (the hot-score ports, the deploy step runner, the n8n workflows, the function's idempotency, the
BigQuery compute lane, the write-back job, the pass-1 document set, the tooling itself). Four later blocks — the notebook witness,
the Cloud Shell runbook, the L2 tiers, the GitHub Actions skill — have recipe files referenced from `docs/architecture.yaml` but no
trailer in their commits; that is the gap a reviewer should ask about. **What a key would have added.** Finer patches (one per aider
edit instead of one per block), `aider` = yes in the ledger, and the recipe text as the literal instruction that produced the diff —
the review surface becomes "did the recipe say this?" instead of "did the author say this?".

### 4.2 The diff ledger — `diff_ledger.py`

**Problem.** Commits get squashed, rebased or buried; the question "what exactly did the assistant propose for block X?" needs a
stable, browsable answer. **Solution.** One `.patch` per commit plus an index row, appended idempotently, committed with the code.

```bash
S=.claude/skills/aider-scaffold/scripts
python3 $S/diff_ledger.py                 # append docs/diffs/NNNN-<sha>-<slug>.patch + a row to docs/diffs/INDEX.md
python3 $S/diff_ledger.py --check         # exit 1 and list every commit missing from the index (CI does this)
python3 $S/diff_ledger.py --aider-only    # only aider's commits
python3 $S/diff_ledger.py --since <rev>   # restrict to <rev>..HEAD
git add docs/diffs && git commit -m "docs: diff ledger update"
```

**What it writes.** `ledger +0028-<sha>-<slug>.patch` per new commit, then `diff_ledger: N patch(es) appended to docs/diffs/INDEX.md`.
The row: `n · sha · date · author · aider (yes/no) · recipe · files · +/− · patch`. `--check` prints `diff_ledger --check: 0 commit(s)
not in docs/diffs/INDEX.md` when current, otherwise `missing: <sha> <subject>` lines and exit 1.

**What it skips, on purpose.** Commits that touch only `docs/diffs/` (otherwise `--check` could never pass) and commits carrying a
`Regenerated-by:` trailer (a bot's regenerated files are not a suggestion). The INDEX.md header states both rules and is rewritten when
that text changes.

**Pitfalls.** CI needs the whole history: `actions/checkout` with `fetch-depth: 0`. Run the ledger as the *last* local step, after
the block commit, and commit it — a push without it is red. The patches are excluded from the architecture tree (`exclude: ['*.patch']`).

**In CloudBQ.** 27 rows for 42 commits; the 15 absent commits are the ledger's own (`docs: start the diff ledger`, fourteen
`docs: diff ledger update`). Every commit that touched the hot-score model, `deploy.sh`, the notebooks, the runbook and the L2 pass has
its patch. The review agents of this project read the working tree rather than the patches; the ledger's value was the trail, not the
review input. **Prospective.** A reviewer who joins late reads `docs/diffs/INDEX.md` top to bottom and has the whole story of the
branch in order, with the recipe that produced each block — no chat archaeology.

### 4.3 The architecture tree — `tree-f-visualizer`

**Problem.** "What is in this repository, which lane uses it, and what is still only proposed?" is answered differently by every
person. **Solution.** One annotations file says what each path *means*; a walk says what *exists*; the renderer draws both as a Windows
`tree /f` listing (text, JSON manifest, single-file interactive HTML), with proposed paths grafted in dashed.

```bash
S=.claude/skills/tree-f-visualizer/scripts
$EDITOR docs/architecture.yaml                     # add the block's node: scenarios, layer, role, status, parity, recipe
python3 $S/tree_f.py --root . --annotations docs/architecture.yaml \
  --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html
python3 $S/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json \
  --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html --check     # CI form: exit 1 when stale
python3 $S/tree_f.py --root . --annotations docs/architecture.yaml --scenario B             # one lane, to stdout
```

A node looks like this (the words for `status` and `parity` are validated; anything else stops the build):

```yaml
nodes:
  sql/deal_tiers_apply.sql: {scenarios: [C], layer: L7, layers: [L7, L13, L15], status: new, parity: Conditional,
                             role: 'gold MERGE on deal_id keyed on @run_time; history rows on change; retirement',
                             recipe: .claude/skills/aider-scaffold/assets/recipes/c_l2_deal_tiers.md}
```

**What it writes.** The three files; `--check` prints `tree_f --check: up to date` or exits 1 naming the stale output. The HTML has
scenario and status chips, a path filter, a details panel and "Copy as tree /f" (byte-identical to the text file). The volume serial
in the header is derived from the content, so an unchanged tree renders byte-identically.

**Pitfalls.** Status words: `existing | modify | new | proposed`. A `proposed` node is the way to show a plan before the file exists —
flip it to `new` in the commit that creates the file. A node's `parity` must equal the lane workbook's word for that layer:
`tests/test_docs_consistency.py` compares the two, so annotating a layer-L0 block `Parallel` when the workbook rates L0 `Divergent`
fails the suite (this page's own first commit did exactly that). The walker ignores `.gitignore` patterns and drops empty directories, so a fresh
clone reproduces the render (that was a CI-only failure once, see §9).

**In CloudBQ.** 92 annotated nodes across lanes A/B/C and layers L0–L17 (this page adds three); regenerated and checked on every commit; the ledger patches
excluded. The tree was bookkeeping — a record that every block has a lane and a layer — not a design input to the scoring arithmetic.
**Prospective.** Publish `docs/architecture_tree.html` as an artifact for a design review: the chips answer "what does lane B need
that A does not?" without a slide.

### 4.4 The lane workbook — `pass-sequence`

**Problem.** When one outcome can be reached through several surfaces (terminals, scenarios, lanes), the parity between them is
asserted in prose and drifts. **Solution.** A YAML spec rates every layer and every step per surface with three words — **Parallel**
(same mechanism, same result), **Conditional** (same result under a stated condition), **Divergent** (different mechanism; the
remediation column says how they are made equivalent) — and a builder renders an Excel workbook whose Overview counts the words live.
The documentation set comes in a fixed order: sequence page → surfaces record → YAML → workbook (the skill page explains why).

```bash
S=.claude/skills/pass-sequence/scripts
$EDITOR docs/execution_surfaces.yaml                                                   # layers, steps, remediation, equality_checks
python3 $S/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out docs/EXECUTION_SURFACES.xlsx --verify
python3 $S/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out /tmp/surfaces.xlsx --verify     # CI form
python3 $S/dump_surfaces_xlsx.py --xlsx docs/EXECUTION_SURFACES.xlsx --out docs/execution_surfaces.yaml     # recover a spec from a hand-made workbook (once)
```

**What it writes.** `wrote docs/EXECUTION_SURFACES.xlsx`, then the counts the Overview formulas will show — for this page's own
workbook: `Layers: {'Parallel': 1, 'Conditional': 6, 'Divergent': 5}  rows=12` — and `verify: OK`. Exactly three surfaces per spec;
any parity word outside the three is refused at build time.

**Pitfalls.** The workbook is derived and never byte-reproducible (openpyxl stamps a time), so a `--verify` run leaves it "modified"
even when nothing changed: `git checkout docs/*.xlsx` unless the YAML changed; CI builds to `/tmp` and verifies the spec, not the
binary. Plain YAML scalars that contain `: ` must be quoted — one unparsable spec was pushed in this project (§9).

**In CloudBQ.** Three specs: pass 1 (lanes A/B/C, layers L0–L17, remediation R01–R53), pass 2 (surfaces N/Q/W for the L2 tiers), and
this page's tooling surfaces (D/C/B). The parallel lane of pass 1 — the layers Parallel across all three scenarios — is what held
whichever orchestrator was chosen. **Prospective.** A new scenario is a new column, not a new document: add the column's cells, rebuild,
and the Overview tells you how much of the pipeline it inherits for free.

### 4.5 "Run a generator, commit what changed" — `regen-workflow`

**Problem.** Derived files (an index, a tree, a workbook) go stale the moment a human forgets step 6, 7 or 8. **Solution.** One command
writes a GitHub Actions workflow that runs the generator and commits the result as a bot, with a change check, a check mode for pull
requests, a trailer the ledger skips, and a push that retries only on a race. The commit step is one shell script embedded in every
generated workflow, so a fix lands once.

```bash
S=.claude/skills/regen-workflow/scripts
python3 $S/new_regen_workflow.py --emit-reusable                                   # once per repo: .github/workflows/regenerate.yml
python3 $S/new_regen_workflow.py --name "Update README index" --paths README.md \
    --run "python3 .claude/skills/regen-workflow/assets/update_readme_index.py --readme README.md --dir docs --dir notebooks --exclude 'docs/diffs/*'" \
    --on push:main --on workflow_dispatch --mode local                             # thin caller of ./.github/workflows/regenerate.yml
python3 $S/new_regen_workflow.py --name "Trees" --paths "docs/ARCHITECTURE_TREE.txt docs/architecture.manifest.json docs/architecture_tree.html" \
    --run "python3 .claude/skills/tree-f-visualizer/scripts/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html" \
    --install pyyaml                                                                # a second consumer, inline (self-contained)
python3 $S/new_regen_workflow.py --name "Workbook" --paths "docs/*.xlsx" --install "pyyaml openpyxl" --on schedule:"0 6 * * 1" --on workflow_dispatch \
    --run "python3 .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out docs/EXECUTION_SURFACES.xlsx --verify"
```

`--mode inline` (default) writes a self-contained file; `--mode local` calls `./.github/workflows/regenerate.yml` and writes it too if
it is missing; `--mode Owner/Repo@tag` calls a shared copy in another repository (pin a tag or SHA; a private host must allow access and
admits private callers only). Triggers: `push[:branches]`, `pull_request[:branches]` (check mode forced — a merge ref cannot be pushed
to), `schedule:"<cron>"`, `workflow_dispatch`. `--check` fails instead of committing. Prerequisites: Python 3.10+ and git; PyYAML is
optional and only adds a parse check of the written file.

**What it writes.** `wrote .github/workflows/<slug>.yml` (plus `wrote .github/workflows/regenerate.yml (the caller needs it; emitted
once)` in local mode). On GitHub the bot prints `No changes to commit` or `Changes:` + a stat + `pushed to <branch>`; in check mode
`::error::regeneration changed the files above — run the generator locally and commit the result` and exit 1.

**The three facts you must know.**
1. A push made with the workflow's `GITHUB_TOKEN` starts no other workflow, so the bot's commit does not run CI. Store a PAT as the
   `REGEN_TOKEN` secret when it should; the generated jobs are guarded so the bot's own commit never re-triggers a regeneration.
2. `workflow_dispatch` appears in the Actions tab only once the workflow file is on the default branch.
3. On a protected branch the bot's push is refused ("the branch did not move: not a race"): put the Actions app or the PAT's user on
   the ruleset's bypass list, or regenerate on a branch and let `pull_request` run in check mode.

**In CloudBQ.** The first consumer is the README's Documents index (`update-readme-index.yml`, on push to `main` and by hand). The
skill went through an adversarial review before the push: three critics, 33 findings with duplicates across critics, every
non-duplicate one fixed and held by 15 tests (fork pull requests, glob deletions, swallowed git errors, secrets passed to a shared
workflow, an unstated PyYAML prerequisite, among others). **Prospective.** The tree (§4.3) and the workbook (§4.4) are the next
consumers — one command each, shown above — after which steps 6, 7 and 8 of the loop never depend on a human remembering them.

### 4.6 The two agents — `.claude/agents/`

`discovery-agent` is read-only: it recovers prior know-how, probes the environment, fans out one analyst per candidate scenario with
adversarial verification and hands over a plan. `implementation-agent` executes that plan as the loop above: one block, one recipe,
one commit, then ledger, tree, workbook, verify. They are the loop with an operator; this page is the loop for a person.

---

## 5 · A worked example, end to end

Adding a BigQuery view `sql/deal_owner_v1.sql` with a test, in a repository that already carries the skills. Lines starting with `$`
are typed; the others are what you should see.

```bash
$ git switch -c feat/deal-owner-view && git status --short            # clean tree, or the scaffolder refuses
$ cp .claude/skills/aider-scaffold/assets/recipes/c_bigquery_compute.md .claude/skills/aider-scaffold/assets/recipes/c_deal_owner_view.md
$ $EDITOR .claude/skills/aider-scaffold/assets/recipes/c_deal_owner_view.md   # purpose, /add sql/deal_owner_v1.sql tests/test_deal_owner.py, contract, do-nots
$ $EDITOR docs/architecture.yaml                                       # sql/deal_owner_v1.sql: {scenarios: [C], layer: L7, status: proposed, role: '…', recipe: …c_deal_owner_view.md}
$ git add -A && git commit -q -m "recipe + proposed node: deal_owner_v1 view"

$ python3 .claude/skills/aider-scaffold/scripts/aider_scaffold.py .claude/skills/aider-scaffold/assets/recipes/c_deal_owner_view.md sql/deal_owner_v1.sql tests/test_deal_owner.py
aider_scaffold: cannot run aider (no LLM API key in the environment).      # ← no key: apply the recipe by hand (with a key, aider commits here)
…
$ $EDITOR sql/deal_owner_v1.sql tests/test_deal_owner.py
$ python3 -m pytest tests -q
<N> passed, 1 skipped in …s
$ git add sql/deal_owner_v1.sql tests/test_deal_owner.py
$ git commit -q -m "scenario C: deal_owner_v1 view + test" -m "Recipe: .claude/skills/aider-scaffold/assets/recipes/c_deal_owner_view.md" -m "Scaffolded-by: hand (no LLM key)"

$ sed -i 's/status: proposed, role: .deal_owner/status: new, role: \x27deal_owner/' docs/architecture.yaml   # or edit: proposed → new
$ python3 .claude/skills/tree-f-visualizer/scripts/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html
$ $EDITOR docs/execution_surfaces.yaml                                  # a Layers row or a Pipeline steps row for the view, parity word, equality check
$ python3 .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out docs/EXECUTION_SURFACES.xlsx --verify
wrote docs/EXECUTION_SURFACES.xlsx
Layers: {'Parallel': …, 'Conditional': …, 'Divergent': …}  rows=…  (what the Overview formulas will show)
Pipeline steps: {…}  rows=…
verify: OK
$ git add docs && git commit -q -m "docs: deal_owner_v1 in the tree and the lane workbook"

$ python3 .claude/skills/aider-scaffold/scripts/diff_ledger.py
ledger +0029-<sha>-recipe-proposed-node-deal-owner-v1-view.patch
ledger +0030-<sha>-scenario-c-deal-owner-v1-view-test.patch
ledger +0031-<sha>-docs-deal-owner-v1-in-the-tree-and-the-lane-wor.patch
diff_ledger: 3 patch(es) appended to docs/diffs/INDEX.md
$ git add docs/diffs && git commit -q -m "docs: diff ledger update"

$ # replay what CI will run, from a clean clone
$ git clone -q . /tmp/replay && cd /tmp/replay && python3 -m pytest tests -q && \
  python3 .claude/skills/tree-f-visualizer/scripts/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html --check && \
  python3 .claude/skills/aider-scaffold/scripts/diff_ledger.py --check && \
  python3 .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out /tmp/s.xlsx --verify && \
  python3 .claude/skills/regen-workflow/assets/update_readme_index.py --readme README.md --dir docs --dir notebooks --exclude 'docs/diffs/*' --check && cd - >/dev/null
<N> passed, 1 skipped …
tree_f --check: up to date
diff_ledger --check: 0 commit(s) not in docs/diffs/INDEX.md
verify: OK
README.md: unchanged
$ git push -u origin feat/deal-owner-view                                # CI "verify" goes green on the pushed head; open the PR
```

What a reviewer opens: the PR diff for the code, `docs/diffs/INDEX.md` rows 29–31 for the trail, the view's node in
`docs/architecture_tree.html` for lane and layer, and the new workbook row for the parity claim. Nothing in that list was typed twice.

---

## 6 · Bootstrapping a new repository

1. Copy the folders `.claude/skills/aider-scaffold/`, `.claude/skills/tree-f-visualizer/`, `.claude/skills/pass-sequence/`,
   `.claude/skills/regen-workflow/` (and `.claude/agents/` if you use the agents). Nothing inside needs editing.
2. Root files: `.aider.conf.yml` and `.aiderignore` from `aider-scaffold/assets/`; `CONVENTIONS.md` from
   `aider-scaffold/assets/CONVENTIONS.template.md` — the rules every block follows, read by aider on every run. Add `.aider*` history
   files to `.gitignore`.
3. `docs/architecture.yaml` with `project:`, `scenarios:`, `layers:` and the first nodes (existing files as `status: existing`); render
   the tree once (§4.3).
4. `docs/execution_surfaces.yaml` with exactly three surfaces and the first layers; build the workbook once (§4.4). Write the sequence page
   and the record from the `pass-sequence` templates when the project has a runner.
5. Start the ledger: `python3 .claude/skills/aider-scaffold/scripts/diff_ledger.py` then commit `docs/diffs/`.
6. CI: a `verify` job with `actions/checkout` (`fetch-depth: 0`), the test suite, and the five check commands of §8.
7. `python3 .claude/skills/regen-workflow/scripts/new_regen_workflow.py --emit-reusable`, then the README-index caller
   (§4.5); add `## Documents` to the README by running the index script once.
8. README: a "Tooling" paragraph pointing here, a "Verify before you push" block (§8), and this file at the root.

Python 3.10+, git and bash are the only hard requirements; `pyyaml`, `openpyxl`, `pytest` (and `nbformat` when notebooks are tested)
for the generators and tests; `aider` only when a key exists.

---

## 7 · Team conventions

- **One block, one commit.** A scaffold step never refactors neighbouring code. The ledger patch is the unit of review.
- **Trailers.** `Recipe: <path>` on every block commit; `Scaffolded-by: hand (no LLM key)` when aider did not run; aider's own
  attribution when it did; `Regenerated-by: <workflow> (<run url>)` only from the bot. Project policy may add co-author and session
  trailers; the ledger ignores them. Never put a model or tool identifier in code or generated files.
- **Parity words** are exactly `Parallel`, `Conditional`, `Divergent`; **status words** exactly `existing`, `modify`, `new`,
  `proposed`. Both builders refuse anything else.
- **Secrets never enter git.** `.env` is ignored, `.env.example` carries the names, tokens live in a secret store; scripts fail loudly
  on a placeholder value.
- **Gate before live.** Dry run first; one explicit flag opens the live path; schedulers and bots are enabled last. For the loop itself
  the single live step is the push.
- **Branch discipline.** Develop on the feature branch; the bot pushes to the branch it ran on; nobody pushes to another branch without
  asking.
- **Review.** A block gets an adversarial review before the push (independent critics, skeptics that try to refute each finding);
  every confirmed finding becomes a test or a `--check` so CI holds it afterwards.

---

## 8 · Verify before you push (cheat-sheet)

```bash
python3 -m pytest tests -q
for f in $(git ls-files '*.sh'); do bash -n "$f"; done
python3 .claude/skills/tree-f-visualizer/scripts/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html --check
python3 .claude/skills/aider-scaffold/scripts/diff_ledger.py --check
python3 .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out /tmp/surfaces.xlsx --verify
python3 .claude/skills/regen-workflow/assets/update_readme_index.py --readme README.md --dir docs --dir notebooks --exclude 'docs/diffs/*' --check
python3 tests/test_regen_workflow.py          # the regen-workflow suite without pytest
```

Expected: a passing test count, `tree_f --check: up to date`, `diff_ledger --check: 0 commit(s) not in docs/diffs/INDEX.md`,
`verify: OK`, `README.md: unchanged`, `regen-workflow OK`. The `--dir` list of the index command is per repository (CloudBQ: `docs`
and `notebooks`; IC-DBT-BQ: `docs` and `dlt-bigquery`) — each README's "Verify before you push" block carries its own, plus the
project's own checks (CloudBQ: Node, the n8n workflow builder, the deploy script's dry run), and `ci.yml` runs the identical list.

---

## 9 · What CloudBQ taught us (remediation rows U01–U09 of the tooling workbook)

| | Symptom | Cause | Fix, and where it lives |
|---|---|---|---|
| U01 | `aider_scaffold.py` exits 2 | no LLM key in the environment | the hand path with both trailers; 17 commits |
| U02 | tree check green locally, red in CI | an empty directory and a folder-named root | walker drops empty dirs, root from `project:` (8d14e0d) |
| U03 | ledger check red in CI | shallow checkout | `fetch-depth: 0` (ci.yml) |
| U04 | workbook "modified" after `--verify` | openpyxl timestamp | restore unless the YAML changed; CI builds to `/tmp` |
| U05 | a spec pushed unparsed | unquoted `: ` in a scalar; no guard per chained step | `yaml.safe_load` before write; `|| fail` per step (40e9544) |
| U06 | fork pull requests would fail at checkout | `ref: github.head_ref` | no `ref:` on the checkout (41a9634) |
| U07 | a deleted file stayed tracked | shell-expanded glob | `set -f` around staging (test) |
| U08 | every secret handed to a shared workflow | `secrets: inherit` | one named secret (610d41e) |
| U09 | generator failed without PyYAML | unstated prerequisite | optional import; install notes (610d41e) |

The pattern behind the table: every tool failed first on the surface that was *not* the author's — CI or the bot. That is the
argument for running steps 3, 5, 6, 7, 8 and 10 locally before every push, and for turning every finding into a check.

---

## 10 · FAQ

- **CI says the tree is stale but I changed no file.** You changed an annotation or added a file the walk lists. Regenerate (§4.3) and
  commit the three outputs.
- **`diff_ledger.py --check` fails.** Run the ledger, commit `docs/diffs/`, push. If it fails only in CI, the checkout is shallow.
- **`test_docs_consistency.py` fails after annotating a node.** Its `parity` word differs from the workbook's row for that layer. Use the
  workbook's word, or omit `parity` on the node.
- **The workbook shows as modified right after `--verify`.** Expected (timestamp). `git checkout docs/*.xlsx` unless you edited the YAML.
- **`aider_scaffold.py` exits 2.** No key. Apply the recipe by hand and commit with `Recipe:` and `Scaffolded-by: hand (no LLM key)`.
- **The Actions tab has no "Run workflow" button.** The workflow file is not yet on the default branch. Merge first.
- **The bot committed but CI did not run on its commit.** It pushed with `GITHUB_TOKEN`. Add a PAT as `REGEN_TOKEN` if CI should run.
- **The bot's push was refused.** Protected branch or a hook. Bypass list, or regenerate on a branch with `pull_request` in check mode.
- **A pull request from a fork failed in the regen workflow.** Regenerate the workflow file with the current skill — the checkout no
  longer names the head branch.
- **Two regen workflows write to the same branch.** Runs of one workflow are serialised per branch; different workflows are reconciled by
  the rebase-and-retry push. Chained regenerations (B reads A's output) belong in one workflow with several `--run`.

---

## 11 · Glossary

- **Block** — one building block with one recipe and one commit (a script, a view, a notebook, a document set).
- **Recipe** — the markdown instruction for a block (`.claude/skills/aider-scaffold/assets/recipes/<block>.md`).
- **Ledger** — `docs/diffs/`: one patch per commit and `INDEX.md`.
- **Annotations** — `docs/architecture.yaml`: what each path means (scenarios, layer, role, status, parity, recipe).
- **Surfaces** — the columns of a lane workbook: terminals, scenarios or actors that must reach the same outcome.
- **Parity** — Parallel / Conditional / Divergent, decided per row; the **parallel lane** is the set of layers Parallel on every surface.
- **Regen workflow** — a GitHub Actions workflow that runs one generator and commits what changed with a `Regenerated-by:` trailer.
- **D / C / B** — developer shell, CI check, bot commit: the three surfaces of the loop itself (`docs/EXECUTION_SURFACES_TOOLING.xlsx`).
- **Replay** — running the whole verify block from a fresh clone before pushing; what CI will see.

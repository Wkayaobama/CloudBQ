# UNIVERSAL_WORKFLOW — how a building block travels from idea to green CI, and how a team keeps it that way

This page is for anyone who will add, review or regenerate something in a repository that carries the four skills under
`.claude/skills/` — `aider-scaffold` (recipes and the diff ledger), `tree-f-visualizer`, `pass-sequence` and `regen-workflow`.
It is written for a team: every command is copy-pasteable from the repository root, every expected output is quoted, and every
claim about what the tools did in CloudBQ is checked against the git history (branch `claude/cloud-run-bigquery-pipeline-e94ziy`
at d18a95f: 42 commits between 2026-10-05 and 2026-10-16; every count below is as of that commit). The same tool files — skill
pages, scripts, references, config assets — are installed in IC-DBT-BQ; only `assets/recipes/` is per project.

**How to read it.** Five minutes: §1, §2 and §8 (the idea, the loop, and the block you run before every push). Thirty minutes:
§4 (one tool at a time) and §5 (a worked example with outputs). Reference: §6 (bootstrapping a new repository), §9 (what went
wrong here and how it was fixed), §10 (FAQ), §11 (glossary). Commands use `$EDITOR` for "open the file in your editor".

---

## 1 · The idea in four sentences

1. **The suggestion is the commit.** Every change — a person's, aider's, or a bot's — is one commit whose body says where it came
   from (`Recipe:`, `Scaffolded-by:`, `Regenerated-by:` trailers). Review happens on `git diff`, never on a chat transcript.
2. **The record is derived, never typed twice.** The patch trail (`docs/diffs/`), the architecture tree (`docs/ARCHITECTURE_TREE.txt`,
   `docs/architecture_tree.html`), the lane workbook (`docs/EXECUTION_SURFACES*.xlsx`) and the README's Documents index are all
   generated from a source you edit (`git log`, `docs/architecture.yaml`, `docs/execution_surfaces*.yaml`, the `docs/` folder).
3. **The check is automated.** CI re-runs every generator in check mode and refuses a push that skipped a regeneration. A bot runs the
   same generators in commit mode when a human should not have to.
4. **Nothing in the tools names a project.** The project's words — scenario ids, layer ids, roles, parity — live in two YAML files.
   The tool files are copied between repositories without edits (CloudBQ → IC-DBT-BQ was the probe).

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
Two layers have no step in the per-block loop because they happen once per repository: U0 (installing the skills, §6) and U9
(writing a regen workflow, §4.5). The replay (10) re-runs U3's checks from a clean clone; the workbook files it under U11 with the push.

Four things about the order:

- **The ledger (5) is drawn where its layer sits, but it is the last thing you run before the replay** — after the block commit *and*
  after the docs commit of steps 6–8 — because every commit it has not seen turns CI's `diff_ledger --check` red. §5 shows the
  real order: block → tree → workbook → docs commit → ledger → replay → push.
- **Step 6 runs after every block.** The tree lists what is on disk, so a new, renamed or deleted file changes it even when no
  annotation changed.
- **Steps 7 and 8 run only when their source changed**: a surfaces YAML, or any `*.md` under the indexed directories.
- **Step 9 runs for a block**, not for a regenerated artefact.

Steps 3, 5, 6, 7 and 8 are exactly what CI repeats, so a developer who runs them before pushing never sees a red check for a reason
they could not have seen locally.

---

## 3 · Three execution surfaces

The same loop is executed by three actors. Knowing which one you are tells you what you may write.

| Surface | Who | Runs | Writes | Never does |
|---|---|---|---|---|
| **D** developer shell | a person on a clone (aider when an LLM key is present) | every step of §2 | the recipe, the block, the annotations, the specs, the commits | push to another branch; commit a secret |
| **C** CI check | `.github/workflows/ci.yml`, job `verify`, on every push and pull request | steps 3, 5, 6, 7, 8 in `--check` / `--verify` mode, the test suite | nothing (builds to `/tmp`) | fix, commit, push |
| **B** bot commit | a regen workflow (`.github/workflows/regenerate.yml` and its callers) | one generator, then `assets/commit_if_changed.sh` | one commit as `github-actions[bot]` with a `Regenerated-by:` trailer | apply a block; run the test suite; retry a push that was refused for a non-race reason |

`docs/execution_surfaces_tooling.yaml` lays the twelve layers out per surface with the parity vocabulary of the `pass-sequence` skill
(the workbook `docs/EXECUTION_SURFACES_TOOLING.xlsx` is built from it). Reading the verdict: **one** layer is Parallel — U8, the README
index: the same script with the same arguments on all three surfaces. **Six** are Conditional — U0 install, U3 verify, U5 ledger,
U6 tree, U7 workbook, U9 workflow generation — on "same commit, regeneration run before the push, a PAT if the bot's commit must run
CI". **Five** are Divergent — U1 recipe, U2 apply, U4 commit, U10 review, U11 push — because only the developer creates, only a
person or an agent reviews, and only the bot commits unattended. Divergent is not a defect here: it names the stages where a
surface has nothing to do.

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

**Anatomy of a recipe.** Markdown, three parts, in this order:

```
# Recipe — <block>: <one line>

/add path/one.py path/two.sql                 # files aider may edit — the wrapper reads this line, so the recipe stands alone
/read-only CONVENTIONS.md other/context.sql   # read-only context; when the line is absent, CONVENTIONS.md alone

<purpose · numbered contract (inputs, outputs, idempotency rule, gate) · what not to touch · how to verify>
```

The two slash lines are instructions to the wrapper, not prose: aider sees exactly those files and nothing else.
`.claude/skills/aider-scaffold/assets/recipes/docs_universal_workflow.md` (this page's own recipe) is a short, complete example.

```bash
S=.claude/skills/aider-scaffold/scripts
# 1. write the recipe (copy an existing one and keep its shape)
$EDITOR .claude/skills/aider-scaffold/assets/recipes/<block>.md
# 2. run it — aider edits the listed files and auto-commits; the tree must be clean first
python3 $S/aider_scaffold.py .claude/skills/aider-scaffold/assets/recipes/<block>.md path/to/file.py path/to/other.sql
python3 $S/aider_scaffold.py <recipe> <files> --dry-run        # show the edits, write nothing
```

**What it writes.** With a key: one commit per aider edit, author `<you> (aider)`, trailer `Recipe: <recipe path>` (the wrapper passes
aider a `--commit-prompt` that asks for it; `.aider.conf.yml` turns on auto-commits and attribution); then the ledger (§4.2) runs.
Without a key the wrapper prints the recipe and then everything you need for the hand path — the output has this shape:

```
aider_scaffold: cannot run aider (no LLM API key in the environment).

Recipe .claude/skills/aider-scaffold/assets/recipes/<block>.md:
------------------------------------------------------------------------
<the recipe, verbatim>
------------------------------------------------------------------------
Files: <the /add files and the files you named>
Read-only context: <the /read-only files, or CONVENTIONS.md>
Command that would run:
  /…/aider --yes-always --no-stream --no-check-update --no-analytics --message-file <recipe> --commit-prompt … --read … <files>

Apply the recipe by hand, then:
  git commit -m '<summary>' -m 'Recipe: <recipe path>' -m 'Scaffolded-by: hand (no LLM key)'
  python3 /…/.claude/skills/aider-scaffold/scripts/diff_ledger.py --ledger docs/diffs
```

and the exit code is 2. Copy the two commands it prints — they already carry the right recipe path — so the ledger row names the
same recipe either way (only its `aider` column differs: yes or no).

**Pitfalls.** The wrapper refuses a dirty tree (`--allow-dirty` exists but defeats "one commit, one suggestion"). A recipe must be
self-contained: aider sees only the recipe, the `/add` files and the `/read-only` files (default `CONVENTIONS.md`). Keys are read from
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, or `AIDER_MODEL` / `--model` with
its own key.

**In CloudBQ.** aider never answered: no key was present in the build environment. Twelve recipes exist (this page adds a
thirteenth). 17 commits carry `Scaffolded-by: hand (no LLM key)`; 13 of them also carry a `Recipe:` trailer (11 naming a recipe
file — the hot-score ports, the deploy step runner, the n8n workflows, the function's idempotency, the BigQuery compute lane, the
write-back job, the pass-1 document set, the tooling — and two naming `docs/discovery/pass_sequence_port.md` and the pass-sequence
skill page). The four earliest tooling commits (8830ca2, 4fbbb49, 63359b6, 9c4eced) carry `Scaffolded-by:` alone; their ledger rows
read `hand (no LLM key)` in the recipe column. Three later blocks — the notebook witness (e88c27a), the L2 tiers (fe9efe5), the
GitHub Actions skill (41a9634) — have recipe files named in `docs/architecture.yaml` but no trailer in their commits, and six more
commits after 2026-10-14 (8d14e0d, 574e954, 9b100f0, 40e9544, de6f286, 610d41e) carry no trailer either, so the ledger's recipe
column reads `—` for rows 19–27. That gap is the first thing a reviewer should ask about; this page's own commit (9b3342a) closes it
for itself with both trailers. **What a key would have added.** Finer patches (one per aider edit instead of one per block),
`aider` = yes in the ledger, and the recipe text as the literal instruction that produced the diff — the review question becomes
"did the recipe say this?" instead of "did the author say this?".

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

**What it writes.** `ledger +NNNN-<sha>-<slug>.patch` per new commit, then `diff_ledger: N patch(es) appended to docs/diffs/INDEX.md`;
when there is nothing to add, `diff_ledger: nothing new`. The row: `n · sha · date · author · aider (yes/no) · recipe · files · +/− ·
patch`. `--check` prints `diff_ledger --check: 0 commit(s) not in docs/diffs/INDEX.md` when current, otherwise `missing: <sha> <subject>`
lines and exit 1.

**What it skips, on purpose.** Commits that touch only `docs/diffs/` (otherwise `--check` could never pass) and commits carrying a
`Regenerated-by:` trailer (a bot's regenerated files are not a suggestion). The INDEX.md header states both rules and is rewritten when
that text changes.

**Pitfalls.** CI needs the whole history: `actions/checkout` with `fetch-depth: 0`. Run the ledger as the *last* local step, after
the block commit and the docs commit, and commit it — a push without it is red. The patches are excluded from the architecture tree
(`exclude: ['*.patch']`).

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

A node, quoted from `docs/architecture.yaml` as it stands (the words for `status` and `parity` are validated; anything else stops
the build):

```yaml
nodes:
  sql/deal_tiers_apply.sql: {scenarios: [C], layer: L7, status: new, parity: Parallel, role: 'Pass 2 scheduled MERGE: deal_tiers_v1 → deal_tiers (IS DISTINCT FROM, previous_tier, last_changed_at) + history rows for this run''s changes; idempotent', recipe: .claude/skills/aider-scaffold/assets/recipes/c_l2_deal_tiers.md, layers: [L7, L13, L15]}
```

`layers:` (optional) lists every layer the block touches; its first entry is the primary layer whose workbook row the `parity` word
must match. A single `layer:` is enough for most blocks. The rule, enforced by `tests/test_docs_consistency.py`: **a node's `parity`
is the word `docs/execution_surfaces.yaml` gives for the node's first layer (here L7 → Parallel), or the key is omitted.** The same
test requires every `new`/`modify` node under a scenario directory (`sql/`, `scoring/`, `tests/`, …) to name an existing recipe.

**What it writes.** The three files; `--check` prints `tree_f --check: up to date`, or `tree_f --check: stale: <files>` and exit 1.
The HTML has scenario and status chips, a path filter, a details panel and "Copy as tree /f" (byte-identical to the text file). The
volume serial in the header is derived from the content, so an unchanged tree renders byte-identically.

**Pitfalls.** Status words: `existing | modify | new | proposed`. A `proposed` node is the way to show a plan before the file exists —
flip it to `new` in the commit that creates the file. The walker excludes everything `.gitignore` matches (`--no-gitignore` turns that
off) and drops empty directories, so a fresh clone reproduces the render (that was a CI-only failure once, see §9). Annotating a layer-L0
block `Parallel` when the workbook rates L0 `Divergent` fails the suite — this page's own first commit did exactly that.

**In CloudBQ.** 92 annotated nodes across lanes A/B/C and layers L0–L17 (this page adds three); 85 of them name a recipe (the seven
without are generated outputs, the recipes folder, the ledger, `.gitignore` and `docs/discovery/`); regenerated and checked on every
commit; the ledger patches excluded. The tree was bookkeeping — a record that every block has a lane and a layer — not a design input
to the scoring arithmetic. **Prospective.** Publish `docs/architecture_tree.html` as an artifact for a design review: the chips answer
"what does lane B need that A does not?" without a slide. The tree is also the next regen-workflow consumer (§4.5): its output is
byte-reproducible, so a bot can own step 6.

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
python3 $S/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out /tmp/surfaces.xlsx --verify     # CI form, and the form for a routine check
```

Recovering a spec from a workbook someone built by hand is a one-off, outside the routine block (it would overwrite the committed
source here): `dump_surfaces_xlsx.py --xlsx <workbook> --out /tmp/recovered.yaml`, then
`build_surfaces_xlsx.py --spec /tmp/recovered.yaml --out /tmp/roundtrip.xlsx --compare <workbook>` proves the recovered spec rebuilds it.

**The spec's shape** (format reference: `.claude/skills/pass-sequence/references/surfaces-spec.md`; `docs/execution_surfaces_tooling.yaml`
is a complete, short example to copy). Exactly three surfaces, any ids; one `motions` entry per surface; `steps`, `remediation` and
`equality_checks` may start empty:

```yaml
title: "<project> — <what the three columns are>"
verdict: |
  One paragraph: what is Parallel, what is Conditional and on what, what is Divergent and why.
legend: |
  Legend: Parity colours — green Parallel, yellow Conditional, orange Divergent. Layers …; Source: branch <b> at <commit>.
surfaces: {A: "A · <label>", B: "B · <label>", C: "C · <label>"}
motions:
  - {motion: "A · <label>", acquire: "…", ubuntu: "<runtime>", driver: "…", state: "…", assessment: "…"}
layers:                      # one row per layer id, fixed before cells are written
  - {id: L7, layer: "Load → MERGE", A: "…", B: "…", C: "…", parity: Parallel, diverges: "", remediation: "", verified: "…"}
steps:                       # the operator's sequence; "7b" ids keep numbering stable
  - {n: 7, step: apply, gate: "LIVE DDL", A: "…", B: "…", C: "…", parity: Divergent, artefact: "…", notes: "…"}
remediation:
  - {id: R01, symptom: "…", layer: L7, surfaces: "A B C", cause: "…", fix: "…", verified: "…"}
equality_checks:
  - {stage: "after apply", compare: "…", A: "…", BC: "…", expected: "…"}
```

**What it writes.** `wrote docs/EXECUTION_SURFACES.xlsx`, then one line per sheet with the counts the Overview formulas will show —
for this page's own workbook `Layers: {'Parallel': 1, 'Conditional': 6, 'Divergent': 5}  rows=12  (what the Overview formulas will show)`
and `Pipeline steps: {'Parallel': 1, 'Conditional': 5, 'Divergent': 5}  rows=11  (what the Overview formulas will show)` — and
`verify: OK`. The builder refuses a fourth surface (`exactly three surfaces are expected`) and any parity word outside the three.

**Pitfalls.** The workbook is derived and never byte-reproducible (openpyxl stamps a time), so a `--verify` run into `docs/` leaves it
"modified" even when nothing changed: build to `/tmp` for a check, build into `docs/` only when the YAML changed, and otherwise
`git checkout docs/*.xlsx`. The same fact keeps the workbook off the bot surface (§4.5). Plain YAML scalars that contain `: ` must be
quoted — one unparsable spec was pushed in this project (§9).

**In CloudBQ.** Three specs: pass 1 (lanes A/B/C, layers L0–L17, remediation R01–R53; `Layers 4/4/10, steps 2/5/6`), pass 2
(surfaces N/Q/W for the L2 tiers; `Layers 0/6/9, steps 2/6/4`), and this page's tooling surfaces (D/C/B; `1/6/5, 1/5/5`). The parallel
lane of pass 1 — the layers Parallel across all three scenarios — is what held whichever orchestrator was chosen. **Prospective.** A new
scenario is a new column, not a new document: add the column's cells, rebuild, and the Overview tells you how much of the pipeline it
inherits for free.

### 4.5 "Run a generator, commit what changed" — `regen-workflow`

**Problem.** Derived files (an index, a tree) go stale the moment a human forgets step 6 or 8. **Solution.** One command writes a
GitHub Actions workflow that runs the generator and commits the result as a bot, with a change check, a check mode for pull requests,
a trailer the ledger skips, and a push that retries only on a race. The commit step is one shell script embedded in every generated
workflow, so a fix lands once.

```bash
S=.claude/skills/regen-workflow/scripts
python3 $S/new_regen_workflow.py --emit-reusable                                   # once per repo: .github/workflows/regenerate.yml
python3 $S/new_regen_workflow.py --name "Update README index" --paths README.md \
    --run "python3 .claude/skills/regen-workflow/assets/update_readme_index.py --readme README.md --dir docs --dir notebooks --exclude 'docs/diffs/*'" \
    --on push:main --on workflow_dispatch --mode local                             # thin caller of ./.github/workflows/regenerate.yml
python3 $S/new_regen_workflow.py --name "Trees" --paths "docs/ARCHITECTURE_TREE.txt docs/architecture.manifest.json docs/architecture_tree.html" \
    --run "python3 .claude/skills/tree-f-visualizer/scripts/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html" \
    --install pyyaml                                                                # a second consumer, inline (self-contained)
```

The workbook is **not** a bot job: its bytes differ on every build (§4.4), so a scheduled rebuild would commit a changed file every
time. Rebuild it locally when the YAML changes; CI verifies the spec.

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
skill went through an adversarial review before the push; its test file grew from 13 tests (41a9634) to 15 (610d41e), each new test
holding one review finding — fork pull requests at checkout, glob deletions, a swallowed git error, one named secret instead of
`secrets: inherit`, an unstated PyYAML prerequisite. The review record itself is not kept in the repository; the tests are.
**Prospective.** The tree (§4.3) is the next consumer — one command, shown above — after which step 6 of the loop never depends on a
human remembering it.

### 4.6 The two agents — `.claude/agents/`

`discovery-agent` is read-only: it recovers prior know-how, probes the environment, fans out one analyst per candidate scenario with
adversarial verification and hands over a plan. `implementation-agent` executes that plan as steps 1–7 and 10–11 of the loop: one
block, one recipe, one commit, then ledger, tree, workbook, verify. Its definition predates the README index and the regen workflows
(step 8 and U9) and does not run them; add those when you use it.

---

## 5 · A worked example, end to end

Adding a BigQuery view `sql/deal_owner_v1.sql` with a test, in a repository that already carries the skills. Lines starting with `$`
are typed; the others are what you should see. Counts such as `<N>` depend on the project.

```bash
$ git switch -c feat/deal-owner-view && git status --short            # clean tree, or the scaffolder refuses
$ cp .claude/skills/aider-scaffold/assets/recipes/c_bigquery_compute.md .claude/skills/aider-scaffold/assets/recipes/c_deal_owner_view.md
$ $EDITOR .claude/skills/aider-scaffold/assets/recipes/c_deal_owner_view.md   # purpose, /add sql/deal_owner_v1.sql tests/test_deal_owner.py, contract, do-nots
$ $EDITOR docs/architecture.yaml   # add: sql/deal_owner_v1.sql: {scenarios: [C], layer: L7, status: proposed, parity: Parallel, role: 'latest owner per deal', recipe: .claude/skills/aider-scaffold/assets/recipes/c_deal_owner_view.md}
$ git add -A && git commit -q -m "recipe + proposed node: deal_owner_v1 view"

$ python3 .claude/skills/aider-scaffold/scripts/aider_scaffold.py .claude/skills/aider-scaffold/assets/recipes/c_deal_owner_view.md
aider_scaffold: cannot run aider (no LLM API key in the environment).      # ← no key: apply the recipe by hand (with a key, aider commits here)
…
Apply the recipe by hand, then:
  git commit -m '<summary>' -m 'Recipe: .claude/skills/aider-scaffold/assets/recipes/c_deal_owner_view.md' -m 'Scaffolded-by: hand (no LLM key)'
  python3 /…/.claude/skills/aider-scaffold/scripts/diff_ledger.py --ledger docs/diffs
$ $EDITOR sql/deal_owner_v1.sql tests/test_deal_owner.py
$ python3 -m pytest tests -q
<N> passed, 1 skipped in …s                                               # 1 skipped (duckdb); 3 skipped on a machine without node
$ git add sql/deal_owner_v1.sql tests/test_deal_owner.py
$ git commit -q -m "scenario C: deal_owner_v1 view + test" -m "Recipe: .claude/skills/aider-scaffold/assets/recipes/c_deal_owner_view.md" -m "Scaffolded-by: hand (no LLM key)"

$ sed -i '/^  sql\/deal_owner_v1.sql:/ s/status: proposed/status: new/' docs/architecture.yaml   # the file exists now: proposed → new (or edit the node by hand)
$ python3 .claude/skills/tree-f-visualizer/scripts/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html
$ $EDITOR docs/execution_surfaces.yaml   # L7 already has a Layers row; add a Pipeline steps row (id 7b) only if the view is a new operator step; the node's parity is L7's word, Parallel
$ python3 .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out docs/EXECUTION_SURFACES.xlsx --verify
wrote docs/EXECUTION_SURFACES.xlsx
Layers: {'Parallel': …, 'Conditional': …, 'Divergent': …}  rows=…  (what the Overview formulas will show)
Pipeline steps: {…}  rows=…  (what the Overview formulas will show)
verify: OK
$ git add docs && git commit -q -m "docs: deal_owner_v1 in the tree and the lane workbook"

$ python3 .claude/skills/aider-scaffold/scripts/diff_ledger.py              # last local step: after the block commit and the docs commit
ledger +NNNN-<sha>-recipe-proposed-node-deal-owner-v1-view.patch
ledger +NNNN-<sha>-scenario-c-deal-owner-v1-view-test.patch
ledger +NNNN-<sha>-docs-deal-owner-v1-in-the-tree-and-the-lane-wor.patch
diff_ledger: 3 patch(es) appended to docs/diffs/INDEX.md
$ git add docs/diffs && git commit -q -m "docs: diff ledger update"

$ # step 9 — review before the push: a second reader (a colleague or the review agents) tries to refute the block; every confirmed
$ #          finding becomes a test or a --check, then back to step 3. No document was added, so step 8 (the README index) is a
$ #          no-op here — the replay below proves it with "README.md: unchanged".

$ # step 10 — replay what CI will run, from a clean clone
$ rm -rf /tmp/replay && git clone -q . /tmp/replay && cd /tmp/replay && python3 -m pytest tests -q && \
  python3 .claude/skills/tree-f-visualizer/scripts/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html --check && \
  python3 .claude/skills/aider-scaffold/scripts/diff_ledger.py --check && \
  python3 .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out /tmp/s.xlsx --verify && \
  python3 .claude/skills/regen-workflow/assets/update_readme_index.py --readme README.md --dir docs --dir notebooks --exclude 'docs/diffs/*' --check && \
  echo REPLAY-OK; cd - >/dev/null
<N> passed, 1 skipped …
tree_f --check: up to date
diff_ledger --check: 0 commit(s) not in docs/diffs/INDEX.md
wrote /tmp/s.xlsx
Layers: {…}  rows=…  (what the Overview formulas will show)
Pipeline steps: {…}  rows=…  (what the Overview formulas will show)
verify: OK
README.md: unchanged
REPLAY-OK
$ git push -u origin feat/deal-owner-view                                # step 11: CI "verify" goes green on the pushed head; open the PR
```

After the merge to `main`, surface B runs for the first time: `update-readme-index.yml` executes the same index command and prints
`No changes to commit`, because you refreshed the index yourself — that is what Parallel means in §3. Had you forgotten, it would have
committed the fix as `github-actions[bot]` with a `Regenerated-by:` trailer, and the ledger would have skipped that commit.

What a reviewer opens: the PR diff for the code, the three new rows of `docs/diffs/INDEX.md` for the trail, the view's node in
`docs/architecture_tree.html` for lane and layer, and the workbook row for the parity claim. Nothing in that list was typed twice.

---

## 6 · Bootstrapping a new repository

1. Copy the folders `.claude/skills/aider-scaffold/`, `.claude/skills/tree-f-visualizer/`, `.claude/skills/pass-sequence/`,
   `.claude/skills/regen-workflow/` (and `.claude/agents/` if you use the agents). Nothing inside needs editing; delete the recipes
   that belong to the source project.
2. Root files — note the rename (the assets carry no leading dot):
   ```bash
   cp .claude/skills/aider-scaffold/assets/aider.conf.yml .aider.conf.yml
   cp .claude/skills/aider-scaffold/assets/aiderignore   .aiderignore
   cp .claude/skills/aider-scaffold/assets/CONVENTIONS.template.md CONVENTIONS.md   # then edit: the rules every block follows, read by aider on every run
   printf '.aider/\n.aider*.history*\n' >> .gitignore
   ```
3. `docs/architecture.yaml` — start from this skeleton, add the existing files as `status: existing`, render once (§4.3):
   ```yaml
   project: <name>
   exclude: ['*.patch']            # the ledger's patches are listed in docs/diffs/INDEX.md, not in the tree
   scenarios: {A: "<label>", B: "<label>", C: "<label>"}
   layers: {L0: "<label>"}
   nodes:
     README.md: {scenarios: [A, B, C], layer: L0, status: existing, role: 'entry page'}
   ```
4. `docs/execution_surfaces.yaml` — the shape in §4.4 (exactly three surfaces; `docs/execution_surfaces_tooling.yaml` is a copyable
   example); build the workbook once. Write the sequence page and the record from the `pass-sequence` templates when the project has a
   runner.
5. Start the ledger: `python3 .claude/skills/aider-scaffold/scripts/diff_ledger.py` then commit `docs/diffs/`.
6. CI — copy this `verify` job and append your project's own checks (`bash -n`, `node --check`, dry runs):
   ```yaml
   name: offline checks
   on: [push, pull_request]
   jobs:
     verify:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v7
           with: { fetch-depth: 0 }          # the ledger check walks the whole history
         - uses: actions/setup-python@v7
           with: { python-version: "3.12" }
         - run: pip install pyyaml openpyxl pytest
         - run: python -m pytest tests -q
         - run: python .claude/skills/tree-f-visualizer/scripts/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html --check
         - run: python .claude/skills/aider-scaffold/scripts/diff_ledger.py --check
         - run: python .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out /tmp/surfaces.xlsx --verify
         - run: python .claude/skills/regen-workflow/assets/update_readme_index.py --readme README.md --dir docs --exclude 'docs/diffs/*' --check
   ```
   These are the four generator checks of §8 plus the test suite.
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
  trailers; the ledger ignores them.
- **Parity words** are exactly `Parallel`, `Conditional`, `Divergent`; **status words** exactly `existing`, `modify`, `new`,
  `proposed`. Both builders refuse anything else. A node's `parity` equals the word of its first layer's row in
  `docs/execution_surfaces.yaml`, or is omitted; a `new`/`modify` node under a scenario directory names an existing recipe
  (`tests/test_docs_consistency.py` checks both).
- **Secrets never enter git.** `.env` is ignored, `.env.example` carries the names, tokens live in a secret store; scripts fail loudly
  on a placeholder value.
- **Gate before live.** Dry run first; one explicit flag opens the live path; schedulers and bots are enabled last. For the loop itself
  the single live step is the push.
- **Branch discipline.** Develop on the feature branch; the bot pushes to the branch it ran on; nobody pushes to another branch without
  asking.
- **Review.** A block gets an adversarial review before the push (independent critics, skeptics that try to refute each finding);
  every confirmed finding becomes a test or a `--check` so CI holds it afterwards.
- This page and the generated files carry no model or tool identifiers (a rule of this page's recipe, not of the tools).

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
`wrote /tmp/surfaces.xlsx` + the two count lines + `verify: OK`, `README.md: unchanged`, `regen-workflow OK`. The `--dir` list of the
index command is per repository (CloudBQ: `docs` and `notebooks`; IC-DBT-BQ: `docs` and `dlt-bigquery`). Each README's "Verify before
you push" block carries its own list plus the project's checks (CloudBQ: Node, the n8n workflow builder, the deploy script's dry run);
`ci.yml` runs the same generator checks and the full test suite with `python -m pytest tests -q`. Build the workbook to `/tmp` in
that block, as here — a `--out docs/…xlsx` leaves the binary modified (§9, U04).

---

## 9 · What CloudBQ taught us (remediation rows U01–U09 of the tooling workbook)

| | Symptom | Cause | Fix, and where it lives |
|---|---|---|---|
| U01 | `aider_scaffold.py` exits 2 | no LLM key in the environment | the hand path with both trailers; 17 commits |
| U02 | tree check green locally, red in CI | an empty directory and a folder-named root | walker drops empty dirs, root from `project:` (8d14e0d) |
| U03 | ledger check red in CI | shallow checkout | `fetch-depth: 0` (ci.yml) |
| U04 | workbook "modified" after `--verify` | openpyxl timestamp | build to `/tmp` for a check; into `docs/` only when the YAML changed |
| U05 | a spec pushed unparsed; CI red at the next run | unquoted `: ` in a plain scalar | quote it (40e9544); build with `--verify` before committing — the builder's `yaml.safe_load` is the parse check |
| U06 | a fork pull request would have failed at checkout | `ref: github.head_ref` in a draft | caught in the pre-push review; 41a9634 never emitted `ref:` (test_inline_workflow_shape) |
| U07 | a deleted file stayed tracked | shell-expanded glob | `set -f` around staging (test_commit_step_globs_stage_deletions) |
| U08 | every secret handed to a shared workflow | `secrets: inherit` | one named secret (610d41e) |
| U09 | generator failed without PyYAML | unstated prerequisite | optional import; install notes (610d41e) |

The pattern behind the table: every tool failed first on the surface that was *not* the author's — CI or the bot. That is the
argument for running steps 3, 5, 6, 7, 8 and 10 locally before every push, and for turning every finding into a check.

---

## 10 · FAQ

- **`aider_scaffold.py` refuses: the tree is dirty.** Commit or stash first; `--allow-dirty` exists but folds your edits into the
  suggestion and breaks "one commit, one suggestion".
- **`aider_scaffold.py` exits 2.** No key. Apply the recipe by hand and run the two commands it printed (`Recipe:` and
  `Scaffolded-by: hand (no LLM key)` trailers, then the ledger).
- **CI says the tree is stale but I changed no annotation.** You added, renamed or deleted a file the walk lists. Regenerate (§4.3) and
  commit the three outputs.
- **`diff_ledger.py --check` fails.** Run the ledger, commit `docs/diffs/`, push. If it fails only in CI, the checkout is shallow.
- **`test_docs_consistency.py` fails after annotating a node.** Either its `parity` differs from the workbook's row for its first
  layer (use that word, or omit `parity`), or a `new`/`modify` node under a scenario directory names no recipe or a recipe file that
  does not exist (write the recipe first, §4.1).
- **The workbook shows as modified right after `--verify`.** Expected (timestamp). `git checkout docs/*.xlsx` unless you edited the YAML;
  check to `/tmp` next time.
- **`build_surfaces_xlsx: exactly three surfaces are expected`.** A spec has two or four ids under `surfaces:`; the sheets have three
  surface columns. Merge or split lanes, or start a second spec (as pass 2 did with N/Q/W).
- **`ModuleNotFoundError: No module named 'yaml' / 'openpyxl' / 'pytest'`.** `pip install pyyaml openpyxl pytest` (CI's install line
  does the same).
- **`git clone … /tmp/replay` says the destination exists.** `rm -rf /tmp/replay` first (§5 does), or clone into `$(mktemp -d)`.
- **The Actions tab has no "Run workflow" button.** The workflow file is not yet on the default branch. Merge first.
- **The bot committed but CI did not run on its commit.** It pushed with `GITHUB_TOKEN`. Add a PAT as `REGEN_TOKEN` if CI should run.
- **The bot's push was refused.** Protected branch or a hook. Bypass list, or regenerate on a branch with `pull_request` in check mode.
- **I wrote a regen workflow by hand with `ref: github.head_ref` on the checkout and fork pull requests fail.** Drop the `ref:`; the
  generated workflows never set one (the event's default ref is the merge ref on `pull_request`).
- **Two regen workflows write to the same branch.** Runs of one workflow are serialised per branch; different workflows are reconciled by
  the rebase-and-retry push. Chained regenerations (the second reads the first's output) belong in one workflow with several `--run`.

---

## 11 · Glossary

- **Block** — one building block with one recipe and one commit (a script, a view, a notebook, a document set).
- **Recipe** — the markdown instruction for a block (`.claude/skills/aider-scaffold/assets/recipes/<block>.md`): `/add`, `/read-only`, contract.
- **Ledger** — `docs/diffs/`: one patch per commit and `INDEX.md`.
- **Annotations** — `docs/architecture.yaml`: what each path means (scenarios, layer, role, status, parity, recipe).
- **Surfaces** — the columns of a lane workbook: terminals, scenarios or actors that must reach the same outcome.
- **Parity** — Parallel / Conditional / Divergent, decided per row; the **parallel lane** is the set of layers Parallel on every surface.
- **Regen workflow** — a GitHub Actions workflow that runs one generator and commits what changed with a `Regenerated-by:` trailer.
- **D / C / B** — developer shell, CI check, bot commit: the three surfaces of the loop itself (`docs/EXECUTION_SURFACES_TOOLING.xlsx`).
- **Replay** — running the whole verify block from a fresh clone before pushing, ending in `REPLAY-OK`; what CI will see.

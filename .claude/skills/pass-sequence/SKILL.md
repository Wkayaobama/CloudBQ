---
name: pass-sequence
description: Produce the documentation set that keeps a gated pipeline at parity across its execution surfaces or candidate scenarios — the ordered sequence page, the surfaces record, and the Excel lane workbook (Layers · Pipeline steps · Remediation · Equality checks with live parity counts) built from a YAML spec. Use when adding a pass or a scenario, comparing lanes, asked "which lane is idempotent / parallel", or when a probe result must enter the record. Docs only; it never changes pipeline code.
---

# pass-sequence

A deployment reaches parity across surfaces not because of the code but because of a method: one
script (or one command sequence) is the execution surface, gates open inline after a dry run,
checkpoints are read back from shared truth, the one local state is named, and a **documentation
set is produced in a fixed order** every time a pass or a scenario is added. This skill produces
that set. Read `references/pattern.md` once for the why; the rest of this file is the how.

Four artefacts, always in this sequence, because each feeds the next:

| # | Artefact | Role | Source of truth |
|---|---|---|---|
| 1 | `docs/PASS{N}_SEQUENCE.md` | the recipe: commands in order, look/edit at each stage, the branch point, evidence | the runner or deploy script + what the operator actually ran |
| 2 | `docs/EXECUTION_SURFACES.md` | the record: motions, parity vocabulary, dated timeline divergence → observation → fix (commit), per-surface operations, probe, open items | git log + operator logs |
| 3 | `docs/EXECUTION_SURFACES.xlsx` from `docs/execution_surfaces.yaml` | the audit: Layers, Pipeline steps, Remediation, Equality checks with live parity formulas | the YAML spec (edit it, rebuild) |
| 4 | a run sheet (optional motion) | the sequential motion: one cell per step, LIVE cells behind a confirm switch | the same spec's steps |

Docs only. A documentation pass never changes pipeline code to fit the documentation; the only
non-markdown edit it may make is a usage comment (a script header). A missing fact (a step's
output, an id, a count) is obtained by running the step or asking the operator — never composed.
Evidence pasted into the record is verbatim operator output with its date and target system.

## What "surfaces" means in a given project

The columns A/B/C of every sheet are whatever the project must keep equivalent:

- **execution surfaces** of one pipeline (mr-load: notebook / terminal / Cloud Shell), or
- **candidate scenarios** for the same outcome (CloudBQ: Cloud Run function / n8n on Cloud Run /
  BigQuery compute + remote JS). Then a *motion* is how a scenario acquires code, runs, and keeps
  state, and the Overview's "Ubuntu" column reads as *runtime* — say so in the legend.

The layer list is the project's fixed decomposition of the execution layer (mr-load: L0 acquire …
L15 materialisation; CloudBQ: L0 deploy unit … L17 cost). Fix it before writing cells; every
analyst and every sheet uses the same ids.

## 0 · Collect the execution layer before writing anything

- **Steps in order, with gates.** From the runner's `case` list, or the deploy script's numbered
  blocks: name, gate, dry/live pair, what the step writes. A command not in the script does not go
  in a sequence page.
- **Surfaces / scenarios.** For each: how the code is acquired, what runtime executes it, what
  drives a step, where state lives.
- **Shared truth vs local state.** What every surface reads from the same place (warehouse tables,
  the secret store, the portal of the token) versus what is per clone or per runtime.
- **What happened.** `git log --oneline` since the previous pass; pasted logs and errors; probes
  (`bq query`, a `status` output). Note the dates.
- **Branch points.** Where an operator chooses between two legitimate routes (delivery via webhook
  versus owned by the orchestrator; live versus dry) — documented, not replaced by a new tool.
- **The checkpoint's view.** What the state machine or the watermark says about the order you are
  about to document; say its limits in the docs instead of changing it.

## 1 · The sequence page — `docs/PASS{N}_SEQUENCE.md`

Start from `assets/PASS_SEQUENCE.template.md`. Keep its sections and order: preconditions; the
sequence as one copy-pasteable `bash` block with `# ── look ──` / `# ── edit ──` inserts after every
step that produces something the operator must read or change (a stage without a look command is
the gap operators hit first); the branch point with both routes and their one prerequisite each;
the produces/look table; evidence (verbatim, dated); pitfalls. Give each surface's verbs: for a
cloud deploy, `gcloud run services describe`, `gcloud scheduler jobs run`, `gcloud logging read`,
`bq query`, `curl … dry_run=1 | python3 -m json.tool`; for a terminal pass, `column -s, -t | less -S`,
`nano`, the download/upload round trip.

## 2 · The surfaces record — `docs/EXECUTION_SURFACES.md`

Start from `assets/EXECUTION_SURFACES.template.md` if absent; otherwise append. The timeline is
append-only: `When · Divergence · Observed how · Closed by` with the commit hash for every fix and
"**not implemented, awaiting consent**" for proposals the operator has not approved. Keep the parity
vocabulary exact: **Parallel** (same mechanism, same result), **Conditional** (same result under a
stated condition), **Divergent** (different mechanism; remediation makes it equivalent).

## 3 · The workbook — `docs/execution_surfaces.yaml` → `docs/EXECUTION_SURFACES.xlsx`

The YAML is the source; the workbook is built from it. Format: `references/surfaces-spec.md`.

```bash
S=.claude/skills/pass-sequence/scripts
# first time only, when a workbook exists but no spec
python3 $S/dump_surfaces_xlsx.py --xlsx docs/EXECUTION_SURFACES.xlsx --out docs/execution_surfaces.yaml
python3 $S/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out /tmp/roundtrip.xlsx --compare docs/EXECUTION_SURFACES.xlsx
# every pass: edit the YAML, rebuild, verify
python3 $S/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out docs/EXECUTION_SURFACES.xlsx --verify
```

Add per pass: a **Layer** per new operator concern, **Pipeline steps** rows (`15b`, `15c` ids keep
numbering stable), **Remediation** rows for every failure observed (symptom · layer · surfaces ·
cause · fix · verified), **Equality checks** for what to compare after each new stage, and an
Overview verdict sentence naming the pass and the commits. Parity is decided per row by the
vocabulary; the producer refuses any other word. The **parallel lane** is the set of layers whose
parity is Parallel across all columns: it is what holds whichever surface or scenario is chosen.

Recalculation: formulas are whole-column `COUNTIF` / `SUM` / `COUNTA` saved with `fullCalcOnLoad`,
so Excel and LibreOffice compute them on open. When LibreOffice recalculation is unavailable (it has
timed out in sandboxes), rely on `--verify`, which prints the values the formulas will show, and say
so in the hand-over.

## 4 · The motion (optional)

`scripts/build_run_sheet.py` generates a Polyglot `.dib` run sheet from the spec's steps for
projects that drive steps from PowerShell helpers (`Invoke-Step`, `Get-PipelineState`, …). Offer it
only when the runner has a `<step>` case list and gates; otherwise state that the motion is the
sequence page's bash block itself.

## 5 · Thread the pointers

Reference documents keep their roles and point at the sequence page instead of repeating it: the
README's "test before scheduling" paragraph, the runner's header comment, the index/structure page.

## 6 · Verify, then hand over

```bash
bash -n <runner or deploy script>                      # header comment is the only script edit
python3 -m py_compile <python entry points>
python3 $S/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out docs/EXECUTION_SURFACES.xlsx --verify
grep -rn "<old count>\|<old branch>" docs             # stale references
```

Commit the set on the working branch with a message that lists the artefacts and says
"documentation only"; push. The hand-over states: what was produced, the one limitation if any
(recalculation), what stays open awaiting consent. Never commit `.env`.

## Worked examples and templates

- `references/worked-example.md` — mr-load pass 2 (execution surfaces) and CloudBQ pass 1 (scenarios
  as lanes): produced files, counts, probes, commits. Read to calibrate depth and tone.
- `references/pattern.md` — the twenty ingredients, each with the failure it prevents, illustrated
  from both projects.
- `assets/PASS_SEQUENCE.template.md`, `assets/EXECUTION_SURFACES.template.md` — section skeletons.
- `evals/evals.json` — prompts and expected outputs for the skill-creator's eval loop.

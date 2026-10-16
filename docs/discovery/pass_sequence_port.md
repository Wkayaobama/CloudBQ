# Porting `pass-sequence` from mir-load to CloudBQ (and IC-DBT-BQ)

Date 2026-10-05. Source: `/home/user/wkayaobama/mir-load/.claude/skills/pass-sequence/` (SKILL.md, references/{pattern,surfaces-spec,worked-example}.md, assets/{PASS_SEQUENCE,EXECUTION_SURFACES}.template.md, scripts/{build_surfaces_xlsx,dump_surfaces_xlsx,build_run_sheet}.py, evals/evals.json) and the worked outputs `docs/execution_surfaces.yaml`, `docs/EXECUTION_SURFACES.md`, `docs/PASS2_SEQUENCE.md`, `docs/EXECUTION_SURFACES.xlsx`. No repository file was modified; everything produced here lives under the scratchpad `discovery/` folder.

## 0. State found on disk before this port

Both target repos already carry an **untracked, partial** copy of the skill (`?? .claude/` in `git status` of CloudBQ and IC-DBT-BQ):

```
.claude/skills/pass-sequence/
  assets/EXECUTION_SURFACES.template.md     IDENTICAL to mir-load
  assets/PASS_SEQUENCE.template.md          IDENTICAL
  references/surfaces-spec.md               IDENTICAL
  scripts/build_run_sheet.py                IDENTICAL
  scripts/build_surfaces_xlsx.py            IDENTICAL
  scripts/dump_surfaces_xlsx.py             IDENTICAL
  scripts/__pycache__/*.cpython-311.pyc     (CloudBQ only; stray, should not be committed)
```

Missing from both copies: `SKILL.md` (so the skill does not register with Claude Code at all — the directory is inert without it), `references/pattern.md`, `references/worked-example.md`, `evals/evals.json`. The six files that are present are byte-identical to the originals (`cmp`), i.e. the generic half of the skill was copied and the mr-load-specific half was (correctly) left out, but nothing replaced it.

## 1. Generic vs mr-load-specific

### 1.1 Generic — portable as-is (or with a one-word change)

| File | Why it is generic |
|---|---|
| `scripts/build_surfaces_xlsx.py` | Pure spec→xlsx renderer. Takes any `title/verdict/legend/surfaces{A,B,C}/motions/layers/steps/remediation/equality_checks/parity_meanings`. Enforces the three parity words at build time; `--verify` recomputes what the ten Overview formulas will show; `--compare` diffs values against another workbook. Nothing in it names mr-load. Two residues (see 1.3): the hard-coded Overview motion header `"Ubuntu"` and the default `PARITY_MEANING["Conditional"]` text "(… same clone for the ledger)", which the spec can override via `parity_meanings`. |
| `scripts/dump_surfaces_xlsx.py` | Inverse of the builder (xlsx→yaml). Positional; reads the five sheets. Generic. Note: it does **not** emit `parity_meanings` (the builder's optional key), so a round trip drops that override — harmless, but worth knowing. |
| `references/surfaces-spec.md` | The spec format and the parity decision rule. Examples inside are mr-load rows (L14, 15b, R21, `Invoke-Ubuntu`), and the "Conditional" bullet names mr-load conditions (same commit, same Google identity, same clone for the ledger) — the format itself is generic. |
| `assets/EXECUTION_SURFACES.template.md` | Section skeleton with `{braces}`; generic except the §4 row `Run the steps | Invoke-Step | {script} <step> | same` and the "same clone for the ledger" phrase in §1. |
| `assets/PASS_SEQUENCE.template.md` | Generic skeleton (preconditions, sequence with look/edit inserts, branch point, produces/look table, evidence, pitfalls). Mentions `Invoke-Step`, "notebook users", "the four `cloudshell` verbs" as examples only. |
| The *method* in SKILL.md §0–§6 | Collect the execution layer first → sequence page → record → yaml→xlsx → optional motion → thread pointers → verify + hand over. Docs-only rule. Evidence verbatim with date. Parity vocabulary exact. This is the portable intellectual core. |
| `references/pattern.md` §1–§20 | The 20 ingredients (one script is the surface; gates inline per live step after a dry run; checkpoints read back; shared truth vs local state; strict pass boundaries; probe closes a reconciliation; equality checks after each stage; branch points documented not tooled away; docs touch no code; commits cited; "not implemented, awaiting consent" as first-class status). Each is stated with the failure it prevents, which is exactly what makes it reusable. The *illustrations* are mr-load (`run_pass1.sh`, `pipeline_state.sh`, SQLite ledger, `deal_decisions.csv`, sandbox portal). |
| The sheet vocabulary | Overview / Layers / Pipeline steps / Remediation / Equality checks; `L##`, `R##`, `15b`-style ids; `LIVE <GATE>` gate strings; Parallel / Conditional / Divergent. |

### 1.2 mr-load-specific — must be rewritten for the port

| Item | Where | What it hard-codes |
|---|---|---|
| Skill description and triggers | `SKILL.md` front matter | "mr-load style", "IDE/Polyglot notebook vs WezTerm/WSL terminal vs Cloud Shell", `.dib` run sheet |
| The three surfaces | SKILL.md, templates, spec examples, yaml | A = zip/clone → VS Code → Polyglot notebook (PowerShell cells); B = WezTerm → Ubuntu (WSL/Docker); C = Cloud Shell. Motion columns "Acquire · **Ubuntu** · Driver · State lives in · DevOps assessment" |
| The runner and its verbs | SKILL.md §0, §1, §4, §6 | `scripts/run_pass1.sh <step>`, the `case` list as the source of steps, `MRLOAD_APPROVE_X=1`, `YES_ALL=1`, `scripts/dev/pipeline_state.sh`, `env_clinic.sh`, `gauth.sh`, `bash -n scripts/run_pass1.sh`, `pytest tests --ignore=tests/e2e` |
| PowerShell / Polyglot motion | `scripts/build_run_sheet.py` entirely; SKILL.md §4 | `Invoke-Ubuntu`, `Invoke-Step`, `Get-PipelineState`, `Invoke-NextStep`, `Invoke-Sequence`, `$ConfirmLive`, `wsl.exe -d Ubuntu-24.04`, `$RepoWsl/$RepoWin/$RepoLinux`, `WSL_UTF8` |
| Cloud Shell verbs | SKILL.md §1, PASS2_SEQUENCE.md, L14, R23, R24 | `cloudshell edit`, `cloudshell download`, ⋮ Upload → `mv`, `column -s, -t | less -S`, `nano` |
| The L-numbering and its content | yaml L0–L15 | Acquire the code / Pick the commit / Line endings & modes / Ubuntu runtime / Python+dbt provisioning / Google credentials / .env / Git safety net / Driving a step / State: ledger / Logs / Shared truth / Offline probe / Updates / Pass-2 decisions file / BQ materialisation. The CloudBQ list L0–L17 is a different decomposition (deploy unit, identity, secrets, trigger, window, scoring, shaping, MERGE, watermark, delivery, write-back, dry-run gate, replay, audit, access, concurrency, observability, cost). |
| Remediation catalogue | yaml R01–R25 | All mr-load incidents (`inspect: command not found`, CRLF, exec bits, dbt FK, ledger duplicates, stage ids of another portal, Drafts/pre-PO) |
| Worked example | `references/worked-example.md` | Pass 2 of mr-load, commits `6f38600`/`765cd01`/`6abaf18`, sandbox 49610528, the ELTA probe, counts 48→50 / 47→57 |
| Evals | `evals/evals.json` | Three prompts about `contacts-live`, `bq: command not found` on WezTerm, `ic-load` run sheet |
| The pass concept itself | everywhere | "pass N" = a numbered HubSpot load pass with a ledger. CloudBQ has no passes yet; the natural unit is the **deploy sequence** (pass 1 = first deploy + first live run + schedulers enabled) and later **scenario reconciliations**. |

### 1.3 Residues of mr-load inside the "generic" scripts (keep, document, or patch later)

1. `build_surfaces_xlsx.py` line `_header(ov, 4, ["Motion", "Acquire", "Ubuntu", "Driver", "State lives in", "DevOps assessment"])` — the motion columns are fixed. For CloudBQ the "Ubuntu" column reads as *runtime* (Cloud Run service / n8n container / BigQuery + JS runtime). Either accept the label and say so in the legend (chosen for this port — no script change, docs-only rule) or, with consent, add an optional `motion_columns:` key to the spec and have `dump_surfaces_xlsx.py` read it back.
2. Default `PARITY_MEANING` mentions "same clone for the ledger" — overridden through the spec's `parity_meanings:` key (done in the skeleton with the user's exact three sentences).
3. `verify()` asserts exactly 10 Overview formulas and Arial everywhere — fine, keep.
4. `build_run_sheet.py` is a Polyglot/PowerShell generator; it reads only `steps[]` from the spec and writes `Invoke-Step '<cmd>'` cells. It will run on the CloudBQ spec (the `step` labels were kept bare: `sa-create`, `bq-grant`, …, `deploy`, `dry-run`, `run-live`, `scheduler-create`, `probe`, `status`, `replay`) but the output is meaningless until a `deploy.sh <step>` case list and PowerShell helpers exist. Port the file unchanged; mark the motion "not applicable yet" in SKILL.md.

## 2. Port plan — `/home/user/CloudBQ/.claude/skills/pass-sequence/` (then IC-DBT-BQ)

Re-interpretation that drives every edit: the skill's **three surfaces A/B/C become the three scenarios A/B/C** of the new-deals pipeline. *Motions* = how each scenario acquires code / runs / stores state. *Layers* = the fixed list L0–L17. *Pipeline steps* = the scenario-A deploy sequence (deploy.sh order, canonical `gcloud run deploy --function` form) with the dry-run gate before every LIVE row. *Remediation* = the user's risk table. *Equality checks* = what must be identical in `hubspot.new_deals` / `hubspot.report_state` regardless of orchestrator.

Steps, in the order they should be done (all docs/skill files; no change to `main.py`, `deploy.sh`, `bigquery_schema.sql`):

1. **Keep the six identical files** already in place (`assets/*`, `references/surfaces-spec.md`, `scripts/*.py`). Delete `scripts/__pycache__/` and add `__pycache__/` is already in `.gitignore` (it is: `__pycache__/`), so a `git add .claude` will skip it — but remove it anyway for a clean tree.
2. **Write `SKILL.md`** (new, ~120 lines) with:
   - front matter `name: pass-sequence`; description rewritten: "Build the documentation set for a gated, multi-scenario data pipeline (CloudBQ new-deals style): the ordered `docs/PASS{N}_SEQUENCE.md` (every gcloud/bq command, the look commands, the dry-run gate, real probe evidence), the `docs/EXECUTION_SURFACES.md` record, the `docs/EXECUTION_SURFACES.xlsx` workbook from `docs/execution_surfaces.yaml`. Use it whenever a scenario (Cloud Run function / n8n on Cloud Run / BigQuery + remote JS + Breeze) is added or compared, a layer L0–L17 changes, someone asks for parity, a lane matrix, 'which step is missing', or wants a `bq query` probe written into the record."
   - §0 "Collect the execution layer": steps from `deploy.sh` top to bottom (the `case` list of mr-load becomes the numbered blocks 1–5 of deploy.sh plus the echoed dry-run curl); scenarios instead of surfaces; shared truth = `hubspot.report_state`, `hubspot.new_deals`, `new_deals_last_7d`, Secret Manager, the HubSpot portal 9201667; local state = none for A (scale to zero), n8n DB for B, JS runtime for C; the branch point = **delivery** (A posts to the n8n webhook vs B owns delivery vs C via Breeze) and **write-back** (only the remote-JS lane can).
   - §1 sequence page: keep the template's sections; replace look/edit verbs by `gcloud run services describe`, `gcloud scheduler jobs describe/run`, `gcloud logging read`, `bq query`, `bq show`, `curl … dry_run=1 | python3 -m json.tool`. Keep the rule "a stage without a look command is the gap operators hit first".
   - §2 record: unchanged method; timeline seeded from the user's risk table (R01 DCL quoting fixed, R02 run.invoker fixed, R03 watermark race fixed, R04 `:latest` pin, R05 deploy syntax) — each row "Closed by" cites the commit once the fixes land in `deploy.sh`; until then "**not implemented, awaiting consent**" (deploy.sh currently still uses `gcloud functions deploy --gen2`, has no `--max-instances 1 --concurrency 1`, no invoker binding, and single-quoted DCL principal — the docs state it, they do not patch it).
   - §3 workbook: same three commands; the legend sentence names L0–L17 and R01–R05.
   - §4 motion: "Not applicable until `deploy.sh` has a `<step>` case list and gates; when it does, `build_run_sheet.py` works unchanged (bare step labels are already in the spec). Alternative motion for this project: a bash run sheet or a Cloud Shell tutorial (`cloudshell launch-tutorial`)."
   - §5 pointers: `cloud_function_new_deals/README.md` "Test before scheduling" paragraph → points to the sequence page; `deploy.sh` header comment may mention the sequence page (the one permitted non-markdown edit).
   - §6 verify: `bash -n cloud_function_new_deals/deploy.sh`; `python3 -m py_compile cloud_function_new_deals/main.py`; `bq query --dry_run` on `bigquery_schema.sql` when authenticated; `build_surfaces_xlsx.py … --verify`.
3. **Write `references/pattern.md`** — keep the 20 ingredients verbatim as principles; swap the illustrations: `run_pass1.sh` → `deploy.sh` + `?dry_run=1`; `pipeline_state.sh` → `hubspot.report_state` watermark as the checkpoint; the SQLite ledger → the MERGE on `deal_id` (the Conditional here is *identity + the same report_state row*, not clone locality); sandbox portal guard → `PORTAL_ID` and `--no-allow-unauthenticated`; "a Cloud Function would fork the loader" (mr-load's declined option) → in CloudBQ the function *is* the loader, and the declined fork is **a second scorer** (n8n Code node / SQL re-implementation) unless an equality check pins it to the Python constants.
4. **Write `references/worked-example.md`** — empty of numbers until the first real run; structure ready: situation, what was produced in order, the probe that closed it (`SELECT entity, COUNT(*) … GROUP BY entity`), the question it answered ("do we need n8n to own extraction?"), numbers worth pinning (rows per entity after first run, duplicate_suspects count, day1_hot list, the two watermarks). Obtain by running, never compose — the skill's own rule.
5. **Write `evals/evals.json`** — three prompts: (a) "we deployed scenario A and ran dry_run=1 on both entities; here is the payload; produce the pass-1 set"; (b) "there is a hand-made workbook and no yaml: bootstrap and add R06 for `PERMISSION_DENIED: secretmanager.versions.access`"; (c) "compare scenario B's n8n MERGE with scenario A's after the first live run — which Equality checks apply".
6. **Seed `docs/execution_surfaces.yaml`** from the skeleton below (§4), build `docs/EXECUTION_SURFACES.xlsx` with `--verify`, start `docs/EXECUTION_SURFACES.md` from the template, and `docs/PASS1_SEQUENCE.md` from the template with the deploy sequence (rows 1–13 of the skeleton) as its bash block.
7. **Install into the personal library** `/home/user/wkayaobama/wkayaobama-skills/skills/pass-sequence/` following README: keep `SKILL.md`, `references/`, `assets/`, `scripts/`, `evals/`; reference paths through `${CLAUDE__ROOT}`; add a row to the README's "When to Use Each Skill" table ("When documenting or reconciling a gated multi-surface / multi-scenario pipeline: sequence page, surfaces record, lane workbook"); add it to the Directory Map. Project repos then carry a thin `.claude/skills/pass-sequence/` (or a copy, per the README's "copy here and commit" maintenance rule).
8. **IC-DBT-BQ second host**: the same six generic files are already there (identical, untracked). Its `SKILL.md` needs its own surfaces: A = `dlt-bigquery` CLI (`discover/load/batch/direct/sql/workflow`, `--dry-run` is the gate) from a laptop with ADC; B = the same CLI from Cloud Shell; C = StackSync workflow (Google Sheet → cascade delete/upsert). Layers reuse the fixed list where it fits (L1 identity, L2 secrets `.env`, L7 load, L11 dry-run, L12 replay, L13 audit, L14 access) and drop the HubSpot-specific ones (L4 window, L5 scoring, L8 watermark, L10 write-back). Steps = the argparse sub-commands with `batch` and `workflow --action delete` as LIVE rows.

## 3. Script run on the real mr-load spec (sandbox proof)

Command, run from `/home/user/wkayaobama/mir-load`:

```
python3 .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml \
  --out /tmp/claude-0/-home-user/ece94197-5071-5d6e-bf73-1f7ece941ed2/scratchpad/discovery/mrload_roundtrip.xlsx \
  --verify --compare docs/EXECUTION_SURFACES.xlsx
```

Exact output:

```
wrote /tmp/claude-0/-home-user/ece94197-5071-5d6e-bf73-1f7ece941ed2/scratchpad/discovery/mrload_roundtrip.xlsx
Layers: {'Parallel': 8, 'Conditional': 4, 'Divergent': 4}  rows=16  (what the Overview formulas will show)
Pipeline steps: {'Parallel': 14, 'Conditional': 7, 'Divergent': 0}  rows=21  (what the Overview formulas will show)
verify: OK
compare vs docs/EXECUTION_SURFACES.xlsx: identical values
EXIT=0
```

These counts match the worked example ("Layers 16 rows (8/4/4), Pipeline 21 rows (14/7/0)"). Output file 25,563 bytes vs the committed 25,562 — one byte of zip metadata; values identical.

Companion checks, same session:

```
dump_surfaces_xlsx.py --xlsx docs/EXECUTION_SURFACES.xlsx --out …/mrload_dump_check.yaml
  → wrote …: 16 layers, 21 steps, 25 remediations, 13 equality checks, 3 motions   EXIT=0
  → yaml.safe_load(dump) == yaml.safe_load(docs/execution_surfaces.yaml): True
build_run_sheet.py --spec docs/execution_surfaces.yaml --out …/mrload_run_check.dib --project mr-load \
  --script scripts/run_pass1.sh --helpers notebooks/mr-load-helpers.ps1 --branch-after deals-dry --branch-step ledger-export
  → wrote …: 24 pwsh cells, 26 markdown cells   EXIT=0
```

And on the CloudBQ skeleton (run from `/home/user/CloudBQ` with its own copy of the scripts):

```
wrote …/cloudbq_skeleton.xlsx
Layers: {'Parallel': 0, 'Conditional': 7, 'Divergent': 11}  rows=18  (what the Overview formulas will show)
Pipeline steps: {'Parallel': 3, 'Conditional': 4, 'Divergent': 6}  rows=13  (what the Overview formulas will show)
verify: OK
EXIT=0
dump → 18 layers, 13 steps, 5 remediations, 6 equality checks, 3 motions; skeleton round-trips through dump: True
```

Environment: Python 3.11.15, openpyxl 3.1.5, PyYAML 6.0.1. LibreOffice was not invoked (the skill says to rely on `--verify` when recalculation is unavailable; `fullCalcOnLoad` is on, so Excel/LibreOffice compute the ten formulas on open).

Scripts verdict: **all three scripts work unmodified in this sandbox; the build/verify/compare round trip on the real mr-load spec is exact (identical values, parity counts 8/4/4 and 14/7/0).**

## 4. The CloudBQ skeleton — `docs/execution_surfaces.yaml`

File: `/tmp/claude-0/-home-user/ece94197-5071-5d6e-bf73-1f7ece941ed2/scratchpad/discovery/cloudbq_execution_surfaces.skeleton.yaml` (verified build above; also returned verbatim in the structured output's `yaml_skeleton`).

Design decisions inside it:

- `surfaces.A/B/C` are the three scenarios, labelled so the Layers/Steps/Equality headers read as lanes.
- `motions` keep the producer's five columns; the "Ubuntu" header is read as *runtime* (stated in the legend).
- `layers` L0–L17 use the fixed ids/labels verbatim. Lane cells `A/B/C`, `remediation`, `verified` are `''` — to be filled from real runs. `diverges` carries the seed from the user's job matrix and risk table so the filler knows what the row is about. `parity` is provisional (the producer refuses an empty parity cell): L5–L8, L3, L4, L12 Conditional (same result when the stated condition holds — same constants, same window, same `report_state` row, same cron); the rest Divergent (different mechanism per scenario). No Parallel yet: nothing has been run on two scenarios.
- `steps` 1–13 are scenario A's deploy sequence in deploy.sh order, with the canonical `gcloud run deploy … --function new_deals_report --source …` form and the user's fixes already in the A cell (`--max-instances 1 --concurrency 1`, invoker binding, double-quoted DCL principal). LIVE gates: `deploy` (LIVE DEPLOY), `run-live` (LIVE NEW_DEALS_WRITE), `scheduler-create` (LIVE SCHEDULER_ENABLE), `replay` (LIVE REPLAY). Row 8 `dry-run` is the dry counterpart that must pass on both entities before any LIVE row below it — "dry_run=1 is the gate before enabling schedulers". `probe` (row 11) and `status` (row 12) are the look commands. B and C step cells are `''` (the sheet is scenario A's sequence; B/C get their own rows when those scenarios are built — `6b`, `6c` style ids keep numbering stable).
- `remediation` R01 DCL quoting (L1), R02 run.invoker (L14), R03 watermark race (L15), plus R04 `:latest` pin (L2) and R05 deploy syntax (L0) from the same risk table; `verified` = "user risk table 2026-10-05 (fixed)" where the user marked it fixed.
- `equality_checks`: after dry-run (payload counts), after first run-live (row counts per entity identical regardless of orchestrator), watermark per entity, hot score for one deal_id across Python/JS/SQL, duplicate flags, delivered XLSX row count.
- `parity_meanings` uses the user's exact three sentences.

## 5. Risks and open points

1. **The two partial copies are inert**: without `SKILL.md` Claude Code does not see a skill; whoever copied them must add the rewritten SKILL.md before anything triggers. They are also untracked — a `git add` will pick up CloudBQ's stray `__pycache__` unless removed (the `.gitignore` already lists `__pycache__/`, so it would be skipped, but the directory should go).
2. **Docs-only rule vs the user's fixes**: the fixes in the risk table (DCL quoting, invoker binding, `--max-instances 1 --concurrency 1`, `gcloud run deploy --function`) are *not* in `deploy.sh` on disk. The skill writes them into the sequence page and the workbook as the operator's commands and records them in the timeline as "closed by <commit>" only once the operator commits them; until then "not implemented, awaiting consent" is the honest status.
3. **"Ubuntu" column label** in the Overview is baked into the builder; accepted and explained in the legend for now. Patching the builder to read optional `motion_columns:` is a small script change that needs consent and a matching change in the dumper.
4. **`parity_meanings` is dropped by `dump_surfaces_xlsx.py`**: a bootstrap from a hand-edited workbook loses the override; re-add it after a dump (the builder falls back to the mr-load default text otherwise, which mentions "the ledger").
5. **Provisional parity words** in the skeleton: they encode expectations, not observations. Every row must be re-decided after the first run on a second scenario; the Overview counts will move.
6. **No run-sheet motion** for CloudBQ: `deploy.sh` has no `<step>` case list and no gates, so `build_run_sheet.py` output would be a skeleton pointing at a non-existent helper. Offer it only if the user later restructures `deploy.sh` into steps (a code change, needs consent).
7. **Scenario B and C evidence is zero today**: the n8n JSON on disk is delivery only (Webhook → Rows → Shape columns → XLSX → Email); scenario B's "own extraction/scoring/MERGE" and scenario C's scheduled query / remote JS do not exist yet. Their lane cells stay empty until something runs; the skill forbids composing facts.
8. **No credentials in the sandbox** (gcloud 530 unauthenticated, no LLM key, no HubSpot token): nothing in §3 touched GCP; the probe rows in the skeleton are commands to run, not evidence. aider is installed but unusable without an API key, so the skeleton was written by hand and validated by the skill's own builder.
9. **IC-DBT-BQ layer fit**: the fixed L0–L17 list is HubSpot-pipeline shaped; L4/L5/L8/L10 have no referent in a CSV→BigQuery→StackSync loader. Use the list where it fits and let the IC-DBT-BQ spec carry its own layer ids rather than forcing eighteen rows.
10. **Personal-library placement**: the wkayaobama-skills README expects `skills/<name>/SKILL.md` referenced through `${CLAUDE__ROOT}` and maintained by copying from the source project; the skill's `scripts/` paths inside SKILL.md (`S=.claude/skills/pass-sequence/scripts`) are repo-relative and should become `S=${CLAUDE__ROOT}/skills/pass-sequence/scripts` in the library copy, with the project copy keeping the relative form.

## 6. Files produced (scratchpad only)

```
/tmp/claude-0/-home-user/ece94197-5071-5d6e-bf73-1f7ece941ed2/scratchpad/discovery/
  mrload_roundtrip.xlsx                    build of the real mr-load spec (--verify OK, --compare identical)
  mrload_dump_check.yaml                   dump of docs/EXECUTION_SURFACES.xlsx; == docs/execution_surfaces.yaml
  mrload_run_check.dib                     run-sheet generator output (24 pwsh / 26 markdown cells)
  cloudbq_execution_surfaces.skeleton.yaml the CloudBQ skeleton (§4)
  cloudbq_skeleton.xlsx                    its build (--verify OK: 18 layers 0/7/11, 13 steps 3/4/6)
  cloudbq_skeleton_dump.yaml               dump of that build; round-trips
  pass_sequence_port.md                    this report
```

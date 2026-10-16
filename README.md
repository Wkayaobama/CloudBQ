# CloudBQ — new-deals pipeline, three lanes, one idempotent outcome

HubSpot deals created since the last run → `hubspot.new_deals` in BigQuery with a day-1 hot score and a duplicate flag → a weekly
report. Three candidate orchestrators are scaffolded side by side so the choice can be made on evidence:

| Lane | Where | Owns | Status |
|---|---|---|---|
| **A** Cloud Run function | `cloud_function_new_deals/` | window, score, MERGE, watermark, audit, delivery POST | code + offline tests; first deploy pending |
| **B** n8n on Cloud Run | `deploy/n8n/`, `workflows/` | B1 delivery tail (recommended) · B2 whole pipeline (generated) | manifests, scripts, generated JSON + parity test |
| **C** Hybrid | `sql/`, `writeback/` | BigQuery compute over the synced deals, Node 22 write-back, Breeze reads | SQL, scripts, job; needs the first sync run |

Shared by every lane: `scoring/` (one hot score — Python, JS, SQL — pinned by `tests/hot_score_vectors.json`), the tables in
`cloud_function_new_deals/bigquery_schema.sql` + `sql/audit_tables.sql`, and `CONVENTIONS.md`.

## Read in this order

0. **`UNIVERSAL_WORKFLOW.md`** — the team page: how a block travels recipe → commit → ledger → tree → workbook → index → CI, on
   three surfaces (developer shell, CI check, bot commit); start here before adding anything.
1. `docs/SCENARIOS.md` — the three lanes condensed and the recommendation.
2. `docs/PASS1_SEQUENCE.md` — the deploy sequence with look commands and the dry-run gate.
   `docs/RUNBOOK_CLOUD_SHELL.md` is the same sequence as a phased operator runbook for `wisekeybq`, with a check after every phase.
3. `docs/EXECUTION_SURFACES.xlsx` (built from `docs/execution_surfaces.yaml`) — the lane matrix: layers L0–L17 × lanes A/B/C,
   parity words, remediation, equality checks; the Overview counts the **parallel lane**. `docs/EXECUTION_SURFACES.md` is the record.
4. `docs/architecture_tree.html` — the architecture as an interactive `tree /f` (scenario and layer filters, lane view);
   `docs/ARCHITECTURE_TREE.txt` is the plain listing; both come from `docs/architecture.yaml`.
5. `docs/diffs/INDEX.md` — one patch per commit; every suggestion is a `git diff`.
6. `notebooks/cloudbq_deploy_and_witness.ipynb` — the same sequence as a notebook for a Vertex AI Workbench instance in the
   project, plus the SQL (schema, `hot_score_v1`, vectors, audit tables) executed and witnessed from Python; `notebooks/README.md`.
7. **Pass 2 (L2 likelihood tiers)** — `docs/PASS2_L2_TIERS.md` (evidence from the CRM, binning spec, lanes N/Q/W, dynamic storage),
   `docs/EXECUTION_SURFACES_L2.xlsx`, `scoring/deal_tiers_v1.constants.json`, `sql/deal_tiers_v1.sql` + `sql/deal_tiers_apply.sql`, `notebooks/l2_deal_tiers.ipynb`.

## Tooling (reusable, project-agnostic — also installed in IC-DBT-BQ)

- `.claude/skills/aider-scaffold/` — `aider_scaffold.py <recipe> [files]` runs a block through aider as auto-committed steps (or prints
  the recipe and exits 2 without an LLM key); `diff_ledger.py` keeps `docs/diffs/`. Recipes for every block: `assets/recipes/`.
- `.claude/skills/tree-f-visualizer/` — `tree_f.py` renders `docs/architecture.yaml` + the tree on disk as `tree /f` text, a manifest, and the HTML page.
- `.claude/skills/pass-sequence/` — the documentation method (ported from mir-load): sequence page → record → YAML → workbook.
- `.claude/skills/regen-workflow/` — `new_regen_workflow.py` writes "run a generator, commit what changed" GitHub Actions workflows for any repository
  (inline, or callers of `.github/workflows/regenerate.yml`); `update_readme_index.py` keeps the Documents index below; the ledger skips the bot's commits.
- `.claude/agents/` — `discovery-agent` and `implementation-agent` definitions.

## Verify before you push

```bash
python3 tests/test_hot_score.py && python3 tests/test_main_offline.py && python3 tests/test_n8n_code.py
for f in cloud_function_new_deals/deploy.sh sql/*.sh writeback/*.sh deploy/n8n/*.sh; do bash -n "$f"; done
node --check writeback/index.mjs && python3 workflows/src/build_workflow.py --check
python3 .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out /tmp/surfaces.xlsx --verify   # to /tmp: rebuild the committed workbook only when the YAML changed (UNIVERSAL_WORKFLOW.md §4.4)
python3 .claude/skills/tree-f-visualizer/scripts/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html --check
python3 .claude/skills/aider-scaffold/scripts/diff_ledger.py --check
python3 .claude/skills/regen-workflow/assets/update_readme_index.py --readme README.md --dir docs --dir notebooks --exclude 'docs/diffs/*' --check
python3 tests/test_regen_workflow.py
```

Secrets never enter git: `.env` is ignored (`.env.example` carries the names), tokens live in Secret Manager, the n8n SA key in a
gitignored folder.

## Documents

<!-- regen:docs-index start -->
- [Execution surfaces — how the three lanes were brought to one idempotent outcome (record)](docs/EXECUTION_SURFACES.md)
- [Pass 1 — the sequence, on any lane (scenario A shown)](docs/PASS1_SEQUENCE.md)
- [Pass 2 — L2 likelihood tiers: design, evidence, execution surfaces](docs/PASS2_L2_TIERS.md)
- [Cloud Shell runbook — CloudBQ lane A on `wisekeybq`](docs/RUNBOOK_CLOUD_SHELL.md)
- [The three lanes, condensed](docs/SCENARIOS.md)
- [Porting `pass-sequence` from mir-load to CloudBQ (and IC-DBT-BQ)](docs/discovery/pass_sequence_port.md)
- [Discovery reports (2026-10-05)](docs/discovery/README.md)
- [Scenario A — Cloud Run function (gcloud, Scheduler OIDC, Secret Manager, BigQuery MERGE)](docs/discovery/scenario_A.md)
- [Scenario B — n8n on Cloud Run + workflow JSON (discovery report)](docs/discovery/scenario_B.md)
- [Scenario C — Hybrid: BigQuery computes, remote JS writes back, Breeze consumes, Claude iterates](docs/discovery/scenario_C.md)
- [Discovery: hot-deal scorer and remote-JS write-back patterns (Scenario C input)](docs/discovery/scorer_repos.md)
- [CloudBQ — synthesis of the three scenarios into the lane workbook (2026-10-05, commit 9e7e18a)](docs/discovery/synthesis.md)
- [notebooks/ — the Pass-1 sequence as a Jupyter notebook (Vertex AI Workbench)](notebooks/README.md)
<!-- regen:docs-index end -->

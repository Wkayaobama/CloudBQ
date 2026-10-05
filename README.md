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

1. `docs/SCENARIOS.md` — the three lanes condensed and the recommendation.
2. `docs/PASS1_SEQUENCE.md` — the deploy sequence with look commands and the dry-run gate.
3. `docs/EXECUTION_SURFACES.xlsx` (built from `docs/execution_surfaces.yaml`) — the lane matrix: layers L0–L17 × lanes A/B/C,
   parity words, remediation, equality checks; the Overview counts the **parallel lane**. `docs/EXECUTION_SURFACES.md` is the record.
4. `docs/architecture_tree.html` — the architecture as an interactive `tree /f` (scenario and layer filters, lane view);
   `docs/ARCHITECTURE_TREE.txt` is the plain listing; both come from `docs/architecture.yaml`.
5. `docs/diffs/INDEX.md` — one patch per commit; every suggestion is a `git diff`.

## Tooling (reusable, project-agnostic — also installed in IC-DBT-BQ)

- `.claude/skills/aider-scaffold/` — `aider_scaffold.py <recipe> [files]` runs a block through aider as auto-committed steps (or prints
  the recipe and exits 2 without an LLM key); `diff_ledger.py` keeps `docs/diffs/`. Recipes for every block: `assets/recipes/`.
- `.claude/skills/tree-f-visualizer/` — `tree_f.py` renders `docs/architecture.yaml` + the tree on disk as `tree /f` text, a manifest, and the HTML page.
- `.claude/skills/pass-sequence/` — the documentation method (ported from mir-load): sequence page → record → YAML → workbook.
- `.claude/agents/` — `discovery-agent` and `implementation-agent` definitions.

## Verify before you push

```bash
python3 tests/test_hot_score.py && python3 tests/test_main_offline.py && python3 tests/test_n8n_code.py
for f in cloud_function_new_deals/deploy.sh sql/*.sh writeback/*.sh deploy/n8n/*.sh; do bash -n "$f"; done
node --check writeback/index.mjs && python3 workflows/src/build_workflow.py --check
python3 .claude/skills/pass-sequence/scripts/build_surfaces_xlsx.py --spec docs/execution_surfaces.yaml --out docs/EXECUTION_SURFACES.xlsx --verify
python3 .claude/skills/tree-f-visualizer/scripts/tree_f.py --root . --annotations docs/architecture.yaml --out-json docs/architecture.manifest.json --out-ascii docs/ARCHITECTURE_TREE.txt --out-html docs/architecture_tree.html --check
python3 .claude/skills/aider-scaffold/scripts/diff_ledger.py --check
```

Secrets never enter git: `.env` is ignored (`.env.example` carries the names), tokens live in Secret Manager, the n8n SA key in a
gitignored folder.

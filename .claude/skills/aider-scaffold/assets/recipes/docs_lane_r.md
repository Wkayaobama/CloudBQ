# Recipe — lane R in the execution surfaces: the raw root + the one SQL implementation as its own column (docs block)

/add docs/execution_surfaces.yaml docs/architecture.yaml docs/EXECUTION_SURFACES.md docs/SCENARIOS.md docs/PASS3_RAW_ROOT.md README.md
/read-only sql/deals_landed_v1.sql sql/new_deals_batch.sql sql/land_raw.sql cloud_function_new_deals/main.py cloud_function_new_deals/deploy.sh sql/scheduled_query.sh

Pass 3 made the shared SQL path (deals_raw / labels_raw → deals_landed_v1 → new_deals_batch_rows → new_deals_batch) the thing every
lane executes; the matrix still showed it as text inside the A and C cells, so "the parallel lane" read as three code paths that
must agree after it had become one.

1. `surfaces.R` in docs/execution_surfaces.yaml; an `R:` cell in every layer (L0–L17) and every pipeline step (1–13) saying how that
   layer is performed inside BigQuery or why it is n/a (no runtime, no trigger, no secret, no delivery, no write-back); the legend
   names the fourth column as the implementation, not a scenario. L6 flips to Parallel (one duplicate rule for every lane, D3).
   Equality checks keep their "BC" key (the builder's legacy fallback). Rebuild the workbook with --verify.
2. docs/architecture.yaml: scenario R declared; the shared blocks tagged R (the two SQL files, land_raw.sql, backfill_raw.sh, the DDL,
   the UDF, the pass-3 tests and page); sql/refresh_pipeline_labels.sh re-layered to L4 (it extracts labels). Regenerate the tree.
3. docs/EXECUTION_SURFACES.md: a lane row and a timeline row; docs/SCENARIOS.md: §R; README "Read in this order" item 3; PASS3 page.

Facts only: every command, object and schedule named in an R cell exists in the repository at this commit.

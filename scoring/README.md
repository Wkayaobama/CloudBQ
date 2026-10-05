# scoring — one hot score, three runtimes

| Runtime | File | Used by | Verified how |
|---|---|---|---|
| Python | `cloud_function_new_deals/main.py` `hot_score()` | Scenario A (Cloud Run function) | canonical; builds `tests/hot_score_vectors.json` |
| JavaScript | `scoring/hot_score_v1.mjs` | Scenario C write-back job; source of the n8n Code node (Scenario B) | `python3 tests/test_hot_score.py` runs it with node: raw score within 1e-9, flags equal |
| BigQuery SQL | `scoring/hot_score_v1.sql` → `hubspot.hot_score_v1` | Scenario C compute lane (views, scheduled query) | `bq query --use_legacy_sql=false < tests/hot_score_vectors.sql` → every `ok` TRUE (needs credentials) |

`scoring/hot_score_v1.constants.json` holds every constant once; the test fails if main.py drifts from it.
This block is the **parallel lane** of the workbook (layer L5): whichever orchestrator runs, the arithmetic is
pinned to the same vectors. Golden vector from the README probe: *Lattice Keystone C0 ASIC*, day-1 score 81.

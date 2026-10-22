# scoring — one hot score, two runtimes

| Runtime | File | Used by | Verified how |
|---|---|---|---|
| BigQuery SQL | `scoring/hot_score_v1.sql` → `hubspot.hot_score_v1` | THE implementation since pass 3: the table function `new_deals_batch_rows` (every lane) and `sql/hot_deals_v1.sql` (write-back views) | `bq query --use_legacy_sql=false < tests/hot_score_vectors.sql` → every `ok` TRUE (needs credentials); offline `tests/test_hot_score_sql_duckdb.py` (15 vectors + 4,000 random deals) |
| Python | `cloud_function_new_deals/main.py` `hot_score()` | test oracle only — builds `tests/hot_score_vectors.json`; the function no longer scores in the request path | `python3 tests/test_hot_score.py` |

`scoring/hot_score_v1.constants.json` holds every constant once; the test fails if main.py drifts from it.
The JavaScript port (`hot_score_v1.mjs`) and the n8n Code node that embedded it were retired in pass 3 phase 3 (decision D6):
the write-back job reads the SQL views, and no lane shapes or scores outside BigQuery any more.
This block is the **parallel lane** of the workbook (layer L5): whichever orchestrator runs, the arithmetic is the one UDF,
pinned to the same vectors. Golden vector from the README probe: *Lattice Keystone C0 ASIC*, day-1 score 81.

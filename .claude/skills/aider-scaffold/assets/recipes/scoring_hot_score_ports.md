# Recipe — shared hot-score v1 across runtimes (parallel-lane block)

/add scoring/hot_score_v1.constants.json scoring/hot_score_v1.mjs scoring/hot_score_v1.sql tests/test_hot_score.py
/read-only cloud_function_new_deals/main.py CONVENTIONS.md

The canonical scorer is `hot_score()` in cloud_function_new_deals/main.py (constants W, BIAS, THRESHOLD, CR, MAXC;
the JS original named in its comment does not exist in any repository). Make the arithmetic identical on every
surface without changing main.py:

1. `scoring/hot_score_v1.constants.json` — every constant and tier boundary in one file (weights, bias, threshold,
   conversion won/total per pipeline, hardware pipeline id, max contacted notes, horizon date and decay days, ARR
   tiers for PKI and default, recency thresholds, forecast states).
2. `scoring/hot_score_v1.mjs` — ESM port reading that JSON; `hotScore(props, now)` returns `{score, hot, raw}`
   with the same branches as Python (first ARR tier is strict `<`, the rest `<=`; closedate year ≤ 2026 → 1 else
   linear decay over 730 days from 2026-12-31; integer day differences like `timedelta.days`); pipelines without a
   conversion rate return nulls. A CLI mode prints one JSON per vector.
3. `scoring/hot_score_v1.sql` — BigQuery SQL UDF `hubspot.hot_score_v1(...)` returning STRUCT<score, hot, raw>,
   same formula, NULL for unscored pipelines; `${PROJECT}` placeholder.
4. `tests/test_hot_score.py` — builds `tests/hot_score_vectors.json` from main.hot_score over ≥ 15 cases covering
   every branch (both scored pipelines, an unscored one, PKI and default tiers at their boundaries, close dates in
   2026 / 2027 / 2028 / 2029, missing 2026 fields, Forecast/BIBA, garbage numbers); asserts constants == JSON,
   Python reproduces the vectors, node's raw score within 1e-9 and flags equal; emits `tests/hot_score_vectors.sql`
   (UNNEST of the vectors against the UDF, `ok` column) for a later `bq query`.

Do not touch main.py, deploy.sh or the n8n JSON. Run `python3 tests/test_hot_score.py` and make it pass.

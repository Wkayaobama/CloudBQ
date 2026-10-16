/add notebooks/cloudbq_deploy_and_witness.ipynb notebooks/README.md tests/test_notebook.py
/read-only cloud_function_new_deals/deploy.sh cloud_function_new_deals/main.py tests/test_hot_score.py scoring/hot_score_v1.sql CONVENTIONS.md

Build the notebook that replicates the Pass-1 sequence (docs/PASS1_SEQUENCE.md) on a Vertex AI Workbench instance and witnesses the SQL.

Rules:
- One code cell per deploy.sh step, in the script's order (check-env enable-apis iam tables secret deploy invoker | dry | run SEALSQ, run ICALPS | probe | enable), each calling `bash {D} <step>` through a streaming `sh()` helper that raises on failure (gate semantics). Nothing is re-implemented.
- `secret` takes the token from getpass and passes it as an environment variable only; `enable` is guarded by a flag the operator flips by hand.
- `.env` is written from a SETTINGS dict on top of .env.example and parsed with shlex (the way `. .env` reads it); placeholders are refused like check-env does.
- Witness section: q() runs SQL through google.cloud.bigquery and prints job id, statement type, bytes processed, slot ms, cache hit; render() does the ${PROJECT}/${DATASET}/${BQ_LOCATION} substitution of deploy.sh tables. Cells: INFORMATION_SCHEMA; scoring/hot_score_v1.sql then tests/hot_score_vectors.sql (assert ok); main.hot_score on the same vectors side by side; report_state / new_deals_runs / new_deals_history / new_deals_last_7d; probe from shell and from Python; the dry payload via an ID token; optional live parity through test_hot_score.emit_sql.
- No outputs committed; tests/test_notebook.py keeps it valid (nbformat), compilable, complete and output-free.

# Recipe — scenario B workflows generated from one source each

/add workflows/src/build_workflow.py workflows/src/shape_score.js workflows/src/node_code.template.js tests/test_n8n_code.py workflows/credentials.map.json.example
/read-only scoring/hot_score_v1.constants.json cloud_function_new_deals/bigquery_schema.sql cloud_function_new_deals/main.py cloud_function_new_deals/n8n_NewDeals_Delivery.json

build_workflow.py writes three files with stable ids and pinned node typeVersions:
- NEW_DEALS_FULL.json (B2): Webhook (Header Auth, responseNode) → Params (entity validated, dry_run, run_ts once) → BigQuery read
  watermark → Code "Window" (half-open window computed once) → HTTP Request HubSpot search (POST, pagination on body.after,
  limit 200) → Pipelines → Owners (paginated) → BigQuery recent names (continue on error) → Code "Shape + score" (GENERATED:
  constants JSON + shape_score.js + SQL templates from the schema; outputs rows, merge_sql with the rows as a BigQuery
  triple-quoted JSON literal through UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(...))), history_sql, watermark_sql, runlog_sql) →
  IF dry → Respond | MERGE → history → watermark → run log → Rows → XLSX → Email → Respond. Frozen MERGE columns = main.py's.
- NEW_DEALS_DELIVERY.json (B1): the existing delivery JSON hardened — Header Auth, zero-row branch, env recipients, respond last.
- NEW_DEALS_ERRORS.json: Error Trigger → email.
`--check` exits 1 on drift; tests/test_n8n_code.py runs the generated Code node in node behind a $('Node') shim with the same
fake deals as the Python tests and asserts every row field equals main.shape(). Node parameter shapes for HTTP Request pagination
are best-effort: validate once on import in the editor.

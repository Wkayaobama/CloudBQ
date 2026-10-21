#!/usr/bin/env python3
"""Offline structure checks for the pass-3 SQL objects (sql/land_raw.sql, sql/deals_landed_v1.sql, sql/new_deals_batch.sql).

    python3 tests/test_pass3_sql.py        or        python3 -m pytest tests -q        (--write regenerates tests/pass3_batch_vectors.sql)

A `bq --dry_run` needs credentials and stops at the first IF, so what can be proved offline is structural: the adapter view types
exactly the properties the landing carries (main.PROPS), the table function's column list equals hubspot.new_deals in order (the
procedure MERGEs with INSERT ROW), the MERGE update list excludes the four frozen columns, the procedure never reads a *_synced_v1
view (the function's service account has no grant on the sync dataset), every data_gaps value emitted is in the vocabulary, and the
rendered scripts carry no placeholder. The executed check (the 15 vectors through the table function in a dev dataset) is the first
authenticated step of phase 2 — docs/PASS3_RAW_ROOT.md §5.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud_function_new_deals"))
import main  # noqa: E402

DDL = (ROOT / "cloud_function_new_deals/bigquery_schema.sql").read_text()
VIEW = (ROOT / "sql/deals_landed_v1.sql").read_text()
PROC = (ROOT / "sql/new_deals_batch.sql").read_text()
LAND = (ROOT / "sql/land_raw.sql").read_text()
WEEKLY = (ROOT / "sql/new_deals_weekly.sql").read_text()
VOCAB = {"sync_stale", "labels_missing", "dedup_horizon_partial", "dedup_scope_batch_only", "raw_landing_failed", "raw_slice_replaced",
         "raw_backfilled_from_current_sync", "source_detail_unavailable", "event_no_window"}


def _ddl_cols(table):
    body = re.search(r"`\$\{PROJECT\}\.\$\{DATASET\}\." + table + r"` \((.*?)\)\n(?:PARTITION|CLUSTER|OPTIONS|;)", DDL, re.S).group(1)
    return re.findall(r"^\s*([a-z0-9_]+) (?:STRING|TIMESTAMP|FLOAT64|DATE|BOOL|INT64|JSON)", body.replace(",", ",\n"), re.M)


def _select_aliases(sql_select):
    """Output column names of a SELECT list: `expr AS alias` or a bare `w.col` / `col`; stops at FROM at depth 0."""
    out, depth, buf = [], 0, ""
    body = sql_select.split("\nFROM ", 1)[0]
    for ch in body:
        if ch == "(": depth += 1
        if ch == ")": depth -= 1
        if ch == "," and depth == 0: out.append(buf.strip()); buf = ""
        else: buf += ch
    out.append(buf.strip())
    names = []
    for e in out:
        m = re.search(r"\bAS\s+([a-z0-9_]+)\s*$", e, re.I | re.S)
        names.append(m.group(1) if m else e.split(".")[-1].strip())
    return names


def test_view_types_exactly_the_landed_properties():
    keys = re.findall(r"JSON_VALUE\(properties, '\$\.([a-z0-9_]+)'\)", VIEW)
    promoted = {"createdate", "pipeline"}          # typed columns of deals_raw (createdate, pipeline_id), read from the table, not the JSON
    assert set(keys) | promoted == set(main.PROPS) and not set(keys) & promoted, (set(keys) | promoted) ^ set(main.PROPS)
    head = VIEW.split("JSON_VALUE", 1)[0]
    assert "run_ts, entity, orchestrator, mode, source, in_scope, fetched_at, deal_id, createdate, pipeline_id," in head
    assert len(main.PROPS) == 29
    struct = re.search(r"TO_JSON\(STRUCT\((.*?)\), stringify_wide_numbers => TRUE\)", LAND, re.S).group(1)   # wide NUMERICs land as strings, never throw
    landed_c = {c.strip() for c in struct.replace("\n", " ").split(",")}
    assert landed_c == set(main.PROPS) - {"hs_object_source_detail_1"}, landed_c ^ set(main.PROPS)   # lane C: source_detail_unavailable until the column is confirmed


def test_table_function_columns_equal_new_deals_in_order():
    tvf = VIEW[VIEW.index("CREATE OR REPLACE TABLE FUNCTION"):]
    final_select = tvf[tvf.rindex("\nSELECT p_entity AS entity"):]
    assert _select_aliases(final_select) == _ddl_cols("new_deals"), (_select_aliases(final_select), _ddl_cols("new_deals"))
    assert "INSERT ROW" in PROC and "SELECT * FROM `${PROJECT}.${DATASET}.new_deals_batch_rows`" in PROC


def test_udf_call_arguments_match_the_udf_signature_positionally():
    udf = (ROOT / "scoring/hot_score_v1.sql").read_text()
    sig = udf[udf.index("hot_score_v1`(") + len("hot_score_v1`("):udf.index(")\nRETURNS")]
    params = re.findall(r"([a-z0-9_]+) (?:STRING|FLOAT64|TIMESTAMP)", sig)
    call = VIEW[VIEW.index("UNNEST([`${PROJECT}.${DATASET}.hot_score_v1`(") + len("UNNEST([`${PROJECT}.${DATASET}.hot_score_v1`("):]
    call = call[:call.index(")]) AS hs")]
    args = [a.strip() for a in call.replace("\n", " ").split(",")]
    rename = {"pipeline": "w.pipeline_id", "hs_deal_stage_probability": "w.stage_probability", "run_ts": "p_run_ts"}
    want = [rename.get(p, "w." + p) for p in params]
    assert args == want, list(zip(args, want))
    assert len(params) == 12


def test_merge_update_list_excludes_the_frozen_columns():
    upd = PROC.split("THEN UPDATE SET")[1].split("WHEN NOT MATCHED")[0]
    for frozen in main.FROZEN: assert not re.search(rf"\b{frozen} =", upd), frozen
    assert "last_seen_run = s.last_seen_run" in upd and "s.last_seen_run >= IFNULL(t.last_seen_run" in PROC
    # every non-frozen new_deals column is updated
    updated = set(re.findall(r"\b([a-z0-9_]+) = s\.", upd))
    assert updated == set(_ddl_cols("new_deals")) - set(main.FROZEN), updated ^ (set(_ddl_cols("new_deals")) - set(main.FROZEN))


def _code(sql):
    """The SQL without its `--` comment text (comments may name what the code must not read)."""
    return "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())


def test_procedure_and_function_read_the_root_only():
    for name, sql in (("new_deals_batch.sql", PROC), ("deals_landed_v1.sql", VIEW)):
        assert "_synced_v1" not in _code(sql), f"{name} reads a sync view — the function SA has no grant on the sync dataset"
        assert "${SYNC_DATASET}" not in _code(sql), name
    assert "deals_landed_v1" in VIEW and "labels_raw" in VIEW


def test_procedure_contract_shape():
    sig = PROC[PROC.index("new_deals_batch`("):PROC.index(")\nBEGIN")]
    params = re.findall(r"(p_[a-z_]+) ([A-Z<>]+)", sig)
    assert [p for p, _ in params] == ["p_run_ts", "p_entity", "p_orchestrator", "p_mode", "p_advance_state", "p_state_report_id",
                                      "p_watermark_in", "p_query_start", "p_query_end", "p_started_ms", "p_gaps"], params
    assert "IF p_mode = 'dry' THEN" in PROC and PROC.count("BEGIN TRANSACTION") == 1 and PROC.count("COMMIT TRANSACTION") == 1
    dry = PROC.split("IF p_mode = 'dry' THEN")[1].split("ELSE")[0]
    assert "MERGE" not in dry and "new_deals_history" not in dry and "report_state" not in dry and "TRUE, p_orchestrator" in dry and "COUNT(*), 0," in dry
    assert "EXCEPTION WHEN ERROR THEN" in PROC and "ROLLBACK TRANSACTION" in PROC and "'FAILED'" in PROC and "RAISE;" in PROC
    assert "GREATEST(t.watermark, s.watermark)" in PROC and "lock_until" in PROC
    assert "CREATE OR REPLACE TEMP TABLE batch" in PROC, "two CALLs in one script must not collide on the temp table"
    assert "IF p_mode IS NULL OR p_mode NOT IN" in PROC and PROC.count("IFNULL(p_advance_state, FALSE)") == 3, "NOT IN / IF treat NULL as false: the guards must be NULL-safe"
    assert "'raw_landing_failed' IN UNNEST(v_gaps)" in PROC and "no slice exists for this key" in PROC, "a failed landing with no slice must not become an OK run with 0 rows"
    assert "BEGIN ROLLBACK TRANSACTION; EXCEPTION WHEN ERROR THEN END;" in PROC, "a cancelled transaction must not hide the FAILED row"
    win = VIEW[VIEW.index("WITH win AS ("):VIEW.index("), horizon AS (")]
    assert "QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_id ORDER BY fetched_at DESC) = 1" in win, "one source row per deal: a doubled slice must never reach the MERGE"
    assert "(p_window_start IS NULL OR (createdate >= p_window_start AND createdate < p_run_ts))" in win, "an event (NULL window) must keep a deal created in run_ts's own second"
    assert "SET v_written = @@row_count" in PROC and "COUNT(*), v_written," in PROC, "rows_written is what the MERGE touched, not COUNT(*)"


def test_every_emitted_gap_is_in_the_vocabulary():
    emitted = set()
    for sql in (PROC, WEEKLY, LAND):
        for arr in re.findall(r"\[((?:'[a-z_]+',?\s*)+)\]", sql): emitted |= set(re.findall(r"'([a-z_]+)'", arr))
    src = (ROOT / "cloud_function_new_deals/main.py").read_text()
    emitted |= set(re.findall(r'gaps\.append\("([a-z_]+)"\)', src))
    assert emitted <= VOCAB, emitted - VOCAB
    for v in ("raw_landing_failed", "dedup_scope_batch_only", "event_no_window"): assert v in emitted, v
    for v in ("sync_stale", "source_detail_unavailable", "raw_backfilled_from_current_sync", "labels_missing", "dedup_horizon_partial"): assert v in emitted, v
    comment = re.search(r"data_gaps: what a run could not read or compute \((.*?)\)", DDL, re.S).group(1)
    assert {c.strip() for c in comment.replace("\n--", "").split(",")} == VOCAB


def test_apply_order_and_placeholders():
    apply = (ROOT / "sql/apply.sh").read_text()
    files = re.search(r'FILES=\((.*?)\)', apply, re.S).group(1)
    order = re.findall(r'/([a-z_0-9]+\.sql)"', files)
    for a, b in (("bigquery_schema.sql", "deals_landed_v1.sql"), ("hot_score_v1.sql", "deals_landed_v1.sql"), ("deals_landed_v1.sql", "new_deals_batch.sql")):
        assert order.index(a) < order.index(b), order
    for sql in (VIEW, PROC, LAND):
        for ph in set(re.findall(r"\$\{([A-Z_]+)\}", sql)): assert ph in ("PROJECT", "DATASET", "PORTAL_ID", "SYNC_DATASET", "SYNC_DEALS_TABLE"), ph


# ---------------------------------------------------------------- the executed check (needs credentials): the 15 vectors through the table function

def sql_literal(v):
    return "CAST(NULL AS STRING)" if v in (None, "") else ("'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'")


def emit_batch_vectors_sql(vectors: dict) -> str:
    """tests/pass3_batch_vectors.sql: land the golden vectors as one deals_raw slice of a DEV dataset (entity VECTORS, orchestrator
    vectors), read them back through deals_landed_v1 → new_deals_batch_rows, compare day1_hot_score / day1_hot_flag to the expected
    values, then drop the slice. The properties land exactly as lane A lands them (HubSpot strings), so this also proves the JSON path."""
    now = vectors["now"].replace("Z", "+00")
    keys = ["pipeline", "hs_deal_stage_probability", "closedate", "calculation___pipeline_2026__k__", "services_value_2026",
            "asp_in_usd_q2_2022_calculation", "tpm__k_y", "product_hierarchy", "num_contacted_notes", "notes_last_updated", "revenue_state"]
    rows, exp = [], []
    for c in vectors["cases"]:
        p = c["props"]; e = c["expected"]
        props = ", ".join(f"{sql_literal(p.get(k))} AS {k}" for k in keys) + f", {sql_literal(c['id'])} AS dealname, {sql_literal('')} AS final_customer"
        rows.append(f"STRUCT({sql_literal(c['id'])} AS deal_id, {sql_literal(p.get('pipeline'))} AS pipeline_id, TO_JSON(STRUCT({props})) AS properties)")
        exp.append("STRUCT(%s AS id, %s AS exp_score, %s AS exp_hot)" % (sql_literal(c["id"]), "CAST(NULL AS FLOAT64)" if e["score"] is None else repr(e["score"]),
                                                                       "CAST(NULL AS BOOL)" if e["hot"] is None else str(e["hot"]).upper()))
    return (
        "-- generated by tests/test_pass3_sql.py from tests/hot_score_vectors.json — the EXECUTED check of pass 3 phase 2. Run it against a DEV\n"
        "-- dataset only (it writes one deals_raw slice and drops it): render ${PROJECT}/${DATASET}, then\n"
        "--   bq query --use_legacy_sql=false < tests/pass3_batch_vectors.sql   → every row ok = TRUE (15 rows)\n"
        f"DECLARE v_run_ts TIMESTAMP DEFAULT TIMESTAMP '{now}';\n"
        "DELETE FROM `${PROJECT}.${DATASET}.deals_raw` WHERE entity = 'VECTORS' AND orchestrator = 'vectors';\n"
        "INSERT INTO `${PROJECT}.${DATASET}.deals_raw` (run_ts, entity, orchestrator, mode, source, deal_id, in_scope, createdate, pipeline_id, properties, fetched_at)\n"
        "SELECT v_run_ts, 'VECTORS', 'vectors', 'dry', 'vectors', deal_id, TRUE, TIMESTAMP_SUB(v_run_ts, INTERVAL 1 DAY), pipeline_id, properties, CURRENT_TIMESTAMP()\n"
        "FROM UNNEST([\n  " + ",\n  ".join(rows) + "\n]);\n"
        "WITH e AS (SELECT * FROM UNNEST([\n  " + ",\n  ".join(exp) + "\n]))\n"
        "SELECT e.id, e.exp_score, r.day1_hot_score, e.exp_hot, r.day1_hot_flag, r.duplicate_suspect,\n"
        "       r.deal_id IS NOT NULL AND (   -- a dropped row must not pass as a NULL-expected case\n"
        "         (e.exp_score IS NULL AND r.day1_hot_score IS NULL AND r.day1_hot_flag IS NULL)\n"
        "         OR (ABS(r.day1_hot_score - e.exp_score) <= 0.1 AND r.day1_hot_flag = e.exp_hot)) AS ok\n"
        "FROM e LEFT JOIN `${PROJECT}.${DATASET}.new_deals_batch_rows`(v_run_ts, 'VECTORS', 'vectors', CAST(NULL AS TIMESTAMP)) r ON r.deal_id = e.id\n"
        "ORDER BY e.id;\n"
        "DELETE FROM `${PROJECT}.${DATASET}.deals_raw` WHERE entity = 'VECTORS' AND orchestrator = 'vectors';\n")


def test_batch_vectors_sql_is_current():
    import json
    vectors = json.loads((ROOT / "tests/hot_score_vectors.json").read_text())
    want = emit_batch_vectors_sql(vectors); have = ROOT / "tests/pass3_batch_vectors.sql"
    assert have.exists() and have.read_text() == want, "regenerate: python3 tests/test_pass3_sql.py --write"
    assert want.count("STRUCT(") == 3 * len(vectors["cases"]) and "new_deals_batch_rows`(v_run_ts, 'VECTORS', 'vectors', CAST(NULL AS TIMESTAMP))" in want


if __name__ == "__main__":
    import json
    if "--write" in sys.argv:
        (ROOT / "tests/pass3_batch_vectors.sql").write_text(emit_batch_vectors_sql(json.loads((ROOT / "tests/hot_score_vectors.json").read_text())))
        print("wrote tests/pass3_batch_vectors.sql")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print("ok ", name)
    print("pass-3 sql structure OK")

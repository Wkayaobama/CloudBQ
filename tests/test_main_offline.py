#!/usr/bin/env python3
"""Offline behaviour tests for cloud_function_new_deals/main.py with a fake HubSpot and a recording fake BigQuery client.

    python3 tests/test_main_offline.py        or        python3 -m pytest tests -q

Pass 3 phase 3 — the function extracts, lands the root and CALLs the procedure; BigQuery computes. Proved here without credentials:
the row contract equals the BigQuery schema; dry mode lands with mode = 'dry', CALLs with mode = 'dry', touches no sink and no state
(decision D1); live mode lands BEFORE the CALL and advances the watermark (releasing the lease) only AFTER it; the CALL carries the
run's window, started_ms and data_gaps (as an ArrayQueryParameter) with advance_state = FALSE; a landing failure fails the run and is
named; a CALL failure releases the lease and adds no second FAILED row (the procedure wrote one); a failure before the CALL writes the
FAILED row here; an overlapping run gets 409; event mode CALLs with mode = 'event' and never touches the watermark; a delivery failure
amends the runs row; the root landing keeps the phase-1 invariants (whole search, JSON dict, strict replacement, event-scoped delete,
time-boxed jobs).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud_function_new_deals"))
import main  # noqa: E402
from flask import Flask  # noqa: E402  (functions-framework dependency)

APP = Flask(__name__)
NOW = datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)
DDL = (ROOT / "cloud_function_new_deals/bigquery_schema.sql").read_text()
TYPES = "STRING|TIMESTAMP|FLOAT64|DATE|BOOL|INT64|JSON"


def _cols(table):
    body = re.search(r"`\$\{PROJECT\}\.\$\{DATASET\}\." + table + r"` \((.*?)\)\n(?:PARTITION|CLUSTER|OPTIONS|;)", DDL, re.S).group(1)
    return re.findall(r"^\s*([a-z0-9_]+) (?:" + TYPES + ")", body.replace(",", ",\n"), re.M)


SCHEMA_COLS = _cols("new_deals")

from google.cloud import bigquery  # noqa: E402

def _Field(name): return bigquery.SchemaField(name, "JSON" if name == "properties" else "TIMESTAMP" if name.endswith(("_run", "run_ts", "createdate", "_at")) else "STRING")


class _Job:
    def __init__(self, rows=None, affected=None, sink=None): self._rows = rows or []; self.num_dml_affected_rows = affected; self._sink = sink
    def result(self, timeout=None):
        if self._sink is not None: self._sink.append(timeout)
        return self._rows


class FakeHubSpot:
    DEALS = [
        {"id": "1", "properties": {"pipeline": "12096408", "dealname": "Lattice Keystone C0 ASIC - phase 1", "final_customer": "Lattice", "createdate": "2026-10-01T10:00:00Z", "hs_deal_stage_probability": "0.2", "amount_in_home_currency": "16002", "asp_in_usd_q2_2022_calculation": "16002", "closedate": "2027-03-31T00:00:00Z"}},
        {"id": "2", "properties": {"pipeline": "766126206", "dealname": "Lattice Keystone (ICALPS)", "final_customer": "Lattice", "createdate": "2026-10-01T10:03:00Z", "hs_deal_stage_probability": "0.1", "amount": "900"}},
        {"id": "3", "properties": {"pipeline": "13772279", "dealname": "Acme Services", "final_customer": "", "createdate": "2026-10-02T10:00:00Z", "hs_deal_stage_probability": "0.5"}},
    ]
    def __init__(self, token): pass
    def search_created(self, start, end): return [d for d in self.DEALS if start <= datetime.fromisoformat(d["properties"]["createdate"].replace("Z", "+00:00")) < end]
    def deal(self, deal_id): return next(d for d in self.DEALS if d["id"] == deal_id)
    def pipelines(self): return {"12096408": "SealSQ Hardware", "13772279": "SealSQ Services", "766126206": "Icalps_hardware"}, {"s1": "Discovery"}
    def owners(self): return {"7": "Ada"}


def _oracle_rows(entity):
    """What the procedure would have written for this entity: main.shape() is the test oracle of the SQL batch. Returned the way the
    BigQuery client returns them — TIMESTAMP as datetime, DATE as date — so the payload's JSON rendering is exercised."""
    from datetime import date
    hs = FakeHubSpot("x"); pl, st = hs.pipelines(); found = hs.DEALS
    deals = [d for d in found if d["properties"]["pipeline"] in main.ENTITIES[entity]["pipelines"]]; others = [d for d in found if d not in deals]
    rows = main.shape(deals, others, entity, pl, st, hs.owners(), NOW, {"lattice": ["999"]})
    rows.sort(key=lambda r: (-(r["amount_kusd"] or 0), r["deal_id"]))
    for r in rows:
        r["createdate"] = datetime.fromisoformat(r["createdate"].replace("Z", "+00:00")); r["first_seen_run"] = r["last_seen_run"] = NOW
        if r["closedate"]: r["closedate"] = date.fromisoformat(r["closedate"])
    return rows


class FakeBQ:
    """Records every SQL/load call (self.calls keeps the order across kinds; self.param_objs the parameter objects); emulates
    report_state, the lease and the procedure (the CALL marks that a runs row exists; the runs-row read answers with the procedure's
    own rows_written and data_gaps). Switches: fail_landing = True | "deals" | "labels"; fail_call = True (the procedure wrote FAILED,
    then raised) | "no_row" (the CALL died before the procedure); fail_read (the history read-back raises after the CALL); replaced
    (delete-older reports rows); no_gaps_column (a runs table deployed before `deploy.sh tables`)."""
    def __init__(self, watermark=None, locked=False, fail_landing=False, fail_call=False, fail_read=False, replaced=False, no_gaps_column=False, entity="SEALSQ", proc_written=None, proc_gaps=("dedup_horizon_partial",)):
        self.sql, self.params, self.param_objs, self.loads, self.deleted, self.calls, self.raw_timeouts = [], [], [], [], [], [], []
        self.watermark, self.locked, self.called = watermark, locked, False
        self.fail_landing, self.fail_call, self.fail_read, self.replaced, self.no_gaps_column = fail_landing, fail_call, fail_read, replaced, no_gaps_column
        self.rows = _oracle_rows(entity); self.project = "p"
        self.proc_written, self.proc_gaps = (len(self.rows) if proc_written is None else proc_written), list(proc_gaps)
    def query(self, q, job_config=None):
        objs = list(job_config.query_parameters) if job_config else []
        params = {p.name: getattr(p, "value", getattr(p, "values", None)) for p in objs}
        self.sql.append(q); self.params.append(params); self.param_objs.append(objs); self.calls.append(("query", q))
        if self.no_gaps_column and "data_gaps" in q and q.startswith("INSERT"): raise RuntimeError("400 Unrecognized name: data_gaps")
        if "SELECT watermark FROM" in q: return _Job([{"watermark": self.watermark}] if self.watermark else [])
        if "SET lock_until = TIMESTAMP_ADD" in q:
            if self.locked: return _Job(affected=0)
            self.locked = True; return _Job(affected=1)
        if "SET watermark = @ts" in q: self.watermark = params["ts"]; self.locked = False
        if q.startswith("CALL `p.hubspot.new_deals_batch`"):
            if self.fail_call == "no_row": raise RuntimeError("404 Not found: Routine p:hubspot.new_deals_batch")
            self.called = True                                   # the procedure writes the runs row, OK or FAILED, before re-raising
            if self.fail_call: raise RuntimeError("400 new_deals_batch: a lane-A run holds the lease")
            return _Job(sink=self.raw_timeouts)
        if "FROM `p.hubspot.new_deals_history`" in q or "FROM `p.hubspot.new_deals_batch_rows`" in q:
            if self.fail_read: raise RuntimeError("503 backendError")
            ids = params.get("ids"); return _Job([dict(r) for r in self.rows if ids is None or r["deal_id"] in ids])
        if q.startswith("SELECT rows_written, data_gaps FROM `p.hubspot.new_deals_runs`"): return _Job([{"rows_written": self.proc_written, "data_gaps": list(self.proc_gaps)}])
        if q.startswith("SELECT COUNT(*) AS n FROM `p.hubspot.new_deals_runs`"): return _Job([{"n": 1 if self.called else 0}])
        if q.startswith("DELETE FROM `p.hubspot.deals_raw`"): return _Job(affected=2 if self.replaced else 0, sink=self.raw_timeouts)
        if q.startswith("DELETE FROM `p.hubspot.labels_raw`"): return _Job(sink=self.raw_timeouts)
        return _Job()
    def get_table(self, name):
        short = name.rsplit(".", 1)[-1]
        cols = {"deals_raw": _cols("deals_raw"), "labels_raw": _cols("labels_raw")}.get(short, SCHEMA_COLS)
        class T: schema = [_Field(c) for c in cols]
        return T()
    def load_table_from_json(self, rows, dest, job_config=None):
        if self.fail_landing in (True, "deals") and dest.endswith("deals_raw"): raise RuntimeError("403 Access Denied: Table deals_raw")
        if self.fail_landing == "labels" and dest.endswith("labels_raw"): raise RuntimeError("403 Access Denied: Table labels_raw")
        self.loads.append((dest, list(rows), job_config.write_disposition)); self.calls.append(("load", dest))
        return _Job(sink=self.raw_timeouts if dest.endswith(("deals_raw", "labels_raw")) else None)
    def delete_table(self, name, not_found_ok=False): self.deleted.append(name); self.calls.append(("drop", name))
    # helpers for the assertions
    def loaded(self, table): return [rows for d, rows, _ in self.loads if d.endswith(table)]
    def first(self, kind, needle): return next(i for i, (k, t) in enumerate(self.calls) if k == kind and needle in t)
    def call(self):
        i = next(i for i, q in enumerate(self.sql) if q.startswith("CALL `p.hubspot.new_deals_batch`")); return self.sql[i], self.params[i], self.param_objs[i]
    def runs_rows(self): return [(self.sql[i], self.params[i], self.param_objs[i]) for i, q in enumerate(self.sql) if q.lstrip().startswith("INSERT INTO `p.hubspot.new_deals_runs`")]


def _invoke(bqc, query, body=None, raises=False):
    import os
    os.environ.update({"HUBSPOT_TOKEN": "x", "BQ_PROJECT": "p", "BQ_DATASET": "hubspot"}); os.environ.pop("DELIVERY_WEBHOOK_URL", None)
    main.HubSpot, main.bq = FakeHubSpot, (lambda: bqc)
    with APP.test_request_context(f"/?{query}", method="POST" if body else "GET", json=body):
        from flask import request
        if not raises: return main.new_deals_report(request)
        try: main.new_deals_report(request)
        except Exception as e: return e
        raise AssertionError("expected the run to fail")


def _writes(bqc): return [q for q in bqc.sql if q.lstrip().startswith(("MERGE", "UPDATE", "INSERT", "DELETE"))]


# ---------------------------------------------------------------- contract and dry gate

def test_row_contract_equals_schema():
    assert len(SCHEMA_COLS) == 31, SCHEMA_COLS
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=SEALSQ&dry_run=1")
    assert code == 200 and payload["rows"], payload
    assert set(payload["rows"][0]) == set(SCHEMA_COLS), set(payload["rows"][0]) ^ set(SCHEMA_COLS)
    assert payload["data_gaps"] == [] and payload["currency_note"]


def test_dry_lands_calls_with_mode_dry_and_touches_no_sink_or_state():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=SEALSQ&dry_run=1")
    assert code == 200 and payload["dry_run"] is True and payload["rows_written"] == 0 and payload["row_count"] == 2
    assert any("SELECT watermark" in q for q in bqc.sql), "dry reads the watermark like a live run"
    (raw,) = bqc.loaded("deals_raw"); assert {r["mode"] for r in raw} == {"dry"} and len(raw) == 3, "dry lands its slice with mode = dry (D1)"
    q, p, _ = bqc.call(); assert p["mode"] == "dry" and "FALSE, NULL" in q
    assert bqc.first("load", "deals_raw") < bqc.first("query", "CALL `p.hubspot.new_deals_batch`")
    assert not any("SET watermark" in q or "lock_until" in q or q.lstrip().startswith(("MERGE", "INSERT", "UPDATE")) for q in bqc.sql), "no sink, no state, no lease, no row of its own (the procedure writes the dry runs row)"
    tvf = next(q for q in bqc.sql if "FROM `p.hubspot.new_deals_batch_rows`" in q); assert "(@ts, @e, @o, @qs)" in tvf and not any("new_deals_history" in q or "SELECT rows_written" in q for q in bqc.sql), "the dry payload comes from the table function, bounded by the window start"
    assert payload["data_gaps"] == []
    assert payload["window"]["watermark_in"].startswith("2026-09-28"), payload["window"]
    r1 = next(r for r in payload["rows"] if r["deal_id"] == "1"); assert r1["duplicate_suspect"]


# ---------------------------------------------------------------- live path: land → CALL → watermark → payload

def test_live_lands_before_the_call_and_advances_the_watermark_after_it():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=SEALSQ")
    assert code == 200 and payload["rows_written"] == 2 and payload["dry_run"] is False
    assert bqc.first("load", "deals_raw") < bqc.first("load", "labels_raw") < bqc.first("query", "CALL `p.hubspot.new_deals_batch`") < bqc.first("query", "FROM `p.hubspot.new_deals_history`") < bqc.first("query", "SET watermark = @ts"), bqc.calls
    assert bqc.locked is False and bqc.watermark is not None, "the watermark UPDATE releases the lease — after the CALL and the read-back"
    assert not any(q.lstrip().startswith(("MERGE `p.hubspot.new_deals`", "INSERT INTO `p.hubspot.new_deals_runs`")) for q in bqc.sql), "the function neither MERGEs the sink nor writes the runs row: the procedure does"
    assert not any("new_deals_staging" in d for d, _, _ in bqc.loads) and not bqc.deleted, "no per-run staging table any more"
    assert any("FROM `p.hubspot.new_deals_history`" in q for q in bqc.sql), "the live payload is rendered from the history slice"
    assert [r["deal_id"] for r in payload["rows"]] == ["1", "3"] and payload["day1_hot"] == ["1"], payload["day1_hot"]
    assert payload["data_gaps"] == ["dedup_horizon_partial"], "the procedure's gaps join the function's in the payload"
    bqc2 = FakeBQ(watermark=NOW - timedelta(days=7), proc_written=1); p2, _ = _invoke(bqc2, "entity=SEALSQ")
    assert p2["rows_written"] == 1 and p2["row_count"] == 2, "rows_written is the MERGE's count from the runs row, not the slice size"


def test_call_carries_the_window_the_gaps_and_advance_state_false():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), replaced=True); _invoke(bqc, "entity=SEALSQ")
    q, p, objs = bqc.call()
    assert q.endswith("(@run_ts, @entity, @orchestrator, @mode, FALSE, NULL, @watermark_in, @query_start, @query_end, @started_ms, @gaps)"), q
    assert p["entity"] == "SEALSQ" and p["orchestrator"] == main.ORCHESTRATOR and p["mode"] == "window"
    assert isinstance(p["run_ts"], datetime) and isinstance(p["watermark_in"], datetime) and p["query_start"] == p["watermark_in"] - timedelta(minutes=5) and p["query_end"] == p["run_ts"]
    assert isinstance(p["started_ms"], int) and p["started_ms"] >= 0
    g = next(o for o in objs if o.name == "gaps"); assert isinstance(g, bigquery.ArrayQueryParameter) and g.array_type == "STRING" and g.values == ["raw_slice_replaced"]
    assert bqc.raw_timeouts and bqc.raw_timeouts[-1] == 240 and bqc.raw_timeouts[0] == 45, "the CALL and the landings are time-boxed (defaults 240 / 45: 4 × 45 + 240 + 3 × 30 + 20 < 540)"


def test_landing_failure_fails_the_run_names_it_and_releases_the_lease():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), fail_landing=True); err = _invoke(bqc, "entity=SEALSQ", raises=True)
    assert "deals_raw" in str(err) and not bqc.called, "no root, no CALL"
    rows = bqc.runs_rows(); assert len(rows) == 1 and rows[0][1]["status"] == "FAILED" and "raw_landing_failed" in rows[0][1]["data_gaps"], rows
    assert any("SET lock_until = NULL" in q for q in bqc.sql) and not any("SET watermark" in q for q in bqc.sql)


def test_labels_only_failure_fails_the_run_after_the_deals_slice_landed():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), fail_landing="labels"); err = _invoke(bqc, "entity=SEALSQ", raises=True)
    assert "labels_raw" in str(err) and bqc.loaded("deals_raw") and not bqc.loaded("labels_raw") and not bqc.called
    assert any(q.startswith("DELETE FROM `p.hubspot.deals_raw`") for q in bqc.sql), "the deals slice was completed (load + delete-older) before the labels load raised"
    rows = bqc.runs_rows(); assert len(rows) == 1 and rows[0][1]["status"] == "FAILED" and "raw_landing_failed" in rows[0][1]["data_gaps"]
    assert any("SET lock_until = NULL" in q for q in bqc.sql) and bqc.watermark == NOW - timedelta(days=7)


def test_call_failure_releases_the_lease_and_writes_no_second_failed_row():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), fail_call=True); err = _invoke(bqc, "entity=SEALSQ", raises=True)
    assert "holds the lease" in str(err) and bqc.called
    assert not bqc.runs_rows(), "the procedure wrote the FAILED row before re-raising; the function adds none"
    assert any(q.startswith("SELECT COUNT(*) AS n FROM `p.hubspot.new_deals_runs`") for q in bqc.sql)
    assert any("SET lock_until = NULL" in q for q in bqc.sql) and not any("SET watermark" in q for q in bqc.sql)


def test_failure_before_the_call_writes_the_failed_row_here():
    class Boom(FakeHubSpot):
        def search_created(self, start, end): raise RuntimeError("429 HubSpot")
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); main.HubSpot = Boom
    try:
        import os; os.environ.update({"HUBSPOT_TOKEN": "x", "BQ_PROJECT": "p", "BQ_DATASET": "hubspot"}); main.bq = lambda: bqc
        with APP.test_request_context("/?entity=SEALSQ"):
            from flask import request
            try: main.new_deals_report(request); raise AssertionError("expected failure")
            except RuntimeError as e: assert "429" in str(e)
    finally: main.HubSpot = FakeHubSpot
    rows = bqc.runs_rows(); assert len(rows) == 1 and rows[0][1]["status"] == "FAILED" and rows[0][1]["data_gaps"] == []
    assert not bqc.loads and not bqc.called and any("SET lock_until = NULL" in q for q in bqc.sql)


def test_overlapping_run_gets_409_and_writes_nothing():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), locked=True); payload, code = _invoke(bqc, "entity=ICALPS")
    assert code == 409 and not bqc.loads and not bqc.called
    assert all("`p.hubspot.report_state`" in q for q in _writes(bqc)), _writes(bqc)   # only the lease row itself (create + take)


def test_first_run_without_watermark_uses_first_run_days():
    bqc = FakeBQ(watermark=None); payload, code = _invoke(bqc, "entity=SEALSQ&dry_run=1")
    assert code == 200 and payload["window"]["watermark_in"] is not None


def test_event_mode_calls_with_mode_event_and_never_touches_state():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), entity="ICALPS"); payload, code = _invoke(bqc, "entity=ICALPS", body={"mode": "event", "objectId": "2", "entity": "ICALPS"})
    assert code == 200 and payload["window"]["mode"] == "event" and payload["rows_written"] == 1
    (raw,) = bqc.loaded("deals_raw"); assert len(raw) == 1 and raw[0]["deal_id"] == "2" and raw[0]["mode"] == "event" and raw[0]["in_scope"] is True
    q, p, _ = bqc.call(); assert p["mode"] == "event" and p["gaps"] == ["event_no_window"] and "watermark_in" not in p and q.endswith("FALSE, NULL, NULL, NULL, NULL, @started_ms, @gaps)"), "no window: literal NULLs, never a NULL-valued parameter"
    h = next(i for i, q in enumerate(bqc.sql) if "FROM `p.hubspot.new_deals_history`" in q); assert "deal_id IN UNNEST(@ids)" in bqc.sql[h] and bqc.params[h]["ids"] == ["2"], "an event reads only its own deal (two events in one second share the slice key)"
    assert not any("SET watermark" in q or "lock_until = TIMESTAMP_ADD" in q for q in bqc.sql)
    i = next(i for i, q in enumerate(bqc.sql) if q.startswith("DELETE FROM `p.hubspot.deals_raw`"))
    assert bqc.sql[i].endswith("AND deal_id IN UNNEST(@ids)") and bqc.params[i]["ids"] == ["2"], "an event landing deletes only its own deal's older rows"


def test_delivery_failure_amends_the_runs_row():
    import os
    class R:
        @staticmethod
        def post(*a, **k): raise RuntimeError("503 n8n cold")
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); real_requests, real_sleep = main.requests, main.time.sleep
    main.requests, main.time.sleep = R, (lambda s: None)
    try:
        os.environ.update({"HUBSPOT_TOKEN": "x", "BQ_PROJECT": "p", "BQ_DATASET": "hubspot", "DELIVERY_WEBHOOK_URL": "https://n8n.example/webhook/x"}); main.HubSpot, main.bq = FakeHubSpot, (lambda: bqc)
        with APP.test_request_context("/?entity=SEALSQ"):
            from flask import request
            payload, code = main.new_deals_report(request)
    finally:
        main.requests, main.time.sleep = real_requests, real_sleep; os.environ.pop("DELIVERY_WEBHOOK_URL", None)
    assert code == 200 and "503" in payload["delivery_error"]
    i = next(i for i, q in enumerate(bqc.sql) if q.startswith("UPDATE `p.hubspot.new_deals_runs` SET status = @st"))
    j = next(j for j, q in enumerate(bqc.sql) if "SET watermark = @ts" in q)
    assert bqc.params[i]["st"] == "OK_DELIVERY_FAILED" and "503" in bqc.params[i]["err"] and bqc.params[i]["e"] == "SEALSQ" and i > j and "AND status = 'OK'" in bqc.sql[i], "amended after the watermark, on the OK row the procedure wrote"


def test_failure_after_the_call_marks_the_procedures_row_failed_and_keeps_the_window():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), fail_read=True); err = _invoke(bqc, "entity=SEALSQ", raises=True)
    assert "503" in str(err) and bqc.called
    assert not any("SET watermark" in q for q in bqc.sql), "the read-back failed before the watermark moved: the window stays replayable"
    i = next(i for i, q in enumerate(bqc.sql) if q.startswith("UPDATE `p.hubspot.new_deals_runs` SET status = @st")); assert bqc.params[i]["st"] == "FAILED" and "503" in bqc.params[i]["err"]
    assert not bqc.runs_rows() and any("SET lock_until = NULL" in q for q in bqc.sql), "the procedure's OK row is amended, not duplicated; the lease is released"


def test_call_failure_without_a_row_writes_the_failed_row_here():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), fail_call="no_row", replaced=True); err = _invoke(bqc, "entity=SEALSQ", raises=True)
    assert "Routine" in str(err) and not bqc.called
    rows = bqc.runs_rows(); assert len(rows) == 1 and rows[0][1]["status"] == "FAILED" and rows[0][1]["data_gaps"] == ["raw_slice_replaced"] and rows[0][1]["mode"] == "window"
    assert not any(q.startswith("UPDATE `p.hubspot.new_deals_runs`") for q in bqc.sql) and any("SET lock_until = NULL" in q for q in bqc.sql)


def test_payload_rows_are_json_strings_and_history_is_the_contract():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=SEALSQ")
    r1 = next(r for r in payload["rows"] if r["deal_id"] == "1")
    assert r1["createdate"] == "2026-10-01T10:00:00+00:00" and r1["closedate"] == "2027-03-31" and r1["first_seen_run"] == NOW.isoformat(), r1
    assert all(not isinstance(v, datetime) for r in payload["rows"] for v in r.values()), "a datetime in the payload would fail JSON rendering outside the try"
    assert _cols("new_deals_history")[3:] == SCHEMA_COLS[1:] and _cols("new_deals_history")[:3] == ["run_ts", "entity", "orchestrator"], "history minus (run_ts, orchestrator) is exactly the 31-column row contract, in order"
    q = next(q for q in bqc.sql if "FROM `p.hubspot.new_deals_history`" in q); assert q.startswith("SELECT * EXCEPT(run_ts, orchestrator) FROM") and q.endswith("ORDER BY amount_kusd DESC, deal_id")


# ---------------------------------------------------------------- the root landing keeps its phase-1 invariants

def test_landing_lands_the_whole_search_with_ddl_columns():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=SEALSQ")
    (raw,) = bqc.loaded("deals_raw"); by_id = {r["deal_id"]: r for r in raw}
    assert set(by_id) == {"1", "2", "3"} and by_id["1"]["in_scope"] is True and by_id["3"]["in_scope"] is True and by_id["2"]["in_scope"] is False
    assert {(r["entity"], r["orchestrator"], r["mode"], r["source"]) for r in raw} == {("SEALSQ", main.ORCHESTRATOR, "window", "hubspot_api")}
    assert {r["run_ts"] for r in raw} == {payload["run_timestamp"]} and set(raw[0]) == set(_cols("deals_raw"))
    (labels,) = bqc.loaded("labels_raw"); assert set(labels[0]) == set(_cols("labels_raw")) and {(r["kind"], r["id"], r["label"]) for r in labels} >= {("pipeline", "12096408", "SealSQ Hardware"), ("stage", "s1", "Discovery"), ("owner", "7", "Ada")}
    r1 = by_id["1"]; assert isinstance(r1["properties"], dict) and r1["properties"] == FakeHubSpot.DEALS[0]["properties"], "a json.dumps() string would land as a JSON scalar"
    assert "hs_lastmodifieddate" in main.PROPS and len(main.PROPS) == 29


def test_window_relanding_replaces_the_whole_older_slice_strictly():
    import os
    os.environ.update({"BQ_PROJECT": "p", "BQ_DATASET": "hubspot"})
    bqc = FakeBQ()
    main.land_raw(bqc, FakeHubSpot.DEALS[:2], {"1"}, "SEALSQ", NOW, "window"); main.land_raw(bqc, FakeHubSpot.DEALS[:1], {"1"}, "SEALSQ", NOW, "window")
    first, second = bqc.loaded("deals_raw")
    f1 = max(datetime.fromisoformat(r["fetched_at"]) for r in first); f2 = datetime.fromisoformat(second[0]["fetched_at"])
    deletes = [(q, p) for q, p in zip(bqc.sql, bqc.params) if q.startswith("DELETE FROM `p.hubspot.deals_raw`")]
    assert len(deletes) == 2 and f2 > f1 and deletes[1][1]["f"] == f2 and "ids" not in deletes[0][1] and not deletes[0][0].endswith("UNNEST(@ids)")
    assert "AND mode = @m" in deletes[0][0] and deletes[0][1]["m"] == "window", "a dry landing in the same second never deletes a live slice (and vice versa)"
    for t in ("deals_raw", "labels_raw"):
        bqc2 = FakeBQ(watermark=NOW - timedelta(days=7)); _invoke(bqc2, "entity=SEALSQ")
        i = next(i for i, q in enumerate(bqc2.sql) if q.startswith(f"DELETE FROM `p.hubspot.{t}`"))
        assert bqc2.first("load", t) < bqc2.calls.index(("query", bqc2.sql[i])), f"{t}: load first, delete-older second"


def test_landing_and_call_jobs_are_time_boxed():
    import os
    os.environ["LAND_TIMEOUT_S"] = "7"; os.environ["CALL_TIMEOUT_S"] = "11"
    try:
        bqc = FakeBQ(watermark=NOW - timedelta(days=7)); _invoke(bqc, "entity=SEALSQ")
    finally: os.environ.pop("LAND_TIMEOUT_S"); os.environ.pop("CALL_TIMEOUT_S")
    assert bqc.raw_timeouts == [7, 7, 7, 7, 11], bqc.raw_timeouts   # 2 loads + 2 deletes + the CALL


def test_failed_row_survives_a_table_without_data_gaps():
    class Boom(FakeHubSpot):
        def search_created(self, start, end): raise RuntimeError("429 HubSpot")
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), no_gaps_column=True); main.HubSpot = Boom
    try:
        import os; os.environ.update({"HUBSPOT_TOKEN": "x", "BQ_PROJECT": "p", "BQ_DATASET": "hubspot"}); main.bq = lambda: bqc
        with APP.test_request_context("/?entity=SEALSQ"):
            from flask import request
            try: main.new_deals_report(request)
            except RuntimeError: pass
    finally: main.HubSpot = FakeHubSpot
    rows = bqc.runs_rows(); assert len(rows) == 2 and "data_gaps" in rows[0][0] and "data_gaps" not in rows[1][0] and rows[1][1]["status"] == "FAILED"


def test_every_table_main_writes_is_created_by_the_ddl_or_a_routine():
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS `\$\{PROJECT\}\.\$\{DATASET\}\.([a-z_]+)`", DDL))
    routines = set()
    for f in (ROOT / "sql").glob("*.sql"): routines |= set(re.findall(r"CREATE OR REPLACE (?:PROCEDURE|TABLE FUNCTION) `\$\{PROJECT\}\.\$\{DATASET\}\.([a-z_]+)`", f.read_text()))
    src = (ROOT / "cloud_function_new_deals/main.py").read_text()
    named = set(re.findall(r"table\([\"']([a-z_]+)[\"']\)", src))
    assert {"deals_raw", "labels_raw", "new_deals_batch", "new_deals_batch_rows", "new_deals_history", "new_deals_runs", "report_state"} <= named, named
    assert "new_deals_staging" not in src and 'table("new_deals")' not in src, "the function no longer writes the sink itself"
    assert named <= created | routines, f"main.py names {named - created - routines} but nothing creates them"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print("ok ", name)
    print("all main.py offline tests passed")

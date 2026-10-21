#!/usr/bin/env python3
"""Offline behaviour tests for cloud_function_new_deals/main.py with a fake HubSpot and a recording fake BigQuery client.

    python3 tests/test_main_offline.py        or        python3 -m pytest tests -q

Proves the scenario-A fixes without credentials: dry mode reads (watermark, warehouse twins) but writes nothing; live mode uses a
per-run staging table and drops it; the MERGE update list excludes the frozen columns; the watermark advances only after the MERGE
and releases the lease; an overlapping run gets 409; the row contract equals the BigQuery schema; duplicate flags across pipelines.
Pass 3 phase 1 (the raw root, in shadow): the extraction lands in deals_raw / labels_raw before anything is shaped from it; a re-landing
of the same key loads first and then deletes the older rows; `properties` lands as the dict; dry does not land; a landing failure never
fails the run and is named in new_deals_runs.data_gaps; event mode lands its one deal with mode = 'event'.
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
    """Column names of one CREATE TABLE block of the DDL, in order."""
    body = re.search(r"`\$\{PROJECT\}\.\$\{DATASET\}\." + table + r"` \((.*?)\)\n(?:PARTITION|CLUSTER|OPTIONS|;)", DDL, re.S).group(1)
    return re.findall(r"^\s*([a-z0-9_]+) (?:" + TYPES + ")", body.replace(",", ",\n"), re.M)


SCHEMA_COLS = _cols("new_deals")


from google.cloud import bigquery  # noqa: E402

def _Field(name): return bigquery.SchemaField(name, "JSON" if name == "properties" else "TIMESTAMP" if name.endswith(("_run", "run_ts", "createdate", "_at")) else "STRING")


class _Job:
    def __init__(self, rows=None, affected=None): self._rows = rows or []; self.num_dml_affected_rows = affected
    def result(self): return self._rows


class FakeBQ:
    """Records every SQL/load call (self.calls keeps the order across kinds); emulates report_state and the lease.
    fail_landing=True makes the deals_raw load raise, as a BigQuery error would."""
    def __init__(self, watermark=None, locked=False, known=None, fail_landing=False):
        self.sql, self.params, self.loads, self.deleted, self.inserted, self.calls = [], [], [], [], [], []
        self.watermark, self.locked, self.known, self.fail_landing = watermark, locked, known or [], fail_landing
        self.project = "p"
    def query(self, q, job_config=None):
        params = {p.name: getattr(p, "value", getattr(p, "values", None)) for p in (job_config.query_parameters if job_config else [])}
        self.sql.append(q); self.params.append(params); self.calls.append(("query", q))
        if "SELECT watermark FROM" in q: return _Job([{"watermark": self.watermark}] if self.watermark else [])
        if "SET lock_until = TIMESTAMP_ADD" in q:
            if self.locked: return _Job(affected=0)
            self.locked = True; return _Job(affected=1)
        if "SELECT deal_id, name_key FROM" in q: return _Job([{"deal_id": d, "name_key": k} for k, d in self.known])
        if "SET watermark = @ts" in q: self.watermark = params["ts"]; self.locked = False
        return _Job()
    def get_table(self, name):
        short = name.rsplit(".", 1)[-1]
        cols = {"new_deals_history": ["run_ts", "orchestrator", *SCHEMA_COLS], "deals_raw": _cols("deals_raw"), "labels_raw": _cols("labels_raw")}.get(short, SCHEMA_COLS)
        class T: schema = [_Field(c) for c in cols]
        return T()
    def load_table_from_json(self, rows, dest, job_config=None):
        if self.fail_landing and dest.endswith("deals_raw"): raise RuntimeError("403 Access Denied: Table deals_raw")
        self.loads.append((dest, list(rows), job_config.write_disposition)); self.calls.append(("load", dest)); return _Job()
    def delete_table(self, name, not_found_ok=False): self.deleted.append(name); self.calls.append(("drop", name))
    def insert_rows_json(self, dest, rows): self.inserted.append((dest, rows)); return []
    # helpers for the assertions
    def loaded(self, table): return [rows for d, rows, _ in self.loads if d.endswith(table)]
    def first(self, kind, needle): return next(i for i, (k, t) in enumerate(self.calls) if k == kind and needle in t)
    def runs_row(self):
        i = next(i for i, q in enumerate(self.sql) if q.lstrip().startswith("INSERT INTO `p.hubspot.new_deals_runs`")); return self.sql[i], self.params[i]


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


def _invoke(bqc, query, monkeypatch=None, body=None):
    import os
    os.environ.update({"HUBSPOT_TOKEN": "x", "BQ_PROJECT": "p", "BQ_DATASET": "hubspot"}); os.environ.pop("DELIVERY_WEBHOOK_URL", None)
    main.HubSpot, main.bq = FakeHubSpot, (lambda: bqc)
    with APP.test_request_context(f"/?{query}", method="POST" if body else "GET", json=body):
        from flask import request
        return main.new_deals_report(request)


def test_row_contract_equals_schema():
    assert len(SCHEMA_COLS) == 31, SCHEMA_COLS
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=SEALSQ&dry_run=1")
    assert code == 200 and payload["rows"], payload
    assert set(payload["rows"][0]) == set(SCHEMA_COLS), set(payload["rows"][0]) ^ set(SCHEMA_COLS)


def test_dry_reads_but_writes_nothing():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), known=[("lattice", "999")])
    payload, code = _invoke(bqc, "entity=SEALSQ&dry_run=1")
    assert code == 200 and payload["dry_run"] is True and payload["rows_written"] == 0
    assert any("SELECT watermark" in q for q in bqc.sql) and any("name_key" in q for q in bqc.sql), "dry run must read like a live run"
    assert not bqc.loads and not any(q.lstrip().startswith(("MERGE", "UPDATE", "INSERT", "DELETE")) for q in bqc.sql), bqc.sql
    assert payload["window"]["watermark_in"].startswith("2026-09-28"), payload["window"]
    r1 = next(r for r in payload["rows"] if r["deal_id"] == "1")
    assert r1["duplicate_suspect"] and "2" in r1["duplicate_of"] and "999" in r1["duplicate_of"], r1  # twin in batch (other pipeline) + twin in warehouse


def test_live_uses_per_run_staging_and_frozen_update_list():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=SEALSQ")
    assert code == 200 and payload["rows_written"] == 2 and payload["dry_run"] is False
    staging = [d for d, _, _ in bqc.loads if "new_deals_staging_sealsq_" in d]
    assert len(staging) == 1 and staging[0] in bqc.deleted, (bqc.loads, bqc.deleted)
    merge = next(q for q in bqc.sql if q.lstrip().startswith("MERGE `p.hubspot.new_deals`"))
    upd = merge.split("UPDATE SET")[1].split("WHEN NOT MATCHED")[0]
    for frozen in ("deal_id =", "first_seen_run =", "day1_hot_score =", "day1_hot_flag ="): assert frozen not in upd, frozen
    assert "duplicate_suspect = s.duplicate_suspect" in upd
    order = [i for i, q in enumerate(bqc.sql) if q.lstrip().startswith("MERGE `p.hubspot.new_deals`") or "SET watermark = @ts" in q]
    assert len(order) == 2 and order[0] < order[1], "watermark must advance after the MERGE"
    assert bqc.locked is False and bqc.watermark is not None
    hist = [d for d, _, _ in bqc.loads if d.endswith("new_deals_history")]; assert hist, "history slice written"
    runlog = [q for q in bqc.sql if q.lstrip().startswith("INSERT INTO `p.hubspot.new_deals_runs`")]
    assert len(runlog) == 1 and "@status" in runlog[0] and "@orchestrator" in runlog[0], "one run-log row via a query INSERT (not a streaming insert)"


def test_overlapping_run_gets_409_and_writes_nothing():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), locked=True); payload, code = _invoke(bqc, "entity=ICALPS")
    assert code == 409 and not bqc.loads and not any(q.lstrip().startswith(("INSERT", "MERGE `p.hubspot.new_deals`")) for q in bqc.sql)


def test_event_mode_never_touches_watermark():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=ICALPS", body={"mode": "event", "objectId": "2", "entity": "ICALPS"})
    assert code == 200 and payload["window"]["mode"] == "event" and payload["rows_written"] == 1
    assert not any("SET watermark" in q or "lock_until = TIMESTAMP_ADD" in q for q in bqc.sql)


def test_first_run_without_watermark_uses_first_run_days():
    bqc = FakeBQ(watermark=None); payload, code = _invoke(bqc, "entity=SEALSQ&dry_run=1")
    assert code == 200 and payload["window"]["watermark_in"] is not None


def test_every_table_main_writes_is_in_the_schema_ddl():
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS `\$\{PROJECT\}\.\$\{DATASET\}\.([a-z_]+)`", DDL))
    src = (ROOT / "cloud_function_new_deals/main.py").read_text()
    named = {n for n in re.findall(r"table\(\"([a-z_]+)\"\)", src) if not n.startswith("new_deals_staging")}
    assert {"deals_raw", "labels_raw"} <= named, "phase 1 lands in the two raw tables"
    assert named <= created, f"main.py writes {named - created} but deploy.sh tables does not create them"


# ---------------------------------------------------------------- pass 3 phase 1: the raw root, in shadow

def test_landing_precedes_shaping_and_lands_the_whole_search():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=SEALSQ")
    assert code == 200 and payload["rows_written"] == 2
    assert bqc.first("load", "deals_raw") < bqc.first("load", "labels_raw") < bqc.first("load", "new_deals_staging_sealsq_") < bqc.first("query", "MERGE `p.hubspot.new_deals`"), bqc.calls
    (raw,) = bqc.loaded("deals_raw")
    by_id = {r["deal_id"]: r for r in raw}
    assert set(by_id) == {"1", "2", "3"}, "in-scope deals AND the out-of-scope duplicate candidate land"
    assert by_id["1"]["in_scope"] is True and by_id["3"]["in_scope"] is True and by_id["2"]["in_scope"] is False
    assert {(r["entity"], r["orchestrator"], r["mode"], r["source"]) for r in raw} == {("SEALSQ", main.ORCHESTRATOR, "window", "hubspot_api")}
    assert by_id["1"]["createdate"] == "2026-10-01T10:00:00Z" and by_id["1"]["pipeline_id"] == "12096408"
    assert {r["run_ts"] for r in raw} == {payload["run_timestamp"]}, "the slice key is the run's own run_ts"
    (labels,) = bqc.loaded("labels_raw")
    assert {(r["kind"], r["id"], r["label"]) for r in labels} >= {("pipeline", "12096408", "SealSQ Hardware"), ("stage", "s1", "Discovery"), ("owner", "7", "Ada")}
    assert set(raw[0]) == set(_cols("deals_raw")) and set(labels[0]) == set(_cols("labels_raw")), "landed rows carry exactly the DDL columns"


def test_same_run_ts_relanding_loads_first_then_deletes_older_rows():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); _invoke(bqc, "entity=SEALSQ")
    for t in ("deals_raw", "labels_raw"):
        i = next(i for i, q in enumerate(bqc.sql) if q.startswith(f"DELETE FROM `p.hubspot.{t}`"))
        assert "run_ts = @ts AND entity = @e AND orchestrator = @o AND fetched_at < @f" in bqc.sql[i], bqc.sql[i]
        p = bqc.params[i]; assert p["e"] == "SEALSQ" and p["o"] == main.ORCHESTRATOR and isinstance(p["f"], datetime) and p["f"].tzinfo is not None
        assert bqc.first("load", t) < bqc.calls.index(("query", bqc.sql[i])), f"{t}: the load comes first, the delete-older second, so a failure between the two never leaves an empty slice"
    (raw,) = bqc.loaded("deals_raw"); fetched = datetime.fromisoformat(raw[0]["fetched_at"])
    assert fetched == bqc.params[next(i for i, q in enumerate(bqc.sql) if q.startswith("DELETE FROM `p.hubspot.deals_raw`"))]["f"], "the rows carry the same fetched_at the delete compares against"


def test_landed_properties_is_the_payload_dict_not_a_string():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); _invoke(bqc, "entity=SEALSQ")
    (raw,) = bqc.loaded("deals_raw"); r1 = next(r for r in raw if r["deal_id"] == "1")
    assert isinstance(r1["properties"], dict) and r1["properties"] == FakeHubSpot.DEALS[0]["properties"], "a json.dumps() string would land as a JSON scalar and every JSON_VALUE would read NULL"
    assert "hs_lastmodifieddate" in main.PROPS and len(main.PROPS) == 29


def test_dry_does_not_land():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=SEALSQ&dry_run=1")
    assert code == 200 and not bqc.loaded("deals_raw") and not bqc.loaded("labels_raw") and not any("deals_raw" in q or "labels_raw" in q for q in bqc.sql)


def test_landing_failure_is_non_fatal_and_named_in_data_gaps():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), fail_landing=True); payload, code = _invoke(bqc, "entity=SEALSQ")
    assert code == 200 and payload["rows_written"] == 2 and "delivery_error" not in payload, "phase-1 shadow: the run passes as before"
    assert not bqc.loaded("deals_raw") and not bqc.loaded("labels_raw"), "labels are not landed without the deals slice"
    q, p = bqc.runs_row()
    assert "data_gaps" in q and "@data_gaps" in q and isinstance(p["data_gaps"], list) and "raw_landing_failed" in p["data_gaps"], (q, p)
    assert "dedup_scope_batch_only" in p["data_gaps"], "an empty warehouse twin map is a named gap too"


def test_runs_row_carries_data_gaps_array_on_a_clean_run():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7), known=[("lattice", "999")]); _invoke(bqc, "entity=SEALSQ")
    q, p = bqc.runs_row()
    assert p["data_gaps"] == [], p   # nothing to name: landing OK, warehouse twins read
    assert "@data_gaps" in q and "ArrayQueryParameter" not in q


def test_event_mode_lands_its_one_deal_with_mode_event():
    bqc = FakeBQ(watermark=NOW - timedelta(days=7)); payload, code = _invoke(bqc, "entity=ICALPS", body={"mode": "event", "objectId": "2", "entity": "ICALPS"})
    assert code == 200 and payload["rows_written"] == 1
    (raw,) = bqc.loaded("deals_raw")
    assert len(raw) == 1 and raw[0]["deal_id"] == "2" and raw[0]["mode"] == "event" and raw[0]["in_scope"] is True
    q, p = bqc.runs_row(); assert "event_no_window" in p["data_gaps"] and "@mode" in q


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print("ok ", name)
    print("all main.py offline tests passed")

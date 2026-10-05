#!/usr/bin/env python3
"""Offline behaviour tests for cloud_function_new_deals/main.py with a fake HubSpot and a recording fake BigQuery client.

    python3 tests/test_main_offline.py        or        python3 -m pytest tests -q

Proves the scenario-A fixes without credentials: dry mode reads (watermark, warehouse twins) but writes nothing; live mode uses a
per-run staging table and drops it; the MERGE update list excludes the frozen columns; the watermark advances only after the MERGE
and releases the lease; an overlapping run gets 409; the row contract equals the BigQuery schema; duplicate flags across pipelines.
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
SCHEMA_COLS = re.findall(r"^\s*([a-z0-9_]+) (?:STRING|TIMESTAMP|FLOAT64|DATE|BOOL)", re.search(r"new_deals` \((.*?)\)\nPARTITION", (ROOT / "cloud_function_new_deals/bigquery_schema.sql").read_text(), re.S).group(1).replace(",", ",\n"), re.M)


from google.cloud import bigquery  # noqa: E402

def _Field(name): return bigquery.SchemaField(name, "TIMESTAMP" if name.endswith(("_run", "run_ts", "createdate")) else "STRING")


class _Job:
    def __init__(self, rows=None, affected=None): self._rows = rows or []; self.num_dml_affected_rows = affected
    def result(self): return self._rows


class FakeBQ:
    """Records every SQL/load call; emulates report_state and the lease."""
    def __init__(self, watermark=None, locked=False, known=None):
        self.sql, self.loads, self.deleted, self.inserted = [], [], [], []
        self.watermark, self.locked, self.known = watermark, locked, known or []
        self.project = "p"
    def query(self, q, job_config=None):
        self.sql.append(q)
        params = {p.name: p.value for p in (job_config.query_parameters if job_config else [])}
        if "SELECT watermark FROM" in q: return _Job([{"watermark": self.watermark}] if self.watermark else [])
        if "SET lock_until = TIMESTAMP_ADD" in q:
            if self.locked: return _Job(affected=0)
            self.locked = True; return _Job(affected=1)
        if "SELECT deal_id, name_key FROM" in q: return _Job([{"deal_id": d, "name_key": k} for k, d in self.known])
        if "SET watermark = @ts" in q: self.watermark = params["ts"]; self.locked = False
        return _Job()
    def get_table(self, name):
        class T: schema = [_Field(c) for c in (SCHEMA_COLS if name.endswith("new_deals") else ["run_ts", "orchestrator", *SCHEMA_COLS])]
        return T()
    def load_table_from_json(self, rows, dest, job_config=None): self.loads.append((dest, list(rows), job_config.write_disposition)); return _Job()
    def delete_table(self, name, not_found_ok=False): self.deleted.append(name)
    def insert_rows_json(self, dest, rows): self.inserted.append((dest, rows)); return []


class FakeHubSpot:
    DEALS = [
        {"id": "1", "properties": {"pipeline": "12096408", "dealname": "Lattice Keystone C0 ASIC - phase 1", "final_customer": "Lattice", "createdate": "2026-10-01T10:00:00Z", "hs_deal_stage_probability": "0.2", "amount_in_home_currency": "16002", "asp_in_usd_q2_2022_calculation": "16002", "closedate": "2027-03-31T00:00:00Z"}},
        {"id": "2", "properties": {"pipeline": "766126206", "dealname": "Lattice Keystone (ICALPS)", "final_customer": "Lattice", "createdate": "2026-10-01T10:03:00Z", "hs_deal_stage_probability": "0.1", "amount": "900"}},
        {"id": "3", "properties": {"pipeline": "13772279", "dealname": "Acme Services", "final_customer": "", "createdate": "2026-10-02T10:00:00Z", "hs_deal_stage_probability": "0.5"}},
    ]
    def __init__(self, token): pass
    def search_created(self, start, end): return [d for d in self.DEALS if start <= datetime.fromisoformat(d["properties"]["createdate"].replace("Z", "+00:00")) < end]
    def deal(self, deal_id): return next(d for d in self.DEALS if d["id"] == deal_id)
    def pipelines(self): return {"12096408": "SealSQ Hardware", "13772279": "SealSQ Services", "766126206": "Icalps_hardware"}, {}
    def owners(self): return {}


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
    assert not bqc.loads and not any(q.lstrip().startswith(("MERGE", "UPDATE", "INSERT")) for q in bqc.sql), bqc.sql
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
    import re as _re
    ddl = (ROOT / "cloud_function_new_deals/bigquery_schema.sql").read_text()
    created = set(_re.findall(r"CREATE TABLE IF NOT EXISTS `\$\{PROJECT\}\.\$\{DATASET\}\.([a-z_]+)`", ddl))
    src = (ROOT / "cloud_function_new_deals/main.py").read_text()
    named = set(_re.findall(r"table\(\"([a-z_]+)\"\)", src)) - {"new_deals_staging"}
    named = {n for n in named if not n.startswith("new_deals_staging")}
    assert named <= created, f"main.py writes {named - created} but deploy.sh tables does not create them"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print("ok ", name)
    print("all main.py offline tests passed")

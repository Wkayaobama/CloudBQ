#!/usr/bin/env python3
"""Parity test: the generated n8n Code node (JavaScript) shapes and scores the same deals exactly like main.py's shape().

    python3 tests/test_n8n_code.py      or      python3 -m pytest tests -q

Builds the Code-node source with workflows/src/build_workflow.py, runs it in node behind a tiny shim for n8n's $('Node') API with
the same fake HubSpot deals as tests/test_main_offline.py, and compares every row field with Python (layer L6 parity evidence).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud_function_new_deals")); sys.path.insert(0, str(ROOT / "workflows" / "src")); sys.path.insert(0, str(ROOT / "tests"))
import main  # noqa: E402
import build_workflow  # noqa: E402
from test_main_offline import FakeHubSpot  # noqa: E402

RUN_TS = datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)
SHIM = """
const DATA = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const $ = (name) => { if (!(name in DATA)) throw new Error('shim: no node ' + name); return { first: () => ({ json: DATA[name][0] }), all: () => DATA[name].map((j) => ({ json: j })) }; };
const $input = $('__input__');
const out = (function () { %s })();
process.stdout.write(JSON.stringify(out));
"""


def _norm(r):
    r = dict(r)
    for k in ("first_seen_run", "last_seen_run"): r[k] = r[k][:19]
    return r


def test_code_node_matches_python_shape():
    node = shutil.which("node")
    if not node:
        import pytest; pytest.skip("node not installed")
    hs = FakeHubSpot("x"); pl, st = hs.pipelines(); owners = {"77": "Ada Lovelace"}
    found = hs.search_created(RUN_TS.replace(day=1), RUN_TS)
    deals = [d for d in found if d["properties"]["pipeline"] in main.ENTITIES["SEALSQ"]["pipelines"]]
    others = [d for d in found if d not in deals]
    known = {"lattice": ["999"]}
    py_rows = main.shape(deals, others, "SEALSQ", pl, st, owners, RUN_TS, known)
    py_rows.sort(key=lambda r: (-(r["amount_kusd"] or 0), r["deal_id"]))

    data = {"Params": [{"entity": "SEALSQ", "dry_run": True, "run_ts": "2026-10-05T07:00:00Z", "portal_id": "9201667", "bq_project": "p", "bq_dataset": "hubspot", "overlap_minutes": 5, "first_run_days": 7}],
            "Window": [{"watermark_in": "2026-09-28T07:00:00Z", "query_start": "2026-09-28T06:55:00Z", "query_end": "2026-10-05T07:00:00Z"}],
            "HubSpot search": [{"results": found[:2]}, {"results": found[2:]}],
            "Pipelines": [{"results": [{"id": k, "label": v, "stages": []} for k, v in pl.items()]}],
            "Owners": [{"results": [{"id": 77, "firstName": "Ada", "lastName": "Lovelace"}]}],
            "Recent names": [{"deal_id": "999", "name_key": "lattice"}], "__input__": [{}]}
    out = subprocess.run([node, "-e", SHIM % build_workflow.code_js()], input=json.dumps(data), capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    item = json.loads(out.stdout)[0]["json"]
    js_rows = item["rows"]
    assert len(js_rows) == len(py_rows) == 2
    for py, js in zip(py_rows, js_rows):
        assert _norm(py) == _norm(js), json.dumps({k: (py.get(k), js.get(k)) for k in set(py) | set(js) if py.get(k) != js.get(k)}, default=str)
    assert item["dry_run"] is True and item["row_count"] == 2 and item["duplicate_suspects"] == 1
    assert "JSON_QUERY_ARRAY(PARSE_JSON('''" in item["merge_sql"] and "day1_hot_score = s." not in item["merge_sql"].split("UPDATE SET")[1].split("WHEN NOT")[0]
    assert item["watermark_sql"].startswith("MERGE `p.hubspot.report_state`") and "NEW_DEALS_SEALSQ" in item["watermark_sql"]
    assert "'n8n'" in item["runlog_sql"] and "IF(true, 0, 2)" in item["runlog_sql"]


def test_generated_files_are_current():
    assert build_workflow.main(["--check"]) == 0


if __name__ == "__main__":
    test_code_node_matches_python_shape(); print("ok  code node == python shape()")
    test_generated_files_are_current(); print("ok  generated workflows current")

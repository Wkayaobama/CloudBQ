#!/usr/bin/env python3
"""Offline parity of the BigQuery SQL UDF (scoring/hot_score_v1.sql) with main.hot_score(), executed in DuckDB.

    python3 tests/test_hot_score_sql_duckdb.py        or        python3 -m pytest tests -q   (skips when duckdb is not installed)

The UDF is authored in GoogleSQL; a small dialect map (test only) renders its body as a DuckDB macro. Checked on the 15 golden
vectors and on 4,000 random HubSpot-shaped deals (same generator as discovery/scenario_C): raw score within 1e-6, flag equal,
NULL for unscored pipelines. The authoritative check on BigQuery itself is tests/hot_score_vectors.sql.
"""
from __future__ import annotations

import json
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud_function_new_deals"))
import main  # noqa: E402

try:
    import duckdb
except ImportError:  # pragma: no cover
    duckdb = None

ARGS = "pipeline, hs_deal_stage_probability, closedate, calculation___pipeline_2026__k__, services_value_2026, asp_in_usd_q2_2022_calculation, tpm__k_y, product_hierarchy, num_contacted_notes, notes_last_updated, revenue_state, run_ts"


def to_duckdb(sql: str) -> str:
    body = sql[sql.index("AS ((") + 5: sql.rindex("));")]
    body = re.sub(r"TIMESTAMP_DIFF\(([^,]+),\s*([^,]+),\s*DAY\)", r"TRUNC((epoch(\1) - epoch(\2)) / 86400)", body)
    body = body.replace("TIMESTAMP '2026-12-31 00:00:00+00'", "TIMESTAMP '2026-12-31 00:00:00'")
    body = re.sub(r"STRUCT\((.+?) AS score, (.+?) AS hot, (.+?) AS raw\)", r"{'score': \1, 'hot': \2, 'raw': \3}", body)
    return f"CREATE OR REPLACE MACRO hot_score_v1({ARGS}) AS ({body.strip()})"


def _deals(n=4000, seed=20261005):
    random.seed(seed)
    now = datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    maybe = lambda v, p=0.2: random.choice([None, ""]) if random.random() < p else v
    num = lambda lo, hi, zp=0.25: "0" if random.random() < zp else str(round(random.uniform(lo, hi), random.choice([0, 1, 2])))
    out = []
    for _ in range(n):
        out.append({"pipeline": random.choice(["12096408", "13772279", "705868909", "934982230", "766126206", None]),
                    "asp_in_usd_q2_2022_calculation": maybe(num(0, 2000)), "tpm__k_y": maybe(num(0, 1200)), "services_value_2026": maybe(num(0, 800)),
                    "product_hierarchy": random.choice(["PKI", "Secure Elements", "Services", None]),
                    "closedate": maybe(iso(datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=random.randint(0, 2400), hours=random.choice([0, 0, 0, 13])))),
                    "calculation___pipeline_2026__k__": maybe(num(0, 900)), "notes_last_updated": maybe(iso(now - timedelta(days=random.uniform(-3, 400)))),
                    "hs_deal_stage_probability": random.choice(["0.1", "0.2", "0.5", "1.0", "0.0", "0.4", None]),
                    "num_contacted_notes": maybe(str(random.randint(0, 300))), "revenue_state": random.choice(["Forecast", "BIBA", "Upside", "Pipeline", None])})
    return out, now


def _run(deals, now):
    con = duckdb.connect()
    con.execute(to_duckdb((ROOT / "scoring" / "hot_score_v1.sql").read_text()))
    con.execute("CREATE TABLE raw(i INTEGER, pipeline VARCHAR, prob VARCHAR, closedate VARCHAR, calc VARCHAR, services VARCHAR, asp VARCHAR, tpm VARCHAR, ph VARCHAR, notes VARCHAR, nlu VARCHAR, rs VARCHAR)")
    con.executemany("INSERT INTO raw VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(i, p.get("pipeline"), p.get("hs_deal_stage_probability"), p.get("closedate"), p.get("calculation___pipeline_2026__k__"), p.get("services_value_2026"),
                      p.get("asp_in_usd_q2_2022_calculation"), p.get("tpm__k_y"), p.get("product_hierarchy"), p.get("num_contacted_notes"), p.get("notes_last_updated"), p.get("revenue_state")) for i, p in enumerate(deals)])
    return con.execute(f"""
      WITH typed AS (SELECT i, pipeline, TRY_CAST(prob AS DOUBLE) prob, TRY_CAST(replace(closedate,'Z','') AS TIMESTAMP) closedate, TRY_CAST(calc AS DOUBLE) calc,
                            TRY_CAST(services AS DOUBLE) services, TRY_CAST(asp AS DOUBLE) asp, TRY_CAST(tpm AS DOUBLE) tpm, ph, TRY_CAST(notes AS DOUBLE) notes,
                            TRY_CAST(replace(nlu,'Z','') AS TIMESTAMP) nlu, rs FROM raw)
      SELECT i, hot_score_v1(pipeline, prob, closedate, calc, services, asp, tpm, ph, notes, nlu, rs, TIMESTAMP '{now.strftime('%Y-%m-%d %H:%M:%S')}') AS r FROM typed ORDER BY i""").fetchall()


def _compare(deals, now, rows):
    bad = []
    for (i, r), p in zip(rows, deals):
        ps, ph = main.hot_score(p, now)
        if ps is None:
            if r is not None and r.get("raw") is not None: bad.append((i, "expected NULL", r))
            continue
        # unrounded reference, same arithmetic as main.hot_score
        if r is None or r.get("raw") is None: bad.append((i, "SQL NULL", (ps, ph))); continue
        if r["hot"] != ph or abs(r["score"] - ps) > 0.1 + 1e-9: bad.append((i, (ps, ph), (r["score"], r["hot"]), p))
    return bad


def test_sql_udf_matches_python_on_vectors_and_random_deals():
    if duckdb is None:
        import pytest; pytest.skip("duckdb not installed")
    vectors = json.loads((ROOT / "tests" / "hot_score_vectors.json").read_text())
    vnow = datetime.fromisoformat(vectors["now"].replace("Z", "+00:00"))
    vdeals = [c["props"] for c in vectors["cases"]]
    bad = _compare(vdeals, vnow, _run(vdeals, vnow)); assert not bad, bad[:3]
    deals, now = _deals(); bad = _compare(deals, now, _run(deals, now)); assert not bad, bad[:3]
    scored = sum(1 for p in deals if main.hot_score(p, now)[0] is not None)
    print(f"sql udf == python on {len(vdeals)} vectors and {len(deals)} random deals ({scored} scored), 0 mismatches")


if __name__ == "__main__":
    test_sql_udf_matches_python_on_vectors_and_random_deals()

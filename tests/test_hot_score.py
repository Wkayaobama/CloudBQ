#!/usr/bin/env python3
"""Regression net for the hot score v1 across runtimes.

    python3 tests/test_hot_score.py            # (re)build vectors from main.py, check constants, run the JS port, emit the SQL check
    python3 -m pytest tests -q                 # same as pytest

Checks: (1) the constants in main.py equal scoring/hot_score_v1.constants.json (drift guard); (2) main.hot_score reproduces
tests/hot_score_vectors.json; (3) node scoring/hot_score_v1.mjs gives the same raw score (|Δ| < 1e-9) and the same flag;
(4) writes tests/hot_score_vectors.sql, the bq query that proves the SQL UDF on the same vectors (run it once credentials exist).
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud_function_new_deals"))
import main  # noqa: E402  (imports functions_framework + requests)

NOW = datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)
CONST = json.loads((ROOT / "scoring" / "hot_score_v1.constants.json").read_text())
VEC = ROOT / "tests" / "hot_score_vectors.json"

CASES = [
    ("hw_qualified_big_arr_2027", {"pipeline": "12096408", "hs_deal_stage_probability": "0.2", "closedate": "2027-03-31T00:00:00Z", "calculation___pipeline_2026__k__": "", "asp_in_usd_q2_2022_calculation": "16002", "product_hierarchy": "Secure Elements", "num_contacted_notes": "3", "notes_last_updated": "2026-10-01T10:00:00Z", "revenue_state": "Pipeline"}),
    ("hw_identified_no_data", {"pipeline": "12096408", "hs_deal_stage_probability": "0.1"}),
    ("hw_forecast_2026_mid_arr", {"pipeline": "12096408", "hs_deal_stage_probability": "0.6", "closedate": "2026-11-15T00:00:00Z", "calculation___pipeline_2026__k__": "250", "asp_in_usd_q2_2022_calculation": "400", "num_contacted_notes": "40", "notes_last_updated": "2026-05-01T00:00:00Z", "revenue_state": "Forecast"}),
    ("svc_biba_tpm_fallback", {"pipeline": "13772279", "hs_deal_stage_probability": "0.4", "closedate": "2026-06-30T00:00:00Z", "services_value_2026": "120", "tpm__k_y": "80", "num_contacted_notes": "223", "notes_last_updated": "2026-01-01T00:00:00Z", "revenue_state": "BIBA"}),
    ("svc_missing_2026_far_close", {"pipeline": "13772279", "hs_deal_stage_probability": "0.3", "closedate": "2029-06-30T00:00:00Z", "services_value_2026": "", "asp_in_usd_q2_2022_calculation": "", "num_contacted_notes": "0"}),
    ("pki_small_arr", {"pipeline": "12096408", "hs_deal_stage_probability": "0.5", "product_hierarchy": "PKI", "asp_in_usd_q2_2022_calculation": "15", "calculation___pipeline_2026__k__": "15", "closedate": "2026-12-31T00:00:00Z"}),
    ("pki_mid_arr_boundary_50", {"pipeline": "12096408", "hs_deal_stage_probability": "0.5", "product_hierarchy": "PKI", "asp_in_usd_q2_2022_calculation": "50", "calculation___pipeline_2026__k__": "50"}),
    ("pki_large_arr", {"pipeline": "13772279", "hs_deal_stage_probability": "0.8", "product_hierarchy": "PKI", "asp_in_usd_q2_2022_calculation": "51", "services_value_2026": "51"}),
    ("arr_boundary_100", {"pipeline": "12096408", "hs_deal_stage_probability": "0.2", "asp_in_usd_q2_2022_calculation": "100", "calculation___pipeline_2026__k__": "1"}),
    ("arr_boundary_1000", {"pipeline": "13772279", "hs_deal_stage_probability": "0.2", "asp_in_usd_q2_2022_calculation": "1000", "services_value_2026": "1"}),
    ("arr_over_1000_services_fallback", {"pipeline": "13772279", "hs_deal_stage_probability": "0.9", "services_value_2026": "2500", "num_contacted_notes": "10", "revenue_state": "Forecast", "closedate": "2027-12-31T00:00:00Z"}),
    ("close_2028_decay", {"pipeline": "12096408", "hs_deal_stage_probability": "0.2", "closedate": "2028-06-30T00:00:00Z", "calculation___pipeline_2026__k__": "10", "asp_in_usd_q2_2022_calculation": "900"}),
    ("garbage_numbers", {"pipeline": "12096408", "hs_deal_stage_probability": "n/a", "asp_in_usd_q2_2022_calculation": "abc", "num_contacted_notes": None}),
    ("not_scored_pipeline_wisekey", {"pipeline": "705868909", "hs_deal_stage_probability": "0.9", "asp_in_usd_q2_2022_calculation": "5000"}),
    ("not_scored_pipeline_icalps", {"pipeline": "766126206", "hs_deal_stage_probability": "0.9"}),
]


def _raw(p):
    """Unrounded score from main.py's arithmetic (mirrors hot_score; kept here so the JS/SQL ports are compared at full precision)."""
    score, hot = main.hot_score(p, NOW)
    if score is None:
        return None
    # recompute z exactly as main.hot_score does, to expose the unrounded value
    arr = main._num(p.get("asp_in_usd_q2_2022_calculation")) or main._num(p.get("tpm__k_y")) or main._num(p.get("services_value_2026"))
    if p.get("product_hierarchy") == "PKI": pts = 0.5 if arr < 20 else (1 if arr <= 50 else 2)
    else: pts = 0.5 if arr < 100 else (1 if arr <= 500 else (2 if arr <= 1000 else 3))
    cd = p.get("closedate"); prox = 0.0
    if cd:
        d = datetime.fromisoformat(cd.replace("Z", "+00:00"))
        prox = 1.0 if d.year <= 2026 else max(0.0, 1 - (d - datetime(2026, 12, 31, tzinfo=timezone.utc)).days / 730)
    hw = p.get("pipeline") == "12096408"
    missing = 1.0 if (not main._num(p.get("calculation___pipeline_2026__k__")) if hw else not main._num(p.get("services_value_2026"))) else 0.0
    nlu = p.get("notes_last_updated"); rec = 0.0
    if nlu:
        days = (NOW - datetime.fromisoformat(nlu.replace("Z", "+00:00"))).days; rec = 1.0 if days <= 90 else (0.5 if days <= 180 else 0.0)
    f = {"stage_prob": main._num(p.get("hs_deal_stage_probability")), "proximity_2026": prox, "missing_2026_field": missing,
         "pipeline_conversion": main.CR[p["pipeline"]] / main.CRMAX, "arr_points": pts / 3, "engagement": math.log1p(main._num(p.get("num_contacted_notes"))) / math.log1p(main.MAXC),
         "recency": rec, "not_in_forecast": 0.0 if p.get("revenue_state") in ("Forecast", "BIBA") else 1.0}
    z = sum(main.W[k] * f[k] for k in main.W) + main.BIAS
    return 100 / (1 + math.exp(-z))


def build_vectors() -> dict:
    cases = []
    for cid, p in CASES:
        score, hot = main.hot_score(p, NOW)
        cases.append({"id": cid, "props": p, "expected": {"score": score, "hot": hot, "raw": _raw(p)}})
    return {"now": NOW.isoformat().replace("+00:00", "Z"), "source": "cloud_function_new_deals/main.py hot_score()", "cases": cases}


def test_constants_match_json():
    assert main.W == CONST["weights"]
    assert main.BIAS == CONST["bias"] and main.THRESHOLD == CONST["threshold"] and main.MAXC == CONST["max_contacted_notes"]
    assert main.CR == {k: v["won"] / v["total"] for k, v in CONST["conversion"].items()}


def test_python_reproduces_vectors():
    vectors = json.loads(VEC.read_text()) if VEC.exists() else build_vectors()
    for c in vectors["cases"]:
        score, hot = main.hot_score(c["props"], NOW)
        assert (score, hot) == (c["expected"]["score"], c["expected"]["hot"]), c["id"]


def test_js_port_matches():
    node = shutil.which("node")
    if not node:
        import pytest; pytest.skip("node not installed")
    vectors = json.loads(VEC.read_text())
    out = subprocess.run([node, str(ROOT / "scoring" / "hot_score_v1.mjs"), str(VEC)], check=True, capture_output=True, text=True).stdout
    got = {r["id"]: r for r in json.loads(out)}
    for c in vectors["cases"]:
        e, g = c["expected"], got[c["id"]]
        if e["raw"] is None:
            assert g["raw"] is None and g["hot"] is None, c["id"]
        else:
            assert abs(g["raw"] - e["raw"]) < 1e-9, (c["id"], g["raw"], e["raw"])
            assert g["hot"] == e["hot"], c["id"]
            assert abs(g["score"] - e["score"]) <= 0.1 + 1e-9, (c["id"], g["score"], e["score"])  # 0.1 only at an exact rounding tie


def sql_literal(v, typ="STRING"):
    """Typed NULLs: with bare NULLs a column that is NULL in every row of the UNNEST would be typed INT64 and break the SAFE_CASTs
    and the STRING parameters of the UDF (it happens on live deals, not on the golden vectors). Backslashes are escaped too."""
    return f"CAST(NULL AS {typ})" if v in (None, "") else ("'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'")


def emit_sql(vectors: dict) -> str:
    rows = []
    for c in vectors["cases"]:
        p, e = c["props"], c["expected"]
        rows.append("STRUCT(%s AS id, %s AS pipeline, %s AS prob, %s AS closedate, %s AS calc_2026, %s AS services_2026, %s AS arr, %s AS tpm, %s AS product_hierarchy, %s AS notes, %s AS notes_last_updated, %s AS revenue_state, %s AS exp_score, %s AS exp_hot)" % (
            sql_literal(c["id"]), sql_literal(p.get("pipeline")), sql_literal(p.get("hs_deal_stage_probability")), sql_literal(p.get("closedate")),
            sql_literal(p.get("calculation___pipeline_2026__k__")), sql_literal(p.get("services_value_2026")), sql_literal(p.get("asp_in_usd_q2_2022_calculation")),
            sql_literal(p.get("tpm__k_y")), sql_literal(p.get("product_hierarchy")), sql_literal(p.get("num_contacted_notes")), sql_literal(p.get("notes_last_updated")),
            sql_literal(p.get("revenue_state")), "CAST(NULL AS FLOAT64)" if e["score"] is None else repr(e["score"]), "CAST(NULL AS BOOL)" if e["hot"] is None else str(e["hot"]).upper()))
    return ("-- generated by tests/test_hot_score.py from tests/hot_score_vectors.json; run after scoring/hot_score_v1.sql:\n"
            "--   bq query --use_legacy_sql=false < tests/hot_score_vectors.sql   → every row ok = TRUE\n"
            "WITH v AS (SELECT * FROM UNNEST([\n  " + ",\n  ".join(rows) + "\n]))\n"
            "SELECT id, exp_score, r.score, exp_hot, r.hot,\n"
            "       (exp_score IS NULL AND r.score IS NULL) OR (ABS(r.score - exp_score) <= 0.1 AND r.hot = exp_hot) AS ok\n"
            "FROM v, UNNEST([`${PROJECT}.${DATASET}.hot_score_v1`(pipeline, SAFE_CAST(prob AS FLOAT64), SAFE_CAST(closedate AS TIMESTAMP),\n"
            "       SAFE_CAST(calc_2026 AS FLOAT64), SAFE_CAST(services_2026 AS FLOAT64), SAFE_CAST(arr AS FLOAT64), SAFE_CAST(tpm AS FLOAT64),\n"
            "       product_hierarchy, SAFE_CAST(notes AS FLOAT64), SAFE_CAST(notes_last_updated AS TIMESTAMP), revenue_state, TIMESTAMP '" + vectors["now"].replace("Z", "+00") + "')]) AS r\n"
            "ORDER BY id;\n")


if __name__ == "__main__":
    vectors = build_vectors()
    VEC.write_text(json.dumps(vectors, indent=1) + "\n")
    (ROOT / "tests" / "hot_score_vectors.sql").write_text(emit_sql(vectors))
    print(f"wrote {VEC.relative_to(ROOT)} ({len(vectors['cases'])} cases) and tests/hot_score_vectors.sql")
    test_constants_match_json(); test_python_reproduces_vectors(); test_js_port_matches()
    print("constants OK · python vectors OK · JS port OK (raw |Δ| < 1e-9, flags equal)")

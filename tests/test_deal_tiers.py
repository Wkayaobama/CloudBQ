#!/usr/bin/env python3
"""Pass 2 (L2 tiers): the constants, the SQL and the Python reference agree on edges, labels and binning semantics.

    python3 tests/test_deal_tiers.py     or     python3 -m pytest tests -q

numpy.digitize(x, edges) (right=False) == bisect.bisect_right(edges, x) == BigQuery RANGE_BUCKET(x, edges): the index of the
first edge greater than x. The reference here is the bisect form so the test needs no numpy; the notebook uses numpy.digitize.
"""
from __future__ import annotations

import bisect
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C = json.loads((ROOT / "scoring" / "deal_tiers_v1.constants.json").read_text(encoding="utf-8"))
EDGES, LABELS = C["edges"], C["labels"]
SQL_VIEWS = (ROOT / "sql" / "deal_tiers_v1.sql").read_text(encoding="utf-8")
SQL_APPLY = (ROOT / "sql" / "deal_tiers_apply.sql").read_text(encoding="utf-8")


def tier_index(certainty):
    """Reference binning: None stays None; otherwise bisect_right over the edges (== numpy.digitize == RANGE_BUCKET)."""
    return None if certainty is None else bisect.bisect_right(EDGES, certainty)


def tier_label(certainty, is_closed=False, is_closed_won=False):
    if is_closed_won: return C["closed_labels"]["won"]
    if is_closed: return C["closed_labels"]["lost"]
    i = tier_index(certainty)
    return None if i is None else LABELS[i]


def test_constants_are_coherent():
    assert EDGES == sorted(EDGES) and len(set(EDGES)) == len(EDGES), "edges must be strictly increasing"
    assert len(LABELS) == len(EDGES) + 1, "one label per bucket: below the first edge, between edges, at or above the last"
    assert all(0.0 < e < 1.0 for e in EDGES), "certainty is a fraction (HubSpot stores probabilities as 0-1)"
    assert set(C["hubspot_property"]["options"]) == set(LABELS) | set(C["closed_labels"].values())


def test_reference_binning_semantics():
    cases = {0.0: 0, 0.1: 0, 0.49: 0, 0.5: 1, 0.6: 1, 0.7499: 1, 0.75: 2, 0.8: 2, 0.89: 2, 0.9: 3, 1.0: 3, None: None}
    for x, expected in cases.items():
        assert tier_index(x) == expected, (x, tier_index(x), expected)
    assert tier_label(0.49) == "Tier4_pipeline" and tier_label(0.5) == "Tier3_opportunity"
    assert tier_label(0.75) == "Tier2_opportunity" and tier_label(0.9) == "Tier1_opportunity" and tier_label(1.0) == "Tier1_opportunity"
    assert tier_label(1.0, is_closed=True, is_closed_won=True) == "Closed_won" and tier_label(0.3, is_closed=True) == "Closed_lost"
    assert tier_label(None) is None


def test_sql_uses_the_same_edges_and_labels():
    edges_sql = "[" + ", ".join(repr(e) for e in EDGES) + "]"
    assert SQL_VIEWS.count(f"RANGE_BUCKET(certainty, {edges_sql})") == 2, "both the bin_index column and the label lookup use the constants' edges"
    assert "[" + ", ".join(f"'{l}'" for l in LABELS) + "]" in SQL_VIEWS, "labels array in the constants' order (index = RANGE_BUCKET)"
    for lab in C["closed_labels"].values():
        assert f"'{lab}'" in SQL_VIEWS
    assert "WHEN pipeline_id = '766126206' THEN icalps_oppocertainty ELSE stage_probability END" in SQL_VIEWS
    assert "WHEN certainty IS NULL THEN NULL" in SQL_VIEWS
    assert "WHEN is_closed IS NULL OR is_closed_won IS NULL THEN NULL" in SQL_VIEWS, "an unknown closed state is never tiered (closed-won at 1.0 would read Tier1)"
    assert "retired_at TIMESTAMP" in SQL_VIEWS


def test_apply_script_is_idempotent_and_shadow_safe():
    assert "MERGE `${PROJECT}.${DATASET}.deal_tiers` t" in SQL_APPLY and "ON t.deal_id = b.deal_id" in SQL_APPLY
    assert "IS DISTINCT FROM" in SQL_APPLY, "a changed tier or certainty is the only thing that writes previous_tier / history"
    assert "BEGIN TRANSACTION" in SQL_APPLY and "COMMIT TRANSACTION" in SQL_APPLY
    for name in re.findall(r"DECLARE (\w+)", SQL_APPLY):
        assert name.startswith("v_"), f"{name}: variables carry v_ so no column can shadow them"
    assert "WHERE last_changed_at = v_run_ts" in SQL_APPLY, "history gets the rows of this run only"
    second = re.search(r"WHEN MATCHED THEN\s+UPDATE SET (.*?)\n", SQL_APPLY).group(1)
    assert second.strip() == "computed_at = v_run_ts", f"an unchanged deal must touch computed_at only, else history receives every deal: {second!r}"
    assert "TIMESTAMP_TRUNC(@run_time, SECOND)" in SQL_APPLY, "pass-1 convention: @run_time keys the run, so a replayed run_time rewrites the same slice"
    assert "INTERVAL 36 HOUR" in SQL_APPLY and "RAISE USING MESSAGE" in SQL_APPLY, "freshness guard as in new_deals_weekly.sql"
    assert "v_batch_rows < v_gold_rows / 2" in SQL_APPLY, "row-count guard: a half-empty transfer must not retire the gold table"
    assert "WHEN NOT MATCHED AND b.tier IS NOT NULL THEN" in SQL_APPLY, "never-tiered deals are not inserted"
    assert "WHEN NOT MATCHED BY SOURCE AND t.tier IS NOT NULL THEN" in SQL_APPLY and "retired_at = v_run_ts" in SQL_APPLY, "deals gone from the sync are retired with a history row"
    assert "QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_id" in SQL_APPLY, "one source row per deal even if the transfer appended"


def test_adapter_view_and_apply_order_carry_the_new_columns():
    adapter = (ROOT / "sql" / "deals_synced_v1.sql").read_text(encoding="utf-8")
    for col in ("icalps_oppocertainty", "AS is_closed,", "AS is_closed_won"):
        assert col in adapter, col
    apply = (ROOT / "sql" / "apply.sh").read_text(encoding="utf-8")
    assert apply.index("deals_synced_v1.sql") < apply.index("deal_tiers_v1.sql"), "views before the tier views that read them"


if __name__ == "__main__":
    for t in (test_constants_are_coherent, test_reference_binning_semantics, test_sql_uses_the_same_edges_and_labels, test_apply_script_is_idempotent_and_shadow_safe, test_adapter_view_and_apply_order_carry_the_new_columns):
        t()
    print("deal tiers OK")

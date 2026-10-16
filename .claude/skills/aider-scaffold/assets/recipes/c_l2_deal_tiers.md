/add scoring/deal_tiers_v1.constants.json sql/deal_tiers_v1.sql sql/deal_tiers_apply.sql sql/deals_synced_v1.sql sql/apply.sh tests/test_deal_tiers.py notebooks/l2_deal_tiers.ipynb
/read-only cloud_function_new_deals/main.py scoring/hot_score_v1.constants.json docs/execution_surfaces_l2.yaml CONVENTIONS.md

Pass 2, layer L2: classify every open deal of every pipeline by likelihood to close, from the certainty the pipeline records, into tiers.

Rules:
- One constants file (edges 0.5 / 0.75 / 0.9 as FRACTIONS, labels Tier4_pipeline … Tier1_opportunity, closed labels, certainty source per pipeline: icalps_oppocertainty for 766126206, hs_deal_stage_probability otherwise). The SQL carries the same literals; tests/test_deal_tiers.py fails on drift.
- Binning is numpy.digitize == bisect_right == BigQuery RANGE_BUCKET; NULL certainty → no tier; closed deals → Closed_won / Closed_lost.
- deals_synced_v1 exposes icalps_oppocertainty, is_closed, is_closed_won; deal_certainty_v1 → deal_tiers_v1 → deal_tiers (gold) + deal_tiers_history + deal_tiers_summary_v1; apply.sh applies them after hot_deals_v1.sql.
- deal_tiers_apply.sql is the scheduled MERGE: v_ variables, BEGIN/COMMIT, MERGE on deal_id with IS DISTINCT FROM, history rows for this run's changes only (idempotent).
- The notebook is the lab (lane N): snapshot through main.HubSpot with hs_v2_date_entered_<stage>, fill rates, distributions, digitize, calibration by stage entry, RANGE_BUCKET parity per deal on deal_tiers_lab, equality with the gold table, the property definition and StackSync mapping sheet. It never writes deal_tiers.

# Pass 2 — L2 likelihood tiers: design, evidence, execution surfaces

Layer 1 (`scoring/hot_score_v1`) scores a **new** deal on the completeness of its information. Layer 2 classifies **every open deal of
every pipeline** by its likelihood to close, from the certainty the pipeline actually records, into bins that become tiers. Pass 2 builds
L2 at the warehouse first (BigQuery), proves it from a notebook, and hands the tier back to the CRM through StackSync. Nothing here
changes pass 1. The lane workbook is `docs/EXECUTION_SURFACES_L2.xlsx` (from `docs/execution_surfaces_l2.yaml`); the constants are
`scoring/deal_tiers_v1.constants.json`; the blocks are `sql/deal_tiers_v1.sql`, `sql/deal_tiers_apply.sql`, `notebooks/l2_deal_tiers.ipynb`,
`tests/test_deal_tiers.py`.

## 1. What the CRM holds (hub 9201667, 2026-10-16, through the HubSpot connector)

**Spelling.** The two properties the operator named exist under these internal names:

| Named | Internal name | Type | Filled | Verdict |
|---|---|---|---|---|
| icalps_oppo_Certainty | `icalps_oppocertainty` (label *IcAlps_OppoCertainty*) | number, fraction 0–1 | 799 of 800 Icalps deals (99.9 %) | **the Icalps certainty** |
| Deal_certainty | `icalps_dealcertainty` | **string**, no values | 0 | unusable |
| — | `hs_deal_stage_probability` (*Deal probability*) | number, fraction 0–1, defaults to the stage's probability | 100 % by definition | **the SealSQ certainty** (and every non-Icalps pipeline) |
| — | `win_probability` | number | mirrors `hs_deal_stage_probability` on SealSQ Hardware (all but 5 deals) | a copy, not a signal |
| — | `hs_forecast_probability` | number | 0 | unused |

**Portfolio.** 1,985 deals: SealSQ Hardware 736 · SealSQ Services 308 · Wisekey Services + PKI 140 · SEALCOIN 1 · Icalps_hardware 800
(Wise.Sat and Quantum & AI hold none). Open deals: 426 — SealSQ Hardware 271, SealSQ Services 65, Wisekey Services + PKI 3, SEALCOIN 1, Icalps 86 (85 with a certainty value).

**Scale.** Both certainties are fractions. The operator's "50 % / 75 % / 90 %" are the edges **0.5 / 0.75 / 0.9**.

**Distributions of open deals.** SealSQ Hardware by stage probability: 0.1 → 140, 0.2 → 46, 0.5 → 78, and manual edits 0.3 ×1, 0.7 ×1,
0.75 ×4, 0.9 ×1 (271 open). SealSQ Services: 0.1 → 29, 0.2 → 24, 0.5 → 9, 0.75 ×3 (65). Icalps by `icalps_oppocertainty` (85 open with a
value): 0.0–0.3 → 55, **0.49 → 6**, 0.5 → 10, 0.6–0.7 → 2, 0.75 → 2, 0.8 → 3, 0.9 → 2, 1.0 → 5. Icalps certainty is only loosely tied to
the stage: deals at the Design Win stage (0.8) carry certainties from 0.0 to 1.0.

**Calibration by stage entry** (`hs_v2_date_entered_<stage>`; the won share is over closed deals):

| Pipeline | Stage entered | Stage probability | Entered | Won | Lost | Open | Won share of closed |
|---|---|---|---|---|---|---|---|
| SealSQ Hardware | Qualified | 0.2 | 271 | 19 | 157 | 95 | 10.8 % |
| SealSQ Hardware | Design In | 0.5 | 173 | 26 | 62 | 85 | 29.5 % |
| SealSQ Hardware | Design Win | 1.0 | 61 | 43 | 16 | 2 | **72.9 %** |
| SealSQ Services | Design In | 0.5 | 68 | 28 | 31 | 9 | 47.5 % |
| Icalps | Design In | 0.6 | 31 | 0 | 2 | 29 | too young |
| Icalps | Design Win | 0.8 | 30 | 5 | 1 | 24 | 83 % (6 closed) |

**Two facts that shape the method.** All 325 Icalps closed-won deals carry certainty 1.0 and SealSQ's closed-won carry the stage's 1.0: the
snapshot cannot calibrate on the certainty value, only on stage entry (above) or on property history (a later pass). And six open Icalps
deals sit at exactly 0.49: a 0.5 edge is already a behavioural boundary for those users.

## 2. The binning

| | |
|---|---|
| input | `certainty` = `icalps_oppocertainty` for pipeline 766126206, `hs_deal_stage_probability` otherwise |
| edges | `[0.5, 0.75, 0.9]` |
| bin index | `numpy.digitize(certainty, edges)` = `bisect_right(edges, certainty)` = BigQuery `RANGE_BUCKET(certainty, edges)`: 0 below 0.5, 1 in [0.5, 0.75), 2 in [0.75, 0.9), 3 at or above 0.9; NULL stays NULL |
| labels | 0 `Tier4_pipeline` · 1 `Tier3_opportunity` · 2 `Tier2_opportunity` · 3 `Tier1_opportunity` |
| closed deals | `Closed_won` / `Closed_lost`, never a tier |
| CRM property | `deal_tier_v1`, enumeration with the six labels, group `cloudbq_l2` |

`RANGE_BUCKET` semantics confirmed in BigQuery's reference: a point equal to a boundary returns the index of the next larger value (so 0.5
is Tier3, not Tier4), a point below the first boundary returns 0, at or above the last returns the array length, NULL returns NULL; the
array must be sorted ascending. `tests/test_deal_tiers.py` pins these cases and keeps the SQL literals equal to the constants.

**Decisions taken as defaults, to confirm or change in the constants:**

- D1 — below 0.5 is `Tier4_pipeline` (the operator named three tiers; most open deals fall here: 187 of 271 on SealSQ Hardware, 61 of 85 on Icalps).
- D2 — one edge set for every pipeline. On SealSQ pipelines the stage probabilities (0.1 / 0.2 / 0.5 / 1.0) make `Tier2_opportunity`
  reachable only through a manual probability edit (4 + 3 deals today) and `Tier1_opportunity` only at Design Win. Alternatives: per-pipeline
  edges, or a calibrated certainty (the won shares above) in place of the stage probability.
- D3 — closed deals are labelled, not tiered.
- D4 — a deal without certainty (one open Icalps deal today) has no tier; a deal whose certainty is cleared later, or that is deleted or merged
  in HubSpot, is **retired**: its gold row keeps `previous_tier`, gets `retired_at`, its `tier` becomes NULL and a history row records it.
- D5 — "dynamically updated at deal creation" is met only by lane W (the webhook, with `deal.creation` and the two `deal.propertyChange`
  subscriptions); lane Q re-tiers within a day. Accept the daily cadence for now, or ask for W to be built.

## 3. Execution surfaces — and the orthogonality the operator noticed

| Lane | Surface | Role | Writes |
|---|---|---|---|
| **N** | Vertex AI Workbench notebook `notebooks/l2_deal_tiers.ipynb` | the lab: CRM snapshot through the function's `HubSpot` client, fill rates, distributions, `numpy.digitize`, calibration, per-deal proof that `RANGE_BUCKET` agrees | `deal_tiers_lab` only |
| **Q** | BigQuery-native: `sql/deal_tiers_v1.sql` views + `sql/deal_tiers_apply.sql` scheduled MERGE over the daily HubSpot → BigQuery transfer | production: the operational tier, daily | `deal_tiers` (gold), `deal_tiers_history` |
| **W** | HubSpot `deal.propertyChange` webhook → the Cloud Run function's event path → MERGE one deal | event: minutes instead of a day | the same gold tables |
| hand-off | StackSync, BigQuery → HubSpot, source table `deal_tiers`, match `deal_id` ↔ Record ID, `tier` → `deal_tier_v1` | the single writer to the CRM | the CRM property |

The notebook is orthogonal to the Cloud Shell runbook on purpose: it is where the bins are *justified* (statistics, calibration), fast to
iterate, and it never writes the gold table. Lane Q is the same kind of surface as pass 1's Cloud Shell steps (`sql/apply.sh`, a scheduled
query), so the operator's runbook habits carry over. The workbook makes the lanes comparable layer by layer: the arithmetic (M5), the labels
(M6) and the source resolution (M4) are the same between N and Q in evidence (one constants file; step 7 proves `RANGE_BUCKET` ≡ `digitize`
per deal) and the workbook marks them **Conditional** only because W is not written yet; the idempotency mechanisms differ (truncate of a lab
table vs MERGE into the gold table, **Divergent**, reconciled by equality check 2); source, trigger, identity, freshness and cost are
**Divergent**; the gold write and the write-back are **Conditional** on the sync and on the property existing. Steps 1 (constants) and 7
(the per-deal parity proof) are the two **Parallel** rows.

**The "watcher".** In lane Q no watcher is needed: the daily transfer carries every edit, the MERGE re-tiers whatever changed (writing
`previous_tier` and a history row for changed deals only) and retires what lost its certainty or left the sync. In lane W the watcher *is*
the webhook, and the list of watched properties lives once in `constants.watch_properties`: for Icalps `icalps_oppocertainty` and
`dealstage`, for every other pipeline `dealstage` (the stage sets the probability) and `hs_deal_stage_probability` (manual edits), plus
`deal.creation` so a new deal is tiered at birth. HubSpot's classic subscriptions take one property per subscription (`subscriptionType`
`deal.propertyChange`, `propertyName`); deliveries arrive as a JSON **array** of events with `objectId`, `propertyName`, `propertyValue`,
`attemptNumber`. W therefore needs its own route, not the function's `objectId` event path: accept the array, no entity gating, every
pipeline, `GET /crm/v3/objects/deals/{id}` for the certainty, the same constants, the same MERGE for one deal. The function is private, so
the route must validate the HubSpot signature on an unauthenticated path, or sit behind the n8n relay of scenario B. W stays proposed until
D5 is decided.

## 4. Storing the bins dynamically — the options, with what the documentation says

| Option | What it is | Verdict |
|---|---|---|
| **Scheduled MERGE into a gold table** (`sql/deal_tiers_apply.sql`) | `deal_tiers_v1` (a view over the sync) → `MERGE deal_tiers` on `deal_id`, `IS DISTINCT FROM` on tier/certainty, `WHEN NOT MATCHED BY SOURCE` retires deals gone from the sync, history rows for changes and retirements only; guarded by the 36 h freshness rule and a row-count rule (the batch must hold at least half the gold rows) | **chosen.** Idempotent, keyed on `@run_time`, pennies, a *table* (StackSync reads tables only), carries `previous_tier`, `retired_at`, `first_tiered_at`, `last_changed_at`, `orchestrator` |
| Materialized view over the synced table | `CREATE MATERIALIZED VIEW … AS SELECT …, RANGE_BUCKET(…)` | not needed and fragile: BigQuery allows a non-aggregate materialized view, but if the transfer drops and recreates its destination table the view breaks and must be recreated; StackSync excludes ordinary and materialized views as sources; and a view holds no history |
| Webhook CDC (lane W) | HubSpot property-change events → function → the same MERGE | the real-time variant of the same materialization; adds a public endpoint, a developer app, signature validation |
| BigQuery CDC (`_CHANGE_TYPE` via the Storage Write API) | row-level upserts streamed into a table | not applicable: the source is a transfer that reloads all available data on every run, not a change stream |

So "CDC watcher + materialized view" becomes: the transfer (daily) or the webhook (event) as the change feed, and the MERGE as the
materialization. The gold layer the tier property is read from is `deal_tiers`; `deal_tiers_summary_v1` is what every surface compares.

## 5. The sequence (lane Q, with the lab beside it)

```bash
D=sql; set -a; . .env; set +a
python3 tests/test_deal_tiers.py                       # 1 constants ↔ SQL ↔ reference binning
# 2 adapter columns are in sql/deals_synced_v1.sql (icalps_oppocertainty, is_closed, is_closed_won)
HUBSPOT_TOKEN=… $D/sync_transfer.sh                    # 3 LIVE TRANSFER — the prerequisite; after the first run: bq ls $SYNC_DATASET, then
set -a; . .env; set +a                                   #   SYNC_DEALS_TABLE / SYNC_OWNERS_TABLE into .env and re-source it (the variables below need it)
bq show --schema --format=prettyjson $PROJECT:$SYNC_DATASET.$SYNC_DEALS_TABLE | grep -E 'icalps_oppocertainty|hs_is_closed'   # the three columns deals_synced_v1 needs — the view fails to create without them
DRYRUN=1 $D/apply.sh && $D/apply.sh                    # 4 LIVE DDL — deal_certainty_v1, deal_tiers_v1, deal_tiers, deal_tiers_history, deal_tiers_summary_v1
# 5–7 the lab: notebooks/l2_deal_tiers.ipynb on the Workbench instance (snapshot, bins, RANGE_BUCKET == digitize per deal)
bq query --use_legacy_sql=false "SELECT * FROM \`$PROJECT.$DATASET.deal_tiers_summary_v1\` ORDER BY 1, 2"      # 6 bins from the sync
RT=$(date -u +%FT%TZ); sed -e "s/\${PROJECT}/$PROJECT/g" -e "s/\${DATASET}/$DATASET/g" $D/deal_tiers_apply.sql | bq query --use_legacy_sql=false --parameter="run_time:TIMESTAMP:$RT"   # 8 LIVE GOLD_WRITE — first backfill
RT=$(date -u +%FT%TZ); sed -e "s/\${PROJECT}/$PROJECT/g" -e "s/\${DATASET}/$DATASET/g" $D/deal_tiers_apply.sql | bq query --use_legacy_sql=false --parameter="run_time:TIMESTAMP:$RT"   #   run twice: the second run adds no history rows
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM \`$PROJECT.$DATASET.deal_tiers_history\` WHERE run_ts = TIMESTAMP '$RT'"                                                              #   → 0
bq query --use_legacy_sql=false "SELECT pipeline_id, tier, COUNT(*) FROM \`$PROJECT.$DATASET.deal_tiers\` GROUP BY 1, 2 ORDER BY 1, 2"   # 9 equality vs the lab and vs the CRM
# 10 LIVE PROPERTY_CREATE — POST /crm/v3/properties/deals with the definition the notebook prints (group dealinformation, like writeback/bootstrap_property.sh; schema-write token, one-off)
# 11 LIVE CRM_WRITE — StackSync UI: source deal_tiers, destination Deals, match deal_id ↔ Record ID, tier → deal_tier_v1, BigQuery → HubSpot
# 12 LIVE SCHEDULE — register deal_tiers_apply.sql as a scheduled query, daily after the 02:00 UTC transfer (DISABLE_SCHEDULE until 8 ran twice cleanly)
```

## 6. Open, in order

1. **Decisions D1–D5** (above). D2 is the one with consequences: with the stage probability as SealSQ's certainty, Tier2 is a manual-edit tier.
   D5 decides whether lane W is built at all.
2. **The first transfer run** — the Deals table's columns are undocumented until then (the connector "transfers all available data"; whether
   custom properties arrive as columns is confirmed by `bq show --schema`). `deals_synced_v1` fails to create if a column is missing.
3. **Scheduling** — `sql/scheduled_query.sh` registers the weekly script only; the daily tier MERGE needs its own registration (one more loop
   or a flag; not written yet).
4. **Lane W** — not written: a dedicated route for HubSpot's array payload (`deal.creation`, `deal.propertyChange` on the watched properties),
   signature validation, the same constants and MERGE. The function's current event path (`objectId`, entity-gated) is not it.
5. **The property and StackSync** — a schema-write token for the one-off creation (extend `writeback/bootstrap_property.sh` for an enumeration, or POST
   the printed JSON); the StackSync source must be the `deal_tiers` *table*; a retired row clears `deal_tier_v1`.
6. **Evidence** — paste the lab's parity line, the summary matrix and the second MERGE's history count here after the first run.

Pass 2 has not run against Google Cloud. Every SQL statement was rendered (`DRYRUN=1 sql/apply.sh`), every test passes, the notebook
compiles; the CRM numbers above are live.

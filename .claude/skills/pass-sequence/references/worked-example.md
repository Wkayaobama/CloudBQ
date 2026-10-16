# Worked examples

## mr-load, pass 2 (execution surfaces: notebook / terminal / Cloud Shell), 2026-09

Produced in order: `docs/PASS2_SEQUENCE.md` (preconditions, the bash block with look/edit inserts,
the branch point API loader vs import wizard, the probe as evidence), `docs/EXECUTION_SURFACES.md`
(timeline rows citing `6f38600`, `765cd01`, `6abaf18`), `docs/execution_surfaces.yaml` →
`docs/EXECUTION_SURFACES.xlsx` (Layers 16 rows 8/4/4 Parallel/Conditional/Divergent; Pipeline steps
21 rows 14/7/0; Remediation R01–R25; 13 equality checks), the run sheet `notebooks/mr-load-run.dib`.
The probe that closed the reconciliation was a `bq query` over the materialised import tables from
Cloud Shell, read column by column. Builder round trip on 2026-10-05 in a fresh sandbox:
`--verify OK`, `--compare identical values`.

## CloudBQ, pass 1 (scenarios as lanes: Cloud Run function / n8n on Cloud Run / BigQuery + remote JS), 2026-10

The columns are candidate orchestrators for one outcome; the layers are the fixed list L0–L17.
Pass 1 = the scenario-A deploy sequence (service account → grants → secret → tables → deploy →
dry run on both entities → first live run → schedulers), recorded before any run with the operator's
risk table as remediation seeds (R01 DCL quoting, R02 run.invoker, R03 watermark race, R04 `:latest`
pin, R05 deploy syntax) and the per-layer lane cells from the discovery analysts. Parity words at
this stage encode expectations; every row is re-decided after the first run on a second lane.
Numbers worth pinning when the first run happens: rows per entity in `hubspot.new_deals`, the two
watermarks, `duplicate_suspects`, the `day1_hot` list, and the hot score of one deal across runtimes.
Obtain by running; never compose.

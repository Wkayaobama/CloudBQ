# The three lanes, condensed

One outcome — every Monday, the deals created since the last run land in `hubspot.new_deals` with a day-1 hot score and a
duplicate flag, and a report goes out — three ways to get there. The lane matrix (`docs/EXECUTION_SURFACES.xlsx`) decides parity
per layer; this page says what each lane needs, in which order, and what it cannot do. Sources: `discovery/scenario_{A,B,C}.md`
(skeptic-verified, 2026-10-05).

## A · Cloud Run function (`cloud_function_new_deals/`)

Order: `deploy.sh check-env → enable-apis → iam → tables → secret → deploy → invoker → dry → run → probe → enable`.
What it owns: extraction (exact `createdate` window from the watermark), scoring, shaping, MERGE, watermark, audit, delivery POST.
Needs: a GCP project, a read-only HubSpot private app, an operator with admin roles. Cost: cents per month (scale to zero).
Cannot: write back to HubSpot (read-only token); receive HubSpot webhooks while private (event mode not deployed).
Idempotency: immutable `createdate`, half-open window with overlap, MERGE on `deal_id`, watermark after MERGE, per-run staging,
lease per entity, frozen day-1 columns, dry mode that reads.

## B · n8n on Cloud Run (`deploy/n8n/`, `workflows/`)

Two shapes. **B1** (recommended): n8n is only the delivery tail — A posts the payload to `NEW_DEALS_DELIVERY` (Header Auth), n8n
builds the XLSX and sends the email (and a text-only email on a zero-row week). **B2**: n8n owns the whole pipeline
(`NEW_DEALS_FULL`): same window, same scorer (generated Code node, proven equal to Python), same MERGE target and frozen columns,
same watermark table — reached through n8n nodes.
Order: `secrets.sh → cloudsql.sh → deploy_n8n.sh → (UI: owner account, 2FA, credentials) → import_workflows.sh → manual test
execution with ?dry_run=1 → scheduler.sh create → scheduler.sh enable`.
Needs: Cloud SQL (≈ $9/month, the floor), a pinned image, the HubSpot token copied into an n8n credential, an SA key for BigQuery.
Cannot: keep secrets in Secret Manager at runtime (community edition), fire a Schedule Trigger while scaled to zero (hence Cloud
Scheduler → webhook), authenticate keylessly to BigQuery.
Trade: the editor as the operating surface and per-node execution data, against a second copy of everything and seven moving parts.

## C · Hybrid (`sql/`, `writeback/`, Breeze)

Compute in BigQuery over a synced copy of HubSpot deals (Google Data Transfer Service HubSpot connector, Preview, daily full
refresh; or HubSpot's own BigQuery sync on Data Hub Enterprise). `new_deals_weekly.sql` runs window → shape → duplicates → MERGE →
history → run log → state in ONE transaction per entity (report_id `NEW_DEALS_<entity>_C`); `hot_deals_v1` ranks open deals per
region with window functions HubSQL does not have; the Node 22 job PATCHes `hot_score_v1` / `hot_flag_v1` onto deals (100 per
call, never NULL, skip unchanged, 207 parsed, logged per deal) so Breeze and workflows can read the score as a property.
Order: `sync_transfer.sh → (first transfer run; put table names in .env) → sql/apply.sh → refresh_pipeline_labels.sh →
bootstrap_property.sh (schema-write token, once) → scheduled_query.sh (DISABLE_SCHEDULE=1 first; one bq mk --transfer_run) →
writeback/deploy_job.sh → deploy_job.sh execute (dry) → deploy_job.sh live → scheduled_query.sh`.
Needs: a second private app with `crm.objects.deals.write` (`hubspot-token-write`), a one-off `crm.schemas.deals.write` token.
Cannot: see a deal created after the last sync until the next run (no event mode; 36 h freshness guard); let Breeze compute
anything (HubSQL: no arithmetic, no CASE, no window functions) — Breeze reads the written-back properties.
Chain timing: sync 02:00 UTC → scheduled queries Mon 03:53 (SEALSQ) / 04:23 (ICALPS) UTC → write-back Mon 05:30 Europe/Zurich → A's report 07:00/07:20.

## The parallel lane

Whichever orchestrator runs, these are the same: the arithmetic (`scoring/`, pinned by vectors across Python, JS and SQL), the
target table and key (`hubspot.new_deals` ON `deal_id`, frozen day-1 columns), the state semantics (`hubspot.report_state`, advance
only after a successful MERGE), replay (rewind the state row, re-run; MERGE converges), and the audit tables (`new_deals_runs`,
`new_deals_history`). That is the idempotent outcome the lane matrix marks **Parallel**; everything else is Conditional (same result
under a stated condition: same clock, same token scopes, same sync freshness) or Divergent (a different mechanism with a named
remediation).

## Recommendation

Run **A** as the production orchestrator (cheapest, fewest parts, exact window, event path possible later), with **B1** as its
delivery tail, and add **C**'s compute + write-back when the score must be visible inside HubSpot (Breeze, workflows) — C's SQL
and the job are already the same arithmetic and the same tables. Build **B2** only if the n8n editor has to be the operating surface;
its JSON is generated and tested, so that choice costs no re-implementation.

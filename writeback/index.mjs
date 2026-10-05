// new-deals write-back (scenario C, layer L10). Node 22 Cloud Run *job*: no HTTP surface, started by Cloud Scheduler via jobs.run.
// Reads the delta view (rows whose computed hot score differs from what HubSpot holds), PATCHes deals in batches of 100,
// logs one row per deal to writeback_log. Idempotent: a same-value PATCH is a projection (f(f(x)) = f(x)); unchanged rows are
// skipped by the view anyway; a NULL score is never sent (it would clear the property). Gate: WRITEBACK_APPROVE unset → DRY.
import { BigQuery } from '@google-cloud/bigquery';

const { BQ_PROJECT, BQ_DATASET = 'hubspot', HUBSPOT_TOKEN, WRITEBACK_APPROVE, BATCH_PAUSE_MS = '600', MAX_ROWS } = process.env;
if (!BQ_PROJECT) throw new Error('BQ_PROJECT is required');
const DRY = WRITEBACK_APPROVE !== '1';
if (!DRY && !HUBSPOT_TOKEN) throw new Error('HUBSPOT_TOKEN is required when WRITEBACK_APPROVE=1');
const HS = 'https://api.hubapi.com';
const RUN_TS = new Date(); RUN_TS.setUTCMilliseconds(0);
const bq = new BigQuery({ projectId: BQ_PROJECT });
const T = (n) => `\`${BQ_PROJECT}.${BQ_DATASET}.${n}\``;
const log = (o) => console.log(JSON.stringify({ severity: 'INFO', run_ts: RUN_TS.toISOString(), ...o }));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const [rows] = await bq.query({ query: `SELECT deal_id, hot_score_v1, hot_flag_v1, previous_score, previous_flag FROM ${T('hot_deals_v1_writeback')} ORDER BY deal_id${MAX_ROWS ? ` LIMIT ${Number(MAX_ROWS)}` : ''}` });
log({ message: 'candidates', candidates: rows.length, dry_run: DRY });

// POST /crm/v3/objects/deals/batch/update — ≤ 100 inputs; 200 = all written, 207 = partial (errors[] names the ids that failed).
async function patchBatch(batch) {
  const body = { inputs: batch.map((r) => ({ id: String(r.deal_id), properties: { hot_score_v1: String(r.hot_score_v1), hot_flag_v1: r.hot_flag_v1 ? 'true' : 'false' } })) };
  for (let attempt = 1; attempt <= 5; attempt++) {
    const res = await fetch(`${HS}/crm/v3/objects/deals/batch/update`, {
      method: 'POST', headers: { Authorization: `Bearer ${HUBSPOT_TOKEN}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (res.status === 429 || res.status >= 500) {          // honour the rate-limit interval header, then retry with backoff
      const wait = Number(res.headers.get('x-hubspot-ratelimit-interval-milliseconds') || res.headers.get('retry-after') * 1000 || 10000) * attempt;
      console.warn(JSON.stringify({ severity: 'WARNING', message: `HTTP ${res.status}`, attempt, wait_ms: wait }));
      await sleep(Math.min(wait, 60000)); continue;
    }
    const json = await res.json().catch(() => ({}));
    if (res.status === 403) throw new Error(`403 from HubSpot — the token lacks crm.objects.deals.write (${JSON.stringify(json).slice(0, 300)})`);
    const failed = new Set((json.errors || []).flatMap((e) => (e.context?.ids || e.context?.objectIds || []).map(String)));
    return batch.map((r) => ({ ...r, http_status: res.status,
      status: res.ok && !failed.has(String(r.deal_id)) ? 'OK' : 'ERROR',
      error: res.ok ? (failed.has(String(r.deal_id)) ? JSON.stringify(json.errors).slice(0, 1000) : null) : JSON.stringify(json).slice(0, 1000) }));
  }
  return batch.map((r) => ({ ...r, http_status: 0, status: 'ERROR', error: 'retries exhausted' }));
}

const results = [];
for (let i = 0; i < rows.length; i += 100) {
  const batch = rows.slice(i, i + 100);
  results.push(...(DRY ? batch.map((r) => ({ ...r, http_status: null, status: 'DRY', error: null })) : await patchBatch(batch)));
  if (!DRY && i + 100 < rows.length) await sleep(Number(BATCH_PAUSE_MS));   // ≈ 17 calls / 10 s, well under the 190 / 10 s burst limit
}
if (results.length) {
  await bq.dataset(BQ_DATASET).table('writeback_log').insert(results.map((r) => ({
    run_ts: RUN_TS.toISOString(), deal_id: String(r.deal_id), hot_score_v1: r.hot_score_v1, hot_flag_v1: r.hot_flag_v1,
    previous_score: r.previous_score ?? null, previous_flag: r.previous_flag ?? null,
    status: r.status, http_status: r.http_status, error: r.error, dry_run: DRY })));
}
const summary = { message: 'summary', patched: results.filter((r) => r.status === 'OK').length, errors: results.filter((r) => r.status === 'ERROR').length, dry: results.filter((r) => r.status === 'DRY').length };
log(summary);
if (summary.errors) process.exit(1);   // non-zero → Cloud Run retries the task (--max-retries); OK rows are logged, so the retry PATCHes only the rest

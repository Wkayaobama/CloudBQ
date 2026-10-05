// hot_score_v1.mjs — JS port of hot_score() from cloud_function_new_deals/main.py (same constants, same branches).
// Used by the Cloud Run write-back job (scenario C) and as the source of the n8n Code-node snippet (scenario B).
// Verified against tests/hot_score_vectors.json by `python3 tests/test_hot_score.py` (which runs this file with node).
import { readFileSync } from 'node:fs';

export const C = JSON.parse(readFileSync(new URL('./hot_score_v1.constants.json', import.meta.url), 'utf8'));
const CRMAX = Math.max(...Object.values(C.conversion).map(c => c.won / c.total));

const num = (v) => { if (v === null || v === undefined || v === '') return 0; const f = Number(v); return Number.isFinite(f) ? f : 0; };
const daysBetween = (later, earlier) => Math.trunc((later - earlier) / 86400000); // python timedelta.days for positive deltas

/** @returns {{score: number|null, hot: boolean|null, raw: number|null}} score rounded to 1 dp like Python's round(s, 1) */
export function hotScore(p, now = new Date()) {
  const cr = C.conversion[p.pipeline];
  if (!cr) return { score: null, hot: null, raw: null };
  const arr = num(p.asp_in_usd_q2_2022_calculation) || num(p.tpm__k_y) || num(p.services_value_2026);
  const tiers = p.product_hierarchy === 'PKI' ? C.arr_tiers.PKI : C.arr_tiers.default;
  let pts = tiers[tiers.length - 1][1];
  for (const [limit, value] of tiers) {
    if (limit === null) { pts = value; break; }
    const strict = limit === tiers[0][0];           // first tier is "< limit", the rest are "<= limit" (as in main.py)
    if (strict ? arr < limit : arr <= limit) { pts = value; break; }
  }
  let prox = 0;
  if (p.closedate) {
    const d = new Date(p.closedate);
    const horizon = new Date(C.horizon_date + 'T00:00:00Z');
    prox = d.getUTCFullYear() <= 2026 ? 1 : Math.max(0, 1 - daysBetween(d, horizon) / C.horizon_decay_days);
  }
  const hw = p.pipeline === C.hardware_pipeline;
  const missing = (hw ? !num(p.calculation___pipeline_2026__k__) : !num(p.services_value_2026)) ? 1 : 0;
  let rec = 0;
  if (p.notes_last_updated) {
    const days = daysBetween(now, new Date(p.notes_last_updated));
    rec = days <= C.recency_days[0][0] ? C.recency_days[0][1] : (days <= C.recency_days[1][0] ? C.recency_days[1][1] : 0);
  }
  const f = {
    stage_prob: num(p.hs_deal_stage_probability), proximity_2026: prox, missing_2026_field: missing,
    pipeline_conversion: (cr.won / cr.total) / CRMAX, arr_points: pts / C.arr_tier_divisor,
    engagement: Math.log1p(num(p.num_contacted_notes)) / Math.log1p(C.max_contacted_notes),
    recency: rec, not_in_forecast: C.forecast_states.includes(p.revenue_state) ? 0 : 1,
  };
  const z = Object.keys(C.weights).reduce((acc, k) => acc + C.weights[k] * f[k], 0) + C.bias;
  const s = 100 / (1 + Math.exp(-z));
  return { score: Math.round(s * 10) / 10, hot: s >= C.threshold, raw: s };
}

// CLI: node hot_score_v1.mjs tests/hot_score_vectors.json  → prints one JSON line per vector
if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop())) {
  const vectors = JSON.parse(readFileSync(process.argv[2], 'utf8'));
  const now = new Date(vectors.now);
  process.stdout.write(JSON.stringify(vectors.cases.map(c => ({ id: c.id, ...hotScore(c.props, now) }))) + '\n');
}

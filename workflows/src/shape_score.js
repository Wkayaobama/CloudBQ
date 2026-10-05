// shape_score.js — pure functions injected into the n8n Code node by build_workflow.py (no imports; `C` = constants object).
// Port of hot_score(), name_key() and shape() from cloud_function_new_deals/main.py. Verified by tests/test_n8n_code.py
// against the Python implementation on identical inputs.
const num = (v) => { if (v === null || v === undefined || v === '') return 0; const f = Number(v); return Number.isFinite(f) ? f : 0; };
const daysBetween = (later, earlier) => Math.trunc((later - earlier) / 86400000);
const CRMAX = Math.max(...Object.values(C.conversion).map((c) => c.won / c.total));

function hotScore(p, now) {
  const cr = C.conversion[p.pipeline];
  if (!cr) return [null, null];
  const arr = num(p.asp_in_usd_q2_2022_calculation) || num(p.tpm__k_y) || num(p.services_value_2026);
  const tiers = p.product_hierarchy === 'PKI' ? C.arr_tiers.PKI : C.arr_tiers.default;
  let pts = tiers[tiers.length - 1][1];
  for (const [limit, value] of tiers) {
    if (limit === null) { pts = value; break; }
    if (limit === tiers[0][0] ? arr < limit : arr <= limit) { pts = value; break; }
  }
  let prox = 0;
  if (p.closedate) { const d = new Date(p.closedate); prox = d.getUTCFullYear() <= 2026 ? 1 : Math.max(0, 1 - daysBetween(d, new Date(C.horizon_date + 'T00:00:00Z')) / C.horizon_decay_days); }
  const hw = p.pipeline === C.hardware_pipeline;
  const missing = (hw ? !num(p.calculation___pipeline_2026__k__) : !num(p.services_value_2026)) ? 1 : 0;
  let rec = 0;
  if (p.notes_last_updated) { const dd = daysBetween(now, new Date(p.notes_last_updated)); rec = dd <= C.recency_days[0][0] ? C.recency_days[0][1] : (dd <= C.recency_days[1][0] ? C.recency_days[1][1] : 0); }
  const f = { stage_prob: num(p.hs_deal_stage_probability), proximity_2026: prox, missing_2026_field: missing, pipeline_conversion: (cr.won / cr.total) / CRMAX,
    arr_points: pts / C.arr_tier_divisor, engagement: Math.log1p(num(p.num_contacted_notes)) / Math.log1p(C.max_contacted_notes), recency: rec,
    not_in_forecast: C.forecast_states.includes(p.revenue_state) ? 0 : 1 };
  const z = Object.keys(C.weights).reduce((a, k) => a + C.weights[k] * f[k], 0) + C.bias;
  const s = 100 / (1 + Math.exp(-z));
  return [Math.round(s * 10) / 10, s >= C.threshold];
}

function nameKey(p) {
  const base = (p.final_customer || '').trim() || (p.dealname || '').split(/[-/|(]/)[0];
  return base.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 40);
}

function shapeRows(deals, others, entity, pl, st, owners, runTs, known, portal) {
  const batchKeys = {};
  for (const d of [...deals, ...others]) { const k = nameKey(d.properties || {}); (batchKeys[k] ??= []).push(String(d.id)); }
  const iso = runTs.toISOString().replace('.000Z', '+00:00');
  return deals.map((d) => {
    const p = d.properties || {}; const did = String(d.id); const k = nameKey(p);
    const dupBatch = (batchKeys[k] || []).filter((x) => x !== did);
    const dupKnown = (known[k] || []).filter((x) => x !== did && !dupBatch.includes(x));
    const [score, hot] = hotScore(p, runTs);
    const ownerId = p.hubspot_owner_id === undefined || p.hubspot_owner_id === null ? null : String(p.hubspot_owner_id);
    return { entity, deal_id: did, dealname: p.dealname ?? null, final_customer: p.final_customer ?? null, name_key: k,
      createdate: p.createdate ?? null, created_by_user_id: p.hs_created_by_user_id ?? null, source: p.hs_object_source_label ?? null,
      owner: ownerId === null ? null : (owners[ownerId] ?? ownerId), sales_region: p.sales_region ?? null,
      pipeline: pl[p.pipeline] ?? p.pipeline ?? null, pipeline_id: p.pipeline ?? null, stage: st[p.dealstage] ?? p.dealstage ?? null,
      probability_pct: Math.round(num(p.hs_deal_stage_probability) * 1000) / 10, amount: num(p.amount), currency: p.deal_currency_code ?? null,
      amount_kusd: num(p.amount_in_home_currency), closedate: (p.closedate || '').slice(0, 10) || null,
      arr_ky: num(p.asp_in_usd_q2_2022_calculation), product_family: p.product_hierarchy ?? null, product: p.prod___product_name_new_ ?? null,
      application: p.application ?? null, icalps_dealtype: p.icalps_dealtype ?? null, icalps_stage: p.icalps_stage ?? null,
      day1_hot_score: score, day1_hot_flag: hot,
      duplicate_suspect: dupBatch.length > 0 || dupKnown.length > 0, duplicate_of: [...dupBatch, ...dupKnown].join(', ') || null,
      deal_url: `https://app.hubspot.com/go-to/${portal}/0-3/${did}`, first_seen_run: iso, last_seen_run: iso };
  });
}

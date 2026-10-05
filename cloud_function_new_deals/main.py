"""
new_deals_report — Cloud Run function (Python 3.12, functions-framework).

Surfaces deals CREATED since the last successful run (watermark on `createdate`), per entity (SEALSQ | ICALPS),
independently of deal stage. Orthogonal to the stage/probability reports.

Idempotency model
  • createdate is immutable in HubSpot → a half-open window [watermark − overlap, run_ts) is exact and replayable.
  • Rows are MERGEd into BigQuery on deal_id → re-running a window never duplicates.
  • The watermark advances only after a successful MERGE → a failed run is retried on the next trigger with no gap.
  • Replay: set report_state.watermark back in time and run again.

Modes
  • GET/POST ?entity=SEALSQ|ICALPS            scheduled window run (Cloud Scheduler)
  • POST {"objectId": "<dealId>", "mode": "event"}   HubSpot workflow webhook on deal creation (near-real-time; no watermark change)
  • ?dry_run=1                                 compute everything, write nothing, return the payload

  • Dry mode builds the BigQuery client and reads watermark + warehouse twins like a live run (so the gate rehearses Monday's
    window exactly); only the MERGE, the watermark advance, the audit rows and the delivery POST are skipped.
  • Per-run staging table (new_deals_staging_<entity>_<run_ts>) so two entities or a retry can never truncate each other.
  • Lease: report_state.lock_until is taken by one atomic UPDATE per entity; an overlapping run gets 409 and nothing moves.
  • day1_hot_score / day1_hot_flag are written once (first observation) and never overwritten by a re-observation or a replay.
  • Audit: one row per run in new_deals_runs (also on failure) and the run's rows in new_deals_history (layer L13).

Environment
  HUBSPOT_TOKEN (Secret Manager)  BQ_PROJECT  BQ_DATASET (default hubspot)  DELIVERY_WEBHOOK_URL (optional, n8n)
  DELIVERY_WEBHOOK_TOKEN (optional, sent as X-Delivery-Token)  OVERLAP_MINUTES (default 5)  FIRST_RUN_DAYS (default 7)
  PORTAL_ID (default 9201667)  ORCHESTRATOR (default cloud-run-function)  LEASE_MINUTES (default 12)
"""
import os, re, json, math, time, logging
from datetime import datetime, timedelta, timezone
import requests
import functions_framework


class _JsonFormatter(logging.Formatter):
    """One JSON object per line; Cloud Logging parses severity/message and keeps the extra fields queryable."""
    def format(self, r):
        o = {"severity": {"WARNING": "WARNING", "ERROR": "ERROR", "CRITICAL": "CRITICAL"}.get(r.levelname, "INFO"), "message": r.getMessage()}
        o.update(getattr(r, "fields", {}) or {})
        return json.dumps(o, default=str)


log = logging.getLogger("new_deals")
if not log.handlers:
    _h = logging.StreamHandler(); _h.setFormatter(_JsonFormatter()); log.addHandler(_h); log.setLevel(logging.INFO); log.propagate = False
def jlog(level, message, **fields): log.log(level, message, extra={"fields": fields})
ORCHESTRATOR = os.environ.get("ORCHESTRATOR", "cloud-run-function")
HS = "https://api.hubapi.com"
PORTAL = os.environ.get("PORTAL_ID", "9201667")
ENTITIES = {
    "SEALSQ": {"pipelines": ["12096408", "13772279", "705868909", "934982230"], "currency": "USD (home)"},
    "ICALPS": {"pipelines": ["766126206"], "currency": "EUR (stored)"},
}
PROPS = ["dealname", "createdate", "final_customer", "sales_region", "pipeline", "dealstage", "hs_deal_stage_probability", "amount",
         "amount_in_home_currency", "deal_currency_code", "closedate", "asp_in_usd_q2_2022_calculation", "tpm__k_y", "services_value_2026",
         "calculation___pipeline_2026__k__", "product_hierarchy", "prod___product_name_new_", "application", "hubspot_owner_id",
         "hs_object_source_label", "hs_object_source_detail_1", "icalps_dealtype", "icalps_stage", "icalps_dealstatus", "num_contacted_notes",
         "notes_last_updated", "revenue_state", "hs_created_by_user_id"]

# ------------------------------------------------------------------ hot-deal score v1 (same constants as hot_deals_score.js, fitted 2026-10-01)
W = {"stage_prob": 2.0712, "proximity_2026": 1.2399, "missing_2026_field": -0.4136, "pipeline_conversion": 1.0918, "arr_points": 4.9843,
     "engagement": 1.3018, "recency": 0.0, "not_in_forecast": 1.5620}; BIAS = -6.4788; THRESHOLD = 45.0
CR = {"12096408": 84 / 730, "13772279": 51 / 303}; CRMAX = max(CR.values()); MAXC = 223

def _num(v):
    try: return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError): return 0.0

def hot_score(p, now):
    """Returns (score, hot) for SEALSQ pipelines; (None, None) for others."""
    if p.get("pipeline") not in CR: return None, None
    arr = _num(p.get("asp_in_usd_q2_2022_calculation")) or _num(p.get("tpm__k_y")) or _num(p.get("services_value_2026"))
    if p.get("product_hierarchy") == "PKI": pts = 0.5 if arr < 20 else (1 if arr <= 50 else 2)
    else: pts = 0.5 if arr < 100 else (1 if arr <= 500 else (2 if arr <= 1000 else 3))
    cd = p.get("closedate"); prox = 0.0
    if cd:
        d = datetime.fromisoformat(cd.replace("Z", "+00:00"))
        prox = 1.0 if d.year <= 2026 else max(0.0, 1 - (d - datetime(2026, 12, 31, tzinfo=timezone.utc)).days / 730)
    hw = p.get("pipeline") == "12096408"
    missing = 1.0 if (not _num(p.get("calculation___pipeline_2026__k__")) if hw else not _num(p.get("services_value_2026"))) else 0.0
    nlu = p.get("notes_last_updated"); rec = 0.0
    if nlu:
        days = (now - datetime.fromisoformat(nlu.replace("Z", "+00:00"))).days; rec = 1.0 if days <= 90 else (0.5 if days <= 180 else 0.0)
    f = {"stage_prob": _num(p.get("hs_deal_stage_probability")), "proximity_2026": prox, "missing_2026_field": missing,
         "pipeline_conversion": CR[p["pipeline"]] / CRMAX, "arr_points": pts / 3, "engagement": math.log1p(_num(p.get("num_contacted_notes"))) / math.log1p(MAXC),
         "recency": rec, "not_in_forecast": 0.0 if p.get("revenue_state") in ("Forecast", "BIBA") else 1.0}
    z = sum(W[k] * f[k] for k in W) + BIAS; s = 100 / (1 + math.exp(-z))
    return round(s, 1), s >= THRESHOLD

# ------------------------------------------------------------------ HubSpot client
class HubSpot:
    def __init__(self, token): self.h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    def search_created(self, start, end):
        body = {"filterGroups": [{"filters": [
                    {"propertyName": "createdate", "operator": "GTE", "value": start.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
                    {"propertyName": "createdate", "operator": "LT", "value": end.strftime("%Y-%m-%dT%H:%M:%S.000Z")}]}],
                "properties": PROPS, "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}], "limit": 200}
        out, after = [], None
        while True:
            if after: body["after"] = after
            r = requests.post(f"{HS}/crm/v3/objects/deals/search", headers=self.h, json=body, timeout=60); r.raise_for_status(); j = r.json()
            out += j.get("results", []); after = (j.get("paging") or {}).get("next", {}).get("after")
            if not after: return out
    def deal(self, deal_id):
        r = requests.get(f"{HS}/crm/v3/objects/deals/{deal_id}", headers=self.h, params={"properties": ",".join(PROPS)}, timeout=30); r.raise_for_status(); return r.json()
    def pipelines(self):
        r = requests.get(f"{HS}/crm/v3/pipelines/deals", headers=self.h, timeout=30); r.raise_for_status()
        pl, st = {}, {}
        for p in r.json().get("results", []):
            pl[p["id"]] = p["label"]
            for s in p.get("stages", []): st[s["id"]] = s["label"]
        return pl, st
    def owners(self):
        out, after = {}, None
        while True:
            r = requests.get(f"{HS}/crm/v3/owners", headers=self.h, params={"limit": 100, **({"after": after} if after else {})}, timeout=30); r.raise_for_status(); j = r.json()
            for o in j.get("results", []): out[str(o["id"])] = f"{o.get('firstName', '')} {o.get('lastName', '')}".strip() or o.get("email", "")
            after = (j.get("paging") or {}).get("next", {}).get("after")
            if not after: return out

# ------------------------------------------------------------------ BigQuery state + sink
def bq():
    from google.cloud import bigquery
    return bigquery.Client(project=os.environ["BQ_PROJECT"])
def table(name): return f"{os.environ['BQ_PROJECT']}.{os.environ.get('BQ_DATASET', 'hubspot')}.{name}"

def _qp(**kw):
    from google.cloud import bigquery
    types = {str: "STRING", datetime: "TIMESTAMP", bool: "BOOL", int: "INT64", float: "FLOAT64"}
    return bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter(k, types[type(v)], v) for k, v in kw.items()])

def read_watermark(client, entity, now):
    rows = list(client.query(f"SELECT watermark FROM `{table('report_state')}` WHERE report_id = @rid", job_config=_qp(rid=f"NEW_DEALS_{entity}")).result())
    return rows[0]["watermark"].replace(tzinfo=timezone.utc) if rows else now - timedelta(days=int(os.environ.get("FIRST_RUN_DAYS", "7")))

def acquire_lease(client, entity, run_ts, start):
    """One run per entity at a time (layer L15). Creates the state row on the first run, then takes lock_until atomically.
    Returns False when another run holds a live lease — the caller answers 409 and writes nothing."""
    minutes = int(os.environ.get("LEASE_MINUTES", "12")); rid = f"NEW_DEALS_{entity}"
    client.query(f"""MERGE `{table('report_state')}` t USING (SELECT @rid AS report_id) s ON t.report_id = s.report_id
                     WHEN NOT MATCHED THEN INSERT (report_id, watermark, updated_at) VALUES (@rid, @wm, CURRENT_TIMESTAMP())""",
                 job_config=_qp(rid=rid, wm=start)).result()
    job = client.query(f"""UPDATE `{table('report_state')}` SET lock_until = TIMESTAMP_ADD(@ts, INTERVAL {minutes} MINUTE)
                           WHERE report_id = @rid AND (lock_until IS NULL OR lock_until < @ts)""", job_config=_qp(rid=rid, ts=run_ts))
    job.result(); return (job.num_dml_affected_rows or 0) == 1

def write_watermark(client, entity, ts):
    """Advance the watermark and release the lease in one statement — only called after a successful MERGE."""
    client.query(f"""UPDATE `{table('report_state')}` SET watermark = @ts, updated_at = CURRENT_TIMESTAMP(), lock_until = NULL WHERE report_id = @rid""",
                 job_config=_qp(rid=f"NEW_DEALS_{entity}", ts=ts)).result()

def release_lease(client, entity):
    try: client.query(f"UPDATE `{table('report_state')}` SET lock_until = NULL WHERE report_id = @rid", job_config=_qp(rid=f"NEW_DEALS_{entity}")).result()
    except Exception as e: jlog(logging.WARNING, "lease release failed", error=str(e))

FROZEN = ("deal_id", "first_seen_run", "day1_hot_score", "day1_hot_flag")   # never overwritten by a re-observation or a replay (G06)

def merge_rows(client, rows, entity, run_ts):
    """Per-run staging table → MERGE on deal_id → staging dropped. Two entities or a retry never share a staging table (G03)."""
    if not rows: return 0
    from google.cloud import bigquery
    tmp = table(f"new_deals_staging_{entity.lower()}_{run_ts:%Y%m%d%H%M%S}")
    schema = client.get_table(table("new_deals")).schema
    cols = [f.name for f in schema]
    try:
        client.load_table_from_json(rows, tmp, job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", autodetect=False, schema=schema)).result()
        upd = ", ".join(f"{c} = s.{c}" for c in cols if c not in FROZEN)
        client.query(f"""MERGE `{table('new_deals')}` t USING `{tmp}` s ON t.deal_id = s.deal_id
                WHEN MATCHED THEN UPDATE SET {upd}
                WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}) VALUES ({', '.join('s.' + c for c in cols)})""").result()
    finally:
        client.delete_table(tmp, not_found_ok=True)
    return len(rows)

def write_history(client, rows, entity, run_ts):
    """Layer L13: how every deal scored on this run (append; a replayed run_ts replaces its slice)."""
    if not rows: return
    from google.cloud import bigquery
    client.query(f"DELETE FROM `{table('new_deals_history')}` WHERE run_ts = @ts AND entity = @e AND orchestrator = @o", job_config=_qp(ts=run_ts, e=entity, o=ORCHESTRATOR)).result()
    hist = [{"run_ts": run_ts.isoformat(), "orchestrator": ORCHESTRATOR, **r} for r in rows]
    client.load_table_from_json(hist, table("new_deals_history"), job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND", autodetect=False,
                                schema=client.get_table(table("new_deals_history")).schema)).result()

def write_run(client, entity, run_ts, window, rows, written, dry, status, error, started):
    """One row per run, also on failure — the probe every scenario shares."""
    rec = {"run_ts": run_ts.isoformat(), "entity": entity, "mode": window.get("mode"), "dry_run": dry, "orchestrator": ORCHESTRATOR,
           "watermark_in": window.get("watermark_in"), "query_start": window.get("query_start"), "query_end": window.get("query_end"),
           "row_count": len(rows), "rows_written": written, "duplicate_suspects": sum(1 for r in rows if r.get("duplicate_suspect")),
           "day1_hot": sum(1 for r in rows if r.get("day1_hot_flag")), "status": status, "error": (error or None) and str(error)[:1000],
           "duration_ms": int((time.monotonic() - started) * 1000)}
    try:   # a query INSERT, not a streaming insert: C's scheduled script DELETEs its own rows in this table and a streaming buffer would block it
        cols = list(rec); from google.cloud import bigquery
        types = {"run_ts": "TIMESTAMP", "watermark_in": "TIMESTAMP", "query_start": "TIMESTAMP", "query_end": "TIMESTAMP", "dry_run": "BOOL",
                 "row_count": "INT64", "rows_written": "INT64", "duplicate_suspects": "INT64", "day1_hot": "INT64", "duration_ms": "INT64"}
        params = [bigquery.ScalarQueryParameter(c, types.get(c, "STRING"), rec[c]) for c in cols]
        client.query(f"INSERT INTO `{table('new_deals_runs')}` ({', '.join(cols)}) VALUES ({', '.join('@' + c for c in cols)})",
                     job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    except Exception as e: jlog(logging.WARNING, "run log insert failed", error=str(e))

def recent_names(client, days=90):
    """name_key → [deal_id, …] over every entity (twins live in other pipelines). Errors are logged as ERROR and the run continues
    with an empty map — the row's duplicate_suspect then reflects the batch only (G07)."""
    q = f"SELECT deal_id, name_key FROM `{table('new_deals')}` WHERE createdate >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {int(days)} DAY) AND name_key != ''"
    out = {}
    try:
        for r in client.query(q).result(): out.setdefault(r["name_key"], []).append(r["deal_id"])
    except Exception as e: jlog(logging.ERROR, "recent_names unavailable; warehouse de-duplication skipped this run", error=str(e))
    return out

# ------------------------------------------------------------------ shaping
def name_key(p):
    base = (p.get("final_customer") or "").strip() or re.split(r"[-/|(]", p.get("dealname") or "")[0]
    return re.sub(r"[^a-z0-9]", "", base.lower())[:40]

def shape(deals, others, entity, pl, st, owners, run_ts, known):
    """deals = in-scope new deals; others = new deals of other pipelines in the same window (duplicate candidates only)."""
    rows, batch_keys = [], {}
    for d in deals + others:
        p = d.get("properties", {}); k = name_key(p); batch_keys.setdefault(k, []).append(str(d["id"]))
    for d in deals:
        p = d.get("properties", {}); did = str(d["id"]); k = name_key(p)
        dup_in_batch = [x for x in batch_keys.get(k, []) if x != did]
        dup_known = [x for x in known.get(k, []) if x != did and x not in dup_in_batch]   # warehouse twins (90 days, every entity)
        score, hot = hot_score(p, run_ts)
        rows.append({
            "entity": entity, "deal_id": did, "dealname": p.get("dealname"), "final_customer": p.get("final_customer"), "name_key": k,
            "createdate": p.get("createdate"), "created_by_user_id": p.get("hs_created_by_user_id"), "source": p.get("hs_object_source_label"),
            "owner": owners.get(str(p.get("hubspot_owner_id")), p.get("hubspot_owner_id")), "sales_region": p.get("sales_region"),
            "pipeline": pl.get(p.get("pipeline"), p.get("pipeline")), "pipeline_id": p.get("pipeline"), "stage": st.get(p.get("dealstage"), p.get("dealstage")),
            "probability_pct": round(_num(p.get("hs_deal_stage_probability")) * 100, 1), "amount": _num(p.get("amount")), "currency": p.get("deal_currency_code"),
            "amount_kusd": _num(p.get("amount_in_home_currency")), "closedate": (p.get("closedate") or "")[:10] or None,
            "arr_ky": _num(p.get("asp_in_usd_q2_2022_calculation")), "product_family": p.get("product_hierarchy"), "product": p.get("prod___product_name_new_"),
            "application": p.get("application"), "icalps_dealtype": p.get("icalps_dealtype"), "icalps_stage": p.get("icalps_stage"),
            "day1_hot_score": score, "day1_hot_flag": hot,
            "duplicate_suspect": bool(dup_in_batch or dup_known), "duplicate_of": ", ".join(dup_in_batch + dup_known) or None,
            "deal_url": f"https://app.hubspot.com/go-to/{PORTAL}/0-3/{did}", "first_seen_run": run_ts.isoformat(), "last_seen_run": run_ts.isoformat()})
    return rows

# ------------------------------------------------------------------ entry point
def _deliver(payload):
    url = os.environ.get("DELIVERY_WEBHOOK_URL")
    if not url: return None
    headers = {"Content-Type": "application/json"}
    if os.environ.get("DELIVERY_WEBHOOK_TOKEN"): headers["X-Delivery-Token"] = os.environ["DELIVERY_WEBHOOK_TOKEN"]
    for attempt, wait in enumerate((0, 5, 15), start=1):             # three tries: the n8n instance may be cold-starting
        if wait: time.sleep(wait)
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=60); r.raise_for_status(); return None
        except Exception as e: err = str(e); jlog(logging.WARNING, "delivery webhook failed", attempt=attempt, error=err)
    return err


@functions_framework.http
def new_deals_report(request):
    started = time.monotonic()
    now = datetime.now(timezone.utc); run_ts = now.replace(microsecond=0)
    body = request.get_json(silent=True) or {}
    entity = (request.args.get("entity") or body.get("entity") or "SEALSQ").upper()
    dry = request.args.get("dry_run") == "1" or body.get("dry_run") is True
    if entity not in ENTITIES: return ({"error": f"unknown entity {entity}"}, 400)
    event = bool(body.get("mode") == "event" and body.get("objectId"))
    client = bq()                                                       # dry mode reads like a live run (G05)
    rows, written, window, leased = [], 0, {"mode": "event" if event else "window"}, False
    try:
        hs = HubSpot(os.environ["HUBSPOT_TOKEN"]); pl, st = hs.pipelines(); owners = hs.owners()
        known = recent_names(client)
        if event:                                                       # HubSpot workflow webhook: one deal, no watermark change
            d = hs.deal(body["objectId"]); deals = [d] if d.get("properties", {}).get("pipeline") in ENTITIES[entity]["pipelines"] else []; others = []
            window["objectId"] = body["objectId"]
        else:
            start = read_watermark(client, entity, now)
            if not dry:
                leased = acquire_lease(client, entity, run_ts, start)
                if not leased:
                    jlog(logging.WARNING, "run already in progress", entity=entity)
                    return ({"error": f"a run for {entity} holds the lease; retry after LEASE_MINUTES", "report_id": f"NEW_DEALS_{entity}"}, 409)
            qstart = start - timedelta(minutes=int(os.environ.get("OVERLAP_MINUTES", "5")))
            found = hs.search_created(qstart, run_ts)
            deals = [d for d in found if d.get("properties", {}).get("pipeline") in ENTITIES[entity]["pipelines"]]
            ids = {str(d["id"]) for d in deals}; others = [d for d in found if str(d["id"]) not in ids]
            window.update({"watermark_in": start.isoformat(), "query_start": qstart.isoformat(), "query_end": run_ts.isoformat()})
        rows = shape(deals, others, entity, pl, st, owners, run_ts, known)
        rows.sort(key=lambda r: (-(r["amount_kusd"] or 0), r["deal_id"]))
        if not dry:
            written = merge_rows(client, rows, entity, run_ts)
            write_history(client, rows, entity, run_ts)
            if not event: write_watermark(client, entity, run_ts)      # advance only after a successful MERGE; releases the lease
            leased = False
        payload = {"report_id": f"NEW_DEALS_{entity}", "run_timestamp": run_ts.isoformat(), "orchestrator": ORCHESTRATOR, "dry_run": dry,
                   "window": window, "row_count": len(rows), "rows_written": written,
                   "duplicate_suspects": sum(1 for r in rows if r["duplicate_suspect"]), "day1_hot": [r["deal_id"] for r in rows if r.get("day1_hot_flag")],
                   "currency_note": ENTITIES[entity]["currency"], "rows": rows}
        if not dry:
            err = _deliver(payload)
            if err: payload["delivery_error"] = err
            write_run(client, entity, run_ts, window, rows, written, dry, "OK" if not err else "OK_DELIVERY_FAILED", err, started)
        jlog(logging.INFO, "run complete", entity=entity, dry_run=dry, rows=len(rows), written=written, window=window, duration_ms=int((time.monotonic() - started) * 1000))
        return (payload, 200)
    except Exception as e:
        jlog(logging.ERROR, "run failed", entity=entity, dry_run=dry, error=str(e), window=window)
        if not dry: write_run(client, entity, run_ts, window, rows, written, dry, "FAILED", e, started)
        if leased: release_lease(client, entity)
        raise

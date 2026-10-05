#!/usr/bin/env python3
"""build_workflow.py — generate the n8n workflow JSON files from one source of truth each.

    python3 workflows/src/build_workflow.py            # writes workflows/NEW_DEALS_FULL.json, NEW_DEALS_DELIVERY.json, NEW_DEALS_ERRORS.json
    python3 workflows/src/build_workflow.py --check    # exit 1 if any generated file differs (pre-push gate)
    python3 workflows/src/build_workflow.py --code     # print the generated Code-node JavaScript (what tests/test_n8n_code.py runs)

Sources: scoring/hot_score_v1.constants.json (constants), workflows/src/shape_score.js (pure functions), workflows/src/node_code.template.js
(n8n glue), cloud_function_new_deals/bigquery_schema.sql (column list and types → MERGE / history SQL), and
cloud_function_new_deals/n8n_NewDeals_Delivery.json (the B1 delivery flow that is hardened into NEW_DEALS_DELIVERY.json).
Stable workflow ids make re-import idempotent; node typeVersions are pinned in PINNED below.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / "workflows"
PINNED = {"n8n-nodes-base.webhook": 2, "n8n-nodes-base.set": 3.4, "n8n-nodes-base.googleBigQuery": 2.1, "n8n-nodes-base.code": 2,
          "n8n-nodes-base.httpRequest": 4.2, "n8n-nodes-base.if": 2.2, "n8n-nodes-base.splitOut": 1, "n8n-nodes-base.convertToFile": 1.1,
          "n8n-nodes-base.emailSend": 2.1, "n8n-nodes-base.respondToWebhook": 1.1, "n8n-nodes-base.errorTrigger": 1}
CRED = {"header": {"httpHeaderAuth": {"id": "REPLACE_WITH_HEADER_AUTH", "name": "new-deals webhook token"}},
        "hubspot": {"hubspotAppToken": {"id": "REPLACE_WITH_HUBSPOT", "name": "HubSpot private app (read)"}},
        "bq": {"googleApi": {"id": "REPLACE_WITH_GOOGLE_SA", "name": "n8n-bq service account"}},
        "smtp": {"smtp": {"id": "REPLACE_WITH_SMTP", "name": "SMTP relay"}}}


def schema_columns() -> list[tuple[str, str]]:
    sql = (ROOT / "cloud_function_new_deals" / "bigquery_schema.sql").read_text()
    body = re.search(r"new_deals` \((.*?)\)\nPARTITION", sql, re.S).group(1)
    return re.findall(r"([a-z0-9_]+) (STRING|TIMESTAMP|FLOAT64|DATE|BOOL)", body)


def sql_templates(cols: list[tuple[str, str]]) -> str:
    def expr(c, t):
        jv = f"JSON_VALUE(r, '$.{c}')"
        return {"STRING": jv, "TIMESTAMP": f"SAFE_CAST({jv} AS TIMESTAMP)", "FLOAT64": f"SAFE_CAST({jv} AS FLOAT64)",
                "DATE": f"SAFE_CAST({jv} AS DATE)", "BOOL": f"SAFE_CAST({jv} AS BOOL)"}[t] + f" AS {c}"
    names = [c for c, _ in cols]
    frozen = {"deal_id", "first_seen_run", "day1_hot_score", "day1_hot_flag"}          # same frozen set as main.py
    src = "SELECT " + ", ".join(expr(c, t) for c, t in cols) + " FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(__ROWS__))) r"
    merge = (f"MERGE __FQ__.new_deals` t USING ({src}) s ON t.deal_id = s.deal_id "
             f"WHEN MATCHED THEN UPDATE SET {', '.join(f'{c} = s.{c}' for c in names if c not in frozen)} "
             f"WHEN NOT MATCHED THEN INSERT ({', '.join(names)}) VALUES ({', '.join('s.' + c for c in names)})")
    history = (f"DELETE FROM __FQ__.new_deals_history` WHERE run_ts = TIMESTAMP '__RUN_TS__' AND entity = '__ENTITY__' AND orchestrator = 'n8n'; "
               f"INSERT INTO __FQ__.new_deals_history` (run_ts, orchestrator, {', '.join(names)}) "
               f"SELECT TIMESTAMP '__RUN_TS__', 'n8n', {', '.join(names)} FROM ({src})")
    watermark = ("MERGE __FQ__.report_state` t USING (SELECT '__RID__' AS report_id, TIMESTAMP '__TS__' AS watermark) s ON t.report_id = s.report_id "
                 "WHEN MATCHED THEN UPDATE SET watermark = s.watermark, updated_at = CURRENT_TIMESTAMP(), lock_until = NULL "
                 "WHEN NOT MATCHED THEN INSERT (report_id, watermark, updated_at) VALUES (s.report_id, s.watermark, CURRENT_TIMESTAMP())")
    runlog = ("INSERT INTO __FQ__.new_deals_runs` (run_ts, entity, mode, dry_run, orchestrator, watermark_in, query_start, query_end, row_count, rows_written, duplicate_suspects, day1_hot, status) "
              "VALUES (TIMESTAMP '__RUN_TS__', '__ENTITY__', 'window', __DRY__, 'n8n', TIMESTAMP '__WM__', TIMESTAMP '__QS__', TIMESTAMP '__QE__', __N__, IF(__DRY__, 0, __N__), __DUP__, __HOT__, 'OK')")
    return "\n".join(f"const {k} = {json.dumps(v)};" for k, v in (("MERGE_SQL", merge), ("HISTORY_SQL", history), ("WATERMARK_SQL", watermark), ("RUNLOG_SQL", runlog)))


def code_js() -> str:
    constants = json.loads((ROOT / "scoring" / "hot_score_v1.constants.json").read_text())
    tpl = (WF / "src" / "node_code.template.js").read_text()
    return (tpl.replace("/*__CONSTANTS__*/", "const C = " + json.dumps(constants) + ";")
               .replace("/*__SHAPE_SCORE__*/", (WF / "src" / "shape_score.js").read_text().strip())
               .replace("/*__SQL_TEMPLATES__*/", sql_templates(schema_columns())))


def node(name, type_, params, pos, creds=None, **extra):
    n = {"parameters": params, "name": name, "type": type_, "typeVersion": PINNED[type_], "position": list(pos)}
    if creds: n["credentials"] = creds
    n.update(extra); return n


def bq(name, sql_expr, pos, on_error=None):
    p = {"resource": "database", "operation": "executeQuery", "projectId": {"__rl": True, "mode": "id", "value": "={{ $env.BQ_PROJECT }}"},
         "sqlQuery": sql_expr, "options": {"location": "={{ $env.BQ_LOCATION || 'EU' }}", "useLegacySql": False}}
    extra = {"onError": "continueRegularOutput"} if on_error else {}
    return node(name, "n8n-nodes-base.googleBigQuery", p, pos, CRED["bq"], **extra)


def hs_request(name, method, url, pos, body=None, paginate_in=None):
    p = {"method": method, "url": url, "authentication": "predefinedCredentialType", "nodeCredentialType": "hubspotAppToken", "options": {}}
    if body: p.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
    if paginate_in:
        p["options"]["pagination"] = {"pagination": {"paginationMode": "updateAParameterInEachRequest", "paginationCompleteWhen": "other",
                                                      "completeExpression": "={{ !$response.body.paging }}", "limitPagesFetched": False,
                                                      "parameters": {"parameters": [{"type": paginate_in, "name": "after", "value": "={{ $response.body.paging.next.after }}"}]}}}
    return node(name, "n8n-nodes-base.httpRequest", p, pos, CRED["hubspot"])


def chain(*names):
    return {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(names, names[1:])}


def build_full() -> dict:
    props = json.dumps(["dealname", "createdate", "final_customer", "sales_region", "pipeline", "dealstage", "hs_deal_stage_probability", "amount",
                        "amount_in_home_currency", "deal_currency_code", "closedate", "asp_in_usd_q2_2022_calculation", "tpm__k_y", "services_value_2026",
                        "calculation___pipeline_2026__k__", "product_hierarchy", "prod___product_name_new_", "application", "hubspot_owner_id",
                        "hs_object_source_label", "hs_object_source_detail_1", "icalps_dealtype", "icalps_stage", "icalps_dealstatus", "num_contacted_notes",
                        "notes_last_updated", "revenue_state", "hs_created_by_user_id"])
    nodes = [
        node("Webhook: new-deals-run", "n8n-nodes-base.webhook", {"httpMethod": "POST", "path": "new-deals-run", "authentication": "headerAuth", "responseMode": "responseNode", "options": {}}, (0, 300), CRED["header"], webhookId="new-deals-run"),
        node("Params", "n8n-nodes-base.set", {"assignments": {"assignments": [
            {"id": "a1", "name": "entity", "type": "string", "value": "={{ ['SEALSQ','ICALPS'].includes(($json.query.entity || 'SEALSQ').toUpperCase()) ? ($json.query.entity || 'SEALSQ').toUpperCase() : 'INVALID' }}"},
            {"id": "a2", "name": "dry_run", "type": "boolean", "value": "={{ $json.query.dry_run === '1' }}"},
            {"id": "a3", "name": "run_ts", "type": "string", "value": "={{ $now.toUTC().startOf('second').toISO({ suppressMilliseconds: true }) }}"},
            {"id": "a4", "name": "overlap_minutes", "type": "number", "value": 5}, {"id": "a5", "name": "first_run_days", "type": "number", "value": 7},
            {"id": "a6", "name": "portal_id", "type": "string", "value": "={{ $env.PORTAL_ID || '9201667' }}"},
            {"id": "a7", "name": "bq_project", "type": "string", "value": "={{ $env.BQ_PROJECT }}"}, {"id": "a8", "name": "bq_dataset", "type": "string", "value": "={{ $env.BQ_DATASET || 'hubspot' }}"}]},
            "options": {}}, (220, 300)),
        bq("Read watermark", "=SELECT FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', watermark) AS watermark FROM `{{ $json.bq_project }}.{{ $json.bq_dataset }}.report_state` WHERE report_id = 'NEW_DEALS_{{ $json.entity }}'", (440, 300)),
        node("Window", "n8n-nodes-base.code", {"mode": "runOnceForAllItems", "jsCode":
             "// half-open window [watermark − overlap, run_ts); computed ONCE — every later node references this item, never $now again\n"
             "const P = $('Params').first().json; const wm = $input.first().json.watermark;\n"
             "const runTs = new Date(P.run_ts); const start = wm ? new Date(wm) : new Date(runTs.getTime() - P.first_run_days * 86400000);\n"
             "const qs = new Date(start.getTime() - P.overlap_minutes * 60000);\n"
             "const iso = (d) => d.toISOString().replace('.000Z', 'Z');\n"
             "return [{ json: { watermark_in: iso(start), query_start: iso(qs), query_end: iso(runTs), hs_start: iso(qs).replace('Z', '.000Z'), hs_end: iso(runTs).replace('Z', '.000Z') } }];"}, (660, 300)),
        hs_request("HubSpot search", "POST", "https://api.hubapi.com/crm/v3/objects/deals/search", (880, 300),
                   body="={{ JSON.stringify({ filterGroups: [{ filters: [{ propertyName: 'createdate', operator: 'GTE', value: $json.hs_start }, { propertyName: 'createdate', operator: 'LT', value: $json.hs_end }] }], properties: " + props + ", sorts: [{ propertyName: 'createdate', direction: 'ASCENDING' }], limit: 200 }) }}",
                   paginate_in="body"),
        hs_request("Pipelines", "GET", "https://api.hubapi.com/crm/v3/pipelines/deals", (1100, 300)),
        hs_request("Owners", "GET", "https://api.hubapi.com/crm/v3/owners?limit=100", (1320, 300), paginate_in="qs"),
        bq("Recent names", "=SELECT deal_id, name_key FROM `{{ $('Params').first().json.bq_project }}.{{ $('Params').first().json.bq_dataset }}.new_deals` WHERE createdate >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY) AND name_key != ''", (1540, 300), on_error=True),
        node("Shape + score", "n8n-nodes-base.code", {"mode": "runOnceForAllItems", "jsCode": code_js()}, (1760, 300)),
        node("Dry run?", "n8n-nodes-base.if", {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
             "conditions": [{"id": "c1", "leftValue": "={{ $('Params').first().json.dry_run }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true", "singleValue": True}}], "combinator": "and"}, "options": {}}, (1980, 300)),
        bq("MERGE new_deals", "={{ $('Shape + score').first().json.merge_sql }}", (2200, 420)),
        bq("History slice", "={{ $('Shape + score').first().json.history_sql }}", (2420, 420)),
        bq("Advance watermark", "={{ $('Shape + score').first().json.watermark_sql }}", (2640, 420)),
        bq("Run log", "={{ $('Shape + score').first().json.runlog_sql }}", (2860, 420)),
        node("Rows", "n8n-nodes-base.splitOut", {"fieldToSplitOut": "rows", "include": "noOtherFields", "options": {}}, (3080, 420)),
        node("XLSX", "n8n-nodes-base.convertToFile", {"operation": "xlsx", "binaryPropertyName": "NEW", "options": {"fileName": "={{ $('Shape + score').first().json.report_id }}_{{ $('Shape + score').first().json.run_timestamp.slice(0,10) }}.xlsx", "headerRow": True, "sheetName": "New deals"}}, (3300, 420)),
        node("Email", "n8n-nodes-base.emailSend", {"fromEmail": "={{ $env.MAIL_FROM }}", "toEmail": "={{ $env.MAIL_TO }}",
             "subject": "={{ $('Shape + score').first().json.report_id }} — {{ $('Shape + score').first().json.row_count }} new deal(s), {{ $('Shape + score').first().json.duplicate_suspects }} duplicate suspect(s)",
             "emailFormat": "text", "text": "={{ (() => { const b = $('Shape + score').first().json; return `${b.report_id} · run ${b.run_timestamp} (n8n)\\nwindow: ${JSON.stringify(b.window)}\\nrows: ${b.row_count} · duplicate suspects: ${b.duplicate_suspects} · day-1 hot: ${b.day1_hot.join(', ') || 'none'}\\namounts: ${b.currency_note}\\n\\n` + b.rows.map(r => `${r.duplicate_suspect ? '[DUP] ' : ''}${r.day1_hot_flag ? '[HOT] ' : ''}${r.dealname} — ${r.final_customer || '-'} — ${r.pipeline} / ${r.stage} ${r.probability_pct}% — ${r.amount_kusd} — created ${(r.createdate||'').slice(0,10)} — ${r.owner}\\n${r.deal_url}`).join('\\n\\n'); })() }}",
             "options": {"attachments": "NEW"}}, (3520, 420), CRED["smtp"]),
        node("Respond", "n8n-nodes-base.respondToWebhook", {"respondWith": "json", "responseBody": "={{ JSON.stringify((({ rows, merge_sql, history_sql, watermark_sql, runlog_sql, ...rest }) => rest)($('Shape + score').first().json)) }}", "options": {}}, (3740, 300)),
    ]
    conn = chain("Webhook: new-deals-run", "Params", "Read watermark", "Window", "HubSpot search", "Pipelines", "Owners", "Recent names", "Shape + score", "Dry run?")
    conn["Dry run?"] = {"main": [[{"node": "Respond", "type": "main", "index": 0}], [{"node": "MERGE new_deals", "type": "main", "index": 0}]]}   # true → respond only; false → write
    conn.update(chain("MERGE new_deals", "History slice", "Advance watermark", "Run log", "Rows", "XLSX", "Email", "Respond"))
    return {"id": "NEW_DEALS_FULL", "name": "NEW_DEALS_FULL", "nodes": nodes, "connections": conn, "active": False,
            "settings": {"executionOrder": "v1", "timezone": "Europe/Zurich", "errorWorkflow": "NEW_DEALS_ERRORS", "saveManualExecutions": True},
            "meta": {"generated_by": "workflows/src/build_workflow.py", "scenario": "B2", "note": "Cloud Scheduler → webhook (Header Auth); ?dry_run=1 computes and responds without writing; writes happen in order MERGE → history → watermark → run log → delivery."}}


def build_delivery() -> dict:
    src = json.loads((ROOT / "cloud_function_new_deals" / "n8n_NewDeals_Delivery.json").read_text())
    wf = copy.deepcopy(src); wf["id"] = "NEW_DEALS_DELIVERY"; wf["name"] = "NEW_DEALS_DELIVERY"
    for n in wf["nodes"]:
        if n["type"] == "n8n-nodes-base.webhook":
            n["parameters"].update({"authentication": "headerAuth", "responseMode": "lastNode"}); n["credentials"] = CRED["header"]
        if n["type"] == "n8n-nodes-base.emailSend":
            n["parameters"]["fromEmail"] = "={{ $env.MAIL_FROM }}"; n["parameters"]["toEmail"] = "={{ $env.MAIL_TO }}"; n["credentials"] = CRED["smtp"]
        n["typeVersion"] = PINNED.get(n["type"], n["typeVersion"])
    wf["nodes"].insert(1, node("Any rows?", "n8n-nodes-base.if", {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
        "conditions": [{"id": "c1", "leftValue": "={{ $json.body.row_count }}", "rightValue": 0, "operator": {"type": "number", "operation": "gt"}}], "combinator": "and"}, "options": {}}, (110, 300)))
    wf["nodes"].append(node("Email (no rows)", "n8n-nodes-base.emailSend", {"fromEmail": "={{ $env.MAIL_FROM }}", "toEmail": "={{ $env.MAIL_TO }}",
        "subject": "={{ $json.body.report_id }} — no new deals this week", "emailFormat": "text",
        "text": "={{ $json.body.report_id }} · run {{ $json.body.run_timestamp }}\nwindow: {{ JSON.stringify($json.body.window) }}\nNo deals were created in the window. Nothing was written.", "options": {}}, (440, 520), CRED["smtp"]))
    wf["connections"] = {"Webhook: new-deals": {"main": [[{"node": "Any rows?", "type": "main", "index": 0}]]},
                         "Any rows?": {"main": [[{"node": "Rows", "type": "main", "index": 0}], [{"node": "Email (no rows)", "type": "main", "index": 0}]]},
                         **chain("Rows", "Shape columns", "XLSX", "Email")}
    wf["settings"] = {"executionOrder": "v1", "timezone": "Europe/Zurich", "errorWorkflow": "NEW_DEALS_ERRORS"}
    wf["meta"] = {"generated_by": "workflows/src/build_workflow.py", "scenario": "B1", "source": "cloud_function_new_deals/n8n_NewDeals_Delivery.json",
                  "hardening": ["Header Auth on the webhook (X-Delivery-Token)", "zero-row branch sends a text-only email", "recipients from MAIL_FROM/MAIL_TO env", "responds when the last node finishes"]}
    return wf


def build_errors() -> dict:
    return {"id": "NEW_DEALS_ERRORS", "name": "NEW_DEALS_ERRORS", "active": False, "settings": {"executionOrder": "v1", "timezone": "Europe/Zurich"},
            "nodes": [node("Error Trigger", "n8n-nodes-base.errorTrigger", {}, (0, 300)),
                      node("Email error", "n8n-nodes-base.emailSend", {"fromEmail": "={{ $env.MAIL_FROM }}", "toEmail": "={{ $env.MAIL_TO }}",
                           "subject": "=[n8n] {{ $json.workflow.name }} failed at {{ $json.execution.lastNodeExecuted }}", "emailFormat": "text",
                           "text": "=workflow: {{ $json.workflow.name }}\nexecution: {{ $json.execution.url }}\nnode: {{ $json.execution.lastNodeExecuted }}\nerror: {{ $json.execution.error.message }}\n\nNothing after the failed node ran; BigQuery state is unchanged unless the failed node was after 'MERGE new_deals' (then re-run the window — the MERGE is idempotent).", "options": {}}, (220, 300), CRED["smtp"])],
            "connections": chain("Error Trigger", "Email error"), "meta": {"generated_by": "workflows/src/build_workflow.py"}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true"); ap.add_argument("--code", action="store_true")
    a = ap.parse_args(argv)
    if a.code: print(code_js()); return 0
    outputs = {"NEW_DEALS_FULL.json": build_full(), "NEW_DEALS_DELIVERY.json": build_delivery(), "NEW_DEALS_ERRORS.json": build_errors()}
    for wf in outputs.values():
        for n in wf["nodes"]:
            assert n["typeVersion"] == PINNED[n["type"]], (n["name"], n["type"])
    stale = []
    for name, wf in outputs.items():
        text = json.dumps(wf, indent=1, ensure_ascii=False) + "\n"; path = WF / name
        if a.check:
            if not path.exists() or path.read_text() != text: stale.append(name)
        else:
            path.write_text(text); print(f"wrote {path.relative_to(ROOT)} ({len(wf['nodes'])} nodes)")
    if a.check:
        print("build_workflow --check:", "up to date" if not stale else "stale: " + ", ".join(stale)); return 1 if stale else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

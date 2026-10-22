#!/usr/bin/env python3
"""build_workflow.py — generate the n8n workflow JSON files from one source of truth each.

    python3 workflows/src/build_workflow.py            # writes workflows/NEW_DEALS_DELIVERY.json, NEW_DEALS_ERRORS.json
    python3 workflows/src/build_workflow.py --check    # exit 1 if any generated file differs (pre-push gate)

Sources: cloud_function_new_deals/n8n_NewDeals_Delivery.json (the B1 delivery flow that is hardened into NEW_DEALS_DELIVERY.json).
B2 (NEW_DEALS_FULL, n8n owning the whole pipeline with a generated Code node) was retired in pass 3 phase 3 (decision D6): the batch is
one SQL implementation over the raw root (sql/new_deals_batch.sql) and every lane calls it — a second shaper has nothing left to mirror.
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


def node(name, type_, params, pos, creds=None, **extra):
    n = {"parameters": params, "name": name, "type": type_, "typeVersion": PINNED[type_], "position": list(pos)}
    if creds: n["credentials"] = creds
    n.update(extra); return n


def bq(name, sql_expr, pos, on_error=None, always_output=False, once=False):
    p = {"resource": "database", "operation": "executeQuery", "projectId": {"__rl": True, "mode": "id", "value": "={{ $env.BQ_PROJECT }}"},
         "sqlQuery": sql_expr, "options": {"location": "={{ $env.BQ_LOCATION || 'EU' }}", "useLegacySql": False}}
    extra = {}
    if on_error: extra["onError"] = "continueRegularOutput"
    if always_output: extra["alwaysOutputData"] = True      # an empty result (first run) must not stop the workflow
    if once: extra["executeOnce"] = True                   # run once, not once per incoming item (search pages)
    return node(name, "n8n-nodes-base.googleBigQuery", p, pos, CRED["bq"], **extra)


def chain(*names):
    return {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(names, names[1:])}


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
    wf["settings"] = {"executionOrder": "v1", "timezone": "Europe/Zurich", "errorWorkflow": "REPLACE_WITH_ERRORS_ID"}   # patched at import from workflows/workflow_ids.map.json
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
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    outputs = {"NEW_DEALS_DELIVERY.json": build_delivery(), "NEW_DEALS_ERRORS.json": build_errors()}
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

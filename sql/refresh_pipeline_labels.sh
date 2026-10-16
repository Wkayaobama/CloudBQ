#!/usr/bin/env bash
# refresh_pipeline_labels.sh — pipelines and stage labels are not a sync asset; load them from the HubSpot API into
# ${DATASET}.pipeline_labels (WRITE_TRUNCATE → re-runnable). Needs HUBSPOT_TOKEN (read scope crm.schemas.deals.read) in the env.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${DATASET:=hubspot}" "${BQ_LOCATION:=EU}" "${HUBSPOT_TOKEN:?HUBSPOT_TOKEN (read) must be in the environment}"
TMP=$(mktemp); HDR=$(mktemp); chmod 600 "$HDR"; trap 'rm -f "$TMP" "$HDR"' EXIT; printf 'Authorization: Bearer %s\n' "$HUBSPOT_TOKEN" > "$HDR"
[[ "$PROJECT" != your-* ]] || { echo "PROJECT holds a placeholder" >&2; exit 2; }
curl -sS -f -H @"$HDR" https://api.hubapi.com/crm/v3/pipelines/deals \
 | python3 -c '
import json, sys, datetime
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
for p in json.load(sys.stdin)["results"]:
    for s in p.get("stages", []):
        print(json.dumps({"pipeline_id": p["id"], "pipeline_label": p["label"], "stage_id": s["id"], "stage_label": s["label"],
                          "stage_probability": float((s.get("metadata") or {}).get("probability") or 0), "refreshed_at": now}))' > "$TMP"
echo "fetched $(wc -l < "$TMP") stage rows"
bq --project_id="$PROJECT" --location="$BQ_LOCATION" load --source_format=NEWLINE_DELIMITED_JSON --replace \
   "${DATASET}.pipeline_labels" "$TMP" pipeline_id:STRING,pipeline_label:STRING,stage_id:STRING,stage_label:STRING,stage_probability:FLOAT64,refreshed_at:TIMESTAMP

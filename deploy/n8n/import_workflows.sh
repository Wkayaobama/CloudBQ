#!/usr/bin/env bash
# import_workflows.sh — import the workflow JSON files into the running n8n through its public REST API (available on all
# self-hosted editions). Import is idempotent by stable workflow id: an existing workflow with the same id is updated (PUT).
#   N8N_URL=https://… N8N_API_KEY=… deploy/n8n/import_workflows.sh [workflows/*.json]
#   --dry-run   print what would be sent
# The API key is created once in the n8n UI (Settings → n8n API). Credentials are NOT imported here: create them in the UI
# (HubSpot App Token from Secret Manager hubspot-token, Google Service Account from deploy/n8n/.secrets/n8n-bq.key.json,
# SMTP, Header Auth = n8n-webhook-token) and set their ids in workflows/credentials.map.json before importing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
DRY=0; [[ "${1:-}" == "--dry-run" ]] && { DRY=1; shift; }
: "${N8N_URL:?}" ; [[ "$DRY" == 1 ]] || : "${N8N_API_KEY:?create one in n8n → Settings → n8n API}"
FILES=("$@"); [[ ${#FILES[@]} -gt 0 ]] || FILES=("$ROOT"/workflows/NEW_DEALS_*.json)
MAP="$ROOT/workflows/credentials.map.json"
for f in "${FILES[@]}"; do
  BODY=$(python3 - "$f" "$MAP" <<'PY'
import json, sys
wf = json.load(open(sys.argv[1])); cmap = json.load(open(sys.argv[2])) if __import__("os").path.exists(sys.argv[2]) else {}
for n in wf.get("nodes", []):                           # remap credential placeholders → real ids
    for ctype, cred in (n.get("credentials") or {}).items():
        if cred.get("id", "").startswith("REPLACE_WITH_") and ctype in cmap: cred.update(cmap[ctype])
print(json.dumps({k: wf[k] for k in ("name", "nodes", "connections", "settings", "staticData") if k in wf}))
PY
)
  ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("id",""))' "$f")
  if [[ "$DRY" == 1 ]]; then echo "would PUT/POST $(basename "$f") (id=${ID:-new}) → $N8N_URL/api/v1/workflows"; continue; fi
  if [[ -n "$ID" ]] && curl -sS -o /dev/null -w '%{http_code}' -H "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_URL/api/v1/workflows/$ID" | grep -q '^200$'; then
    curl -sS -f -X PUT -H "X-N8N-API-KEY: $N8N_API_KEY" -H "Content-Type: application/json" "$N8N_URL/api/v1/workflows/$ID" -d "$BODY" >/dev/null && echo "updated $ID"
  else
    NEW=$(curl -sS -f -X POST -H "X-N8N-API-KEY: $N8N_API_KEY" -H "Content-Type: application/json" "$N8N_URL/api/v1/workflows" -d "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
    echo "created $(basename "$f") as $NEW — set \"id\": \"$NEW\" in the file so the next import updates in place"
  fi
done
echo "activate in the UI after a manual test execution (the n8n-native dry run), or: curl -X POST \$N8N_URL/api/v1/workflows/<id>/activate"

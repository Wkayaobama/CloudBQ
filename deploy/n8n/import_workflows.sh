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
FILES=("$@"); [[ ${#FILES[@]} -gt 0 ]] || FILES=("$ROOT/workflows/NEW_DEALS_ERRORS.json" "$ROOT/workflows/NEW_DEALS_DELIVERY.json")   # errors first: the other references its id (B2 NEW_DEALS_FULL retired, pass 3 phase 3)
MAP="$ROOT/workflows/credentials.map.json"; IDMAP="$ROOT/workflows/workflow_ids.map.json"; [[ -f "$IDMAP" ]] || echo '{}' > "$IDMAP"
HDR=$(mktemp); chmod 600 "$HDR"; trap 'rm -f "$HDR"' EXIT; [[ "$DRY" == 1 ]] || printf 'X-N8N-API-KEY: %s\n' "$N8N_API_KEY" > "$HDR"   # the key never appears on argv
for f in "${FILES[@]}"; do
  BODY=$(python3 - "$f" "$MAP" "$IDMAP" <<'PY'
import json, os, sys
wf = json.load(open(sys.argv[1])); cmap = json.load(open(sys.argv[2])) if os.path.exists(sys.argv[2]) else {}; idmap = json.load(open(sys.argv[3]))
for n in wf.get("nodes", []):                           # remap credential placeholders → real ids
    for ctype, cred in (n.get("credentials") or {}).items():
        if cred.get("id", "").startswith("REPLACE_WITH_") and ctype in cmap: cred.update(cmap[ctype])
st = wf.get("settings", {})
if st.get("errorWorkflow") == "REPLACE_WITH_ERRORS_ID":
    if "NEW_DEALS_ERRORS" in idmap: st["errorWorkflow"] = idmap["NEW_DEALS_ERRORS"]
    else: st.pop("errorWorkflow", None)                 # imported before the error workflow: re-run the import once it exists
print(json.dumps({k: wf[k] for k in ("name", "nodes", "connections", "settings", "staticData") if k in wf}))
PY
)
  KEY=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("id",""))' "$f")
  ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],""))' "$IDMAP" "$KEY")
  if [[ "$DRY" == 1 ]]; then echo "would PUT/POST $(basename "$f") (id=${ID:-new}) → $N8N_URL/api/v1/workflows"; continue; fi
  if [[ -n "$ID" ]] && curl -sS -o /dev/null -w '%{http_code}' -H @"$HDR" "$N8N_URL/api/v1/workflows/$ID" | grep -q '^200$'; then
    curl -sS -f -X PUT -H @"$HDR" -H "Content-Type: application/json" "$N8N_URL/api/v1/workflows/$ID" -d "$BODY" >/dev/null && echo "updated $KEY ($ID)"
  else
    NEW=$(curl -sS -f -X POST -H @"$HDR" -H "Content-Type: application/json" "$N8N_URL/api/v1/workflows" -d "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
    python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); m[sys.argv[2]]=sys.argv[3]; json.dump(m, open(sys.argv[1],"w"), indent=1)' "$IDMAP" "$KEY" "$NEW"
    echo "created $KEY as $NEW (recorded in workflows/workflow_ids.map.json — gitignored; the next import updates in place)"
  fi
done
echo "activate in the UI after a manual test execution (the n8n-native dry run), or: curl -X POST -H @<headerfile> \$N8N_URL/api/v1/workflows/<id>/activate"
echo "(if NEW_DEALS_ERRORS was created in this run, run the import once more so the other workflows point at its id)"

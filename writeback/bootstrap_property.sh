#!/usr/bin/env bash
# bootstrap_property.sh — one-time creation of the deal properties the write-back fills (GET before POST → re-runnable).
# Needs a token with crm.schemas.deals.write in HUBSPOT_SCHEMA_TOKEN (use it once; it is not stored anywhere).
set -euo pipefail
: "${HUBSPOT_SCHEMA_TOKEN:?a token with crm.schemas.deals.write, used once}"
HDR=$(mktemp); chmod 600 "$HDR"; trap 'rm -f "$HDR"' EXIT; printf 'Authorization: Bearer %s\n' "$HUBSPOT_SCHEMA_TOKEN" > "$HDR"   # token never on argv
H=(-H @"$HDR" -H "Content-Type: application/json")
ensure() {  # name label type fieldType description
  if curl -sS -o /dev/null -w '%{http_code}' "${H[@]}" "https://api.hubapi.com/crm/v3/properties/deals/$1" | grep -q '^200$'; then echo "exists: $1"; return; fi
  curl -sS -f "${H[@]}" -X POST https://api.hubapi.com/crm/v3/properties/deals \
    -d "{\"name\":\"$1\",\"label\":\"$2\",\"type\":\"$3\",\"fieldType\":\"$4\",\"groupName\":\"dealinformation\",\"description\":\"$5\",\"hasUniqueValue\":false,\"formField\":false}" >/dev/null
  echo "created: $1"
}
ensure hot_score_v1 "Hot score v1" number number "Day-1 hot-deal score (0-100), model v1 fitted 2026-10-01; written weekly by the new-deals write-back job from BigQuery hubspot.hot_deals_v1"
ensure hot_flag_v1  "Hot deal v1"  bool   booleancheckbox "hot_score_v1 >= 45; written weekly by the new-deals write-back job"

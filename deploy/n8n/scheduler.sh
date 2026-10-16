#!/usr/bin/env bash
# scheduler.sh — scenario B2 trigger: Cloud Scheduler → n8n webhook (keeps n8n at minScale 0; same clock as scenario A).
# Jobs are created PAUSED; resume after the dry run (?dry_run=1) passed: deploy/n8n/scheduler.sh enable
# note: gcloud takes the webhook token in --headers on the command line (visible in `ps` for the call's duration) — run from a trusted shell.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${REGION:=europe-west6}" "${SCHEDULE_SEALSQ:=0 7 * * 1}" "${SCHEDULE_ICALPS:=20 7 * * 1}"
DRYRUN="${DRYRUN:-0}"; [[ "$PROJECT" != your-* ]] || { echo "PROJECT holds a placeholder" >&2; exit 2; }; run() { if [[ "$DRYRUN" == 1 ]]; then printf '  $'; printf ' %q' "$@"; echo; else "$@"; fi; }
case "${1:-create}" in
  enable) for e in SEALSQ ICALPS; do run gcloud scheduler jobs resume "n8n-new-deals-$e" --project "$PROJECT" --location "$REGION"; done ;;
  pause)  for e in SEALSQ ICALPS; do run gcloud scheduler jobs pause  "n8n-new-deals-$e" --project "$PROJECT" --location "$REGION"; done ;;
  create)
    N8N_URL=${N8N_URL:-$([[ "$DRYRUN" == 1 ]] && echo https://n8n-000000000000.$REGION.run.app || gcloud run services describe n8n --project "$PROJECT" --region "$REGION" --format 'value(status.url)')}
    TOKEN=$([[ "$DRYRUN" == 1 ]] && echo '<n8n-webhook-token>' || gcloud secrets versions access latest --secret n8n-webhook-token --project "$PROJECT")
    for e in SEALSQ ICALPS; do
      sched=$([[ $e == SEALSQ ]] && echo "$SCHEDULE_SEALSQ" || echo "$SCHEDULE_ICALPS")
      args=(--project "$PROJECT" --location "$REGION" --schedule "$sched" --time-zone Europe/Zurich --uri "${N8N_URL}/webhook/new-deals-run?entity=${e}"
            --http-method POST --headers "X-Delivery-Token=${TOKEN},Content-Type=application/json" --message-body '{}' --attempt-deadline 900s --max-retry-attempts 3)
      if [[ "$DRYRUN" != 1 ]] && gcloud scheduler jobs describe "n8n-new-deals-$e" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then run gcloud scheduler jobs update http "n8n-new-deals-$e" "${args[@]}"
      else run gcloud scheduler jobs create http "n8n-new-deals-$e" "${args[@]}"; run gcloud scheduler jobs pause "n8n-new-deals-$e" --project "$PROJECT" --location "$REGION"; fi
    done
    echo "dry run: curl -X POST -H 'X-Delivery-Token: <token>' '${N8N_URL}/webhook/new-deals-run?entity=SEALSQ&dry_run=1'   then: deploy/n8n/scheduler.sh enable" ;;
  *) sed -n '2,4p' "$0"; exit 1 ;;
esac

#!/usr/bin/env bash
# Offline end-to-end test: runs the REAL workflow in a real n8n against mock APIs.
# No API keys, no accounts, no network needed (beyond having n8n installed).
#
#   npm install -g n8n          # or: export N8N_CMD="npx n8n"
#   ./tests/run_tests.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
N8N_CMD="${N8N_CMD:-n8n}"
MOCK_PORT="${MOCK_PORT:-9911}"
N8N_PORT="${N8N_PORT:-5678}"
TMP="$(mktemp -d)"
export N8N_USER_FOLDER="$TMP/n8n-home" N8N_DIAGNOSTICS_ENABLED=false N8N_LISTEN_ADDRESS=127.0.0.1 N8N_PORT
mkdir -p "$N8N_USER_FOLDER"
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; rm -rf "$TMP"; }
trap cleanup EXIT

echo "== starting mock APIs on :$MOCK_PORT"
python3 "$HERE/mock_server.py" "$MOCK_PORT" & PIDS+=($!)
sleep 1

echo "== preparing offline copy of the workflow"
python3 "$HERE/make_test_workflow.py" "$ROOT/workflows/gtm-automation.json" "$TMP/test.json" "$MOCK_PORT"
$N8N_CMD import:workflow --input="$TMP/test.json" >/dev/null 2>&1

echo "== running the pipeline (research > enrich > qualify > CRM > slots > Slack)"
if ! $N8N_CMD execute --id=gtmtest0000000001 > "$TMP/exec.log" 2>&1; then
  tail -30 "$TMP/exec.log"; echo "pipeline execution FAILED"; exit 1
fi
grep -q "Execution was successful" "$TMP/exec.log" || { tail -30 "$TMP/exec.log"; echo "pipeline execution FAILED"; exit 1; }
echo "pipeline executed successfully"
python3 "$HERE/check_pipeline.py" "$MOCK_PORT"

echo "== starting n8n to test the approval webhook"
$N8N_CMD publish:workflow --id=gtmtest0000000001 >/dev/null 2>&1
$N8N_CMD start > "$TMP/n8n.log" 2>&1 & PIDS+=($!)
for _ in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$N8N_PORT/webhook/gtm-approval" || true)
  [ "$code" = "400" ] && break
  sleep 2
done
[ "$code" = "400" ] || { tail -20 "$TMP/n8n.log"; echo "n8n webhook did not come up"; exit 1; }
python3 "$HERE/approval_flow_test.py" "$MOCK_PORT" "$N8N_PORT"
echo "== ALL TESTS PASSED"

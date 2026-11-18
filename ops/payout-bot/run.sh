#!/usr/bin/env bash
# D46 daily payout (#314): finish yesterday's sends -> export inputs -> plan (#315) -> send (#316).
# Every step is idempotent: a re-run never plans a day twice and never sends a memo twice.
# Exit codes: 0 ok, non-zero = a step failed (see the journal); nothing is retried blindly.
set -euo pipefail
REPO="${COIN_REPO:-/opt/coin}"
CFG="${PAYOUT_CFG_DIR:-/etc/coin/payout-bot}"
PY="${COIN_PY:-$REPO/.venv/bin/python}"
NODE="${COIN_NODE:-/usr/bin/node}"
SD="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["state_dir"])' "$CFG/inputs.json")"
send() { "$NODE" "$REPO/ops/payout-bot/send.mjs" --plan "$1" --config "$CFG/config.json"; }
cd "$REPO"

# 1. The latest plan may have unsent transfers (failed run, day cap): send them first.
last="$(ls "$SD"/plan-*.json 2>/dev/null | sort | tail -n 1 || true)"
if [[ -n "$last" ]]; then send "$last"; fi

# 2. Inputs for the UTC day that just ended (refuses on unsent transfers or a short day).
out="$("$PY" tools/payout_inputs.py export --config "$CFG/inputs.json")"
echo "$out"
day="$("$PY" -c 'import json,sys; print(json.loads(sys.argv[1])["day"])' "$out")"
in="$SD/inputs-$day"
plan="$SD/plan-$day.json"

# 3. Plan once per day; carry comes from the previous plan.
if [[ ! -f "$plan" ]]; then
  carry=()
  if [[ -n "$last" && "$last" != "$plan" ]]; then carry=(--carry-in "$last"); fi
  "$PY" tools/payout_plan.py --snapshot "$in/snapshot.json" --balances "$in/balances.json" \
    --exclude "$in/exclude.json" "${carry[@]}" --day "$day" --out "$plan.tmp"
  mv "$plan.tmp" "$plan"
fi

# 4. Send it.
send "$plan"

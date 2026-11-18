# GTASP10 holder payouts (D46)

Automatic: nobody signs, picks or changes a payment by hand.

| Timer (UTC) | Runs | Signs? |
|---|---|---|
| `coin-holder-snapshot` every hour at :40 | `tools/payout_inputs.py snapshot`: every holder of our mint, minus excluded wallets, into `holder_state.json` (holding clock restarts at 0; the day's **minimum** balance counts) | no |
| `coin-payout` daily 00:10 | `run.sh`: 1. send what the last plan still owes; 2. `payout_inputs.py export` for the day that ended; 3. `tools/payout_plan.py` (#315) once per day, carry from the previous plan; 4. `send.mjs` (#316) | step 1 and 4 |

Files in `/var/lib/coin/payout-bot`: `holder_state.json`, `inputs-<day>/`, `plan-<day>.json`, `ledger.jsonl`.
Public: `/var/www/gtasp10/data/payouts.json`, shown as "Latest payouts" on the Rewards page.

## Never twice, never more than held
- A plan is made once per day. `export` refuses while the previous plan has transfers the ledger
  does not show as sent (the wallet still holds them), and on a day with fewer than 20 of 24 snapshots
  (no plan that day; the budget waits and is split the next day).
- The sender (`send.mjs`) never sends a memo twice (ledger + on-chain), never more of a token than the
  wallet holds, keeps the fee bot's SOL, and has a per-day cap. See its header.
- Exclusions: `team_wallets` → team, the system wallet → system, program-owned (off-curve) accounts →
  pool, plus `excluded` in the config (`burn`, `cex`, ...). They are published in each plan.

## Safety
- Same key as the fee bot (`/etc/coin/fee-bot/keypair.json`, owner `coinbot`, mode 600). Never printed.
- Kill switch: `touch /etc/coin/payout-bot/STOP` pauses payouts for everyone (announce any use), or `"enabled": false`.
- `"mode": "dry"` in `config.json` simulates and never sends.

## Install (server, as root; after the fee bot)
```
install -d -o coinbot -g coinbot -m 700 /etc/coin/payout-bot /var/lib/coin/payout-bot
cd /opt/coin/ops/payout-bot && npm ci --ignore-scripts --omit=dev
install -o coinbot -g coinbot -m 600 config.example.json /etc/coin/payout-bot/config.json
install -o coinbot -g coinbot -m 600 inputs.example.json /etc/coin/payout-bot/inputs.json  # set mint, system_wallet, team_wallets
install -o coinbot -g coinbot -m 600 /etc/coin/fee-bot/env /etc/coin/payout-bot/env         # HELIUS_API_KEY only
chmod -R o+rX /opt/coin/.venv                                                                # coinbot runs the repo's Python
cp coin-holder-snapshot.* coin-payout.* /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now coin-holder-snapshot.timer
```

## Go live
1. Let snapshots run one full UTC day (`journalctl -u coin-holder-snapshot`: 24 runs).
2. Keep `"mode": "dry"`, `systemctl start coin-payout`, read `plan-<day>.json` and the `dry` ledger lines.
3. Smoke test: `"mode": "live"`, `"max_transfers_per_day": 1`; run once; check the tx and memo on Solscan.
4. Normal caps, then `systemctl enable --now coin-payout.timer`.

Tests: `uv run pytest tests/test_payout_inputs.py tests/test_payout_run_sh.py` · `cd ops/payout-bot && npm test`.

# GTASP10 fee bot (D45)

Every hour (minute 20 UTC) the bot:
1. moves the coin's creator fees into the **system wallet** (pump.fun fee sharing set to 100% this
   wallet, `fee_mode: "sharing"`; or the wallet is the creator itself, `fee_mode: "creator"`);
2. keeps **30%** as the SOL prize pot (the draw stays off, legal #8) and puts **70%** in the basket budget;
3. buys the current index members with the basket budget via Jupiter, split by `weight_bps`.

Bought basket tokens stay in the system wallet (public). Paying them out to holders is the next step
(not in this bot yet). Everything is in `/var/lib/coin/fee-bot/ledger.jsonl` and the public summary
`/var/www/gtasp10/data/fee-bot.json`.

## Fee modes
- `"forwarded"` (GTASP10 now): pump.fun legacy creator rewards can't be shared, so the creator claims them and
  sends SOL from `forward_from` (the creator wallet) to the system wallet. The bot counts only plain transfers
  `forward_from` → system wallet after its cursor; the first live run only sets the cursor (earlier deposits,
  like the reserve, are not fees). Each counted transfer is split 67/28/5 like a claim (`collected` in the ledger).
- `"sharing"` / `"creator"`: the bot claims from pump.fun itself.

## Safety
- The secret key lives only in `/etc/coin/fee-bot/keypair.json` (owner `coinbot`, mode 600). The bot
  refuses any other mode or owner. It is never printed, logged or committed (`*keypair*.json` is gitignored).
- The RPC URL holds the Helius key and is never printed.
- **Public rules (#345):** split, caps, slippage and reserves come only from `econ/params.json` in the repo
  (72h timelock, sha256 in `fee-bot.json`). `config.json` holds only paths, mode and mint; it may lower a cap
  (shown publicly as `local_lower_caps`), never raise it or set a rule.
- Caps: `max_per_swap_lamports`, `max_per_run_lamports`, `max_per_day_lamports`; slippage at most 3%;
  price impact gate; buys only from a fresh, non-dry-run index whose weights sum to 10000; never buys its own mint.
- The wallet must hold pot + basket + `min_reserve_lamports` (tx fees and token-account rent) or the bot stops.
- D46: before buying, up to `payout_rent_target_lamports` of free SOL is set aside from the basket budget
  (within the day cap) so the payout bot can open holders' token accounts (`payout_rent` in the ledger).
- Kill switch: `touch /etc/coin/fee-bot/STOP` or `"enabled": false`. One run at a time (lock file).
- `"mode": "dry"` does everything except sign and send.

## Install (server, as root)
```
useradd --system --no-create-home --shell /usr/sbin/nologin coinbot
install -d -o coinbot -g coinbot -m 700 /etc/coin/fee-bot /var/lib/coin/fee-bot
cd /opt/coin/ops/fee-bot && npm ci --ignore-scripts --omit=dev
sudo -u coinbot node keygen.mjs /etc/coin/fee-bot/keypair.json   # prints the PUBLIC address only
install -o coinbot -g coinbot -m 600 config.example.json /etc/coin/fee-bot/config.json  # then set "mint"
printf 'HELIUS_API_KEY=%s\n' "<from /etc/coin/index.env>" > /etc/coin/fee-bot/env  # chown coinbot, chmod 600
chown coinbot /var/www/gtasp10/data   # or a group with write access to fee-bot.json
cp coin-fee-bot.service coin-fee-bot.timer /etc/systemd/system/ && systemctl daemon-reload
```
Give the public address to kiwi: he sets it as 100% fee recipient on pump.fun (one change, then locked)
and sends ~0.1 SOL for the reserve.

## Go live
1. `"mode": "dry"`: `systemctl start coin-fee-bot.service; journalctl -u coin-fee-bot -n 50`. Check `distributable`,
   `plan` and `dry_buy` lines.
2. Smoke test: `"mode": "live"`, add `"max_per_run_lamports": "20000000"` (0.02 SOL) to `config.json`. Run once, check the signatures on Solscan
   and `ledger.jsonl`.
3. Remove the local cap (back to the public caps), then `systemctl enable --now coin-fee-bot.timer`.

# Red team replay, part 2: current rules (D35-D39) and D39 draw (#189)

Updates the #162 table for the hourly schedule. Read from `index/params.json` (not the old filters):
F1 4h, F2 $50k liquidity, F3 top10 <= 30%, F4 8 SOL (DexScreener 24h x 1/400), F9 >= 50 window
wallets, F10 volume > 0, F11 MC <= 100x liquidity, weights `mc_volume_capped` cap 25%, prize slippage
300 bps. Draw rules from `engine/hourly_draw.py` (D39: linear odds, 5% supply cap, 0.01% min holding,
>= 100 groups, 5% odds cap, rollover). Part 1 (hysteresis, 1h-wait curve): `index_redteam_hourly_2026-11-18.md`.
Model: `sim/index_attacks.py`; tests: `tests/test_index_hourly_attacks_d39.py`. Offline, no trading.
No yield or APR claims. Costs are model assumptions, not quotes.

| Attack | Still works? | Cost (model) | Stopped / bounded by | Gap for rule issues |
|---|---|---|---|---|
| Cheap top-10 slot (thin pool, inflated MC) | Partly. A $50k pool carries a $5M MC (F2 + F11 = 100x). Above that: blocked (F11), property-tested | >= max($50k, MC/100) pool | F2, F11 | A $5M-MC coin still ranks if it also passes F4/F9; no free-float check (F7 removed, D37) |
| Wash volume | YES. F10 is volume > 0. Wash buys weight, bounded at 25% by the cap; F4 needs 3,200 SOL of volume for 8 SOL fees (turnover, fees return to LPs) | fees ~1/400 of volume, plus pool fee | weights cap 25%, F4 | Raw volume at 50% of weight (D36) is the exposure; accepted by kiwi 18 Nov |
| Sybil traders | YES at small size. F9 counts any wallet, so 50 dust wallets pass | ~0.15 SOL (50 x 0.003 SOL, assumption) | F9 (>= 50), 49 fail | Funding-cluster check not built (#169 closed, superseded) |
| Sybil in the draw | NO gain. Splitting 3% of supply over N wallets never raises odds (property test); dust under 0.01% is not eligible | n/a | linear odds, min holding, supply cap 5% | none; < 100 groups rolls over |
| Prize-basket sandwich (0.1 SOL buy, 25 bps pool fee, 3% slip) | Only in thin pools: 10 SOL pool +0.00225 SOL (2.3% of buy); 50 SOL pool and deeper: loss for the attacker | 1.5 SOL front-run at 10 SOL pool | 300 bps slippage + pool depth (F2 $50k) | Prize buys bigger than ~1% of pool depth, or a shallow basket token, need a depth check before mainnet (needs kiwi `APPROVED`) |

Sandwich profit is ~ slippage x buy (3% max) whenever it is positive; test bound is slip x buy +2% +
floor. Hourly rebalance and hourly draw schedules hold in all rows: membership change needs rank <= 8
(enter) and > 12 (exit); the 1h-wait curve gives 0 before 1h.

## Run
`uv run pytest tests/test_index_hourly_attacks_d39.py tests/test_index_hourly_attacks.py -q`

# F2 liquidity-floor sensitivity — 2026-11-19T13:00Z run

Issue: #251. Read-only replay of the saved index inputs; **no parameter or `INDEX_RULES.md` change**.
The F2 value ($50k today) is kiwi's decision.

- Source data: `origin/index-data:index/out/2026-11-19T13.json` (`as_of 2026-11-19T13:00:00Z`,
  `inputs_hash 0135a9db203b…`, 138 candidates).
- Replayed from the server-side `inputs_hash` preimage `data/index/inputs/2026-11-19T13.json`
  (the tool refuses the file if it does not hash to the recorded `inputs_hash`).
- Weights: D40 (`sqrt(MC)`, 18% cap, 5% floor), i.e. the weights code currently on `main`; the
  handoff superseded D36. Only `filters.min_liquidity_usd` is changed per row.
- The only `index/params.json` difference between the run's commit (`ec13510`) and current `main`
  is the payout split (unrelated to index selection), so membership/weights replay identically.

## Result

| F2 floor (USD) | pass all filters | members | top-10 (ticker bps) | bps sum | F2 excluded | not measured |
|---:|---:|---:|---|---:|---:|---:|
| 5,000 ⚠ | 18 | 10 | DCTY 1800, GTA6 1764, GTASZN 1009, Leonida 1198, GATO 1098, DacityCoin 634, WASTED 862, Macca 635, Apocrycoin 500, Dacity 500 | 10000 | 12 | 35 |
| 10,000 ⚠ | 18 | 10 | DCTY 1800, GTA6 1764, GTASZN 1009, Leonida 1198, GATO 1098, DacityCoin 634, WASTED 862, Macca 635, Apocrycoin 500, Dacity 500 | 10000 | 15 | 34 |
| 25,000 | 18 | 10 | DCTY 1800, GTA6 1764, GTASZN 1009, Leonida 1198, GATO 1098, DacityCoin 634, WASTED 862, Macca 635, Apocrycoin 500, Dacity 500 | 10000 | 23 | 29 |
| 50,000 | 12 | 10 | DCTY 1800, GTA6 1764, GTASZN 1009, Leonida 1198, GATO 1098, DacityCoin 634, WASTED 862, Macca 635, Apocrycoin 500, Dacity 500 | 10000 | 31 | 29 |

⚠ below the prescreen of the saved run: coins under it were never measured, so this row is a
lower bound (they are counted in *not measured*, not guessed).

*pass all filters* = coins passing F2 at this floor plus every other filter unchanged;
*members* = the top 10 actually selected (weights sum to 10,000 bps).

## What it means

- **F2 is not binding for the current top-10.** At $50k, 12 coins pass every filter for 10 seats,
  and the selected 10 (and their D40 weights) are identical at $25k, $10k and $5k.
- **Lowering F2 only changes the bench.** $50k → $25k adds 6 more eligible coins (12 → 18); going
  below $25k adds none among measured coins. The top-10, their order and their weights do not move.
- **Raising F2 above $50k is what would bind.** The table does not test that direction (issue scope
  is $5k–$50k); at $50k there are only 2 spare eligible coins before the 10-seat buffer is hit.
- **The $5k/$10k rows are lower bounds.** The hourly run only measures pools at or above the
  DexScreener prescreen (F2 × 1/2 = $25k today), so coins between $5k and $25k were never measured.
  They are reported as *not measured* (35 and 34), not guessed. At $25k and $50k the rows are exact.

## Reproduce

```bash
uv run python tools/index_f2_sensitivity.py data/index/inputs --last 1 \
  > reports/index_f2_sensitivity_2026-11-19.md
```

On the server the inputs live in `/opt/coin/data/index/inputs/` (local, not published, pruned
after 48h). No network, no keys.

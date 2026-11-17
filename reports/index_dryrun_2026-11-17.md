# GTA 6 index — first live dry run (17 Nov 2026)

Command (read-only; no keys needed):

```
uv run python tools/run_index.py --as-of 2026-11-17T23:15:00Z --out index/out \
  --rpc-url https://api.mainnet-beta.solana.com
```

Result: `index/out/2026-11-17.dryrun.json`, **96 live candidates**, 0 members (expected: F4 is
skipped and F5/F7/F9 have no wired source yet, so every coin is `insufficient_data`).

Reason counts over the 96 candidates: `insufficient_data` 83, `F1` 11 (younger than 6h),
`weak_keyword` 2 (Lucia/Jason, listed for kiwi's review).

Metrics collected for all 96 candidates: liquidity 35, market cap 89, 24h volume 89,
mint/freeze authorities 40, coverage 96. Market data: DexScreener (`/latest/dex/search`
per strong keyword + batched `/tokens/v1/solana/{mints}`). Authorities: Solana JSON-RPC
`getAccountInfo` (public endpoint rate-limited 56 of the 96 calls; those stay `None`).

Top candidates by market cap (single sample, so coverage is ~1/288 of a 24h window):

| ticker | age h | liquidity USD | MC USD | volume 24h USD | coverage | F8 |
|---|---|---|---|---|---|---|
| GTA6 | 486.2 | 48,262,981 | 12,065,742,861 | 2 | 0.0035 | revoked |
| GTA6 | 241.8 | 564,485 | 141,121,350 | 40 | 0.0035 | revoked |
| GTA | 3,613.8 | 15,499,999 | 31,564,764 | 0 | 0.0035 | revoked |
| GTA6 | 481.3 | 194,465 | 17,650,506 | 7,555,905 | 0.0035 | revoked |
| Leonida | 16.4 | 23,838 | 1,437,831 | 112,619 | 0.0051 | — |
| GTA | 2,016.3 | 103,454 | 941,557 | 358,300 | 0.0035 | revoked |
| GTA 6 Coin | 15,806.5 | 83,219 | 447,606 | 93,848 | 0.0035 | revoked |
| Leonida | 307.6 | 54,573 | 432,859 | 225,711 | 0.0035 | — |
| GTAVI | 34.4 | 35,412 | 230,586 | 234,304 | 0.0035 | revoked |
| GTA | 17.0 | 25,167 | 125,228 | 243,732 | 0.0049 | revoked |

## Data still missing (fail-safe: `None` → `insufficient_data`)

- **F4 total fees**: deliberately not implemented (issue #161 step 6, kiwi's choice pending);
  dry runs skip it. A dry-run output is never official.
- **F5 bundle, F7 serial creator**: need Helius Parsed Events; no `HELIUS_API_KEY` in this
  environment, and the create/bundle heuristics were not verified against a live key, so they
  are not shipped. Metrics stay `None`.
- **F9 unique traders**: `helius_history` + `unique_traders` are implemented and unit-tested
  against recorded shapes; wire the key and they fill on the hourly pass.
- **F3 top 10**: `top10_pct` is implemented (top-10 share, excluding burn, hubs and pool/curve
  vaults detected by their authority's owner program). It needs `--holders` and an RPC endpoint
  that is not rate-limited; otherwise the metric stays `None`.
- **F6 dev %**: `dev_pct` + `creator_from_history` are implemented; they run when the Helius
  key is present (creator = fee payer of the mint's earliest parsed transaction).

## Next run

The G3 cron samples every 5 minutes (`--collect-only`) and runs the rebalance at 18:00 UTC.
Coverage only reaches the 50% floor after repeated samples, which is what this first pass is
missing. With `HELIUS_API_KEY` set, F9/F6 fill automatically; F4 still needs kiwi's decision.

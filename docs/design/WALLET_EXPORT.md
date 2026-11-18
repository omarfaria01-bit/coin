# WALLET_EXPORT — `/gtasp10/data/wallets/<address>.json` (v1, #273)

Producer: `adapters/wallet_export.py` (post-launch, read-only: no keys, no tx, no clock).
All numbers come from the engine; the page must not recompute them.

| Field | Meaning |
|---|---|
| `schema` | 1 |
| `address` | wallet (base58) |
| `as_of` | ISO-8601 UTC of the snapshot |
| `holding_seconds` | age of the wallet's oldest still-held lot |
| `supply_share` | balance / total supply, 9 decimals, floored |
| `draw_odds` | share of the hourly draw odds (D39: linear, 5% supply cap, 0.01% min, 5% odds cap); cluster odds split by balance; 9 decimals, floored |
| `multiplier` | `{exact: "num/den", decimal}` = `engine.loyalty.loyalty_multiplier(holding_seconds)` (0 below 1h, 5× at 4h, log to 10× at 30 days) |
| `eligible` | in the draw (cluster eligible and wallet not excluded) |
| `excluded_reason` | `null` or reason from `adapters.solana_keys.rewards_excluded` |
| `accrued` | `[{ticker, amount (base units, string), usd (2 decimals)}]` |

Caller contract: drop excluded wallets from `scores`/`cluster_balances` first (D39); write with
`write_wallet_files` (atomic temp + rename). Going live needs kiwi; draws stay OFF (legal #8).

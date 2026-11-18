# INDEX_OUTPUT_SCHEMA — the hourly index JSON (v0.1)

Output contract of the GTASP10 index job for the front end (#164, #224).
Producer: `tools/run_index.py`, `index/select.py`, `index/emergency.py`,
`tools/index_watch.py`; rules `INDEX_RULES.md` §5–§8. Documents today's format.

## 1. Where the files are

The hourly job publishes to the **`index-data` branch** of `omarfaria01-bit/coin`,
in the directory `index/out/`. The main branch never carries index output.

| File | Written when |
|---|---|
| `index/out/<YYYY-MM-DDTHH>.json` | official hourly rebalance (`rebalance_hours` = 1, the production setting) |
| `index/out/<YYYY-MM-DD>.json` | rebalance with `rebalance_hours` != 1 (date-only name) |
| `index/out/<same stem>.dryrun.json` | any run with a non-empty `dry_run.skip_filters`; never official |
| `index/out/emergency.json` | by `--mode emergency`, right after the hourly rebalance |

Examples: `index/out/2026-11-18T03.json`, `index/out/2026-11-18T18.dryrun.json`.
The suffix comes from `tools/run_index.py:_out_name`; `.dryrun.json` wins over
`.json` when filters were skipped.

**Cadence.** The `coin-index-sample.timer` writes quotes every 5 minutes to
`data/index/samples/<YYYY-MM-DD>.jsonl` in the main checkout (gitignored, *not*
published). The `coin-index-hourly.timer` runs at `:00` UTC: one closing sample,
then `--mode rebalance` for `HH:00:00Z`, then `--mode emergency`, then commits
`index/out/` to `index-data`. One commit per changed hour ("index
YYYY-MM-DDTHH:MMZ"). If a step fails, nothing is pushed and the previous remote
file stays.

**Consumption.** Read the greatest file name matching
`^\d{4}-\d{2}-\d{2}T\d{2}\.json$`; skip `emergency.json` and `*.dryrun.json`.
Check `as_of` against the file name, and treat `dry_run: false` as the only
official index. Hours can be missing when the job failed; do not assume a
gap-free hourly series.

**Encoding.** Canonical JSON: UTF-8, sorted keys, no insignificant whitespace,
written atomically (temp file + rename). Arrays are in rank order or mint byte
order as stated below. Files are never edited after the next hour is published.

## 2. Top-level keys

<!-- index-output-schema-keys:start -->
```json
{
  "top_level_required": ["as_of", "changes", "code_commit", "dry_run", "emergency", "excluded", "inputs_hash", "members", "params_hash", "skipped_filters"],
  "top_level_conditional": ["data_hold", "exit_notice"],
  "member": ["log_s", "metrics", "mint", "rank", "ticker", "weight_bps"],
  "member_metrics": ["age_hours", "bundle_pct", "coverage", "creator_launches_7d", "description", "dev_pct", "extensions", "freeze_authority_revoked", "independent_traders", "liquidity_usd", "mc_usd", "median_trade_sol", "mint", "mint_authority_revoked", "name", "roundtrip_share", "sources", "ticker", "token_program", "total_fees_sol", "top10_pct", "unique_traders", "volume_usd", "volume_wallets", "window_fees_sol"],
  "excluded": ["mint", "reason", "ticker"],
  "changes": ["entered", "exited"],
  "change_exited": ["mint", "reason"],
  "emergency": ["at", "mint", "reason"]
}
```
<!-- index-output-schema-keys:end -->

| Key | Type | Unit | Meaning / nullability |
|---|---|---|---|
| `as_of` | string | ISO-8601 UTC `...Z` | Rebalance timestamp, a whole hour. Matches the file name. |
| `code_commit` | string | git sha | `git rev-parse HEAD` of the producer checkout, or `"unknown"` when git is unavailable. |
| `dry_run` | bool | — | `true` iff `skipped_filters` is non-empty. Official files are always `false`. |
| `skipped_filters` | array[string] | filter id | Filters bypassed, e.g. `["F3"]`; `[]` for an official run. |
| `params_hash` | string | sha256 hex | Hash of the canonical params JSON (`index/params.json` model). Changes with any param. |
| `inputs_hash` | string | sha256 hex | Hash of `{candidates, prev_members, overrides}` (candidates sorted by mint bytes). Same inputs + params ⇒ same file. |
| `members` | array[object] | — | Current members, rank order, `0..membership.size`. Empty is valid: no coin passed the filters. |
| `excluded` | array[object] | — | Candidates that are not members, with the first reason. `no_keyword` coins are omitted. |
| `changes` | object | — | Difference against the previous published file. |
| `emergency` | array[object] | — | Emergency removals applied to this file; `[]` normally. |
| `exit_notice` | array[string] | mint | **Conditional**, present (possibly `[]`) iff `rebalance_hours` == 1. Mints whose rank exit is deferred one hour. |
| `data_hold` | array[string] | mint | **Conditional**, present only when non-empty. Mints whose new hour was `insufficient_data` and whose last passing metrics were carried forward. |

No API key, secret or RPC URL appears in the file. Hashes are not secret and
are safe to display.

## 3. `members[]`

| Key | Type | Unit | Meaning |
|---|---|---|---|
| `mint` | string | base58 | Solana mint address. |
| `ticker` | string | — | Symbol from discovery; `""` when unknown. |
| `rank` | int | 1-based | `1` = highest `log_s`. Contiguous within the file. |
| `log_s` | float | — | Score from INDEX_RULES §4, rounded to `score.round_decimals` (12). |
| `weight_bps` | int | basis points | `0..10000`; the file's `weight_bps` sum to `10000` whenever `members` is non-empty. `equal` or `score_capped` per params. |
| `metrics` | object | — | The measured window values for this member. |

`metrics` (a `Metrics` snapshot; `null` means "not measured / unknown", never 0):

| Key | Type | Unit | Meaning |
|---|---|---|---|
| `mint` | string | base58 | Same mint as the member (repeated). |
| `ticker` | string | — | Same ticker as the member. |
| `name` | string | — | Token name. |
| `description` | string | — | Token description; `""` allowed. |
| `coverage` | float | fraction 0..1 | Share of 5-minute buckets in the window that have a sample (D35: any samples count, zero = insufficient_data). |
| `age_hours` | float | hours | Age since first pool/curve. |
| `liquidity_usd` | float | USD | Window arithmetic mean pool liquidity (curve reserve for bonding curves). |
| `mc_usd` | float | USD | Window arithmetic mean market cap. |
| `top10_pct` | float | percent 0..100 | Median of hourly holder samples, excluding vaults, burn, hubs and treasury. |
| `total_fees_sol` | float | SOL | Lifetime trader fees (transaction + priority fees + tips). |
| `window_fees_sol` | float | SOL | Trader fees inside the window. |
| `bundle_pct` | float | percent 0..100 | Supply bought in the creation block by more than one wallet. |
| `dev_pct` | float | percent 0..100 | Creator holding at measurement. |
| `creator_launches_7d` | int | count | Tokens by this creator in the 7 days before `as_of`, this one included. |
| `mint_authority_revoked` | bool | — | F8. |
| `freeze_authority_revoked` | bool | — | F8. |
| `token_program` | string | program id | Legacy SPL Token or Token-2022 (F8c). |
| `extensions` | array[string] | — | Token-2022 mint extension names; `[]` for legacy SPL. |
| `unique_traders` | int | wallets | Wallets that paid fees in the window (score input). |
| `independent_traders` | int | wallets | Wallets ≥ `min_trader_volume_sol` in the window, creator excluded (F9). |
| `volume_usd` | float | USD | Window total volume. |
| `roundtrip_share` | float | fraction 0..1 | Share of SOL volume that is same-wallet round trips (F10). |
| `volume_wallets` | int | wallets | Wallets with volume left after removing round trips (F10). |
| `median_trade_sol` | float | SOL | Median trade size after removing round trips (F10). |
| `sources` | object | — | Metric name → `"<source>@<ISO-8601Z fetch time>"`. `{}` today: the mapping is not wired yet. |

All integers here are counts or basis points; no lamport or token base-unit
amounts appear (the prize split in INDEX_RULES §7 is engine output).

## 4. `excluded[]`

`{mint, ticker, reason}`, sorted by mint bytes. `reason` is one of
`insufficient_data` (a required metric is missing), `weak_keyword`, `denied`,
`self`, or the first failed filter `F1`…`F11` (an F8c failure is reported as
`F8`). A coin that passes everything is either a member or is not listed here;
`no_keyword` coins are not listed at all. A missing metric always counts as a
failure, never as a pass.

## 5. `changes`

- `entered`: array of mint strings, rank order.
- `exited`: array of `{mint, reason}`, mint byte order. `reason` is the filter
  that now fails (or `insufficient_data`, `denied`, `weak_keyword`), `rank_<N>`
  when it fell out of the buffer band, or `not_measured` when it was absent from
  the new run. Emergency removals do **not** appear here; they are only in
  `emergency`.

With `rebalance_hours` = 1, a `rank_<N>` exit is moved to `exit_notice` for one
hour instead of leaving immediately. A filter failure still exits at once. On
the next run the coin leaves (its exit reason is then reported normally).

## 6. `emergency` and `emergency.json`

`emergency` entries are `{at, mint, reason}` appended in application order;
`at` is ISO-8601 UTC. `reason` is `rug_flag`, `authority_enabled` or
`liquidity_drop` (INDEX_RULES §5). The member is already removed from `members`
and the weights recomputed; no replacement is added until the next rebalance.

`index/out/emergency.json` is a convenience mirror of the current file's
removals: `{at, emergency}` with the same `emergency` array. It is overwritten
on each emergency run, so use the hourly file for history.

## 7. Empty and null cases

| Situation | Result |
|---|---|
| no coin passes the filters | `members: []`, `changes.entered: []`; still a valid official file |
| a member's hour is missing | member keeps last passing `metrics` for that hour and is listed in `data_hold` |
| a required metric is unknown | the coin is `insufficient_data` (or the filter that needs it fails) |
| dry run with skipped filters | `dry_run: true`, filters in `skipped_filters`, e.g. `top10_pct: null` |
| nothing was removed | `emergency: []` |
| no rank exit was deferred | `exit_notice: []` (hourly runs only) |
| no source strings wired | `sources: {}` in every member |
| previous file absent (first run) | `changes.entered` lists every member, `changes.exited: []` |

## 8. Real example (redacted lists)

Top level from `origin/index-data`, commit `c70357f`, file
`index/out/2026-11-18T03.json`. `excluded` had 99 entries; 2 are shown and the
rest elided. Values are otherwise unchanged.

```json
{
  "as_of": "2026-11-18T03:00:00Z",
  "changes": {"entered": [], "exited": []},
  "code_commit": "c6c0ca8d4f91701f63032d3d9097bcec72bbc450",
  "dry_run": false,
  "emergency": [],
  "excluded": [
    {"mint": "5tT8HDQSxFTB2Yhg9hVkxEzmSrHwWG8w4nJDmBK95q6", "reason": "insufficient_data", "ticker": "VICECITY"},
    {"mint": "AF91MhDySwUYvZruDMWKrd6tJ8phbBMoZ4VysD7pump", "reason": "insufficient_data", "ticker": "VICE CITY"}
  ],
  "exit_notice": [],
  "inputs_hash": "b4f8243c332202d696cacaa2dc8a7a4a02035cee790c4019dc7f9b47cbf7a0a5",
  "members": [],
  "params_hash": "2923c0799e8448c9f6a262ca5696fe2a2657b057cf5fab79f2222e4cf1531962",
  "skipped_filters": []
}
```

Member object from the offline dry-run test fixture (`tests/test_index_e2e_offline.py`,
`2026-11-18.dryrun.json`); the `metrics` object is shown on one line for width:

```json
{"log_s": 10.272375497948, "metrics": {"age_hours": 12.0, "bundle_pct": 2.0, "coverage": 1.0, "creator_launches_7d": 1, "description": "", "dev_pct": 1.0, "extensions": [], "freeze_authority_revoked": true, "independent_traders": 500, "liquidity_usd": 80000.0, "mc_usd": 1000000.0, "median_trade_sol": 0.1, "mint": "G9ZMir6uh66Y7viPkXAy7myA9jjE4T1YgheVUmGDpump", "mint_authority_revoked": true, "name": "Good To Ape", "roundtrip_share": 0.0, "sources": {}, "ticker": "GTA", "token_program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "top10_pct": null, "total_fees_sol": 150.0, "unique_traders": 500, "volume_usd": 200000.0, "volume_wallets": 100, "window_fees_sol": 40.0}, "mint": "G9ZMir6uh66Y7viPkXAy7myA9jjE4T1YgheVUmGDpump", "rank": 1, "ticker": "GTA", "weight_bps": 10000}
```

The fixture run is a dry run (F3 skipped), so its member's `top10_pct` is `null`.

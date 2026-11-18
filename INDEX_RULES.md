# INDEX_RULES.md — GTA 6 Index (v0.1, 17 Nov 2026)

The index tracks the **top 10 GTA 6 memecoins on Solana**, chosen every hour by the published rules below. Anyone can recompute it from the published inputs. Parameters live in `index/params.json` (validated by `index/params.py`, unknown keys rejected); changing one needs a DECISIONS.md entry. The temporary coin name and ticker are **GTASP10** (D26).

Holder rewards and draw prizes are both paid in the index basket (section 7). Out of scope for this coin (D24): supply vesting, dev-token locks, early-buy vesting, taint/forfeit, underwater boost, treasury bot.

## 1. Universe

A token is a **candidate** if it is a Solana token and its name, ticker or description matches the keyword list (case-insensitive):

- **One tier (D35).** Any match is a candidate: `GTA`, `GTA6`, `GTA 6`, `GTAVI`, `GTA VI`, `GTA5`, `GTAV`, `Grand Theft`, `Grand Theft Auto`, `Vice City`, `ViceCity`, `Leonida`, `Leonida Keys`, `Port Gellhorn`, `Ambrosia`, `Grassrivers`, `Mount Kalaga`, `Lucia`, `Lucia Caminos`, `Jason Duval`, `Cal Hampton`, `Boobie Ike`, `DreQuan`, `Real Dimez`, `Raul Bautista`, `Brian Heder`, `Rockstar`, `Rockstar Games`, `Take-Two`, `TTWO`, `Wasted`, `Mission Passed`, `Wanted Level`, `Tommy Vercetti`, `Vercetti`. Bare `VI` and bare `Jason` are not keywords (they match unrelated coins).
- A keyword matches only when no letter touches it on either side (so `GTA` matches `GTA6` and `$GTA`, but not `AGTAB`).
- **D37 (kiwi 18 Nov):** the list is one big GTA-series vocabulary (`keywords.strong` in params). Ambiguous words
  (`keywords.needs_context`: Jason, Vice, Trevor, Franklin, ...) count only with GTA context: a strong word, or a second
  different ambiguous word, in the same name/ticker/description.
- **Discovery (D37):** top-down, never new launches. DexScreener search for the vocabulary terms (Solana); the top h24-volume
  (trending) coins are collected first, then the biggest market caps (`discovery` in params). Seed file and last members too.

`index/overrides.json` holds only `deny` entries (scams), each with a mint, a reason and the issue where kiwi approved it. There is no allow list. The index coin itself (`self_mint`) is never a candidate.

## 2. Measurement

- **Rebalance time:** every hour (`rebalance_hours` = 1). `rebalance_hour_utc` is unused while that is 1.
- **Window:** the 24 hours before that hour, or the token's whole life if it is younger. An hourly run does not shrink the window to one hour.
- **Sampling:** the adapter samples every candidate every 5 minutes (holder data every hour). Averages are arithmetic means of the samples in the window; "median" is the median of the hourly holder samples. One sample per hour cannot fill a 5-minute window, so the 5-minute sampler has to be running.
- **Coverage (D35):** no minimum. Whatever samples exist in the window are used; a coin with zero samples is `insufficient_data` (fail-safe). A current member whose new hour is `insufficient_data` keeps its last passing metrics for that hour. A run that errors does not replace the published file.
- **Sources:** each metric's source and definition are listed in `reports/research_index_data_2026-11.md` and fixed in DECISIONS.md. Only officially allowed access is used, no scraping against terms.

## 3. Hard filters (all must pass)

| # | Filter | Rule |
|---|---|---|
| F1 | Age | ≥ 4h since the token's first pool or curve |
| F2 | Liquidity | average ≥ $50,000 (pool liquidity in USD; for coins on a bonding curve, the curve's quote reserve in USD) |
| F3 | Top 10 holders | median between **13% and 27%** of total supply, excluding pool/curve vaults, the burn address, listed hubs (`data/hubs/solana_hubs.csv`) and the index treasury |
| F4 | Total fees | **≥ 8 SOL** paid by the token's traders since launch: transaction fees + priority fees + tips |
| F5 | Bundle at launch | ≤ 30% of supply bought in the creation block by more than one wallet |
| F6 | (removed, D35) | no dev filter |
| F7 | Serial creator | the creator created ≤ 3 tokens (this one included) in the 7 days before the rebalance |
| F8 | Authorities | mint authority and freeze authority both revoked |
| F9 | Real traders | ≥ 200 wallets that each traded ≥ 0.05 SOL in the window; the creator wallet does not count (D33, #170) |
| F10 | Volume | window volume > 0, Helius raw volume as-is (D35). No round-trip cleanup, no turnover band, no wallet or median-trade minimum |
| F11 | Market cap vs liquidity | average market cap ≤ 100 × average pool liquidity (D29, #167). A thin pool cannot carry a huge market cap |
| F8c | Token program (part of F8) | legacy SPL Token, or Token-2022 with only allowlisted mint extensions (D32, #171); anything else fails, unknown = insufficient_data |

F1, F4, F5, F6, F10 and coverage follow kiwi's 18 Nov decisions (D35). F3 and F4 are kiwi's parameters. A coin that fails any filter is listed in the output with the first filter it failed. A missing metric counts as a failure (`insufficient_data`), and the output names it (`missing`, D37). For coins with more history than the page cap, F4 and F9 accept a measured lower bound that already passes (D37).

**Dry runs only:** `dry_run.skip_filters` can skip filters whose data source isn't wired yet (e.g. F4). Any output computed with a skipped filter is marked `"dry_run": true` and is never the official index.

## 4. Score

Only coins that pass every filter are scored:

```
log S = 0.4·ln(MC) + 0.3·ln(Liquidity) + 0.2·ln(Fees) + 0.1·ln(Traders)
```

- `MC`, `Liquidity`: window averages in USD. `Traders`: F9's count.
- `Fees`: trader fees in the window if the source provides them, otherwise lifetime total fees (`score_fees_window` in params; the choice is a DECISIONS.md entry). The choice is **global**: every coin is scored on the same fee measure, and a coin missing it is `insufficient_data`.
- Any metric that is not a finite number (NaN, infinity) counts as missing.
- The filters guarantee every input is > 0. Changing units (USD vs SOL, lamports) does not change the ranking.
- `log S` is rounded to 12 decimals. Ties are broken by mint address (byte order). **Rank 1 = highest S.**

## 5. Membership (buffer rule)

`size = 10`, `enter_rank = 8`, `exit_rank = 12`. With `P` = passing coins ranked by S and `M_prev` = the previous hour's members:

1. `E` = coins of `P` ranked ≤ `enter_rank`, plus members of `M_prev` still in `P` and ranked ≤ `exit_rank`.
2. New members = the `size` best-ranked coins of `E`.
3. If that gives fewer than `size`, fill with the best-ranked remaining coins of `P`.
4. A coin that fails a filter is never a member. The index may hold fewer than 10 coins, or none.
5. First rebalance (no `M_prev`): the top `size` of `P`.

So a newcomer must reach the top 8 to enter, and a member is only replaced when it falls below 12th or is beaten for its place. On the hourly cadence a rank exit waits one more hour (`exit_notice`); a filter failure still removes the coin immediately.

**Emergency removal** (at any time, not only at rebalance): pool liquidity down ≥ 50% within 1h on two samples 15 min apart (D34), mint or freeze authority re-enabled, or the token flagged as a rug by the data source. The member is removed with the reason logged; weights are recomputed among the remaining members; no replacement until the next rebalance.

## 6. Weights

- `mc_volume_capped` (default, D36, kiwi 18 Nov): `weight_i = 0.5 * MC_i / sum MC + 0.5 * Volume_i / sum Volume`, with MC the window-average market cap and Volume the raw Helius window volume (a half whose sum is 0 counts as equal). Then capped at 25% per coin with water-filling. With fewer than 4 members the cap can't hold, so weights fall back to `equal`.
- `equal` (option): every member weighs `1/n`.
- `score_capped` (option): proportional to S, capped at `cap_pct` with water-filling; same fallback rule.

Weights are published as integer basis points summing to 10,000: floor each, then hand out the remaining points one by one by largest remainder, ties to the better rank.

## 7. How the coin uses the index: basket rewards

- Creator fees for this coin: 70% holder rewards, 30% draw pot (`payout` in params). No team share and no buyback. Both pots are paid in the index basket, not in SOL. Holder rewards stay on a 24h cadence; the draw closes every hour.
- At each draw, a prize of `D` lamports is split: member `i` gets `floor(D · bps_i / 10000)` lamports; the leftover lamports go to the rank-1 member.
- Each part buys that member's token, sliced, with a 3% slippage cap (`prize_slippage_bps`). A part below `min_prize_lamports` (0.01 SOL) is not bought; it stays in the pot for the next hour. A part that can't be bought within the cap is paid in SOL.
- The engine file `config/coin.json` is not this split (D26). Buying basket tokens is a mainnet write and needs kiwi's `APPROVED <issue#>`. This repo does not send those transactions.

## 8. Output (`index/out/<YYYY-MM-DDTHH>.json`, canonical JSON)

- `as_of` (rebalance time), `params_hash`, `code_commit`, `inputs_hash`
- `members`: mint, ticker, rank, `log_s`, `weight_bps`, every metric, and `sources` mapping each metric to `"<source>@<ISO fetch time>"`
- `excluded`: mint, ticker, first failed filter (or `insufficient_data`, `denied`)
- `changes`: entered / exited, with the reason
- `emergency`: removals since the last rebalance, with the reason

Canonical JSON = UTF-8, sorted keys, no insignificant whitespace, arrays sorted by rank or mint.

## 9. Known limits (published)

- Every number comes from third-party data. If a source is wrong, the index is wrong until the next run.
- Someone can pay to qualify: buying real liquidity, real fees and 200 real traders costs money, and the 24h averages make a last-minute pump useless, but it is not impossible. Red-team results are reported in `reports/`.
- Membership in the index is not an endorsement and not advice.

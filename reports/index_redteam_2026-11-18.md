# Index red team — GTA 6 index v0.1 (18 Nov 2026 CET)

Scope: `INDEX_RULES.md` v0.1 (#157) and the `index/` code (#158–#160), all merged on `main` at `6129c84` (#157–#160, plus #165 emergency/review fixes), against the attacks in #162. Date note: data reads were made 2026-11-17 23:00–23:25 UTC (2026-11-18 00:00–00:25 CET). The filename uses the CET date; every chain/API timestamp below is UTC. Analysis and simulation only: no wallets, no token creation, no mainnet writes. The G2 adapter (#161) is not merged and F4 has no confirmed source, so "replay" below means the actual pure filter/select code on synthetic metrics, plus a cost model using live chain constants. Replay pinned `main@6129c84`; re-run it if the rules or code change.

## TL;DR

A well-funded attacker can buy a top-10 slot for roughly **10–17 SOL ($750–$1,300) plus recoverable capital**, and can make a low-float coin rank **#1** with a $50k pool. The binding constraints are not the hard filters; they are the 10 SOL F4 floor and the 24-hour averaging. Three things are cheap enough to be launch-day risks: a low-float high-MC coin, a sybil-distributed supply, and a fixed 10 SOL fee floor that does not scale with market cap. One config hole (`self_mint: null`) and one process hole (F4 can be skipped) must be closed before the first official output.

| # | Attack | Works? | Cost (17 Nov 2026 UTC) | Rule that stops it | Proposed fix |
|---|---|---|---|---|---|
| 1 | Low-float high-MC: 0.1% float + $50k liquidity, 37 holder wallets | **Yes** | ~17 SOL ($1,290) + $50k recoverable capital | none; F10 only forces 5% volume | #167 |
| 2 | Wash volume to pass F10 (attacker owns the pool) | **Yes** | 0.27–6.7 SOL at 0.02% protocol fee; 334 SOL at 1% | F10 ratio only; no wallet/round-trip check | #170 |
| 3 | 200 fake traders to pass F9 | **Yes** | 0.04–0.20 SOL + 0.30 SOL refundable rent | none | #170 |
| 4 | Disperse supply to land inside 13–27% (F3) | **Yes** | 0.055 SOL rent + 0.0002 SOL fees | none (F3 is the target) | #169 |
| 5 | Split launches across fresh creator wallets (F7) | **Yes** | 0.04–0.24 SOL for 10 launches | none | #169 |
| 6 | Pump MC/liquidity just before 18:00 UTC | **No** for 5 min; **Yes** if held 24h / own LP | 5 min needs a 29.8× spike; 24h needs 1.1× | 24h arithmetic mean | #167, #169 |
| 7 | Impersonator/rebrand with a GTA keyword | **Yes** if metadata is mutable (UNVERIFIED for pump.fun) | ~0.000005 SOL + the normal filters | keyword is the target; F8 ignores metadata | #171 |
| 8 | Snipe/bundle just after the creation slot (F5) | **Yes** next slot / single wallet | priority fee + capital | F5 only looks at the creation block and >1 wallet | #169 |
| 9 | Index coin includes itself (`self_mint: null`) | **Yes** (config) | 0 | none | #166 |
| 10 | Publish an official file with F4 skipped | **Yes** by mistake | removes the 10 SOL floor | process only; `dry_run` is a flag | #166 |
| 11 | Token-2022 permanent delegate / hook / fee / pause | **Yes** if the venue allows it | ~0.02 SOL + capital | F8 checks only mint/freeze | #171 |
| 12 | Sandwich the prize basket buy | **Yes** | capital; max 0.3% of prize pool `D` per 10% member | 3% slippage cap limits, not removes, the profit | #172 |
| 13 | Dump a rival to trigger 1h emergency removal | **Yes** for a large holder | bag + slippage; may be profitable as an exit | the 1h drop rule is the trigger | #172 |
| 14 | Multi-pair DexScreener inflation (fake pair) | **UNVERIFIED** | pool creation + capital | adapter pair selection is not defined yet | #167 |

## 1. Low-float high-MC — the strongest attack

Market cap is `price × supply`; price is set by the pool. Put a fraction `f` of supply in the pool with quote liquidity `L`:

```
P = L / (f·S)      MC = P·S = L / f
```

With `L = $50,000` and `f = 0.1%`, `MC = $50,000,000` — a top score with a $50k pool. The non-pool 99.9% sits in sybil wallets: to keep top10 ≤ 27%, 37 wallets are enough (`n ≥ 37·(1−f)`), costing 37 × 0.00148844 = **0.055 SOL** of refundable rent. F6 checks only the creator wallet, so the creator keeps one of the 37.

F10 then requires `0.05 × MC = $2.5M` of 24h volume. If the attacker owns the pool, the LP share of the swap fee comes back to them; the net cost is the protocol share. At 0.02% that is **$500 (6.7 SOL)**, at 0.25% **$6,250 (83 SOL)**, at a 1% pump curve **$25,000 (334 SOL)**. Add F4's 10 SOL and the sybil rent: **~17 SOL ($1,290) + $50k recoverable capital** at the low end.

Replay (10 synthetic candidates, main `6129c84`):

```
rank  1 FLOAT    logS=11.327296 bps= 1000 mc=50000000 liq=50000
rank  2 REBRAND  logS=11.276874 bps= 1000 mc=8000000  liq=400000
rank  3 T22      logS=10.794624 bps= 1000 mc=5000000  liq=150000
rank  4 LEGIT    logS=10.428108 bps= 1000 mc=2000000  liq=150000
```

FLOAT passes F1–F10 with `top10=20%`, `dev=2%`, `200` traders, `10` SOL fees, `volume=$2.5M`. DexScreener documents FDV as `(total supply − burned) × price`; `marketCap` may use self-reported circulating supply, and aggregation across pairs is not documented (docs read 17 Nov 2026 UTC).

## 2. Wash volume and fake traders (F10, F9)

F10 is a ratio, not a quality check. At $2M MC the minimum is $100k; at $50M it is $2.5M. A round trip is counted twice, and an attacker who owns the LP gets the LP fee back. Self-LP numbers:

```
MC $2,000,000  V $100,000   own LP 0.02%  0.27 SOL ($20)
MC $50,000,000 V $2,500,000 own LP 0.02%  6.68 SOL ($500)
MC $50,000,000 V $2,500,000 pump curve 1% 333.82 SOL ($25,000)
```

F9 only counts unique wallets. 200 wallets that each buy 0.01 SOL and sell once cost **0.043 SOL ($3.2)** non-recoverable, plus 0.298 SOL of refundable ATA rent. At 0.05 SOL per wallet: 0.203 SOL ($15) + rent. The F4 floor (10 SOL) is separate and larger, but F9 itself is not a barrier.

## 3. F3 dispersion, F6 dev, F7 serial creator, F5 bundle

- **F3:** 20% across 10 wallets passes; 37 wallets keep top10 at 27% while the cluster holds 99.9%. Cost of the dispersion: 0.055 SOL rent + 0.0002 SOL fees.
- **F6:** only the creator address is checked. One transfer to a fresh wallet makes `dev_pct` pass while the economic position is unchanged.
- **F7:** four fresh creator wallets cover ten launches. Cost: ~0.01 SOL funding each + 0–0.02 SOL creation per token = **0.04–0.24 SOL**.
- **F5:** "creation block by more than one wallet". A single wallet in the creation block is not a multi-wallet bundle; a buy in the next slot is outside the window. A priority/Jito bundle can land it immediately after creation.
- **F1:** 6h. The window is the token's whole life if younger, so a token created at 12:00 can be in the 18:00 index the same day. Minimum attack time is ~7h, not days.

Replay: `SYBIL` passes all filters with `top10=20%`, `dev=2%`, `creator_launches_7d=2`, `unique_traders=250`, `volume/MC=0.05`. Boundary checks behave as written:

```
top10=27.000000 -> None
top10=27.000001 -> F3
volume=100000 turnover=0.050000 -> None
volume=99999  turnover=0.050000 -> F10
```

## 4. Timing — last-minute pump vs a 24h hold

The 24h average is 288 five-minute samples. A spike lasting `k` samples raises the average by `(spike−1)·k/288`. To raise it 10%:

| Spike duration | Multiple needed |
|---|---|
| 5 min | 29.8× |
| 30 min | 5.8× |
| 1 h | 3.4× |
| 6 h | 1.4× |
| 24 h | 1.1× |

A last-minute 5-minute pump is useless. On a constant-product pool the buy to move price by `m` is `L·(√m−1)`: 29.8× on a $50k pool needs a $223k buy for five minutes, and it must be sold back after 18:00. A 24h hold at 1.1× is cheap if the attacker owns the LP and can reprice by moving liquidity; it is expensive for everyone else. So the rule correctly kills the "pump at 17:59" attack, but not a sustained, LP-owned price.

## 5. Identity, metadata and Token-2022

A candidate is any token whose name, ticker or description matches a strong keyword (weak keywords need an `allow` entry). A pre-existing token with mutable metadata can add `GTA 6` for one update (~0.000005 SOL base fee), then pass the other filters with its existing liquidity/traders/fees. Whether pump.fun mints keep a mutable metadata authority is **UNVERIFIED**; check one live mint. If metadata is immutable, the attacker must launch a new coin and pay the full cost.

`Metrics` has no field for token program, metadata authority or extensions. In the replay a Token-2022 mint is indistinguishable from a legacy SPL mint and passes:

```
T22 first_failed=None status=None logS=10.794623981827
```

Token-2022 officially supports `permanent_delegate`, `transfer_hook`, `transfer_fee`, `pausable` and `default_account_state` (SPL docs, 17 Nov 2026 UTC). Revoking mint/freeze does not remove them. A permanent delegate can transfer or burn a holder's tokens; a hook can block the basket buy; a fee taxes it; a frozen default state makes new ATAs unusable. Raydium rejects transfer hooks and Meteora DBC revokes one at graduation, but a custom pool or another venue may not; the G2 adapter must record the owner program and extensions.

## 6. Prize basket and emergency removal

The index JSON is public and lists members and weights. Each prize part buys with a 3% slippage cap; a searcher can buy ahead of the basket buy and sell into it. If the prize is `D` and the member weight is 10%, the part is `0.1D` and the maximum gross capture is `0.003D`: 0.3 SOL per draw at `D=100 SOL`, 3 SOL at `D=1000 SOL`. The cap bounds the loss but does not remove the profit, and a thin pool makes the 3% easier to hit.

Emergency removal triggers on a ≥50% liquidity drop in 1h. On a constant-product pool, halving the quote reserve requires selling an amount equal to the current token reserve and drops the price ~75%. A large holder can do that as an exit; it removes a competitor, and with equal weights the remaining members go from 1/10 to 1/9 (+11%) with no replacement until the next rebalance. The 15-minute job in #163 would act on a single print.

## 7. Operational and data-integrity findings

- **`self_mint: null`.** With it unset, a GTA-keyword index coin is eligible; with it set, the same candidate is excluded as `self`. Replay:
  ```
  status of SYBIL with self_mint=null: None
  status of SYBIL with self_mint=SYBIL: self
  ```
- **F4 skipped.** `dry_run.skip_filters: ["F4"]` lets a coin with `total_fees_sol=0` pass when the other score inputs exist (the replay sets `window_fees_sol=1`), and it becomes a member with `dry_run: true`. That is correct dry-run behaviour, but #163 publishes from a cron; an operator can put the dry-run params on the official path.
- **Multi-pair.** DexScreener exposes pair-level `marketCap`, `fdv`, `liquidity.usd` and `volume`; it does not document token-level aggregation. If the adapter sums pairs, an attacker can add a fake pair; if it takes the first/max, an attacker can choose the pair that flatters MC or volume. Pin "deepest SOL/USDC pair from an allowlisted DEX" and record the pair address.
- **Coverage DoS.** A public RPC/API can be exhausted to drop samples; missing data is fail-safe (excluded), so the result can be an empty index rather than a wrong one. Use multiple providers, retries and an alert; an official run must abort, not publish a partial file.
- **Dust prizes.** With 10 equal members, a 1-lamport prize gives rank 1 all 1 lamport; 9,999 gives rank 1 1,008 and the others 999. This is only material for dust-sized prizes; the split function is correct for normal sizes. Recorded as informational, no issue.

## 8. Cost model assumptions

| Input | Value | Source |
|---|---|---|
| SOL/USD | 74.89 | CoinGecko simple price, 17 Nov 2026 UTC |
| Token-account rent (165 B) | 0.00148844 SOL (1,488,440 lamports) | `getMinimumBalanceForRentExemption(165)`, mainnet + devnet, 17 Nov 2026 UTC |
| Base fee | 0.000005 SOL/signature | Solana docs; verified on tx `2fpoWQS5gxbTWL4fQHMZEXScH7ZfS2aEXyNpdvyJgbfBdUAqBsDuXrqQnM2FNsbq8dbfhExzktB9FqkggN8yXorg` (fee 5,036, 1 signature) |
| F4 floor | 10 SOL = $749 | `index/params.json` |
| Swap/protocol fee | 1% pump curve; 0.02–0.25% own DEX pool | Assumption; verify the venue before using these numbers |
| Token creation | 0–0.02 SOL | Assumption/upper bound; pump.fun docs were not reachable 17 Nov 2026 UTC — **UNVERIFIED** |

Costs exclude capital that is returned (liquidity, ATA rent) and exclude the attacker's market risk. A 3% slippage cap on a prize part is a limit on the victim, not on the attacker.

## 9. Replay output (actual command)

Metrics used (synthetic; all other fields pass: `coverage=1`, `age=48h`, `bundle=0%`, `dev=2%`, `creator_launches_7d=2`, authorities revoked):

| Ticker | MC USD | Liquidity USD | Fees SOL | Traders | Volume USD | Top10 |
|---|---|---|---|---|---|---|
| LEGIT | 2,000,000 | 150,000 | 12 | 250 | 300,000 | 20% |
| SYBIL | 2,000,000 | 150,000 | 12 | 250 | 100,000 | 20% |
| FLOAT | 50,000,000 | 50,000 | 10 | 200 | 2,500,000 | 20% |
| REBRAND | 8,000,000 | 400,000 | 12 | 250 | 800,000 | 20% |
| T22 | 5,000,000 | 150,000 | 12 | 250 | 300,000 | 20% |

`uv run python reports/index_redteam_replay.py`, `main` at `6129c84` (#157–#160, #165), 17 Nov 2026 UTC. The script is committed in this PR under `reports/`; it uses only the pure `index/` code and synthetic metrics. The block below is an abridged excerpt (ranks 1–5, no filler rows, no dust section); run the script for the full output.

```
== filter/score checks ==
LEGIT    first_failed=None   status=None       logS=10.428107689077
SYBIL    first_failed=None   status=None       logS=10.428107689077
FLOAT    first_failed=None   status=None       logS=11.327295665934
REBRAND  first_failed=None   status=None       logS=11.276874209429
T22      first_failed=None   status=None       logS=10.794623981827

== rebalance with ten candidates (self_mint is null in params.json) ==
rank  1 FLOAT    logS=11.327296 bps= 1000 mc=50000000 liq=50000
rank  2 REBRAND  logS=11.276874 bps= 1000 mc=8000000  liq=400000
rank  3 T22      logS=10.794624 bps= 1000 mc=5000000  liq=150000
rank  4 LEGIT    logS=10.428108 bps= 1000 mc=2000000  liq=150000
rank  5 SYBIL    logS=10.428108 bps= 1000 mc=2000000  liq=150000
...
dry_run: False skipped: []

== self_mint guard ==
params.self_mint = None
status of SYBIL with self_mint=null: None
status of SYBIL with self_mint=SYBIL: self

== dry_run skipped F4 (no fee source) ==
F4 checked: F4
F4 skipped: None
dry_run: True members: ['NOFEE']

== F3 boundary ==
top10= 12.999999 -> F3
top10= 13.000000 -> None
top10= 27.000000 -> None
top10= 27.000001 -> F3

== F10 boundary / turnover ==
volume=     99999 turnover=0.050000 -> F10
volume=    100000 turnover=0.050000 -> None
volume=   6000000 turnover=3.000000 -> None
volume=   6000001 turnover=3.000001 -> F10
```

## 10. Proposed fixes (one issue each)

| Fix | Issue | What it changes |
|---|---|---|
| P0 official-run guards (`self_mint`, F4, no skipped filters) | #166 | config + `--official` code guard |
| F11 MC/liquidity cap + free float + pair selection | #167 | new filter/param, score input |
| F4 fee floor scales with MC | #168 | kiwi's F4 parameter |
| F1/F3/F5/F6/F7 seasoning + cluster-aware checks | #169 | launch/holder rules |
| F9/F10 trader and volume quality | #170 | sybil/wash resistance |
| F8 metadata authority + Token-2022 allowlist | #171 | asset integrity |
| Prize execution + emergency debounce | #172 | operational hardening |

## 11. Before the 19 Nov official rebalance

1. **P0, do now:** set `self_mint` and enforce #166. If F4 has no source, keep the official index off (as #163 already says) rather than publishing a `dry_run` file.
2. **P1 if the rules can still change:** #167 (low-float), #169 (seasoning/clusters), #170 (F9/F10), #171 (metadata/Token-2022). These are the attacks that cost under 20 SOL.
3. **P1, kiwi's number:** #168. A flat 10 SOL is 0.0015% of a $50M coin; the floor should scale or the index is a pay-to-enter leaderboard at the high end.
4. **P2:** #172. Do not run a public prize buy as a single market order at a known slot.
5. Keep the "someone can pay to qualify" caveat in `INDEX_RULES.md` §9 known limits, and add these measured costs to it once the rules are updated.

## 12. Limitations

- The rules and code are merged on `main` at `6129c84` (#157–#160, #165). The replay pins that commit; if they change, re-run it.
- G2 (#161) is unmerged, so there is no live recorded index data; the replay is synthetic. The cost model uses live constants, not live attack transactions. The replay is reproducible from `reports/index_redteam_replay.py`.
- Pump.fun creation fee, metadata mutability and Token-2022 venue policy were not confirmed on 17 Nov 2026 UTC; those rows are marked **UNVERIFIED**. The pump.fun docs pages returned 403/transport errors from this session.
- No wallet, token creation, swap or mainnet write was used. All chain reads were `getMinimumBalanceForRentExemption`, `getSignaturesForAddress` and `getTransaction` against the public RPC.

## Sources (accessed 17 Nov 2026 UTC)

- `INDEX_RULES.md` v0.1 (#157), `index/params.json`, `index/filters.py`, `index/select.py` (#158–#160).
- `reports/research_index_data_2026-11.md` (G1): F4 source gap, DexScreener/Birdeye/Solana Tracker fields.
- DexScreener API reference: https://docs.dexscreener.com/api/reference.md (pair-level fields; FDV definition).
- Token-2022 extension list: https://spl.solana.com/token-2022/extensions.
- `reports/research_token2022_claims_2026-11.md`: Raydium/Meteora Token-2022 policies.
- Mainnet RPC: `getMinimumBalanceForRentExemption(165)` = 1,488,440 lamports; tx `2fpoWQ…8yXorg` fee 5,036 / 1 signature.
- CoinGecko simple price: SOL $74.89.

— Grok (from #162 red team)

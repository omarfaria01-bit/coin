# ENGINE_DESIGN.md — module interfaces (v0.2)

Source of truth for the math: `COIN_MATH.md`. This file fixes **interfaces, types and
determinism rules** so modules can be written in parallel. Signatures live in the stub files
under `engine/`; this document explains them. Changing a public signature needs a DECISIONS.md
entry.

## 1. Rules for every engine module

1. **Pure.** No network, no file I/O, no `time.time()`/`datetime.now()`, no global state.
   Inputs in, outputs out. Adapters (`adapters/`) do all I/O.
2. **Deterministic.** Same inputs → byte-identical outputs on any machine.
   - Iterate dicts/sets only after sorting by key (wallet/cluster ids sort as strings).
   - Events are processed in `(slot, sig, ix)` order.
   - Randomness only from an explicit `bytes` argument (VRF output or test seed).
   - Arithmetic: float64 for scores/shares/prices, **int** for every amount that is paid,
     transferred or stored (token base units, lamports). Convert float → int only with
     `math.floor` (payouts) or `math.ceil` (locked amounts), never `round()`.
3. **Conservation.** Every function that splits an int amount returns the remainder
   explicitly, so callers can assert `Σ parts + remainder == input`.
4. **Typed params.** Functions take the relevant sub-model of `engine.params.CoinParams`,
   never raw dicts.

## 2. Types (`engine/types.py`)

| Type | Meaning |
|---|---|
| `WalletId`, `ClusterId` | base58 strings. A cluster's id is its lexicographically smallest wallet. |
| `TokenEvent` | one token movement: `BUY` (pool→wallet), `SELL` (wallet→pool), `TRANSFER` (wallet→wallet), with `lamports` for buys/sells (fees included) and the tx `fee_payer`. |
| `SolTransfer` | native SOL transfer between two wallets. |
| `FirstFunding` | first SOL inflow ever received by a wallet, plus the wallet's first activity time. |
| `Lot` | `(amount, cost_lamports_per_token, t_acquired, source)`; `source` is `POOL_BUY` or `TRANSFER_IN`. |
| `PricePoint` | `(ts, price)` with price in SOL per whole token. |

Aggregator swaps (Jupiter etc.) that route through the pool are normalized to `BUY`/`SELL` by
the adapter; the engine never sees program ids.

## 3. Epoch pipeline (who calls what)

```
adapters.solana_read  ──> events, sol_transfers, fundings, prices
engine.ledger.build_lots            -> lots per wallet (LIFO)                 §1
engine.sybil.build_evidence/cluster -> wallet -> cluster                      §7
engine.twab.twab (per wallet, summed per cluster)                             §2
eligibility filter (B̄·TWAP ≥ min USD, held ≥ 1h, not forfeited)              §2, §11
engine.scoring.*                    -> s_c = B̄·H·F·U                         §3–6
engine.rewards.epoch_budget         -> R_e                                    §8
engine.rewards.capped_shares        -> π_c (≤ CAP; Σ < 1 if N < 1/CAP)        §6
engine.rewards.allocate             -> cluster payouts + rollover             §6
engine.rewards.split_to_wallets     -> wallet payouts + dust (∝ B̄_w·H_w)      §6
engine.merkle                       -> claims.json + root (or push list)      §13
```
Weekly: `engine.draws.draw_winners` + `split_prizes` on the draw pot (§9).
Hourly: `engine.fees.route` (§10). Every minute in paper/devnet: `engine.treasury_bot.decide` (§12).

## 4. `engine/sybil.py` (owner: Grok)

### 4.1 `build_evidence(holders, events, sol_transfers, fundings, balances_at_epoch_end, hubs, p) -> list[Evidence]`

Only pairs where **both** wallets are in `holders` produce evidence. Wallets in `hubs` never
produce or receive evidence. Each `Evidence` has `a < b` (string order). Output sorted by
`(a, b, kind, ref)`.

| Kind | Rule | Weight (`p.weights`) | `ref` |
|---|---|---|---|
| `SAME_FEE_PAYER` | link every pair of holders that appear (as `src` or `dst`) in events paid by the same non-hub `fee_payer`. A holder paying its own fees links nobody unless it also paid fees for another holder's event. | 1.0 | first sig |
| `DIRECT_TRANSFER` | a `TokenEvent` of kind `TRANSFER` or a `SolTransfer` between two holders. | 1.0 | sig |
| `SAME_FIRST_FUNDER` | two holders whose `FirstFunding.funder` is the same non-hub wallet, and each funding happened within `funder_window_hours` before that holder's first `BUY`. | 1.0 | funder id |
| `CO_BUY` | `BUY` events of a and b with `|slot_a − slot_b| ≤ co_buy_slot_tolerance` and sizes within `co_buy_size_tolerance` (relative to the larger), on **≥ `co_buy_min_occurrences` distinct slots** for the pair. | 0.7 | first sig |
| `IDENTICAL_BALANCES` | a group of ≥ `identical_balance_min_wallets` holders whose epoch-end balances are all within `identical_balance_tolerance` (relative) of each other and whose `created_ts` all fall within `identical_balance_created_within_hours`; link every pair in the group. | 0.6 | `"group:<smallest id>"` |

Emit at most **one** evidence per `(a, b, kind)` (keep the first by ref order).

Complexity guard: the pairwise kinds must not be O(n²) over all holders. Group first (by fee
payer, by funder, by slot window, by balance bucket), then link inside groups.

### 4.2 `cluster(holders, evidence, p) -> ClusterResult`

1. Union-find over all evidence with `weight ≥ p.strong_edge`.
2. For each remaining pair `(a, b)` in different components, sum the weights of all its
   evidence (one per kind); if the sum `≥ p.merge_threshold`, union them. Process pairs in
   sorted order. (With default weights this step never fires; keep it for tuned weights.)
3. `cluster_of[w]` = smallest wallet id in w's component. Every holder appears, singletons too.
4. `confidence[c]` = 1.0 for singletons; otherwise the **minimum**, over the unions that built
   the cluster, of `min(1.0, evidence sum for that union's pair)`.
5. `review` = clusters with `len(members) ≥ p.review_cluster_size`, sorted.

### 4.3 Required tests

- Hubs never create edges; pairs with a non-holder never create edges.
- Each evidence rule: one positive and one negative example at its threshold edges
  (e.g. co-buys on exactly 2 vs 3 slots; sizes at 10% vs 10.1%).
- 50 wallets with the same first funder → one cluster (COIN_MATH §14 row 1).
- Output is identical when the input lists are shuffled (hypothesis).
- 10k holders with sparse evidence clusters in < 5 s on a laptop.

## 5. `engine/draws.py` (owner: Grok)

- `uniform_from(randomness, cluster_id)`: `h = sha256(randomness + cluster_id.encode("utf-8"))`,
  `n = int.from_bytes(h[:8], "big")`, return `(n + 0.5) / 2**64` (strictly inside (0, 1)).
- `draw_winners(scores, randomness, k)`: entries with `score ≤ 0` are dropped.
  `t_c = sqrt(score)`; key `= ln(u_c) / t_c` (log form of `u^(1/t)`, avoids underflow).
  Return the top `min(k, N)` ids by key descending; ties broken by id ascending.
- `split_prizes(pot, winners, prize_split)`: winner at rank i gets `floor(pot · split[i])`.
  If fewer winners than ranks, unused shares stay in the pot. Returns `(prizes, remainder)` with
  `Σ prizes + remainder == pot`.

Required tests: determinism (same randomness → same winners, different randomness → different
with high probability); no duplicates; `k > N`; conservation; a chi-square check over many seeds
that first-pick frequency ∝ sqrt(score) (tolerance documented in the test).

## 6. Other modules (owner: Claude)

`ledger`, `twab`, `scoring`, `rewards`, `vesting`, `fees`, `treasury_bot`: signatures and
docstrings in the stubs are the contract. `merkle`: leaf format waits for the distributor
decision after the P1 research issue.

## 7. Property tests that must hold (CI)

- Σ payouts + rollover + dust == R_e exactly.
- Every share ≤ CAP for any N, including N < 1/CAP.
- Moving tokens between wallets of the same cluster never changes the cluster's payout.
- With clustering disabled and the cap not binding, splitting a wallet never increases reward.
- Vesting: locked amount never increases over time.
- Draws and claims: same inputs → byte-identical outputs.

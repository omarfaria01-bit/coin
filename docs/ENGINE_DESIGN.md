# ENGINE_DESIGN.md — module interfaces (v0.3)

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

## 6. Other modules (owner: Grok since D11, Claude reviews)

`ledger`, `twab`, `scoring`, `rewards`, `vesting`, `fees`, `treasury_bot`: signatures and
docstrings in the stubs are the contract; exact edge-case rules are in the issues
(#13 ledger/twab, #14 scoring, #15 rewards, #16 fees/vesting). `merkle`: jup-ag/distributor leaf
(D7), golden vectors from upstream Rust (#17). Price unit everywhere: lamports per token base
unit (D13).

## 7. Property tests that must hold (CI)

- Σ payouts + rollover + dust == R_e exactly.
- Every share ≤ CAP for any N, including N < 1/CAP.
- Moving tokens between wallets of the same cluster never changes the cluster's payout.
- With clustering disabled and the cap not binding, splitting a wallet never increases reward.
- Vesting: locked amount never increases over time.
- Draws and claims: same inputs → byte-identical outputs.

## 8. `engine/epoch.py` — epoch orchestrator (pure)

```python
@dataclass(frozen=True, slots=True)
class VestingEntry:          # one vested wallet (dev buy / early buy), soft mode
    wallet: WalletId; vested_amount: int; p_entry: float; t0: int   # p_entry in D13 units

@dataclass(frozen=True, slots=True)
class EpochState:            # carried between epochs; epoch 0 = all empty, pot 0
    epoch: int
    pot: int                                   # holder pot, lamports-equivalent token units*
    carry: Mapping[WalletId, int]              # push amounts below min_transfer, carried forward
    forfeit_until: Mapping[ClusterId, int]     # unix ts
    unlocked: Mapping[WalletId, float]         # monotone vesting state per vested wallet
    vesting: tuple[VestingEntry, ...]

@dataclass(frozen=True, slots=True)
class EpochInputs:
    t0: int; t1: int                            # [t0, t1), t1 − t0 == epoch.hours·3600
    slot_range: tuple[int, int]
    events: tuple[TokenEvent, ...]              # ALL events from launch to t1 (ledger history)
    sol_transfers: tuple[SolTransfer, ...]; fundings: tuple[FirstFunding, ...]
    prices: tuple[PricePoint, ...]              # 1-min series, SOL per whole token
    decimals: int; sol_usd: float
    pot_inflow: int                             # routed to holder pot during the epoch
    excluded: frozenset[WalletId]; hubs: frozenset[WalletId]

def run_epoch(inp: EpochInputs, params: CoinParams, prev: EpochState) -> tuple[EpochResult, EpochState]
```
\* The pot unit is whatever the payout asset is (lamports if paid in SOL). The engine treats it as an
opaque int.

Steps (all deterministic, every int split checked for conservation):
1. `twap(a, b)` helper over `prices`, converted to D13 units. A time-weighted mean of the 1-min
   series on `[a, b)`; it raises if the window has no price.
2. `lots = build_lots(events ≤ t1, excluded, lambda ts: twap(ts − 3600, ts))`.
3. Holders = wallets with lots at t1 or a non-zero balance inside `[t0, t1)`. Clusters via
   `build_evidence` + `cluster` (balances at t1).
4. Per-wallet balance changes from events → `twab` per wallet; `B̄_c = Σ_w B̄_w`.
5. Eligibility (§2): `B̄_c · twap(t0,t1) / 1e9 · sol_usd ≥ min_eligible_usd` (base units ×
   lamports per base unit = lamports), earliest lot `t_acquired` of the cluster `≤ t1 − min_hold`,
   and `forfeit_until.get(c, 0) ≤ t1`.
6. `H_c` = amount-weighted hold over all the cluster's lots at t1. `F_c` from BUY/SELL volume of
   the cluster in `[t1 − window, t1)` (transfers don't count). `U_c` with `twap(t1 − 6h, t1)`.
7. Soft vesting (D10): for each `VestingEntry`, each outflow event (SELL or TRANSFER out) from
   that wallet in `[t0, t1)`: update `unlocked` with `twap(ts − unlock_twap_h, ts)`, compute
   `locked`, and if `breaches_soft_lock` → `forfeit_until[cluster] = ts + forfeit_days`. Forfeited
   clusters this epoch score 0.
8. `pot = prev.pot + pot_inflow`. `R = epoch_budget(pot, …)`. If `!rewards.enabled` or
   `R < min_epoch_payout` → no payouts, everything rolls over.
9. `capped_shares` → `allocate(R)` → per cluster `split_to_wallets(weights = B̄_w·H_w)`.
   `pot_next = pot − Σ paid`. Rollover and dust stay in the pot.
10. Rail (§13): `N_eligible < push_max_eligible` → push list. `amount + carry[w] ≥ min_transfer` is
    paid, otherwise it is carried (carried amounts are already out of the pot). Otherwise
    `merkle.claims_document(payouts, version = epoch)`.
11. `EpochResult`: per-wallet payouts, per-cluster score rows (B̄, H, F, U, s, π), rollover, dust,
    rail + claims doc/push list, review clusters, `inputs_hash` = sha256 of a canonical JSON of
    `(slot_range, params.model_dump(), counts + sha256 of the sorted events)`.

Conservation, asserted inside `run_epoch`:
`prev.pot + pot_inflow + Σ prev.carry == pot_next + Σ transferred_or_claimable_now + Σ next.carry`.

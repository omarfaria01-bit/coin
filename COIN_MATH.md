# COIN_MATH.md — Algorithms spec (v0.3.3, 14 Nov 2026) — **mechanisms frozen, parameters to be confirmed by simulation**

Coin (working name): **Linkgox**. Owner: kiwi + Omega. Manager: Claude Code. Chain: **Solana**. Launchpad: **unknown until release** → everything pad-specific lives in `config/pad.json` (section 15).

All parameters below are **defaults**. They live in `config/coin.json` and are tuned with the simulator (section 14). They are not hard-coded.

> **Freeze policy.** No new mechanism is added after this version. A formula changes only when an acceptance test in section 14 fails, and the change is recorded in DECISIONS.md with the failing evidence.
> **Parameters are not frozen.** The holding curve, the start time, the eligibility shares and the draw period below are defaults. The simulator compares them with the listed variants before launch.

> **v0.3.3 changes (faster rewards, small holders, fifth review):**
> - **Fast start.** Tokens start earning after 2 hours instead of 48. The holding curve is steeper in the first 3 days and keeps growing up to 90 days (max 2.8×).
> - **Eligibility no longer uses any price.** It is a minimum share of supply held on average. The base reward path (sections 1–4, 6–8) is now price-free, so it works from the first minute on any pool, and nobody's trades can affect it.
> - **Small balances are never lost.** Every wallet has a running reward balance that is paid out when it passes a small threshold.
> - A shared fee payer is informational only and can never contribute to a merge.
> - The draw payout has an explicit formula, and the draw period is a parameter.
> - Same-second trades, payout accounting units and the no-grief wording are corrected.
> - New holding and retention tests in section 14, and a holder view in section 17.

Design principles:
1. **Linear pro-rata for money, concave only for luck.** The score is a plain sum over lots, so splitting wallets can't increase it. Clustering matters only for the cap and the draws.
2. **Time-weighted everything.** Any snapshot or spot value can be gamed in one block.
3. **Cluster, then score.** Clusters are computed first; the ledger and scores are built on them.
4. **Monotone safety.** A lock can only decrease, a tax can only decrease, caps never loosen automatically.
5. **Reproducible by anyone.** Every payout is a deterministic function of (finalized on-chain data in a slot range, params file, code commit).
6. **A cluster is a rule, not an accusation.** Clustering is probabilistic. It is never presented as proof of common ownership.
7. **No grief.** Nothing a third party does *to your wallet* without your signature (sending you tokens or SOL, paying your fees, copying your trades) can lower your score or your eligibility. You are grouped with another wallet only through something you signed: a shared transaction, sending something back, or buying with money that mostly came from that wallet.
   - **Market risk is not covered.** Other people's trades move the price. That can change the underwater boost and the price unlock, which depend on price. It cannot change base rewards, which don't.

---

## 0. Conventions (apply to every section)

**Unit of account.** Every price, cost and threshold is in the **quote asset `Q`** of the coin's pool (SOL by default; set in `pad.json`). USD is for display only and never enters a formula. There is no external price oracle.

**Numbers.**
- Token amounts and Q amounts are integers in base units.
- The **payout path** (sections 1–9, 11, 13) uses only integers and exact rationals (`fractions.Fraction` in the reference implementation). Binary floats, `ln`, `exp` and non-integer `sqrt` are forbidden there.
- Rounding happens only at the final payout step (section 6).
- The treasury bot (section 12) may use floats, because it never affects claims.

**One clock: block time in whole seconds.**
- Only **finalized** slots are used. Events are ordered by (slot, transaction index, instruction index).
- A slot's time is its block time in integer Unix seconds. If it is missing, or lower than the previous slot's, the previous slot's value is used.
- Every quantity that changes over time (a balance, the pool price, the pool depth) is a **step function of the second**: its value in second `t` is the state after all events with block time ≤ `t`.
- A state that begins and ends inside the same second has zero duration and zero weight. Skipped slots need no rule, because slots are not used as a clock.
- Epoch `e` covers the seconds `[t_e, t_e + 86,400)`, starting 00:00 UTC. `E = 86,400`.
- An epoch is finalized only when **two independent RPC sources** return the same event-log hash for its slot range. Until then the epoch is delayed, never skipped or estimated.

**Price (from pool reserves, not from swaps).**
- `p(t)` = the price quoted by the pool in second `t`, implied by its reserves (or by the curve's virtual reserves before graduation). It is an exact rational and always > 0. The adapter in `pad.json → price_source` reads it.
- With no swaps the price doesn't move, because the pool is still quoting it.
- States that exist only inside one second get no time weight. The price of a second is the one implied by the reserves at the end of that second, including whatever fees the trades left in the pool.

**Trusted second (executable depth).** Second `t` is trusted if a simulated swap of `D_TRUST` (default 2 SOL) in **either** direction would move the pool price by less than 5%.
- The adapter computes this from the pool's own integer math, so it works for constant-product and concentrated-liquidity pools alike.
- For a constant-product pool this means a Q reserve above ~81 SOL, so most of a bonding curve's early life is untrusted.
- **No untrusted price is ever used.** Only the underwater boost (section 5), the price unlock (section 11) and the bot (section 12) read prices, and each pauses on untrusted seconds. Base rewards and eligibility read no price at all.

**Time-weighted prices** (two kinds, each robust in the direction an attacker wants to push):
- `P̄_e` = **arithmetic** mean of `p(t)` over the epoch's 86,400 seconds. Used where an attacker wants a *lower* price (underwater boost, section 5).
- `P̃_h(t)` = **harmonic** mean of `p` over the 86,400 seconds before `t`: `86400 / Σ (1/p)`. Used where an attacker wants a *higher* price (vesting, section 11).

**What a time-weighted price does and doesn't protect.** It bounds the effect of a price the pool holds *briefly*. A price the pool holds for the whole window is, for this spec, the real price. Holding a pool at a wrong price is costly, because anyone can trade against it; section 14 measures that cost.

**Serialization.** Output files use canonical JSON: UTF-8, keys sorted, no insignificant whitespace, integers as decimal strings, arrays sorted by a documented key (wallet address in byte order). Hashes are SHA-256 over those bytes.

**Final means final.** A published epoch is never recomputed, clawed back or topped up. Later changes (cluster merges, overrides, params) only affect future epochs.

---

## 1. Ledger (per wallet → per cluster)

**Order of computation every epoch:** (1) build the cluster map (section 7), (2) rebuild the ledger from the immutable event log under that map, (3) score.

Every wallet holds **lots**: `(amount, cost_Q, t_acquired, source, origin, tainted_until)`.
- `origin` is the lot's original acquisition (buy tx, price, time). It is never overwritten.
- **Pool buy** → `cost_Q` = executed price (Q in / tokens out, fees included), `source = pool`.
- **Transfer between wallets of the same cluster** → internal move. The lot keeps everything.
- **Transfer from another cluster** → `t_acquired` = transfer time (age resets), `source = transfer`, `cost_Q = null`. `tainted_until` travels with the lot (section 11).
- **Sell or transfer out** → lots are removed **LIFO** (newest first) from the wallet that sends. Selling part of a position keeps the oldest lots.
- **Excluded accounts:** pool/curve vaults, burn address, treasury, bot, fee router, dev wallets (they follow their own rules), listed hubs.

**No-grief check.** Tokens you receive become your newest lots. They never change the age, cost or eligibility of the lots you already had, and they are the first to leave when you sell.

**Retroactive merges.** If two clusters merge at epoch `n`, the ledger for epoch `n` is rebuilt from genesis with the new map, so old transfers between them count as internal (age and cost restored from `origin`). Epochs before `n` stay as published.

## 2. Balance over time and eligibility

`B_c(t)` = the cluster's balance in second `t` (step function, section 0).

```
B̄_c = (1/E) · Σ_{t in epoch} B_c(t)          (time-weighted average balance, exact)
```

**Eligibility (price-free):**
```
B̄_c  ≥  MIN_ELIGIBLE_SHARE · total supply        (default 1/1,000,000 of supply = 1,000 tokens of 1B)
```
- It uses no price, so it can't be affected by a thin pool, by a manipulated price, or by other people selling.
- It is an average over the epoch, so buying seconds before the epoch ends doesn't qualify anyone.
- What it means in money: at a $1M market cap the minimum is about $1. A €100 position stays eligible at any market cap below roughly $100M.
- Its only purpose is to skip dust. Small holders are protected by section 13 (balances carry forward), not by this number.

## 3. Hold multiplier (age): fast start, long-term loyalty

`h(a)` is **0 below `T_START` = 2 hours**, then **piecewise linear** between published knots, flat after 90 days:

| age | < 2h | 2h | 6h | 12h | 24h | 48h | 72h | 7d | 14d | 30d | 60d | 90d+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| h | 0 | 1.00 | 1.15 | 1.30 | 1.50 | 1.75 | 1.90 | 2.10 | 2.30 | 2.50 | 2.70 | 2.80 |

- After 2 hours a token earns. After one day it counts 1.5×, after three days 1.9×, and it keeps growing for three months.
- The multiplier acts on the **score** (your share of the pot). It is not a yield: 1.5× does not mean +50% on your money.
- Each lot has its own age. Buying more never resets the age of what you already hold.

For each lot, its age-weighted time in the epoch is split at 48h, the age where the underwater boost can start (section 5):

```
E1_lot = (1/E) · Σ_{t in epoch, T_START ≤ age < 48h, t ≥ tainted_until} amount · h(a(t))
E2_lot = (1/E) · Σ_{t in epoch, age ≥ 48h,           t ≥ tainted_until} amount · h(a(t))
```

Because `h` is linear between knots, the sum over each segment has a closed form: exact rationals, no approximation.

**Simulator variants to compare:** the previous curve (start at 48h, max 2.0× at 30d), and a middle one (start at 12h, 1.05× at 24h, 1.5× at 7d, 2.0× at 30d, 2.35× at 90d).

## 4. The start rule (replaces the flipper discount)

**A token starts earning when it has been held for `T_START` (2 hours).** Lot-time below that scores zero, and nothing is paid back later for it.

What the rule and the curve do together:
- **Scalping earns nothing.** Under LIFO, a token bought and sold within 2 hours never counts.
- **Short holds earn little.** Someone who holds in 4-hour cycles averages 0.51× per hour held, about a quarter of a 7-day holder (2.1×). In 12-hour cycles it is 0.96×, under half.
- **Snapshot sniping is useless.** Everything is time-weighted, and the first 2 hours count zero.
- **No cluster-level factor.** A lot's score depends only on that lot, so a wrong cluster merge can't change it.
- **Splitting can't help.** `h` never falls as a lot ages, so keeping the oldest lots (what LIFO does) is the best a holder can do. No arrangement of the same trades across several wallets scores more than one wallet. (The one bounded exception is in section 5.)
- **A bag is never penalized for trading around it.**

What a short start time costs, stated plainly: with 48h a day trader earned nothing; with 2h he earns something for the hours he actually held. That is the price of paying small holders quickly.

**Simulator variants to compare:** `T_START` = 6h, 12h, 48h.

## 5. Underwater boost (per lot)

The goal is to keep holders who are in loss from capitulating, without making the boost profitable to farm.

For each lot with `source = pool`, on its lot-time with **age ≥ 48h** (both `cost_Q` and `P̄_e` are in Q per token):

```
d_lot = max(0, 1 − P̄_e / cost_Q)
u_lot = 1 + β · min(d_lot, D_max) / D_max    β = 1/2, D_max = 3/4  → max 1.5×
```
Lots with `source = transfer` have `u_lot = 1`. If more than 10% of the epoch's seconds are untrusted (section 0), `u_lot = 1` for everyone that epoch.

Anti-gaming:
- **Only pool buys count.** Transferred lots have no cost, so a fake high cost can't be injected.
- **48h age for the boost.** Rewards start at 2h, but the boost starts at 48h. Buying the top on purpose costs a real loss and earns no boost for 2 days.
- **Cap at 1.5×.**
- **Dump bound (holds for any price history).** If the pool is held at any lower price for τ seconds, then
  ```
  P̄_e  ≥  (E − τ) / E · A_rest
  ```
  where `A_rest` is the arithmetic mean of the other `E − τ` seconds. For τ = 1h the factor is 23/24.
  - So a 1h dump raises `u_lot` by at most **0.028 above the boost that the other 23 hours alone would give**.
  - It does not bound the change against "what the hour would have been": if that hour was a spike, removing the spike moves the mean a lot, but only back to the level the rest of the day supports.

Two known effects, stated publicly and measured in section 14:
- The boost rewards holding a losing position. It is a share of fees, never a reason to hold a dying coin. It is judged by **total ROI**, not by its size.
- With the boost on, a newer lot bought high can earn more than an older lot bought low, so choosing which lot to sell (possible only across separate wallets) can be worth up to the boost itself. The gain is bounded by 1.5×.

## 6. Score, share, whale cap, exact payout

```
s_c = Σ_lots ( E1_lot + u_lot · E2_lot )       (exact rational)
S   = Σ s_c over eligible clusters
```

- The score is a sum over lots. No factor is computed at cluster level.
- **Multiplier bounds (published):** a token younger than 2h counts 0; from 2h to 48h it counts 1.0× to 1.75×; after 48h, 1.75× to 2.8×, and up to 4.2× with the full underwater boost. Changing a parameter that moves these bounds needs a DECISIONS.md entry.
- **If `S = 0`** (nobody has an eligible token older than 2h): nothing is distributed, `R_e` stays in the pot, and no division is performed.

**Whale cap with bounded redistribution** (when `S > 0`). Parameters: `CAP = 1/20` (5%), uplift limit `G = 2`.

```
θ* = sup { θ ≥ 0 : Σ_c min(CAP, θ · s_c) ≤ 1 }        (θ* = ∞ if N · CAP ≤ 1)
θ  = min(θ*, G / S)
π_c = min(CAP, θ · s_c)
rollover_share = 1 − Σ_c π_c  ≥ 0                       (a fraction; that part of R_e stays in the pot)
```

- With many holders, θ = θ*: the excess of capped clusters is redistributed pro-rata to the others (standard water-filling) and rollover_share = 0.
- Since θ ≤ G/S, nobody's share can exceed **2× their proportional share**. With few holders the rest stays in the pot. The cap is never loosened.
- Examples with 10 eligible clusters:
  - 10 equal clusters: each gets 5%, 50% rolls over.
  - One cluster with 91% of the score and nine with 1% each: 5% + 9 × 2% = 23% paid, 77% rolls over.
- Exact algorithm for θ*: start with no cluster capped; repeatedly set θ = (1 − k·CAP) / Σ_{uncapped} s (k = number capped) and cap every cluster with θ·s_c > CAP, until stable.

**Exact payout (integers).** With `R_e` the epoch payout in Q base units:
1. `T = floor(R_e · Σ π_c)`.
2. Each cluster gets `floor(R_e · π_c)`.
3. The leftover units up to `T` go one each by largest remainder; ties broken by cluster id.
4. `Σ payouts == T`. Define `rollover_units = R_e − T` (Q base units); it stays in the pot.
5. Conservation check, all in Q base units: `Σ payouts + rollover_units == R_e`.

**Per-wallet split.** For wallet `w` in cluster `c`, `s_w` = the part of `s_c` from lots physically held in `w`. The wallet gets `floor(payout_c · s_w / s_c)`, leftovers by largest remainder, ties broken by wallet address.

## 7. Sybil clustering

Wallets are nodes (holders, and the wallets that fund them). Evidence between two wallets is either **strong** (merges on its own) or a **link signal** (merges only in combination).

| Tier | Evidence | Weight | What the grouped wallet signed |
|---|---|---|---|
| Strong | S1. Both wallets are **holders** and both signed the same transaction | merge | that transaction |
| Strong | S2. **Funded buy** (defined below) | merge | the buy |
| Strong | S3. Manual confirmation, logged in `cluster_overrides.json` | merge | reviewed |
| Link, **two-sided** | L1. Token transfers in **both directions** between the two | 0.6 | a transfer back |
| Link, **two-sided** | L2. SOL transfers in **both directions** between the two | 0.5 | a transfer back |
| Link | L3. One-way token transfers on ≥ 2 distinct days | 0.3 | nothing (sender alone) |
| Link | L4. Co-trades: same second ±1, size within 10%, ≥ 3 occurrences | 0.4 | nothing (a copier alone) |
| Link | L5. Identical balances (±0.1%) across ≥ 4 wallets created within 24h | 0.3 | nothing |
| Link | L6. Sale proceeds sent to the same non-hub destination within 24h | 0.5 | nothing (one side, at a cost) |

**S2, funded buy.** Wallet `W` is merged with wallet `X` (not a hub) if, at the time of any pool buy by `W`, both hold:
- `X` sent `W` at least **50% of all the SOL `W` has ever received** from other wallets, and
- that amount is at least **50% of everything `W` has spent on buys** so far.

All wallets funded this way by the same `X` end up in `X`'s cluster, whether or not `X` holds the token.
- A farm funded from one wallet is caught.
- An attacker who sends dust to a victim is not: to force a merge he would have to pay for more than half of everything the victim buys, and the victim would have to spend it.

**S2 uses totals, not a trace of each coin.** Tracking which SOL paid for which buy would need every movement of every wallet since its creation, and SOL is fungible anyway. The two 50% conditions give the guarantee that matters: forcing a merge costs at least half of what the victim spends. A wallet that already had its own money is not merged by a small top-up, because the sender fails at least one of the two conditions.

**A shared fee payer is informational only.** Two wallets whose fees are paid by the same third party (a trading app, a relayer, a gasless service) get **no** link weight from it. It can't satisfy the two-sided requirement and can't contribute to a merge. It is only reported in the review list. Nobody can get a holder grouped just by paying that holder's fees.

**Merge rule for a pair:** any strong evidence, **or** link signals summing to ≥ 1.0 **that include at least one two-sided signal (L1 or L2)**. Clusters are the connected components of merged pairs (union-find).

- Alice pays Bob once in the token: no two-sided signal, **no merge**.
- An attacker sends tokens and SOL to a victim and copies the victim's trades: every signal is one-sided, **no merge**.
- Two users of the same trading app that pays their fees: no evidence at all, **no merge**. The payer shows up in the review list.

**Hubs (`hubs.json`, public).**
- A hub is a wallet whose edges are ignored: CEX hot wallets, bridges, aggregator programs, relayers and gasless fee-payer services, the pool.
- The list is seeded from public labels and changed **only by a logged, reviewed entry**. There is no automatic hub rule: an automatic threshold would let a sybil farmer turn his own funding wallet into a "hub" and un-merge his farm.
- Being listed as a hub, or as a candidate, is not an accusation.

**Review list (`reports/review.csv`), no automatic effect:** any wallet with ≥ 25 distinct counterparties (hub candidate), any fee payer shared by ≥ 5 holders, any cluster with > 50 wallets, and any merge resting only on link signals.

**Monotonicity.** Evidence only accumulates, so merges only grow. The only exceptions are logged overrides (`hubs.json` additions, `cluster_overrides.json`). They apply from the next epoch, over the full history, and never touch published epochs.

**What a wrong merge can change (stated publicly, measured in section 14):**
- the 5% cap, which becomes shared
- the draw, which becomes one entry
- the age and cost of tokens the two wallets sent each other, which are restored

It cannot change the score of any token that never moved between the two wallets.

**Known residual risk (stated publicly):** wallets funded independently through separate CEX withdrawals, which never interact, cannot be linked. A whale can evade the cap this way, at the price of losing age and boost on any tokens it moves.

## 8. Reward pot

Inflows to the holder reward pot (all in Q):
- its share of creator fees (section 10)
- realized treasury-bot profit sweeps (section 12), if the bot is enabled
- realized staking yield, if `lst_share > 0`

**Payout rule: proportional draw-down** (not "pay what came in"):

```
R_e = α · Pot_e        α = 1/10 per day
```

- `Pot_e` = pot balance in Q at the epoch boundary, **before** the payout. Only realized Q counts.
- Payouts are always in Q, from liquid Q.
- If `R_e < MIN_EPOCH_PAYOUT`, the epoch is skipped. Nothing is lost; it stays in the pot.
- **Theoretical decay:** with no inflows and a payout every day, `Pot_{e+1} = 0.9 · Pot_e`, so after 7 days payouts are 0.9⁷ ≈ 47.8% of the starting level.
- **Actual decay** can be slower: skipped epochs, `S = 0` and whale-cap rollover all leave money in the pot.

**Liquid staking (optional, `lst_share` default 0 at launch):**
- At most `lst_share` (max 50%) of the pot may sit in a liquid staking token.
- It is valued at `min(market price, stake-pool redemption rate)`, so a depeg can only lower `Pot_e`, never inflate it.
- Yield counts only when realized (converted back to Q). It is never promised or projected.
- If the market price is > 1% below redemption, no conversions are made and payouts use liquid Q only.

## 9. Draws (luck component)

This is the part built for small holders: one entry per person, odds that grow with the square root of the score, and prizes large enough to matter to a small position.

A separate draw pot (section 10). A draw closes every `DRAW_PERIOD` = 7 epochs (`n` below).

**Snapshot.** At the end of the period's last epoch the eligible list is frozen and its hash is published. Anything that happens after the snapshot has no effect on this draw.

**Eligible cluster (price-free):**
- eligible for rewards (section 2) in **at least ⌈5n/7⌉ of the `n` epochs** (5 of 7)
- `B̄_c ≥ MIN_DRAW_SHARE · total supply` in the final epoch (default 1/100,000 of supply = 10,000 tokens of 1B)
- not in forfeit state (section 11)

These are time-weighted conditions. Dust sent to a wallet can't remove them, and a last-day entry can't meet them. There is **no separate prize for small wallets**: that would pay people to split.

**Weight (integer):** `w_c = isqrt( floor( Σ s_c over the n epochs ) )`.
- `s_c` is in token base units × multiplier, so `floor` already fixes the integer unit. `isqrt` is the exact integer square root.
- One entry per cluster. A cluster with 100× the score gets 10× the odds.
- Domain: clusters with weight 0 are dropped, and `1 ≤ W = Σ w_c < 2¹²⁸` (asserted). If no cluster is eligible, there is no draw and the pot carries over.

**Draw payout.**
```
D = δ · DrawPot_close            δ = 1 for the weekly draw   (DrawPot_close = draw pot balance in Q at the snapshot)
prizes: 1 × 40% of D,  3 × 10% of D,  6 × 5% of D            (10 winners, 100% of D)
```
- Each prize is `floor(D · share)` in Q base units. The few units lost to rounding stay in the draw pot.
- If there are fewer eligible clusters than prizes, the unassigned prizes stay in the draw pot for the next draw.
- A cluster's prize is split to its wallets as in section 6.

**Randomness.** A VRF output `ρ` (Switchboard on-demand randomness, or ORAO VRF) is requested **after** the snapshot hash is on-chain (commit → reveal). The stream of 256-bit integers is:

```
x_i = SHA-256( "COIN_SYSTEM_DRAW_V1" ‖ genesis_hash ‖ mint ‖ draw_index ‖ snapshot_hash ‖ ρ ‖ i )     i = 0, 1, 2, …
```

**Selection (sequential weighted sampling, no replacement, no modulo bias):**
1. Sort eligible clusters by cluster id. `W` = sum of remaining weights.
2. Take the next `x_i`. If `x_i ≥ floor(2²⁵⁶ / W) · W`, discard it and take the next one (rejection sampling).
3. `r = x_i mod W`. The winner is the first cluster whose cumulative weight exceeds `r`.
4. Remove the winner, update `W`, repeat for the next prize.

**Simulator variants to compare:** a daily draw (`n` = 1, δ = 1/3) and a 3-day draw (`n` = 3, δ = 1/2). A week is long in memecoin time, so a shorter draw may hold small holders better.

## 10. Fee routing (creator-fee share only; the pad keeps its own cut)

| Destination | Default |
|---|---|
| Dev wallets (kiwi + Omega) | 25% |
| Holder reward pot | 35% |
| Draw pot | 25% |
| Buyback & burn | 15% |

- A router script runs hourly. Buyback is sliced over time (small chunks, never one big buy).
- Burn = the token program's `Burn` instruction from the router's own token account. The supply decrease is checked on-chain after each burn and logged. P1 research must confirm the pad's token allows it.
- If draws are disabled (section 16), their 25% goes to the holder reward pot.
- Every movement is logged to `ledger/fees.csv` and is public.

## 11. Price-weighted vesting (early buys + dev buy)

Scope: the dev buy, plus pool buys in the first `T_EARLY` (default 15 min, or until MC ≥ `MC_EARLY`, whichever comes first). Computed **per lot**, in Q.

```
u_time  = clamp((t − t0) / T_v, 0, 1)                        T_v = 7 days
r       = P̃_h(t) / P_entry                                   24h harmonic mean / the lot's buy price
u_price = clamp((r − 1) / (M − 1), 0, 1)                     M = 5
unlocked(t) = max(unlocked(t−), u_time, u_price)             can only go up
locked_c = Σ_lots (1 − unlocked_lot) · amount_lot
```

- `unlocked` is evaluated at every minute boundary (`t` divisible by 60).
- `u_price` is evaluated only when `t ≥ t0 + 24h` **and** every second of the 24h window is trusted (section 0). Otherwise it is skipped for that minute; the time unlock continues.
- Plain reading: each +1× above the entry price unlocks 25%. At 5× everything is unlocked. After 7 days everything is unlocked anyway.
- If the price dumps, nothing extra unlocks.

**Pump bound (holds for any price history).** If the pool is held at a higher price for τ seconds, then
```
P̃_h  ≤  E / (E − τ) · H_rest
```
where `H_rest` is the harmonic mean of the other `E − τ` seconds. For τ = 1h the factor is 24/23 = 1.0435, whatever the size of the pump.
- So a pump can never unlock more than a price 4.35% above what the rest of the window supports.
- From a flat price this is an unlock change of at most `r · 0.0435 / 4` (1.1% at entry price, < 5% for r ≤ 4.5).

Implementation depends on the pad (`pad.json → vesting_mode`):

- **A. `native`** — the pad supports vesting or Token-2022 transfer hooks. Tokens are really locked on-chain: map these params to the pad's config, or use a hook that rejects any transfer leaving `balance < locked`.
- **B. `soft`** — no hooks. **This is not a lock. It is an economic penalty**, and public docs must say so.
  - Rule: a cluster's balance must stay ≥ `locked_c`.
  - Any **outflow** that breaks it (a sell, or a transfer to another cluster) puts the cluster in **forfeit**: score 0 for the current epoch and the next 30, and no draws for 30 days. The forfeited share stays in the pot.
  - Tokens that left while locked are **tainted**: the lots get `tainted_until = t + 30 days` and score 0 until then.
  - **Taint belongs to the lot and follows it** through any number of further transfers, to any wallet. It ends only at `tainted_until` or when the tokens are sold to the pool.
  - Receiving tainted tokens doesn't affect the receiver's other lots (principle 7).
  - Transfers inside the same cluster are internal, and the locked amount follows the cluster.
- **Dev tokens: always hard-locked**, whatever the pad, through an existing audited lock program (e.g. Streamflow or Jupiter Lock). Never a custom program.

## 12. Anticyclical treasury bot (phase 2, **off by default**)

Inventory-based mean reversion: buy dips, sell rips. **Never wash trading or fake volume.** The bot is enabled only if the backtest in section 14 passes and kiwi approves.

```
x_t = ln(price), per-minute series
μ_t = EMA(x, half-life 6h)
σ_t = max( sqrt(EWMA((x − μ)², half-life 24h)), σ_min )      σ_min = 0.10
z_t = (x_t − μ_t) / σ_t
target token share   f* = clamp(f0 − γ·z, f_min, f_max)      f0 = 0.5, γ = 0.15, f_min = 0.1, f_max = 0.9
trade only if |f − f*| > band (0.05)
size = min(needed, 2% of 1h pool volume, MAX_TRADE_Q)
```

**Hard risk limits:**
- **Capital at risk is fixed** at funding (`BOT_CAPITAL_Q`). It is never topped up automatically and never takes from the reward pot.
- `MAX_NET_BUY_Q`: cumulative buys minus sells can never exceed 30% of `BOT_CAPITAL_Q`.
- `MAX_BUY_Q_24H`: at most 10% of `BOT_CAPITAL_Q` bought per 24h.
- No trading in the first 24h after launch.

**Stops (buys halt; sells still allowed):**
- **Daily loss:** equity (Q + tokens at the pool price) down ≥ 5% of `BOT_CAPITAL_Q` in 24h → no buys for 24h.
- **Total drawdown:** equity down ≥ 25% of `BOT_CAPITAL_Q` from its peak → the bot stops completely until kiwi reviews it.
- **Falling knife:** price is −40% from the 72h high.
- **Liquidity:** the current second is untrusted (section 0), or pool depth is down ≥ 30% within 1h.
- **Data anomaly:** price jump > 50% in one minute, data older than 2 minutes, or two RPC sources disagreeing by > 1%.
- The `STOP` file exists.

**Profit sweep (realized only).**
- PnL is tracked with average-cost accounting. Only **realized** PnL (from completed sells) counts.
- Weekly: sweep 50% of (cumulative realized PnL − its previous high-water mark) to the reward pot, in Q, and only from Q the bot actually holds.
- Unrealized gains are never distributed.

**Execution:** slippage cap, Jito for MEV protection, modes `paper` → `devnet` → `live`. The bot wallet and these rules are public.

## 13. Payout rails: every wallet has a running balance

Each epoch writes `epochs/<n>/{inputs.json, clusters.json, scores.json, balances.json, claims.json, root.txt}` in canonical JSON. `inputs.json` holds the slot range, the event-log hash confirmed by two RPC sources, the params hash and the code commit.

**Running balance per wallet** (`balances.json`, in Q base units):
- `earned_total` — everything the wallet has earned so far
- `paid_total` — everything already sent or claimed
- `pending = earned_total − paid_total` — earned, not yet paid

**Small amounts are never lost.**
- `pending` is paid when it reaches `MIN_PAYOUT_Q` (default 0.001 SOL; it can change with network fees but never above the published maximum of 0.005 SOL).
- Below that it simply stays in `pending` and keeps growing. It never expires and is never taken back, even if the wallet stops being eligible.
- Draw prizes are added to `earned_total` and follow the same rule.

**Small holder count (< 500 eligible): push payouts.** A direct transfer of `pending` in Q (a native SOL transfer when Q is SOL) to every wallet above `MIN_PAYOUT_Q`. The holder pays nothing and does nothing.

**Larger holder count: claims.** Use an existing audited Merkle distributor (jup-ag/distributor or the Solana Merkle-airdrop template). Don't write a custom program. The leaf format is fixed by the audited program and is not modified. The program chosen in P1 must provide all of the following, verified and recorded in DECISIONS.md:
- **Context binding:** a claim is bound to the program id and to a distributor account that is unique per (mint, epoch), so a proof can't be reused for another epoch or token.
- **Replay protection:** a per-claimant claim-status account, so nothing can be claimed twice.
- **Unclaimed amounts:** after 30 days they are pulled back from that distributor and **re-credited to the same wallet's `pending`**, to be offered again. Only after 180 days with no claim at all do they return to the reward pot, and this is logged.
- **Deployed code = audited code:** the on-chain program hash matches a verifiable build of the audited commit.
- **Paying Q when Q is native SOL:** these distributors pay SPL tokens, so the distributor is funded in wrapped SOL and the claim transaction closes the wSOL account so the holder receives native SOL. This is an assumption until an end-to-end devnet test in P5 proves it (fund, claim, unwrap, double-claim rejected, pull-back). If the test fails, payouts stay push-based.

## 14. Simulator and acceptance criteria (all must pass before any mainnet use)

The simulator is a pure off-chain model (no blockchain, no UI) built on the reference engine. It runs Monte Carlo over seeds and over these **inputs**: number of holders, initial distribution, price path and volatility, pool depth, daily volume, buy/sell frequency, share of whales, wallets per owner, creator-fee level, and every parameter in `coin.json`. It includes arbitrage agents that trade against a mispriced pool.

**Outputs for every run:**
- reward distribution by percentile, and the Gini coefficient of rewards next to the Gini of balances
- reward concentration over 90 days (top-10% share of rewards per 30-day window)
- cost and profit of each attack
- reward pot evolution
- treasury bot PnL and drawdown
- **honest vs. informed gap:** reward per token of a simple holder vs. an agent that knows every formula and plays optimally
- **false-merge damage:** `|R_merged − R_correct| / R_correct` when two independent clusters are wrongly merged
- **sybil recall:** share of same-owner wallets correctly grouped, separately for self-funded farms and CEX-funded farms
- **eligibility manipulation:** any way to change another cluster's eligibility (target: none exists, since eligibility is price-free)
- **reward rate by holding time:** reward per token-hour for holds of 1h, 4h, 12h, 1d, 3d, 7d, 30d, 60d, 90d
- **what a small holder gets:** for a €100 position, reward share, days to first payout, and draw odds per period
- **retention comparison** between the default curve and the variants (sections 3, 4, 9), over 30, 60 and 90 days: share of holders still in, average balance held, selling right after the 30/60/90-day marks, reward concentration, gap between loyal holders and reward farmers. Holder behaviour here comes from modelled agents, so these are comparisons between designs, not forecasts.
- **forced-merge cost:** Q an attacker must give a victim to trigger S2
- **reward stability:** change in each honest holder's share when one parameter moves by ±10%
- **price manipulation cost:** Q lost by an attacker to move `P̄_e` or `P̃_h` enough to change a payout or an unlock

**Acceptance table:**

| Scenario | Pass condition |
|---|---|
| Whale splits into 50 wallets funded from one wallet | Rewards gain ≤ 0%, 1 draw entry, cap still applies |
| Scalper keeping a balance by churning (no lot reaches 2h) | Score = 0 |
| Snapshot sniper (buys before the epoch ends) | Score = 0 for 2h, then only time-weighted |
| Holding time 7d vs 30d vs 60d vs 90d, same balance | Score strictly increasing, then flat after 90d |
| Trader in 4h cycles vs a 7-day holder | Reward per token-hour ≤ 30% of the holder's |
| Partial sale | Score lost is exactly that of the lots sold (newest first) |
| New buy on top of an old bag | Age and score of the old lots unchanged |
| Transfer to another owner | Receiver starts from age 0 with no cost basis; no advantage moves with the tokens |
| €100 holder at market caps from $50k to $50M | Eligible in every case; first payout within the time reported |
| Small balance below `MIN_PAYOUT_Q` | Stays in `pending`, never decreases, paid once the threshold is passed |
| **Any split** of the same trades across 2–10 unlinked wallets, boost off (property test, random trades) | Total score never higher than with one wallet |
| Same, boost on | Gain reported; never above the boost (1.5×) on the lots involved |
| Underwater farmer (buys the top on purpose) | **Total ROI** = (final value + rewards − capital − costs) / capital is lower than buying at the epoch mean price, in ≥ 95% of seeds |
| Holding the pool lower for ≤ 1h, on random price histories | `P̄_e ≥ (23/24) · A_rest` always; `u_lot` at most 0.028 above the rest-of-window boost; attacker's net PnL negative |
| Pump of any size for ≤ 1h, on random price histories | `P̃_h ≤ (24/23) · H_rest` always; from a flat price, unlock change < 5% for r ≤ 4.5 |
| Buy and sell in the same second | The intra-second states get zero weight; `p(t)` is the price from the end-of-second reserves, fees included |
| Dump, then 6h with no trades (arbitrage agents present) | Attacker's net PnL negative |
| Pump, then 24h with no trades (arbitrage agents present) | Attacker's net PnL negative |
| Pool depth below the trust threshold (including a whole bonding-curve phase) | Base rewards and eligibility unaffected; boost off and price unlock paused; no untrusted price read anywhere |
| Slots with missing or decreasing block time, skipped slots | Same output as the clean log with the documented clamping rule |
| Two RPC sources disagree | Epoch delayed, not finalized |
| Soft vesting: selling locked tokens | Forfeit applied |
| Soft vesting: moving locked tokens out through 3 wallets in a row | Forfeit applied; the lots stay tainted at every hop; no gain vs. holding |
| **Dust attack:** attacker sends any amount of tokens or SOL to a victim | Victim's score, eligibility and payout are not lower |
| **Forced merge, free actions:** transfers to the victim, copy trades, same destination | No merge |
| **Forced merge, funding:** attacker sends SOL to a victim before the victim buys | No merge unless he supplied ≥ 50% of the victim's lifetime inflows and buy spend; his cost is reported |
| Two users of the same fee-paying app, plus any one-sided signals from an attacker | No merge; payer appears in the review list |
| Single commercial transfer between two owners | No merge |
| Chain A–B (co-signed), B–C (one transfer), C–D (co-trades) | Only A–B merged |
| **False merge of two independent clusters** | Tokens that never moved between them score exactly the same; cap and draw damage reported (first target: median ≤ 5%, 95th percentile ≤ 20%) |
| Sybil recall | Farms funded from one wallet ≥ 95%. CEX-funded farms: reported as the known residual risk |
| Whale cap with 10 clusters | No cluster above 5%, no share above 2× proportional, the rest stays in the pot |
| `S = 0` | Nothing distributed, pot unchanged, no error |
| Circular transfers (A→B→C→A, inside and across clusters) | No gain in score, age or boost |
| Moving the whole bag to a new wallet funded by the old one | Age and cost preserved |
| Retroactive merge | Past epochs unchanged; current epoch equals a from-genesis rebuild |
| Exact payout | `Σ payouts + rollover_units == R_e`, all in Q base units, on every seed |
| Draw payout | Prizes sum to ≤ `D`; unassigned prizes and rounding units stay in the draw pot |
| Multiplier bounds | Tokens under 2h score 0; never above 2.8× without boost, 4.2× with it |
| Higher multiplier vs. concentration | With the 2.8× curve the top-10% reward share is not higher than with the 2.0× curve by more than 5 points (first target) |
| Volume −90% overnight | Payouts ≥ 45% of the prior level after 7 days |
| Informed agent vs. simple holder | First target: informed agent's reward per token ≤ 1.25× the simple holder's |
| Reward concentration | Reported with both Gini values. Pass = with a stable holder base, the top-10% share of rewards is not still rising between day 60 and day 90 |
| Reward stability | First target: ±10% on any one parameter moves no honest holder's share by more than 15% |
| Draw fairness | Over 100,000 simulated draws, win frequencies match weights (χ² test, p > 0.01) |
| **Independent implementation** | A second implementation of sections **0–9 and 11** in a different language (Rust or TypeScript with big rationals), written from this document only, gives byte-identical `claims.json` and root on 1,000 random seeds, including runs with vesting, forfeits and tainted lots |
| Treasury bot backtest | ≥ 200 real memecoin price paths, of which ≥ 30% rugs or near-total liquidity loss; parameters tuned on half, judged on the other half; real costs (pool fee, slippage from actual liquidity, priority fees). Pass = out-of-sample median PnL ≥ 0 **and** max loss on any path ≤ 35% of capital. If it fails, the bot stays off. |

Rows marked "first target" are starting thresholds. If the simulator shows one is wrong, change it through DECISIONS.md with the evidence, not silently.

## 15. `config/pad.json` (filled when the pad launches)

```json
{
  "name": null, "program_ids": [], "token_program": "spl|token2022",
  "quote_asset": "SOL",
  "price_source": {"before_graduation": null, "after_graduation": null, "pool_type": "cpmm|clmm|curve", "reserve_accounts": []},
  "curve": {"type": null, "graduation_mc": null, "venue_after": null},
  "creator_fee": {"bps": null, "recipient": "address we control", "claim_method": null},
  "vesting_mode": "native|soft", "native_vesting_params_map": {},
  "dev_buy": {"max_pct": null, "lockable": null},
  "burn_allowed": null, "anti_snipe": null, "transfer_hook_allowed": null,
  "docs_url": null, "verified_by": null, "verified_at": null
}
```

## 16. Launch scope (feature flags in `coin.json`)

Everything above is built and tested, but not everything is switched on at launch.

| Feature | At launch | Turned on when |
|---|---|---|
| Fee routing, buyback & burn (10) | **on** | — |
| Holder rewards: 2h start, holding curve, cap, running balances (1–4, 6–8, 13) | **on** | — |
| Dev tokens hard-locked (11) | **on** | — |
| Public rules page with every wallet, `hubs.json` and overrides; holder view (17) | **on** | — |
| Underwater boost (5) | off | after 7 days of clean epochs |
| Draws (9) | off | ≥ 100 eligible clusters and the VRF flow tested on devnet. Until then the draw pot keeps accumulating, so the first draw is a large one |
| Early-buy vesting (11) | depends on the pad | `native` if the pad supports it; `soft` only if kiwi approves |
| Liquid staking of the pot (8) | off | pot large enough to matter, kiwi approves |
| Treasury bot (12) | off | section 14 backtest passed and kiwi approves |

## 17. What the holder sees (read-only page built from the epoch files)

The page shows facts from published epochs. It never shows an APR, a projected yield or a "you will earn" number, because rewards depend on fees that change every day.

For a connected or pasted wallet:
- **Position:** tokens held, and an indicative value (labelled as indicative).
- **Holding age and multiplier** per lot, and the weighted multiplier of the wallet.
- **Next step:** time left to the next knot of the curve ("1.90× in 14 hours").
- **Share of the last epoch's payout**, as a percentage.
- **Rewards, in three separate numbers:** earned so far, already paid, pending (and how far `pending` is from `MIN_PAYOUT_Q`).
- **Draw:** eligible or not for the current period, epochs counted so far, and the wallet's share of total draw weight.
- **Cluster:** which wallets are grouped with this one and the evidence type, with a link to ask for a review.

Fixed wording on the page: rewards come only from fees actually collected; the multiplier changes your share of the pot, not the size of the pot; nothing here is a promise of return.
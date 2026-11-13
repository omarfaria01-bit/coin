# COIN_MATH.md — Algorithms spec (v0.2, 14 Nov 2026)

Owner: kiwi (+ Omega, not active yet). Manager: Claude Code. Chain: **Solana**. Launchpad: **unknown until release** → everything pad-specific lives in `config/pad.json` (section 15).

Changes from v0.1: whale cap with few holders (§6), per-wallet payout split defined (§6), soft vesting closes the transfer loophole and stops overclaiming (§11), unlock TWAP window is a parameter + 6h-pump test (§11, §14), treasury bot funding source and buyback-timing rule (§12), legal review gate (§16), section reference fixes.

All parameters below are **defaults**. They live in `config/coin.json` and are tuned with the simulator (section 14). They are not hard-coded.

Design principles:
1. **Linear pro-rata for money, concave only for luck.** Paying rewards linearly in balance makes splitting wallets useless by construction. Sybil detection is only needed where something is "per head" (draws, caps).
2. **Time-weighted everything.** Use TWAB for balances and TWAP for prices. Any snapshot or spot value can be gamed in one block.
3. **Cluster, then score.** Every metric is computed on clusters (groups of wallets of the same owner), not on raw wallets.
4. **Monotone safety.** A lock can only decrease, a tax can only decrease, caps can only tighten. Nothing can be turned against holders later.
5. **Reproducible.** Every payout is a deterministic function of (on-chain data in slot range, params file, code commit). Anyone can recompute it.

---

## 1. Ledger (per wallet → per cluster)

Every wallet holds a list of **lots**: `(amount, cost_per_token_SOL, t_acquired, source)`.

- Buy from the pool → `cost` = executed price (SOL in / tokens out, fees included).
- Transfer in → `cost` = 1h TWAP at transfer time, `t_acquired` = transfer time. The age resets, and the transfer adds a sybil edge (section 7).
- Sell or transfer out → lots are removed **LIFO** (newest first). Selling part of a position keeps the age of the oldest lots, and selling everything resets the clock.
- Excluded accounts: pool/curve vaults, burn address, treasury, bot, fee router, dev wallets (they follow their own rules), and known CEX hot wallets.

## 2. Time-weighted average balance (TWAB)

For cluster `c` in epoch `e` (default epoch = 24h, starting 00:00 UTC):

```
B̄_c = (1/E) · ∫_{epoch} B_c(t) dt
```

This is computed exactly from piecewise-constant balances between transfer events (no sampling).
- A snapshot sniper who buys 5 minutes before the epoch ends gets 5/1440 ≈ 0.35% of a full-day weight.
- **Eligibility:** `B̄_c · TWAP_epoch ≥ MIN_ELIGIBLE_USD` (default $10) and the cluster has held for ≥ 1h.

## 3. Hold multiplier (age)

Per lot with age `a` in days:

```
h(a) = 1 + min(1, ln(1 + a) / ln(31))
```

| age | 0 | 1d | 3d | 7d | 14d | 30d+ |
|---|---|---|---|---|---|---|
| h | 1.00 | 1.20 | 1.40 | 1.61 | 1.79 | 2.00 |

Cluster multiplier: `H_c = Σ_lots (amount · h(age)) / Σ_lots amount`, measured at epoch end.

## 4. Flipper discount (churn)

The discount is based on traded volume relative to balance, not on the number of trades, so splitting trades into many small ones doesn't help.

```
χ_c = min(V_buy, V_sell)_{last 48h} / max(B̄_c, ε)      (round-trip volume in tokens)
F_c = 1 / (1 + κ · χ_c)                                κ = 2
```

- A pure holder has χ = 0, so F = 1.
- A cluster that churns 5× its balance per day has χ ≈ 10 over 48h, so F ≈ 0.05.
- Transfers between own wallets don't count as churn, but they create sybil edges and reset age.

## 5. Underwater boost (anti-manipulation version)

The goal is to keep holders who are in loss from capitulating, without making it profitable to farm the boost.

For each lot with `source = pool buy` and `age ≥ 48h`:

```
d_lot = max(0, 1 − P̃ / cost_lot)        P̃ = 6h TWAP
D_c   = amount-weighted mean of d_lot over eligible lots
U_c   = 1 + β · min(D_c, D_max) / D_max  β = 0.5, D_max = 0.75  → max 1.5×
```

Anti-gaming rules:
- **Only pool buys count**, so you can't inject a fake high cost through transfers.
- **48h age requirement:** buying the top to farm the boost costs a real loss, and you wait 2 days before you get anything.
- **6h TWAP:** pushing the price down to inflate the boost costs real money for 6h.
- **Cap at 1.5×.**
- **Cost basis is computed at cluster level.**

## 6. Score, share, whale cap

```
s_c = B̄_c · H_c · F_c · U_c
π_c = s_c / Σ s
```

- **Whale cap:** `π_c ≤ CAP` (default 5%). Excess is redistributed with water-filling: cap, renormalize the others, repeat until stable.
- **Few holders:** if `N_eligible < 1/CAP` (fewer than 20 clusters at 5%), the shares can't sum to 1 under the cap. Water-filling then ends with every cluster at `CAP`, and the leftover `R_e · (1 − N·CAP)` **stays in the reward pot** for the next epoch. Nothing is forced onto capped clusters. The loop must terminate in at most `N` iterations.
- The cap is the main thing whales try to evade by splitting, which is why clustering exists.
- **Per-wallet split:** a cluster's payout goes to its wallets in proportion to `B̄_w · H_w`, where `H_w` is the amount-weighted hold multiplier of that wallet's own lots. `F_c` and `U_c` are cluster-level and don't affect the split. Rounding: floor to the token's base unit per wallet; the remainder dust stays in the pot.

## 7. Sybil clustering

Wallets are nodes in a graph. Evidence becomes edges with weights:

| Evidence | Weight |
|---|---|
| Same fee payer on any tx | 1.0 |
| Direct transfer of this token or of SOL between two holders | 1.0 |
| Same first funder within 72h before first buy (funder not a CEX/bridge/known service) | 1.0 |
| Co-buys: same slot ±1, size within 10%, ≥ 3 occurrences | 0.7 |
| Identical balances (±0.1%) across ≥ 4 wallets created within 24h | 0.6 |

Algorithm:
1. Union-find on all edges with weight ≥ 0.7.
2. Merge weaker pairs if the summed evidence is ≥ 1.0.
3. Output clusters with a confidence score. Clusters with ≥ 10 wallets go to `reports/review.csv` for human review.

Safety:
- Maintain an allowlist of non-owner hubs (CEX hot wallets, bridges, Jupiter/aggregator programs, the pool itself) so they never become edges.
- A false positive only hurts per-head benefits and the cap, because linear rewards are unchanged. That makes errors cheap.
- **Known residual risk:** wallets funded independently through different CEX withdrawals are undetectable. Document this publicly.

## 8. Reward pot: payouts that don't die when volume dies

Inflows to the holder reward pot:
- its share of creator fees (section 10)
- treasury-bot realized profit sweeps (section 12)
- staking yield, because the idle pot is held partly in a liquid staking token (e.g. JitoSOL)

Payout per epoch is **exponential smoothing**, not "pay what came in":

```
R_e = α · Pot_e        α = 0.10 per day  (half-life ≈ 6.6 days)
```

- If fees drop to zero, payouts fall gradually (≈ 48% of the previous level after 7 days) instead of stopping overnight.
- If `R_e < MIN_EPOCH_PAYOUT`, skip the epoch and roll the money over, to save tx costs.

## 9. Draws (luck component)

There is a separate draw pot (section 10), with weekly draws (configurable).

- **Eligible:** clusters with B̄ ≥ threshold, held ≥ 24h, and not in forfeit state (section 11, soft mode B).
- **One ticket entity per cluster**, with weight `t_c = sqrt(s_c)`. The concave weight gives small holders real odds, and clustering stops splitting from exploiting it.
- **Selection:** Efraimidis–Spirakis weighted sampling without replacement:
  `key_c = u_c^(1/t_c)`, with `u_c = uniform(0,1)` derived from `hash(randomness ‖ cluster_id)`. Pick the top-k keys.
- **Randomness:** an on-chain VRF (Switchboard on-demand randomness, or ORAO VRF), requested **after** the snapshot hash is published (commit → reveal). Nobody, us included, can pick the winners.
- Default prize split: 1 × 40%, 3 × 10%, 6 × 5%.

## 10. Fee routing (creator-fee share only; the pad keeps its own cut)

| Destination | Default |
|---|---|
| Dev wallets (kiwi + Omega) | 25% |
| Holder reward pot | 35% |
| Draw pot | 25% |
| Buyback & burn | 15% |

- A router script runs hourly. Buyback is TWAP-sliced (small chunks, never one big buy), then burned with the token burn instruction.
- Every movement is logged to `ledger/fees.csv` and is public.

## 11. Price-weighted vesting (early buys + dev buy)

Scope: the dev buy, plus buys in the first `T_EARLY` (default 15 min, or until MC ≥ `MC_EARLY`, whichever comes first).

```
u_time  = clamp((t − t0) / T_v, 0, 1)                        T_v = 7 days
u_price = clamp(ln(P̃ / P_entry) / ln(M), 0, 1)              M = 5, P̃ = TWAP over UNLOCK_TWAP_H (default 6h)
unlocked(t) = max(unlocked(t−), u_time, u_price)             ← monotone: lock only decreases
locked = (1 − unlocked) · vested_amount
```

- At 2× the unlocked share is ln2/ln5 ≈ 43%. At 5× it is fully unlocked. After 7 days it is fully unlocked anyway.
- If the price dumps, nothing extra unlocks.
- A 1h pump can't unlock much, because P̃ is a 6h TWAP.
- **Known risk:** on day 1 liquidity is thin, so a group of early buyers may be able to hold 2× for 6h cheaply. The simulator tests this (section 14). If it fails, raise `UNLOCK_TWAP_H` (e.g. 12–24h) or `M`, and log the change in DECISIONS.md.

Implementation depends on the pad (`pad.json → vesting_mode`):
- **A. `native`:** the pad supports vesting or Token-2022 transfer hooks. Map these params to the pad's config, or use a transfer hook that enforces `balance − locked ≥ 0` on transfers.
- **B. `soft` (no hooks):** vesting is applied **to rewards**. If a vested wallet sells more than its unlocked part, it forfeits pending rewards and draw eligibility for 30 days, and the forfeited amount goes back to the pot.
  - **Transfers out count as sells.** Any outflow from a vested wallet (sell or transfer) is checked against its unlocked amount. Otherwise you could send the tokens to a fresh wallet and sell from there.
  - **Forfeit applies to the whole cluster** the vested wallet belongs to, including wallets that received tokens from it (a direct transfer is a 1.0 sybil edge, section 7).
  - **Honest limit:** soft mode only takes rewards away. A sniper who doesn't care about rewards can still dump. `docs/PUBLIC_RULES.md` must not claim early buyers "can't dump" unless `vesting_mode = native`.
- **Dev tokens: always hard-locked**, whatever the pad, through an existing audited lock program (e.g. Streamflow or Jupiter Lock). Never use a custom program for this.

## 12. Anticyclical treasury bot

The bot runs inventory-based mean reversion, buying dips and selling rips. **It is never used for wash trading or fake volume.**

**Funding:** the bot starts with `TREASURY_SEED_SOL` (default: set by kiwi, from the dev wallets) and receives **no** share of creator fees in v1 (section 10 has no treasury line). The seed amount, the source wallet and the bot wallet are published before launch.

**No information edge:** the team knows when the fee router buys back and when payouts happen. So the router's buyback schedule and the epoch payout times are published, and the bot does not trade in a ±`BOT_QUIET_MIN` window (default 15 min) around a scheduled buyback or payout. The simulator checks that bot orders never fall in those windows.

```
x_t = ln(price), 1-min TWAP from the pool
μ_t = EMA(x, half-life 6h)
σ_t = sqrt(EWMA((x − μ)², half-life 24h))
z_t = (x_t − μ_t) / σ_t
target token share   f* = clamp(f0 − γ·z, f_min, f_max)     f0 = 0.5, γ = 0.15, f_min = 0.1, f_max = 0.9
trade only if |f − f*| > band (0.05)
size = min(needed, 2% of 1h pool volume, MAX_TRADE_SOL)
```

- **Profit sweep:** weekly, 50% of `(equity − high-water mark)` goes to the reward pot.
- **Circuit breakers:**
  - It doesn't trade in the first 24h (price discovery).
  - It stops buying if the price is −60% from the 7-day high or liquidity < `L_MIN`.
  - Daily loss limit, plus a `STOP` file kill switch.
  - Slippage cap, and MEV protection through Jito.
- **Modes:** `paper` → `devnet` → `live`. Live only after kiwi's explicit approval (see the prompts).
- The bot wallet is public and its rules are published.

## 13. Payout rails

- Each epoch writes `epochs/<n>/{inputs.json, scores.csv, claims.json, root.txt}`. `inputs.json` holds the slot range, params hash, code commit, and data hash.
- **Claims:** use an existing audited Merkle distributor (jup-ag/distributor or the Solana Merkle-airdrop template). Don't write a custom program unless there is no alternative.
- **Small holder count (< 500 eligible):** push payouts instead, with a min transfer threshold. Amounts below it are carried forward.

## 14. Simulator: acceptance criteria (must pass before any mainnet use)

| Attack / scenario | Pass condition |
|---|---|
| Whale splits into 50 wallets with the same funder | Rewards gain ≤ 0%, draws ≤ 1 ticket entity, cap still applies |
| Flipper churning 5×/day | Score ≤ 10% of an equal-balance holder |
| Snapshot sniper (buys 5 min before epoch end) | ≤ 0.5% of a full-day weight |
| Underwater farmer (buys the top, waits) | Boost ≤ 1.5× and a net loss after costs |
| 1h pump to unlock vesting | Unlock change < 5% |
| 6h sustained 2× pump at day-1 liquidity by early-buyer group | Cost of holding the pump (slippage + fees + loss on unwind) ≥ market value of what it unlocks |
| Whale cap with 5, 10, 19, 20, 100 eligible clusters | Every π ≤ CAP, Σ payouts + rollover == R_e, loop terminates |
| Vested wallet transfers to fresh wallet, then sells (soft mode) | Forfeit triggers on the whole cluster |
| Treasury bot vs. published buyback/payout schedule | 0 bot orders inside the quiet windows |
| Volume −90% overnight | Payouts ≥ 45% of the prior level after 7 days |
| Treasury bot on 20 historical memecoin paths | Max drawdown ≤ 35%, no buying after a −60% breaker, positive median PnL |
| Determinism | Same inputs produce a byte-identical `claims.json` and root |

## 15. `config/pad.json` (filled when the pad launches)

```json
{
  "name": null, "program_ids": [], "token_program": "spl|token2022",
  "curve": {"type": null, "graduation_mc": null, "venue_after": null},
  "creator_fee": {"bps": null, "recipient": "address we control", "claim_method": null},
  "vesting_mode": "native|soft", "native_vesting_params_map": {},
  "dev_buy": {"max_pct": null, "lockable": null},
  "anti_snipe": null, "transfer_hook_allowed": null,
  "docs_url": null, "verified_by": null, "verified_at": null
}
```

## 16. Legal review gate (before PUBLIC_RULES.md and before P7)

Holders receive a share of creator fees (section 8) and there is a prize draw (section 9), run by identifiable people based in Italy. That combination may fall under EU financial-instrument rules (MiCA / MiFID) and Italian prize-draw or gambling rules. This spec is not legal advice.

- Before `docs/PUBLIC_RULES.md` is final and before anything in P7, kiwi gets a written opinion from a crypto lawyer.
- The design must stay modular so the lawyer's answer can switch features off without rewriting the engine: `draws.enabled`, `holder_rewards.enabled` and each fee-routing share are config flags in `coin.json`.
- Any change the lawyer requires is logged in DECISIONS.md and re-run through the simulator.

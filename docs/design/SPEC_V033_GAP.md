# SPEC_V033_GAP — COIN_MATH v0.2 → v0.3.3

Date: 14 Nov 2026. Source: kiwi's v0.3.3 drop. Engine baseline: `main` at `b2669c2`.
This document does not change `coord/STATE.md` or `coord/DECISIONS.md`. Suggested ADR
notes below are for Claude to record after review.

Mechanisms in v0.3.3 are frozen. Parameters are not: the holding curve, `T_START`,
eligibility shares and the draw period are defaults; the simulator must compare the
listed variants and kiwi chooses.

---

## 0. Conventions (new section)

**What changed.** Unit of account is the pool quote asset `Q` (SOL by default);
USD is display-only and never enters a formula. The payout path (sections 0–9, 11,
13) may use only integers and exact rationals (`fractions.Fraction`); `float`,
`ln`, `exp` and non-integer `sqrt` are forbidden there. One clock: finalized
block time in whole seconds; events ordered by `(slot, tx index, instruction
index)`; missing/decreasing block time is clamped forward. Price comes from pool
reserves (exact rational), not from swap prints. A second is *trusted* only if a
simulated swap of `D_TRUST` (default 2 SOL) moves the price by less than 5%. Two
time-weighted prices: arithmetic `P̄_e` (underwater) and harmonic `P̃_h`
(vesting). Canonical JSON + SHA-256. An epoch is finalized only when two
independent RPC sources agree on the event-log hash. Published epochs are never
recomputed.

**What the engine does now.** `engine/types.py` still documents prices as float
SOL per whole token. `engine/twab.py` and `engine/epoch.py::_twap` use float
arithmetic means of `PricePoint` swap/spot series. There is no `engine/events.py`
or `engine/prices.py`. No trusted-second test, no harmonic mean, no dual-RPC
hash, no canonical-JSON helper. D2 (`float64` for scores, int for money) and D13
(lamports per token base unit, float conversion in the orchestrator) are the
current arithmetic policy.

**What must change.** New modules `engine/events.py` and `engine/prices.py`
(prompt layout). Rewrite time/price helpers used by `engine/epoch.py`,
`engine/ledger.py`, `engine/vesting.py`, `engine/scoring.py`. Add a CI check that
payout-path modules do not import `math` or contain float literals (only
`treasury_bot.py` and `sim/` may). Canonical JSON writer for every epoch artifact.
Adapter work: reserve reads + two-RPC confirmation (later; offline fixtures first).

**What breaks.** Almost every numeric test (scores, TWAPs, unlock fractions).
D2 is superseded by the exact-arithmetic rule; D13's float conversion path is
superseded for the payout path (reserve prices stay exact rationals in Q).

**Size.** L (new modules + CI + types).

---

## 1. Ledger

**What changed.** Lots gain `origin` and `tainted_until`; cost is `cost_Q` (or
`null` for cross-cluster transfers). Same-cluster transfers are internal moves
(age, cost, origin kept). Cross-cluster transfers reset age, set `source =
transfer`, and carry taint; they no longer receive a 1h TWAP cost. Order of
computation is: cluster map, then rebuild ledger from the event log, then score.
A retroactive merge at epoch `n` rebuilds epoch `n` from genesis under the new
map; earlier published epochs stay frozen. No-grief: inbound tokens become the
newest lots and never change the age/cost/eligibility of lots already held.

**What the engine does now.** `engine/types.py::Lot` is
`(amount, cost_lamports_per_token: float, t_acquired, source)`.
`engine/ledger.py::build_lots` always attributes inbound transfers at
`twap_1h(ts)` and does not know clusters, origin, or taint. Event order is
`(slot, sig, ix)`, not `(slot, tx index, ix)`.

**What must change.** Extend `Lot`. `build_lots` must take the cluster map,
treat intra-cluster transfers as moves, set `cost_Q = None` on foreign
transfers, propagate `tainted_until`, and support a from-genesis rebuild for
the current epoch only.

**What breaks.** `tests/test_ledger.py`, `engine/epoch.py` (1h TWAP injection),
any fixture that assumes transfer lots have a cost basis.

**Size.** L.

---

## 2. Eligibility (price-free)

**What changed.** Eligibility is `B̄_c ≥ MIN_ELIGIBLE_SHARE · total supply`
(default `1/1_000_000`, i.e. 1,000 tokens of a 1B supply). No price, no USD,
no separate 1h hold gate (the 2h start rule in §4 covers short holds).

**What the engine does now.** `EligibilityParams.min_eligible_usd` (default $10)
and `min_hold_hours` (1h). `engine/epoch.py` computes
`usd = twab_c · epoch_twap / 1e9 * sol_usd` and requires both the USD floor
and the 1h hold.

**What must change.** Replace those fields in `config/coin.json`,
`config/coin.schema.json`, `engine/params.py`. `engine/epoch.py` and
`engine/twab.py` callers must compare TWAB to a supply share. Drop `sol_usd`
from the eligibility path.

**What breaks.** `tests/test_config.py`, `tests/test_epoch.py`,
`tests/test_properties.py`, sim acceptance rows that use the $10 gate.
D4's provisional USD thresholds are obsolete for eligibility.

**Size.** S–M.

---

## 3. Hold multiplier (new curve)

**What changed.** `h(a) = 0` below `T_START = 2h`, then piecewise-linear between
published knots, flat at **2.8× after 90 days**. Knots: 2h 1.00, 6h 1.15, 12h
1.30, 24h 1.50, 48h 1.75, 72h 1.90, 7d 2.10, 14d 2.30, 30d 2.50, 60d 2.70,
90d+ 2.80. Per-lot time in the epoch is split at 48h into `E1_lot` (no boost)
and `E2_lot` (boost applies). Closed form on each linear segment; exact
rationals, no `ln`.

**What the engine does now.** `engine/scoring.py::hold_multiplier` is
`h(a) = 1 + min(1, ln(1+a)/ln(1+horizon_days))` with `horizon_days = 30`, max
**2.0×**, and a token earns from age 0. `amount_weighted_hold` is a single
cluster-level `H_c` at epoch end, not an integral of `h(a(t))` over the epoch.

**What must change.** Replace `HoldParams.horizon_days` with `t_start_seconds`
plus an explicit knot table. Rewrite `hold_multiplier` / add `E1_lot`/`E2_lot`
integrators in `engine/scoring.py`. Cluster `H_c` is no longer a score input.

**What breaks.** All scoring tests, epoch goldens, the §14 1h-pump-unrelated
hold tables, and PR #61's sweep of `H`.

**Simulator variants kiwi picks later:** (A) default curve above; (B) previous
curve (start 48h, max 2.0× at 30d); (C) middle curve (start 12h, 1.05× at 24h,
1.5× at 7d, 2.0× at 30d, 2.35× at 90d).

**Size.** M–L.

---

## 4. Start rule (replaces the flipper discount)

**What changed.** The cluster-level churn factor `F_c = 1/(1+κχ)` is removed.
A lot scores zero until it has been held `T_START` (default 2h); that time is
never paid back. Scalping under LIFO earns nothing. No cluster-level factor.

**What the engine does now.** `ChurnParams` (`window_hours=48`, `kappa=2`) and
`engine/scoring.py::churn_factor` are part of `score = B̄ · H · F · U`.
`engine/epoch.py` accumulates 48h buy/sell volume per cluster.

**What must change.** Delete `churn` from config, schema, params, scoring,
epoch, sim agents, and tests. `T_START` lives with the hold-curve params.

**What breaks.** `tests/test_scoring.py`, `sim/acceptance.py` flipper row,
`sim/agents.py` if it farms `F_c`.

**Simulator variants kiwi picks later:** `T_START` = 6h, 12h, 48h vs default 2h.

**Size.** M.

---

## 5. Underwater boost (per lot)

**What changed.** Boost is per eligible *lot*, not a cluster average: only
`source = pool` lots with age ≥ 48h, `u_lot = 1 + β·min(d, D_max)/D_max`,
`d_lot = max(0, 1 − P̄_e / cost_Q)`, `P̄_e` = **epoch arithmetic mean** (not a
6h TWAP). Transfer lots have `u_lot = 1`. If more than 10% of the epoch's
seconds are untrusted, `u_lot = 1` for everyone. Dump bound: a 1h dump raises
`u_lot` by at most 0.028 above the rest-of-window boost. Feature is **off at
launch** (§16) until 7 clean epochs.

**What the engine does now.** `engine/scoring.py::underwater_boost` averages
drawdown over eligible lots and returns one cluster `U_c`. Window is
`underwater.twap_hours = 6`. Always on. No untrusted-second pause.

**What must change.** Per-lot `u_lot` applied only to `E2_lot`. Use `P̄_e`.
Add the 10% untrusted kill-switch and a `coin.json` feature flag
`underwater.enabled` (default false). Keep β=1/2, D_max=3/4.

**What breaks.** `tests/test_scoring.py`, `sim/acceptance.py::row_underwater`,
epoch orchestrator.

**Size.** M.

---

## 6. Score, whale cap, exact payout

**What changed.** `s_c = Σ_lots (E1_lot + u_lot · E2_lot)` (sum over lots, no
cluster factors). Multiplier bounds: 0 under 2h; up to 2.8× without boost,
4.2× with it. If `S = 0`, nothing is paid and no division is performed.
Whale cap: `CAP = 1/20` plus an uplift limit `G = 2`, so no share may exceed
2× its proportional share; leftover `rollover_share` stays in the pot (the
10-equal-clusters example pays 5% each and rolls 50%). Exact integer payout:
`T = floor(R_e · Σπ_c)`, floor per cluster, leftover units by largest
remainder (ties by cluster id). Per-wallet split is by `s_w` (the wallet's
own lot score), not `B̄_w · H_w`, also largest remainder.

**What the engine does now.** `engine/scoring.py::score` is `B̄·H·F·U`.
`engine/rewards.py::capped_shares` is classic water-filling with no `G`
(when `N < 1/CAP` every cluster is capped and the rest rolls, which is
directionally similar but not the 2×-proportional rule). `allocate` and
`split_to_wallets` floor and leave dust in the pot; they do **not** use
largest remainder, so `Σ payouts` can be less than `T` by more than the
documented remainder rule. Wallet weights are `B̄_w · H_w`.

**What must change.** New score entry point; add `G` to `ScoringParams`;
rewrite `capped_shares` / `allocate` / `split_to_wallets` for exact rationals
+ largest remainder; `S = 0` short-circuit in `engine/epoch.py` and
`engine/rewards.py`.

**What breaks.** `tests/test_rewards.py`, `tests/test_properties.py` (sum
conservation still required, but the share shape changes), PR #61's cap
sweep interpretation, whale-cap sim rows that expect the old leftover rule
without the 2× bound.

**Size.** M–L.

---

## 7. Sybil clustering

**What changed.** Evidence is rebuilt from scratch.

| Now on `main` (v0.2) | v0.3.3 |
|---|---|
| Same fee payer, weight 1.0, strong | **Informational only. Never a merge input.** Reported if a payer is shared by ≥ 5 holders |
| Direct token or SOL transfer, weight 1.0, strong | Two-sided token (L1, 0.6) or two-sided SOL (L2, 0.5). One-way token on ≥ 2 days is L3 (0.3) and cannot merge alone |
| Same first funder within 72h, weight 1.0 | Replaced by **S2 funded buy**: X sent W ≥ 50% of all SOL W ever received *and* that amount is ≥ 50% of W's lifetime buy spend |
| Co-buys: same slot ±1, size within 10%, ≥ 3, weight 0.7 (strong) | L4 co-trades: same **second** ±1, weight 0.4, one-sided |
| Identical balances, weight 0.6 | L5, weight 0.3 |
| — | New: S1 both holders signed the same tx (strong); S3 manual override; L6 sale proceeds to the same non-hub destination within 24h (0.5) |

Merge rule: any strong evidence, **or** link weights summing to ≥ 1.0 **that
include at least one two-sided signal (L1 or L2)**. Review list: ≥ 25
counterparties, shared fee payer of ≥ 5 holders, cluster > 50 wallets, or
merge resting only on link signals. Hubs live in `hubs.json` and change only
by a logged review (no automatic hub threshold).

**What the engine does now.** `engine/sybil.py::build_evidence` / `cluster`
implement the v0.2 table (`SybilWeights.same_fee_payer = 1.0` is a strong
edge). Union-find on weight ≥ 0.7, then weak pairs summing to ≥ 1.0, with no
two-sided requirement.

**What must change.** Rewrite evidence kinds, weights, and the merge rule in
`engine/sybil.py`, `engine/params.py`, config/schema. Add `hubs.json` and
`cluster_overrides.json`. Fee payer goes to the review list only.
`tests/test_sybil.py` and `tests/test_hubs.py` need a new fixture set.

**What breaks.** Every sybil test; any scenario that merged on a one-way
transfer or a shared fee payer (those merges are now forbidden). This is a
behavior break, not just a param tweak.

**Size.** L.

---

## 8. Reward pot

**What changed.** Same `R_e = α · Pot_e` with `α = 1/10` per day. Skip if
`R_e < MIN_EPOCH_PAYOUT` (money stays). Liquid staking is `lst_share` (default
0, max 50%), valued at `min(market, redemption)`, yield only when realized.
Theoretical 7-day decay is 0.9⁷ ≈ 47.8%.

**What the engine does now.** `engine/rewards.py::epoch_budget` already does
`R_e = floor(α_epoch · pot)` and scales α for non-24h epochs. `lst_fraction`
is already 0. No depeg valuation rule is implemented.

**What must change.** Rename/cap `lst_share`, add the min(market, redemption)
valuation when LST is later enabled. Little of the daily smoothing path needs
to change. Feature flag already exists as `rewards.enabled`.

**What breaks.** Low. Tests of `epoch_budget` should still hold. The volume-drop
sim row (≥ 45% after 7 days) stays, with the tighter 47.8% theory.

**Size.** S.

---

## 9. Draws

**What changed.** Period is `DRAW_PERIOD = n` epochs (default 7), not a fixed
"weekly" with a USD floor. Eligibility is price-free: rewards-eligible in at
least `⌈5n/7⌉` of the `n` epochs, `B̄_c ≥ MIN_DRAW_SHARE · supply` in the
final epoch (default `1/100_000`), not in forfeit. Weight is the integer
`w_c = isqrt(floor(Σ s_c over n epochs))`, not `sqrt(s_c)` as a float.
Payout: `D = δ · DrawPot_close` with `δ = 1` for the weekly default; prizes
1×40% + 3×10% + 6×5%; floor each prize; unassigned prizes and rounding stay
in the draw pot. Selection is **sequential weighted sampling with rejection**
(no modulo bias), with an explicit SHA-256 stream
`"COIN_SYSTEM_DRAW_V1" ‖ genesis_hash ‖ mint ‖ draw_index ‖ snapshot_hash ‖ ρ ‖ i`.
This **replaces Efraimidis–Spirakis**. Draws are **off at launch** (§16) until
≥ 100 eligible clusters and a devnet VRF test; the draw pot still accumulates.
If draws stay disabled, their 25% fee share goes to the holder pot (§10).

**What the engine does now.** `engine/draws.py` is E–S with `t_c = sqrt(s_c)`,
`u` from `sha256(randomness || id)[:8]`, `DrawParams.min_balance_usd` and
`min_hold_hours=24`, `enabled: true` in `coin.json`. `split_prizes` already
floors and returns remainder.

**What must change.** Replace `draw_winners` (and drop `math.sqrt`/`math.log`).
New eligibility and integer weights. Add `draw_period_epochs`, `delta`,
`min_draw_share`. Default `draws.enabled = false`. Fee reroute when disabled
(`engine/fees.py::route`).

**What breaks.** `tests/test_draws.py`, `sim/acceptance.py::row_draws_fairness`
(the χ² test remains, but the sampler is different). D8 (ORAO VRF) still
applies as the randomness source; only the off-chain consumption changes.

**Simulator variants kiwi picks later:** daily (`n=1`, `δ=1/3`) and 3-day
(`n=3`, `δ=1/2`) vs default weekly (`n=7`, `δ=1`).

**Size.** M–L.

---

## 10. Fee routing

**What changed.** Same 25/35/25/15 split. If draws are disabled, the 25% goes
to the holder reward pot. Burn must be the token program's `Burn` from the
router's own account, with an on-chain supply check. `pad.json` gains
`burn_allowed`. Buyback is still sliced over time (the "TWAP-sliced" wording
is dropped; the idea stays).

**What the engine does now.** `engine/fees.py::route` always splits all four
legs and dumps rounding dust on `holder_pot`. No "draws off → holder pot"
branch. No burn helper.

**What must change.** Conditional reroute in `route` (or a pre-step that sets
`draw_pot=0`, `holder_pot=0.60`). Schema field `burn_allowed`. Burn/supply
check is P5/on-chain, not this PR.

**What breaks.** `tests/test_fees.py` once the disabled-draw path exists.

**Size.** S.

---

## 11. Vesting (formula + taint)

**What changed.** `u_price` is now **linear**:
`clamp((P̃_h(t)/P_entry − 1)/(M − 1), 0, 1)` with `M = 5` (each +1× unlocks
25%; 5× fully unlocked). `P̃_h` is the **24h harmonic mean**. It is evaluated
only when `t ≥ t0 + 24h` **and** every second of that window is trusted;
otherwise only the time unlock runs. Evaluated at minute boundaries, per lot.
Soft mode: outflow that leaves `balance < locked_c` forfeits the cluster
(score 0 for the current epoch and the next 30, no draws for 30 days). Tokens
that left while locked are **tainted** (`tainted_until = t + 30d`) and the
taint follows the lot through further transfers.

This **supersedes D14** (6h→24h arithmetic TWAP chosen to keep a *log*
unlock under 5% on a 1h 3× pump) and the proposed 36h follow-up. The new
bound is analytical: a 1h pump can move `P̃_h` by at most `24/23`, so from a
flat price the unlock change is < 5% for `r ≤ 4.5`, at a fixed 24h harmonic
window. Raising the window to 36h is no longer the lever v0.3.3 uses.

**What the engine does now.** `engine/vesting.py::unlocked_fraction` uses
`ln(twap/p_entry)/ln(M)` and an arithmetic TWAP of
`params.vesting.unlock_twap_hours` (24 on `main`). Soft breach is
`breaches_soft_lock(balance, locked)` only; there is no taint field and no
trusted-window gate. D10 (`vesting_mode` default `soft`) remains a pad
decision; §16 now says soft early-buy vesting is on only if kiwi approves.

**What must change.** New `u_price`, harmonic `P̃_h` in `engine/prices.py`,
24h+trusted gate, per-lot unlocked state, taint in the ledger, forfeit that
zeros score and draw eligibility. `unlock_twap_hours` as a tunable may stay
in config (default 24) but D14/D15-36h should not be merged as a default
change without a new failing §14 row.

**What breaks.** `tests/test_vesting.py` (the 1h 3× / 24h vs 36h arithmetic
cases are about a formula that no longer exists), `engine/epoch.py` vesting
block, sim pump rows.

**Size.** L.

---

## 12. Treasury bot (phase 2, off by default)

**What changed.** Bot is **off until** the §14 backtest passes and kiwi
approves. New hard limits: fixed `BOT_CAPITAL_Q` (never topped up from the
pot), `MAX_NET_BUY_Q` = 30% of capital, `MAX_BUY_Q_24H` = 10%. Stops (buys
halt, sells allowed): daily loss 5% of capital, total drawdown 25% from
peak (was a 60% / 7-day-high breaker), falling knife −40% from the 72h high,
untrusted second or depth −30% in 1h, data anomalies, `STOP` file. `σ_min =
0.10`. Profit sweep is **realized** PnL only (average-cost), 50% of the
high-water increment, in Q the bot actually holds. Backtest bar: ≥ 200 real
paths, ≥ 30% rugs, train/test split, median PnL ≥ 0 and max loss ≤ 35%; else
the bot stays off. The published quiet window around buyback/payout
(`BOT_QUIET_MIN`, D4-era) is **not** in the v0.3.3 bot section.

**What the engine does now.** `engine/treasury_bot.py::decide` is still
`NotImplementedError`. Params include `breaker_drawdown=0.6`, `quiet_minutes=15`,
`high_7d` in `MarketView`, `mode=paper`. No capital-at-risk caps, no `σ_min`.

**What must change.** Implement (or re-spec) `decide` against the new limits.
Default the feature flag off. Drop or keep quiet windows only if Claude
records a reason: they are absent from v0.3.3 §12 (the "no information edge"
rule of v0.2 is not restated). Backtest dataset is a later `type:data` issue.

**What breaks.** `tests/test_sim_*` quiet-window assertions if any; current
bot tests are thin because the function is unimplemented. PR #60 runbook
text that assumes a live bot on launch.

**Size.** L (implementation), S (flags/params now).

---

## 13. Payout rails and running balances

**What changed.** Epoch artifacts are
`epochs/<n>/{inputs.json, clusters.json, scores.json, balances.json,
claims.json, root.txt}` in canonical JSON (`scores.csv` is gone). Each wallet
has a running balance: `earned_total`, `paid_total`, `pending =
earned_total − paid_total`. `pending` is paid when it reaches `MIN_PAYOUT_Q`
(default 0.001 SOL, published max 0.005 SOL); it never expires and is never
clawed back for ineligibility. Draw prizes go through the same balance.
Push rail still at < 500 eligible. Merkle claims must have context binding,
replay protection, and a pull-back schedule: unclaimed after 30 days is
**re-credited to the same wallet's `pending`**; only after 180 days with no
claim at all does it return to the pot. Paying native SOL via wSOL unwrap is
an assumption to prove on devnet; if it fails, stay on push.

**What the engine does now.** `engine/epoch.py` / `adapters/epoch_files.py`
(on `main`: `scores.csv`, `claims.json`, `root.txt`, `inputs.json`).
`RewardParams.push_min_transfer_lamports` is already 0.001 SOL but is a
push-threshold, not a running `pending` ledger. Merkle leaf work
(`engine/merkle.py`, D7) has no 30d/180d re-credit path.

**What must change.** New artifact set + canonical JSON. A persistent
`balances.json` store across epochs in the orchestrator. Claim pull-back
state machine (can be stubbed offline). Align `MIN_PAYOUT_Q` naming.

**What breaks.** `tests/test_epoch.py`, `tests/test_epoch_files.py`, PR #57
CLI fixture shape, PR #58 golden files (they snapshot `payouts.csv` /
`result.json` / `state.json` under the old names and math).

**Size.** M–L.

---

## 14. Simulator acceptance

**What changed.** The table grows from 12 rows to ~45, plus required run
outputs (Gini, percentiles, honest-vs-informed gap, false-merge damage, sybil
recall, reward rate by holding time, €100-holder path, retention comparison
of curve variants, forced-merge cost, reward stability, price-manipulation
cost). Several v0.2 rows are replaced: the flipper "≤ 10% of a holder" row
becomes "scalper with no lot ≥ 2h → score 0" and "4h cycles ≤ 30% of a 7-day
holder per token-hour". The 1h pump row is now the harmonic-mean bound.
New property tests: no-grief dust, no forced merge, split-never-increases-score
(boost off), `pending` monotone, `S = 0`, taint through 3 hops, independent
implementation in Rust or TypeScript on 1,000 seeds.

**What the engine does now.** `sim/acceptance.py` implements a short v0.2
subset (whale cap, underwater, sybil split, zero inflow, draw fairness).
`sim/epoch_runner.py` and `sim/sweep.py` sweep the old `(cap, alpha, H, M)`.

**What must change.** Rebuild the acceptance suite and required outputs.
Add variant-comparison reports for the curves, `T_START` and draw periods.
Independent implementation is a standalone issue.

**What breaks.** `tests/test_sim_acceptance.py`, `sim/sweep.py`, PR #61
report (wrong parameters, wrong formulas).

**Size.** L (acceptance), XL (independent impl).

---

## 15. `pad.json`

**What changed.** New keys: `quote_asset` (default `"SOL"`), `price_source`
(`before_graduation`, `after_graduation`, `pool_type`, `reserve_accounts`),
`burn_allowed`. Existing curve/fee/vesting/dev-buy keys stay.

**What the engine does now.** `config/pad.json` and `PadParams` lack those
three fields.

**What must change.** `config/pad.json`, `config/pad.schema.json`,
`engine/params.py::PadParams`. No runtime adapter yet.

**Size.** S.

---

## 16. Launch scope (replaces the legal-review section)

**What changed.** Section 16 is now feature flags and launch defaults, not a
legal gate. Launch on: fee routing + buyback, holder rewards (2h curve, cap,
running balances), dev-token hard lock, public rules + holder view. Launch
off: underwater boost, draws (pot still fills), liquid staking, treasury bot.
Early-buy vesting: `native` if the pad supports it; `soft` only with kiwi's
approval. Legal review is intentionally absent here (kiwi is handling that
separately; this PR does not discuss it).

**What the engine does now.** `rewards.enabled` and `draws.enabled` exist;
`draws.enabled` defaults to **true** (must flip to false). No flags for
boost, vesting-soft, LST, or bot-beyond-mode. `docs/PUBLIC_RULES.md` is not
written yet.

**What must change.** Flags in `coin.json` matching the table, all defaulted
as specified. Claude should note in DECISIONS.md that the legal-review
*section number* has moved; the engineering gate "flags in coin.json so
features can be switched off" remains.

**Size.** S.

---

## 17. Holder view (new)

**What changed.** A read-only page built from published epoch files: position,
per-lot age and multiplier, next knot, last-epoch share, earned/paid/pending,
draw status, cluster + evidence, no APR or projected yield.

**What the engine does now.** Nothing. Prompt DoD item 6 now requires one
static HTML file. No `docs/PUBLIC_RULES.md` yet either.

**What must change.** A later `type:docs` / front-end issue. Needs the new
epoch artifacts first. Do not start it on the v0.2 file layout.

**Size.** M, after §13.

---

## Prompt diffs (not tokenomics, but they affect planning)

kiwi's updated prompts were dropped in verbatim (placeholders filled like the
current repo). Material differences vs the prompts already on `main`:

- v1 DoD now includes §0, exact-arithmetic CI, holder page, ≥ 200 bot paths,
  and an independent second implementation.
- New required engine modules: `events.py`, `prices.py`.
- Grok's standing work adds the independent implementation and a broader
  red-team list (sub-2h payouts, dust grief, forced merge, taint laundry).
- **Conflict with existing ADRs, needs a kiwi/Claude confirmation, not a
  silent revert:**
  - The new Grok prompt asks Grok to install Claude Code on the bot computer,
    clone to `~/work/coin-system`, and put Serena/Context7 in Claude's MCP
    list. D6 says Claude Code runs only in kiwi's sessions and the GitHub
    Action, never on Grok's computer. The live clone is `~/work/coin`.
  - The new Grok prompt restricts installs to a fixed allowlist plus
    `[tool-review]` issues. D5 (kiwi's 14 Nov directive, still in the *current*
    prompts on `main`) allows official-source installs logged in #1.
  - The new Claude prompt re-lists `claude-code-router` as optional pending
    a DECISIONS entry. PR #50 is already open to record D15 (free-model
    routing approved 14 Nov 2026, 08:06 Europe/Rome).
  - Branch-protection option C (kiwi's choice on issue #7) and the "liveness
    check if Grok is silent 24h" language are absent from the new Claude
    prompt; they remain in force unless kiwi says otherwise.

Recommendation: adopt the v0.3.3 *mission, DoD, tests and layout*; keep D5, D6,
D12/PR #50 and the `~/work/coin` path unless kiwi explicitly wants those
prompt sections to override the ADRs.

---

## Decisions that need an ADR update (Claude-owned files; not edited here)

| ADR | Effect of v0.3.3 |
|---|---|
| D2 float64 scores, int money | **Supersede.** Payout path is integers + `Fraction` only. |
| D4 provisional USD / 1h hold / quiet window | Eligibility and draw floors become supply shares. Quiet window is no longer in §12. |
| D10 `vesting_mode` default `soft` | Soft early-buy vesting now wants an explicit kiwi approval at launch. Dev hard-lock unchanged. |
| D13 float lamports-per-base in the orchestrator | Payout-path prices are exact rationals from reserves. |
| D14 `unlock_twap_hours` 6→24 (log unlock) | **Supersede.** New formula is linear in the 24h **harmonic** mean, with an analytical 1h-pump bound. |
| "D15" on PR #56 (24→36h) | Do not treat as the next default. Number also collides with PR #50's D15 (router). |
| D7 / D8 | Still valid as program choices; leaf/VRF *consumption* must match §13 and §9. |
| D5, D6, D12 | Stay, unless kiwi confirms the new prompt text overrides them. |

---

## Open PR conflict check (#50, #56–#61)

All of these are open against `main` at the time of this write-up.

| PR | Verdict vs v0.3.3 | Why |
|---|---|---|
| [#50](https://github.com/omarfaria01-bit/coin/pull/50) Record D15: free-model routing | **No tokenomics conflict.** Safe to merge independently. Prompt text in this PR still calls CCR "optional pending approval"; Claude should keep the already-approved routing. Touches only `coord/DECISIONS.md`. |
| [#56](https://github.com/omarfaria01-bit/coin/pull/56) unlock_twap_hours 24→36h + STATE | **Hard conflict. Do not merge as a spec default.** It retunes the *old* log-unlock + arithmetic TWAP (D14 follow-up). v0.3.3 replaces both the formula and the average (24h harmonic). Also writes `coord/DECISIONS.md` and `coord/STATE.md` under a second "D15". Close or rebase into a note that 36h is no longer the planned lever. |
| [#57](https://github.com/omarfaria01-bit/coin/pull/57) `tools/run_epoch.py` | **Soft conflict.** The CLI idea remains useful; fixture `tests/fixtures/run_epoch_two.json` and the output contract (`scores.csv` etc.) will be wrong after the engine rewrite. Merge-as-tool is ok only if a follow-up updates artifacts; otherwise hold and retarget. |
| [#58](https://github.com/omarfaria01-bit/coin/pull/58) Golden epoch replay | **Hard conflict.** Goldens are byte-level snapshots of v0.2 scores, payouts and file names. They will fail under v0.3.3 math and §13 artifacts. Do not merge as a lasting baseline; regenerate after the engine rewrite. |
| [#59](https://github.com/omarfaria01-bit/coin/pull/59) Offline tx→TokenEvent parser | **Mostly no conflict.** Fixtures and the parser stay valuable. Follow-up needed for §0: price from *reserves* (new `prices.py`), same-second zero-weight states, order `(slot, tx index, ix)`. Not a reason to close the PR. |
| [#60](https://github.com/omarfaria01-bit/coin/pull/60) Runbook + checklist | **Soft / docs conflict.** Useful first draft, but launch flags (§16), running balances, holder view, bot-off-by-default, harmonic vesting and draw-off-by-default are missing or wrong. Merge only as a draft to be rewritten, or hold. |
| [#61](https://github.com/omarfaria01-bit/coin/pull/61) Sensitivity (cap, alpha, H, M) | **Hard conflict.** Sweeps the v0.2 log-horizon `H` and log-unlock `M` (and interprets results under `s = B̄·H·F·U`). Those knobs and the report's conclusions do not apply. Close or redo against the knot curve, `T_START`, `G`, and supply-share eligibility after the engine rewrite. |

---

## Proposed issue breakdown

Claude should open these (or an equivalent set) after merging this spec PR.
Sizes: S ≤ ~1 day, M 1–2 days, L several days, XL a phase.

| # | Title | Owner | Prio | Size |
|---|---|---|---|---|
| A | [spec] Adopt v0.3.3 in `coin.json` / schemas / `ENGINE_DESIGN.md` / feature flags (no formula code yet) | claude | P0 | M |
| B | [code] `engine/events.py` + `engine/prices.py`: second clock, reserve price, trusted seconds, arithmetic + harmonic means, canonical JSON | grok (from Claude's interface spec) | P0 | L |
| C | [code] Ledger v0.3.3: cluster-aware rebuild, `origin`, `tainted_until`, internal moves, no-grief LIFO | grok | P0 | L |
| D | [code] Scoring v0.3.3: knot curve, `E1`/`E2`, drop churn, per-lot boost, `Fraction` scores | grok | P0 | L |
| E | [code] Rewards v0.3.3: `G=2` cap, largest-remainder payout, `S=0` path, running `pending` balances | grok | P0 | M |
| F | [code] Sybil v0.3.3: S1–S3, L1–L6, two-sided merge rule, fee payer informational, `hubs.json` | grok | P0 | L |
| G | [code] Vesting v0.3.3: linear `u_price`, 24h harmonic mean, trusted window, taint + 30d forfeit | grok | P0 | L |
| H | [code] Draws v0.3.3: `isqrt` weights, rejection sampling, `DRAW_PERIOD`/`δ`, supply-share eligibility, default off | grok | P0 | M |
| I | [code] Fees: disabled-draw 25% → holder pot; pad schema `quote_asset` / `price_source` / `burn_allowed` | grok | P0 | S |
| J | [test] CI: no `math`/`float` in the payout-path modules; new property tests listed in the Claude prompt | grok | P0 | M |
| K | [sim] Rebuild §14 acceptance table + required outputs on the new engine | grok | P1 | L |
| L | [sim] Variant comparison for kiwi: holding curves, `T_START`, eligibility shares, draw period | grok | P1 | L |
| M | [code] Treasury bot v0.3.3 limits, default off (implementation; backtest later) | claude spec + grok | P1 | L |
| N | [docs] Holder view (§17) static HTML from epoch files; no APR | grok | P1 | M |
| O | [docs] Rewrite runbook / launch checklist against §16 flags | grok | P1 | S |
| P | [data] Seed `hubs.json` from public labels (with sources) | grok | P1 | M |
| Q | [code] Independent implementation of §§0–9,11 in Rust or TypeScript, 1,000-seed byte match | grok | P2 | XL |
| R | [data] ≥ 200 historical memecoin minute paths (≥ 30% rugs) for the bot backtest | grok | P2 | L |
| S | [needs:kiwi] After issue L: pick holding curve, `T_START`, eligibility shares, draw period (and soft vesting / bot / LST when those reports exist) | kiwi | P1 | — |

Issue L/S should not be treated as done by either agent. The spec is explicit
that kiwi chooses after seeing the comparison.

Suggested merge order on the engine: A → B → C → D+E (can stack) → F and G in
parallel (different files) → H+I → J → K/L. Do not start Q until the Python
reference on `main` matches v0.3.3, or the two implementations will lock in
the wrong bytes.

---

## Out of scope for the spec PR that carries this file

No engine or config code is changed in that PR. No merge. No edits to
`coord/STATE.md` or `coord/DECISIONS.md`. No legal discussion.

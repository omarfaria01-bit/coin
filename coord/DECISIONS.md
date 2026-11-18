# DECISIONS (ADR log)

Format: ID · date · decision · why · alternatives.

## D1 · 2026-11-14 · Repo is private; branch protection pending kiwi
Why: the Action runs with secrets on @claude; public issues invite injected instructions.
Free private personal repos have no enforced branch protection, so "only Claude merges" is a
rule until kiwi picks a paid plan or an org + fork workflow (needs:kiwi issue).

## D2 · 2026-11-14 · float64 for scores, int for money; floor payouts, ceil locks
Why: determinism with Python floats is fine when operation order is fixed; all paid/stored
amounts are ints so conservation is exact. Alternatives: Fraction/Decimal everywhere (slow, no
benefit for byte-identical claims once payouts are ints).

## D3 · 2026-11-14 · Cluster id = smallest wallet id in the cluster
Why: deterministic and stable when unrelated wallets join/leave. Alternative: hash of members
(changes whenever membership changes).

## D4 · 2026-11-14 · Provisional params where COIN_MATH is silent
`min_epoch_payout` 0.01 SOL, push `min_transfer` 0.001 SOL, draw `min_balance_usd` $10,
`lst_fraction` 0 (no LST until decided), `mc_early_usd` none (time window only). Marked
PROVISIONAL in engine/params.py; tune with the simulator.

## D5 · 2026-11-14 · Tool/download policy (kiwi's directive)
Claude and Grok may install/download anything from official sources without a review issue,
logged in #1 / here. Still forbidden: wallets, browser extensions, pirated software, anything
asking for keys. Key/money/publishing rules unchanged.

## D6 · 2026-11-14 · Claude Code runs only in kiwi's sessions and the GitHub Action
Not on Grok's computer; kiwi's Claude login never goes on a machine another agent controls.
Comments from `claude[bot]` / `github-actions[bot]` produced by `.github/workflows/claude.yml`
in this repo are Claude.

## D7 · 2026-11-14 · Merkle claims: jup-ag/distributor (`DiS3nNjFVMieMgmiQFm6wgJL7nevk4NrhXKLbtEH1Z2R`)
Leaf per reports/research_onchain_2026-11.md §1.2 (sha256, 0x00/0x01 prefixes, claimant‖u64le‖u64le).
New `version` + vault per epoch. We call the deployed program and write our own Python leaf
code; no GPL source is vendored. **Valid only for a legacy SPL mint**: the program uses
`Program<Token>`. Token-2022 rail is open (#18). Alternatives: Streamflow airdrop (leaf
unpublished), Saber (stale), self-deployed Foundation example (last resort).

## D8 · 2026-11-14 · VRF: ORAO Classic (`VRFzZoJdhFWL8rkvu87LpKM3RbcVezpMEc6X5GVDr7y`)
Seed = published snapshot hash; output consumed off-chain by `engine/draws.py`. Same ID on
devnet/mainnet, Apache-2.0, 0.001 SOL/request (re-read NetworkState at integration).
Alternative: Switchboard On-Demand (price unverified).

## D9 · 2026-11-14 · Dev-token lock: Streamflow Token Lock, `transferableByRecipient=false`
Cancellation impossible by construction. Fallback: Jupiter Lock with cancel + recipient-change
both `None` (upgradeable program, source repo 404 on 2026-11-14 — note publicly if used).

## D10 · 2026-11-14 · `vesting_mode` default `soft`
Raydium CPMM/CLMM reject hooks, Meteora DBC strips them at graduation, Jupiter Trigger excludes
them. Switch to `native` only with a sourced pad finding.

## D11 · 2026-11-14 · Grok implements the remaining engine modules; Claude specs and reviews
kiwi's directive (work never stops, reuse-first). ledger/twab/scoring/rewards/fees/vesting/
merkle/epoch move to `owner:grok` issues with exact specs (#13–#17, #26). Claude reviews money
code line by line. Legal opinion (#8) is handled by kiwi with his lawyers and does not block
engineering; it still gates PUBLIC_RULES.md and P7 (COIN_MATH §16).

## D12 · 2026-11-14 · Free CLIs allowed for simple, non-secret work
kiwi authorized `gemini -p` and `opencode run -m opencode/deepseek-v4.1-flash-free` (plus
Haiku subagents in `.claude/agents/`) for research/drafts/boilerplate. Never send them keys,
`.env`, `coord/` strategy or unreleased launch details; every fact they return is re-checked
at the primary source. Routing Claude Code itself through a gateway stays off.

## D13 · 2026-11-14 · Price unit inside the engine = lamports per token base unit
`Lot.cost_lamports_per_token`, all `twap` arguments to ledger/scoring/vesting use it.
`PricePoint.price` (SOL per whole token) is converted once in the orchestrator:
`lamports_per_base = price · 1e9 / 10**decimals`. Why: BUY cost is `lamports/amount` with no
conversion, so comparisons are unit-safe.

## D14 · 2026-11-14 · `unlock_twap_hours` default 6 → 24 (COIN_MATH §11 / §14 row 5)
Test (tests/test_vesting.py): a 1h pump to 3× entry on a 6h TWAP unlocks ln(4/3)/ln5 = 17.9% (> 5%
limit, FAIL); on a 24h TWAP it unlocks ln(1+2/24)/ln5 = 4.97% (PASS, thin margin). Chose the longer
window over raising M (M=5 keeps the 2× ⇒ 43% curve). Cost: honest price-driven unlock reacts
~4× slower; the 7-day time unlock is unchanged. Margin is thin (4.97% vs 5%): if sim shows
a 1h 3.1× pump failing, raise to 36h rather than change M. `vesting_mode` stays soft (D10).
Related: D7 stays valid only for a legacy SPL mint; for a Token-2022 mint the v1 rail is push
payouts (report `reports/research_token2022_claims_2026-11.md` §5, #18). Decision on mint
program stays open for kiwi/pad choice.

## D15 · 2026-11-14 · Enable CCR + LiteLLM routing of cheap work to free models
kiwi approved in chat at 08:06 Europe/Rome, 2026-11-14, verbatim: "APPROVED: accendi il
router verso i modelli gratuiti". Relayed by Grok from chat (this file is updated via PR
for Claude to merge; Grok does not write `main`).
Routing (box-local CCR 3.1.3 + LiteLLM 1.109.1): Haiku-class subagents, background, simple,
and long-context-light tasks go to Gemini `gemini-3.1-flash-lite` (`GEMINI_API_KEY` from the
environment). OpenCode public/free models are configured in CCR as a secondary free target
when the Zen endpoint accepts them; the OpenCode CLI remains available for `opencode/*-free`
models. Main reasoning and review stay on Claude Sonnet (`claude-sonnet-5` via the local
Claude Code login imported into CCR). If a free model errors, CCR falls back to Claude
Sonnet. Never route secrets, security reviews, or final merges. Keys stay in environment
variables and CCR's local data dir, never in git. Router launch uses the isolated profile
`ccr 'Claude via Router' cli` (separate settings under
`~/.claude-code-router/profiles/claude-via-router/`); plain `claude` on kiwi's subscription
must keep using `~/.claude/settings.json` with no `apiKeyHelper` or `ANTHROPIC_BASE_URL`.
This supersedes the last sentence of D12 ("Routing Claude Code itself through a gateway
stays off"); the rest of D12 still holds.

## D16 · 2026-11-14 · Adopt COIN_MATH v0.3.3 (mechanisms frozen, parameters open)
kiwi's v0.3.3 (merged #62) is the source of truth. **Superseded:** D2 (float64 scores: payout
path is ints + `Fraction`), D4 (USD eligibility/1h hold: now supply share, §2), D13 (float
price conversion: payout-path prices are exact rationals), D14 and the "24→36h" idea in #56 (unlock is
linear in the 24h *harmonic* mean, §11; #56 closed). D10 stays the default code path, but soft early-buy
vesting at launch needs kiwi's explicit OK. **Unchanged:** D5, D6, D12, clone path `~/work/coin`; kiwi
(#62 comment, 2026-11-14 10:27) confirmed install policy: Grok installs what it needs, logged on #1; the
install-allowlist in the new prompts is ignored, and the "Omega = none" text must never be read as a login.
**Open parameters** (kiwi picks after the variant report): hold curve, `T_START`, eligibility shares, draw
period. Slices merged so far: #63 #68 #69 #75 #76 #77 #78 #80 (+ #57 #59 tooling). #70 (balances) needs a
180-day pull-back fix; #64 (auto-review) needs a security rework.

## D17 · 2026-11-14 · Draw stream byte layout (COIN_MATH §9 leaves it open)
`x_i = SHA-256("COIN_SYSTEM_DRAW_V1" ‖ genesis_hash[32] ‖ mint[32] ‖ draw_index[u64 BE] ‖
snapshot_hash[32] ‖ ρ[32] ‖ i[u64 BE])`, as implemented in `engine/draws.py` (#78). Fixed-width
fields make the concatenation unambiguous. The independent implementation (issue Q) must use the same
layout; if kiwi wants another, change both and log it here.

## D18 · 2026-11-14 · Cluster id and forfeit window in `run_epoch` (#82 PR3, #103)
**Cluster id** = the cluster's smallest *holder* wallet (smallest member only if it has no holder, e.g. a
lone funder), so ids are always holder addresses. Ids are not stable across epochs (a merge with a smaller
holder renames the cluster), so state keyed by cluster id is never carried: `forfeit_until` is recomputed
each epoch by replaying the full log under the current map (`soft_vesting_breaches`), and
`prev.forfeit_until` is ignored. **Forfeit window:** a cluster is forfeited in every epoch with
`t0 < forfeit_until` (was: eligible iff `forfeit_until <= t1`). With 24h epochs and `forfeit_days = 30`
that is the breach epoch plus the next 30, as COIN_MATH §11 B says; the old test gave only the next 29.

## D19 · 2026-11-14 · §16 launch flags default off (#82 step 6, #107)
`draws.enabled` = **false** (was true), new `underwater.enabled` = false and new `treasury_bot.enabled`
= false, per COIN_MATH §16. Turn on: draws at ≥ 100 eligible clusters + VRF flow tested on devnet (the
draw pot keeps accumulating meanwhile; `route_v033(draws_disabled=False)`, and once draw code reads
`draws.enabled` it is the single source of truth); boost after 7 clean epochs; bot after the §14
backtest passes and kiwi approves (`enabled=false` wins over any `mode`; `live` stays rejected without
kiwi's `APPROVED`). `run_epoch` raises on `underwater.enabled=true` until §5 u_lot is wired, instead
of ignoring it. Sim re-run: `sim.run --e2e --seeds 10`, all rows PASS.

## D20 · 2026-11-14 · §11 price unlock from reserves (#82, #108)
New param `prices.d_trust_lamports` = 2 SOL (D_TRUST, §0). `VestingEntry.p_entry` is an exact `Fraction`
in Q base units per token base unit (the unit of `prices.price_at`); `state.json` stores `"num/den"`, and
legacy JSON floats still load by their repr. u_price is skipped for any minute whose 24h window starts
before the first known reserve point or holds an untrusted second (§11). **Fixed-point P̃_h:** exact
Σ dt/p needs the lcm of every quote reserve (a 50k-point history exhausts memory), so each
constant-reserve piece of the window adds `ceil(len · reserve_base · 2^128 / reserve_quote)` and
P̃_h = window · 2^128 / Σ. Rounding up only lowers P̃_h (relative error < n · P̃_h / (window · 2^128) for n pieces; < (n+2)/2^128
when P̃_h ≲ window), so the unlock
is never above the exact one; the independent implementation (§14) must use the same rule. This is the
one place in the payout path that rounds before the final payout step; COIN_MATH §0 and §11 say so.

## D21 · 2026-11-14 · T_START = 6h (kiwi, #85)
kiwi decided **T_START = 6 hours** (was 2h) after the #119 variant report; his decision relayed on #85 and
by the operator instruction of this loop. Other parameters unchanged (default curve, eligibility 1/1,000,000,
draws off at launch, draw period later). The knot table is unchanged: `h` is 0 below 6h and jumps to the
6h knot (1.15) at T_START, exactly the "T_START 6h" variant in the #119 report. Effect measured there:
the 4-hour-cycle trader earns 0; €100 holder first paid in 1.7 days. Changed: `hold.t_start_seconds`
21600, `DEFAULT_T_START_SECONDS`, config/coin.json + schema, COIN_MATH §3–4, goldens regenerated.

## D22 · 2026-11-15 · `pad_rewards` extension point: design accepted, code NOT started (#29)
Accepted as design only (ENGINE_DESIGN §9, docs/design/PAD_REWARDS.md): a disabled-by-default,
pure, informational hook after the epoch result; cannot touch payouts/conservation; pad fee-share
never enters `R_e`. Open question resolved by recommendation: config lives under `pad.json`
(pad-specific, still empty). **No code issue is opened**: the pad's features are unknown and
#29 step 4 requires kiwi to confirm scope first. Enabling (or even building) needs: real pad spec,
sim re-run, kiwi `APPROVED`, and legal/disclosure review (#8; related-party risk, hard rule 6).

## D24 · 2026-11-17 · Index coin: no supply vesting or locks (kiwi, #156)
kiwi decided (in chat with the cloud Claude session, 17 Nov): the first coin on the engine is the GTA 6
index coin, and it has **no supply vesting, no dev-token lock, no early-buy vesting, no taint/forfeit,
no underwater boost, no treasury bot**. Their flags stay off (D19 already has them off at launch) and the
dev lock is removed from this coin's launch checklist. This overrides the COIN_MATH §16 "dev tokens
hard-locked: on" row **for this coin only**. Launch stays clean under hard rule 6: 0% bundle, no team
buys except an optional single dev buy in the creation tx from the publicly declared dev wallet.
No engine default changed, so no sim re-run is needed.

## D25 · 2026-11-17 · GTA 6 index rules v0.1 (kiwi's parameters, #156)
`INDEX_RULES.md` + `index/params.json`. kiwi set F3 (top 10 holders between 13% and 27%) and F4
(total fees ≥ 10 SOL, a minimum). Other values are starting defaults chosen by Claude: liquidity ≥ $50k,
bundle ≤ 10%, dev ≤ 5%, ≤ 3 launches in 7 days, authorities revoked, ≥ 200 unique traders,
turnover 0.05–3, score `0.4 ln MC + 0.3 ln Liq + 0.2 ln Fees + 0.1 ln Traders`, buffer 8/12,
equal weights, rebalance 18:00 UTC. Open: the data source for F4 and F9 (G1 found no confirmed
official source for total fees; `reports/research_index_data_2026-11.md`). Until a source is fixed,
F4 cannot be evaluated and the index is computed only as a dry run.

## D23 · 2026-11-18 · Align `params.py` defaults to COIN_MATH v0.3.3 (#152)
Eight defaults in `engine/params.py` / `config/coin.json` moved to the spec values: `underwater.twap_hours`
6→24 (§5), `sybil.weights.same_fee_payer` 1→0, `direct_transfer` 1→3/5, `co_buy` 7/10→2/5,
`identical_balances` 3/5→3/10, `sybil.review_cluster_size` 10→50 (§7), `draws.min_balance_usd` 10→0 (§9),
`treasury_bot.breaker_drawdown` 3/5→2/5 (§12). COIN_MATH is the source of truth, so the code was stale.
All eight fields are unused by `run_epoch` today (enforced weights live in `engine/sybil_v033.py`), so the
sim re-run is unchanged: only goldens' `inputs_hash` moves, payouts/scores/state are byte-identical
(`tools/regen_golden.py --check`, 33 acceptance rows PASS). `KNOWN_DRIFT` is now empty; the consistency
test fails hard on any future movement. No kiwi decision needed (spec values, not new choices).

## D26 · 2026-11-17 · GTASP10, Helius, hourly basket index (kiwi, #156)
kiwi, 18 Nov 00:38–00:59 Rome, via Grok on #156. Temporary name/ticker **GTASP10**.
Data source is Helius mainnet RPC + DAS + Parsed Events (key only in `HELIUS_API_KEY`, never
committed or logged). DAS cannot search by name, so discovery is pump.fun create history plus
explicit mints. F4 is the parsed `fee` (base + priority, already one total) plus native tips to
the eight Jito tip accounts in `adapters/helius_parse.py`, once per successful swap of that mint.
A truncated history leaves the fee fields empty. DexScreener is only pool liquidity, price/MC
when DAS has no `price_info`, and `volume.h24` from that same pair. No `/search`, no GMGN scrape.
Rebalance and the draw are hourly. The score window stays 24h with 5-minute samples. Rank exits
wait one extra hour; a current member with `insufficient_data` keeps its last passing metrics.
This coin's fees are 70% holder rewards (daily) and 30% draw pot, both paid in the basket, with
no team share and no buyback. A prize part below 0.01 SOL carries over. `config/coin.json` is
unchanged, so there is no sim re-run; basket buys are not built and still need `APPROVED`.
#164 is postponed. Still open: dev wallet, X link, keyword OK, index treasury address.

## D27 · 2026-11-18 · T_START = 1h and a 5× curve that saturates at 4h (kiwi, #156)
kiwi, 18 Nov 01:02 Rome (comment 6964683656), supersedes T_START = 6h (D21) and the 90-day / 2.8× curve.
`h(a)` = 0 below 1h; knots 1h→1×, 1h30→1×, 1h45→1.5×, 2h→2×, 2h30→3×, 3h→4×, 4h→5× (max, flat after),
linear between knots. Changed: `engine/scoring.py` defaults, `engine/params.py`, `config/coin.json` + schema,
COIN_MATH §3/§4/§14, acceptance rows, goldens (`tools/regen_golden.py`). Boost age (48h) and the underwater
boost are untouched (boost still off at launch).
**Measured consequence (not hidden):** because the curve is flat from 4h, a ~5h flipper earns 0.53× of a long
holder's reward per token-hour (seed 0). The old §14 bound (≤ 30%) cannot hold with this curve, so the row
bound is now ≤ 60% and is flagged for kiwi. Loyalty beyond 4h earns no extra multiplier. Reward per
token-hour by holding time (seed 1, 12 days): 4h 1.40 · 12h 2.02 · 24h 2.07 · 72h 2.13 · 7d 2.14.

## D28 · 2026-11-18 · Hourly draw, 70/30 fees, no team share, no buyback (kiwi, #156)
kiwi, 18 Nov 00:53–00:58 Rome (comments 6964535858, 6964592643, 6964626883). Fees: 100% of creator fees go to
holders: 70% holder rewards / 30% draw pot, dev 0%, buyback 0% (`FeeParams`, COIN_MATH §10; extends D26).
Draw: one per hour (`draws.period_hours` = 1, was 7 days); eligible only after a 1h hold (`min_hold_hours` = 1 =
T_START, a younger cluster scores 0); linked wallets are merged by the existing cluster rule; no cluster above 5%
of the odds (`draws.cap`, exact water-filling; with < 20 clusters odds become equal); odds ∝ isqrt(score); minimum
pot 0.01 SOL (`draws.min_pot_lamports`), below it the pot rolls over; Σ prizes + rollover = pot (tested).
Randomness stays the commit→reveal VRF stream of §9 (`rho` is input, never made in the engine).
New pure module `engine/hourly_draw.py` (+ Hypothesis tests). **Still OFF** (`draws.enabled` false): the legal
gate (COIN_MATH §16/#8) and the VRF devnet test are not done, and the hourly job does not call it yet, so the
engine's daily epoch is unchanged apart from the 70/30 pots. Goldens regenerated (`tools/regen_golden.py`);
holder pot is now 70% of fees, so payouts per epoch roughly double versus the 35% default.

## D29 · 2026-11-18 · F11: market cap ≤ 100 × liquidity (#167, Claude, new filter)
Red team #162 showed a 0.1% float on a $50k pool reports a $50M market cap and ranks first (constant-product:
MC = L / f). Added **F11** `mc_usd ≤ max_mc_liquidity_ratio × liquidity_usd` (default 100, exact Fraction
compare), checked after F10 so F1–F10 results do not change. Missing mc or liquidity → `insufficient_data`.
Not added yet (needs data design): the free-float / independent-holder check and the pair-selection pin from #167
steps 2–3. F3/F4 untouched (kiwi's). A coin at ratio 100 (e.g. $6M MC on $60k) still passes; kiwi can change
the ratio in `index/params.json` (params_hash moves, so it shows in the hourly output).

## D30 · 2026-11-18 · Persistent seed mint universe for sampling (#196, Claude)
Discovery only sees recent pump.fun creates, so the first hourly run was empty and `min_coverage` (1/2 of the 24h
window) can never fill. `index/seed_mints.txt` (96 mints from the 17 Nov dry-run) is now passed with `--mints-file`
by `ops/index-job/index-job.sh` (override path with `COIN_INDEX_MINTS`), and discovery pages go 25 → 100
(`COIN_INDEX_DISCOVER_PAGES`). A seed is only a mint to measure: keyword, F1–F11, `min_coverage` and `deny` all
still apply; it is not an `allow` entry. No param changed, `min_coverage` untouched. DAS has no name search, so
keyword discovery stays parsed pump.fun history.

## D31 · 2026-11-18 · F5 bundle window: first 10 slots, single sniper counts, creator exempt (#169, Claude)
Red team #162: F5 counted only the creation slot and only 2+ wallets, so one sniper wallet or a next-slot buy
(Jito bundle) scored 0. `bundle_pct` now sums buys by every non-excluded wallet in the first 10 slots
(`BUNDLE_WINDOW_SLOTS`, ~4 s); the creator's own buy is left to F6 (`dev_pct` ≤ 5%). Threshold `max_bundle_pct`
(10) unchanged; metric is stricter, so some coins that passed now fail F5. Not done (needs kiwi or chain data
design): F1 48h seasoning (kiwi picks 48/72h), creator-cluster F3/F6/F7 (needs funding-trace collection).

## D32 · 2026-11-18 · F8c: token program and Token-2022 extension allowlist (#171, Claude)
F8 only checked mint/freeze authorities. Added **F8c** (inside F8): legacy SPL Token passes; Token-2022 passes only when every
mint extension is in `filters.token2022_allowed_extensions` (default `metadataPointer`, `tokenMetadata`, `interestBearingConfig`,
`scaledUiAmountConfig`); any other extension (PermanentDelegate, TransferHook, TransferFeeConfig, Pausable, DefaultAccountState,
Confidential*, unknown) or any other program fails F8. Unknown program/extensions → `insufficient_data` (fail-safe). The adapter
reads the owner program and `info.extensions` from the parsed mint account (no new RPC call). Not done: F8b metadata-authority
check (step 0 needs a live pump.fun mint check first; metadata mutability is UNVERIFIED) and creator-cluster deny; kept in #171.

## D33 · 2026-11-18 · F9/F10 measure independent activity (#170, Claude)
Red team #162: 200 wallets x 0.01 SOL passed F9, and F10 counted round-trip volume. Now, from the parsed swaps in the window
(buy = fee payer receives the mint, SOL out; sell = reverse; tips excluded): **F9** counts wallets with volume >=
`min_trader_volume_sol` (0.05), creator wallet excluded, against `min_unique_traders` (200). **F10** removes same-wallet
opposite-side matches within `roundtrip_minutes` (10) from the DexScreener window volume (`volume_usd * (1 - roundtrip_share)`),
keeps the 0.05-3 turnover band on that, and also needs `min_volume_wallets` (30) wallets with volume left and a median remaining
trade >= `min_trade_sol` (0.01). Missing/ambiguous swap data (truncated history, unknown side or SOL) -> `insufficient_data`.
`unique_traders` (fee payers) still feeds the score. Published per member: `independent_traders`, `roundtrip_share`,
`volume_wallets`, `median_trade_sol` (source helius-parsed-events). Not done: creator/LP funding-cluster exclusion (needs
first-funder collection, left in #170); collector uses the default thresholds for these facts. Stricter than before, so
some coins that passed F9/F10 now fail.

## D34 · 2026-11-18 · Emergency liquidity removal needs two samples (#172, Claude)
Red team #162: one 1h print at -50% could remove a member (a big holder can fake it by pulling liquidity, or one bad
sample). Now `emergency_reason` removes for `liquidity_drop` only if the previous sample (`emergency.confirm_gap_s`, 900 s
earlier, vs its own 1h-ago value) also shows >= 50%; missing earlier data = no removal. Authority re-enabled and rug flag stay
immediate. New param default 900 (no params.json change, no golden change). Not done (in #172): second data source,
price-recovery check, manual confirm above a size, basket-buy TWAP/private path (mainnet, needs kiwi).

## D35 · 2026-11-18 · kiwi's index rule changes (#156, chat 08:22 Rome relayed by Grok; Claude)
Source: kiwi in chat 18 Nov 08:22, relayed by the Grok executor (not a cloud-agent comment). Supersedes D30 "keyword and
min_coverage still apply" and the F1/F4/F5/F6/F10 parts of D31/D33 where they differ.
1. Universe: one keyword tier, 35 words (INDEX_RULES §1); weak tier and `overrides.allow` removed; `deny` stays (scams).
2. `min_coverage` removed: any samples in the window count; zero samples = `insufficient_data`.
3. F1 6h -> 4h. 4. F4 10 -> 8 SOL. 5. F6 removed; F5 `max_bundle_pct` 10 -> 30.
6. Volume = Helius raw as-is; F10 = volume > 0. Round-trip/turnover/30-wallet/median-trade params removed. F9 (200) and F11 kept.
7. Weights: NOT changed, waiting for kiwi's choice.
Risk, said plainly: with no coverage minimum and no wash cleanup, a coin with one hour of samples can enter, and wash volume
is no longer filtered (F9 200 independent traders is the remaining check). Collector still publishes `roundtrip_share` etc.
as data. `sim/index_coverage.py` keeps its own `min_coverage` argument as a pure what-if tool. Params unknown keys are
rejected, so old configs with the removed keys fail loudly. Hetzner: pull /opt/coin after merge.
Job speed (same PR): `coin-index-sample` uses its own lock (`$LOCK.sample`) and never pulls code, so it is no longer skipped
while the hourly run holds the flock; hourly no longer repeats a sample pass (the 5-min timer owns sampling); default
`COIN_INDEX_DISCOVER_PAGES` 100 -> 10 (the seed file is the universe, D30). `_load_samples` skips a torn last jsonl line.


## D36 · 2026-11-18 · Index weights: market cap + volume, capped 25% (#156, kiwi chat 08:58 Rome relayed by Grok; Claude)
Source: kiwi's choice in chat 18 Nov 08:58, relayed by the Grok executor. Closes item 7 of D35.
`weight_i = 0.5 * MC_i / sum MC + 0.5 * Volume_i / sum Volume`, MC = window-average market cap, Volume = raw Helius window
volume; then cap 25% per coin with water-filling; fewer than 4 members -> equal (cap cannot hold). Integer bps summing to
10,000, largest remainder, ties to better rank. New `weights.mode = "mc_volume_capped"`, `cap_pct = 25` are the defaults
(`equal`, `score_capped` stay as options). Rank/membership still use the score S (§4); only the weights changed.
Risk, said plainly: volume is raw (no wash cleanup, D35), so a coin with inflated volume gets up to half-weight pull from
it; the 25% cap and F9 (200 traders) are the only limits. A half whose total is 0 counts as equal. Hetzner: pull /opt/coin.

## D39 · 2026-11-18 · Rewards audit fixes: linear draw odds, 5% supply cap, commit → reveal (kiwi, #156, #271)
kiwi, 18 Nov 13:12 Rome, on the audit (#271): "risolvi tu tutto questi problemi usando la matematica";
decisions delegated by kiwi to Grok (orchestrator). Supersedes the sqrt weight of §9/D28.
- **C1** draw odds ∝ score (linear, exact integers). Proofs in COIN_MATH §9; `tests/test_rewards_d39_math.py`;
  table `reports/rewards_d39_sybil_2026-11.md`: attacker with 3% of supply → 3.85% odds for 1, 10, 100 wallets
  (old sqrt: 1.14% → 3.52% → 10.35% → 26.75% at 1,000); 1,000 pieces of 0.003% are below the minimum → 0.
- **H2** score on min(balance, 5% of supply) (`SUPPLY_CAP`), plus the 5% odds cap. Site wording: "No holder
  can count more than 5% of supply".
- **C1/H1** minimum 0.01% of supply per entrant (`MIN_HOLDING_SHARE`, via `is_draw_eligible`); fewer than 100
  eligible groups (§16) → no draw, pot rolls over (never equal odds).
- **H3/M1** `engine/draw_commit.py`: snapshot hash over every input (scores, balances, overrides, hubs, excluded,
  cut-off, params); one ORAO request seeded with it, no retry; `tools/draw_verify.py` + payout guard refuse on
  mismatch. Offline only; no devnet/mainnet tx.
- **M2** `cluster(..., s2_two_sided=True)`: S2 merges need an L1/L2 on the same pair, else `funding_review`.
  Default stays off for the daily epoch (turning it on fails the §14 "same first funder" rows); the hourly draw
  job must call it with True.
- **M3** `adapters/solana_keys.py`: off-curve (PDA, program-owned) owners, dev and treasury excluded; run_epoch
  writes `excluded.json` per epoch (fixture flag `exclude_off_curve`, default true; goldens/test fixture use
  random addresses so they set it false).
- **M4** `engine/payout_guard.py`: memo key `GTASP10:e<epoch>:d<draw>:<wallet>`, skip keys done locally or seen
  on-chain, block on unresolved intents.
- Params live as constants in `engine/hourly_draw.py` (not `coin.json`, so `params_hash` and goldens of the daily
  epoch do not move); they are committed in every draw's snapshot hash. Draws stay **off**.


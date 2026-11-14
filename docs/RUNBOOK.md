# RUNBOOK — offline epoch procedure and launch-readiness

This is the operator guide for running the **offline** reward engine and
deciding whether the system is ready to go further. It does not send
transactions, create tokens, or touch wallets. Any step that would touch
mainnet or money is marked **needs kiwi APPROVED** and is not done here.

Sources: `docs/ENGINE_DESIGN.md` §8, `COIN_MATH.md` §13 / §14 / §16,
`coord/DECISIONS.md` (D2, D7, D10, D11, D13, D14).

No real wallet or key addresses appear in this document.

---

## 1. Hard rules (every run)

- Engine modules stay pure: no I/O, no `time.time()`. I/O lives in `adapters/`
  and `tools/`.
- Money fields are ints. Scores may be float64 (D2). Conservation is asserted
  inside `engine.epoch.run_epoch`:
  `prev.pot + pot_inflow + Σ prev.carry == pot_next + Σ transferred + Σ next.carry`.
- No mainnet writes, no signatures, no seed phrases. Devnet throwaways only,
  and only after kiwi APPROVED a named `needs:kiwi` issue.
- Legal opinion (#8) is kiwi's, with his lawyers (D11, COIN_MATH §16).
  Engineering may continue; it does not publish `docs/PUBLIC_RULES.md` or
  start P7 until that opinion exists.

## 2. Kill switch

Holder rewards are gated by `rewards.enabled` in `config/coin.json`
(COIN_MATH §16). To halt payouts without touching the pot math: set `rewards.enabled` to
`false` in `config/coin.json`, then re-run the epoch from the last good
`state.json`. Payouts are zero; the pot grows by `pot_inflow` only.


The flag is `engine.params.RewardParams.enabled` (default `true`).
`draws.enabled` is the matching switch for the prize draw.

**Test:** `tests/test_epoch.py::test_rewards_disabled_zero_payouts_pot_gains_inflow`
and the `rewards_disabled` row of `uv run python -m sim.epoch_runner`.

Turning the switch back on **needs kiwi APPROVED** if any payout would
leave the machine (push transfer or merkle vault).

## 3. Per-epoch operator procedure (offline)

Work from a clean checkout of `main`. Do not run these against mainnet RPC
for writes. Artifact directory `epochs/` is gitignored except `epochs/README.md`.

### 3.1 Pre-flight

```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run python tools/gen_schema.py --check
uv run pytest --cov=engine --cov-report=term --cov-fail-under=90
```

Expected: tests green, engine coverage ≥ 90%. **Test:** CI job `test` in
`.github/workflows/ci.yml`.

Confirm `config/coin.json` is the params you intend (`adapters.config_loader.load_coin`)
and that `config/pad.json` is still the unfilled template until the pad is
chosen. **Test:** `tests/test_config.py::test_committed_coin_json_equals_defaults`,
`test_committed_pad_json_is_unfilled_template`. Filling `pad.json` from a
live pad **needs kiwi APPROVED**.

### 3.2 Inputs

Assemble, offline, an `EpochInputs` (ENGINE_DESIGN §8):

| Field | Meaning | Check |
|---|---|---|
| `t0`, `t1` | `[t0, t1)`, `t1 - t0 == epoch.hours * 3600` | engine rejects a bad window |
| `slot_range` | inclusive recorded slot span | recorded in the artifact hash |
| `events` | **all** token events from launch through `t1` | see §4 missing events |
| `sol_transfers`, `fundings` | sybil evidence | |
| `prices` | 1-min (or sparse) SOL/whole-token series covering lookbacks | see §4 bad price feed |
| `decimals`, `sol_usd`, `pot_inflow` | ints / float as typed | inflow ≥ 0 |
| `excluded`, `hubs` | wallets left out; public hubs allowlist | `tests/test_hubs.py` |

Prices and events come from **recorded** fixtures or a prior read-only pull
committed as `data/MANIFEST.json`. Do not invent a feed at run time.

On current `main` there is no epoch CLI yet. Build `EpochInputs` in process
and call `engine.epoch.run_epoch` / `adapters.epoch_files.write_epoch`
(see `epochs/README.md`). Once PR #57 (`tools/run_epoch.py`) is merged:

```bash
uv run python tools/run_epoch.py tests/fixtures/run_epoch_two.json --out epochs --dry-run
uv run python tools/run_epoch.py PATH/TO/FIXTURE --out epochs
# resume from epochs/state.json; --dry-run writes nothing
```

Carry state between epochs via `epochs/<n>/state.json` (and, with the CLI,
`epochs/state.json`). Start epoch 0 from `empty_state()` or a seeded
`vesting` list. Do not hand-edit money fields.

### 3.3 Run and inspect

`run_epoch` returns `(EpochResult, EpochState)`. Write artifacts with
`adapters.epoch_files.write_epoch` (`epochs/<n>/{result.json,payouts.csv,tree.json,state.json,inputs_hash.txt}`).
A second write of identical bytes is a no-op; a changed overwrite is refused.

**Tests:** `tests/test_epoch_files.py` (round-trip, idempotent write, int money,
hash mismatch). Layout: `epochs/README.md`.

Inspect, at least:

```bash
# result.rail is push | merkle | none (COIN_MATH §13, push_max_eligible=500)
# result.review lists clusters that need a human look (sybil.review_cluster_size)
# result.inputs_hash must match epochs/<n>/inputs_hash.txt
# conservation is already asserted; if it raises, stop (see §4)
```

`rail=merkle` uses the D7 leaf (`engine.merkle`, jup-ag/distributor,
program `DiS3nNjFVMieMgmiQFm6wgJL7nevk4NrhXKLbtEH1Z2R`). That rail is
**valid only for a legacy SPL mint** (D7, #18). A Token-2022 mint must not
use this merkle program; v1 fallback is push (research report §5). Choosing
the mint program **needs kiwi APPROVED**.

Publishing a merkle root, funding a vault, or pushing payouts
**needs kiwi APPROVED**. This runbook stops at writing local artifacts.

### 3.4 Acceptance before any mainnet use (COIN_MATH §14)

```bash
uv run python -m sim.epoch_runner --seeds 10 --out reports/sim_epoch_e2e.md
uv run python -m sim.sweep --out reports/vesting_twap_sweep.md
```

`sim.epoch_runner` is the e2e gate: it exits non-zero if any row fails or
the run takes more than 60s. `--strict` on `sim.run` applies only to
`--scenario` runs, not to `--e2e` (the e2e path calls `epoch_runner` and
does not read `--strict`). Use `sim.epoch_runner` directly, or
`uv run python -m sim.run --e2e --seeds 10` without expecting `--strict`
to change the exit code.
**Tests:** `tests/test_epoch_runner.py`, `tests/test_sim_run.py`,
`tests/test_sim_acceptance.py`, `tests/test_vesting.py`.
Committed e2e report: `reports/sim_epoch_e2e.md`.

Do not change `config/coin.json` defaults because a sweep looked nicer
(propose only; a default change is a DECISIONS.md entry).

## 4. Failure modes

Each mode maps to a test, or is called out as a **gap**.

| Failure | What you see | What to do | Test / gap |
|---|---|---|---|
| Bad price feed (empty window, or gaps that leave `_twap` with no price) | `ValueError: twap: window has no price` | Stop. Restore a recorded series that covers `[t0, t1)` and lookbacks (1h lot cost, `unlock_twap_hours`, underwater 6h). Do not interpolate with the wall clock. | Formula: `tests/test_epoch.py::test_twap_dense_series_is_time_weighted_mean`. **Gap:** no dedicated operator fixture that starts from a broken feed file and asserts the CLI/adapter error (arrives with #51's missing-`prices` rejection). |
| Bad epoch window | `ValueError: t1-t0 must equal epoch.hours*3600` | Fix `t0`/`t1`. | `tests/test_epoch.py::test_rejects_bad_window_and_negative_pot` |
| Negative pot / inflow | `ValueError: pot and pot_inflow must be >= 0` | Do not run; inputs are corrupt. | same test as above |
| Missing events (ledger history truncated before `t1`) | Run may still succeed with wrong holders, lots, or TWAB. Conservation can still hold on a silently incomplete set. | Compare event counts and `inputs_hash` to the previous epoch and to `data/MANIFEST.json`. If counts drop unexpectedly, stop. | Determinism/hash: `tests/test_epoch.py::test_determinism_shuffled_events`. **Gap:** no test that an omitted historical BUY changes the hash *and* is flagged as "incomplete history" (the engine cannot know what it was not given). This is an operator check. |
| Conservation error | `ValueError: conservation failed: L != R` from `run_epoch` | **Stop. Do not write artifacts. Do not pay.** File a `type:redteam` issue with the fixture. | `tests/test_epoch.py::test_conservation_random_small_worlds`, `tests/test_epoch.py::test_golden_three_equal_holders`, `tests/test_epoch.py::test_push_carry_below_min_transfer_paid_next_epoch`; also asserted in `sim.epoch_runner.conservation_holds`. |
| Overwrite of a different `epochs/<n>/` | `FileExistsError: refusing to overwrite` | Keep the existing dir; investigate why inputs changed. Identical bytes are a no-op. | `tests/test_epoch_files.py::test_refuses_overwrite_with_different_content` |
| Artifact hash mismatch | `ValueError: inputs_hash.txt does not match result.json` on `read_epoch` | Treat the directory as corrupt. Re-run from inputs; do not edit files by hand. | `tests/test_epoch_files.py::test_incomplete_dir_and_hash_mismatch` |
| Soft-lock forfeit | cluster in `forfeit_until`, score 0 | Expected when a vested wallet (or its cluster) sells/transfers through the lock (D10). Confirm against `result.review` and vesting state. | `tests/test_epoch.py::test_soft_vesting_transfer_then_sell_forfeits_cluster` |
| Kill switch left off | `rail=none`, empty payouts, pot grew | Confirm `rewards.enabled` was intentional. Re-enabling payouts that would go on-chain **needs kiwi APPROVED**. | see §2 |
| Token-2022 mint + merkle rail | D7 program will not accept the mint | Do not publish a D7 tree. Use push or wait for a decided Token-2022 rail (#18). | Documented in `reports/research_token2022_claims_2026-11.md`. **Gap:** no engine test that refuses merkle when `pad.token_program` is `token2022` (`pad.json` is still unfilled). |

## 5. Offline go / no-go checklist

Tick every line before anyone talks about mainnet, a paid pad, or publishing
rules. Each item is either covered by a test cited here or marked **gap**.

| # | Check | Go if | Test / gap |
|---|---|---|---|
| 1 | CI quality gate | `ruff`, schema check, `pytest --cov-fail-under=90` green | `.github/workflows/ci.yml`; `tests/test_config.py::test_schema_files_up_to_date` |
| 2 | Unknown config keys rejected | `coin.json` / `pad.json` use `extra=forbid` | `tests/test_config.py::test_unknown_keys_rejected` |
| 3 | Live treasury mode cannot be committed | `treasury_bot.mode` is not `live` in the committed file | `tests/test_config.py::test_live_mode_cannot_be_committed` |
| 4 | Conservation | `run_epoch` cannot return a result that breaks the §8 identity | `tests/test_epoch.py::test_conservation_random_small_worlds` (see also §4) |
| 5 | Determinism | shuffled event order → same payouts and `inputs_hash` | `tests/test_epoch.py::test_determinism_shuffled_events`; merkle: `tests/test_merkle.py::test_claims_document_order_independent`. **Gap on main:** a committed 3-epoch golden replay is PR #58 (#52), not yet on `main`. |
| 6 | §14 e2e on `run_epoch` | `uv run python -m sim.epoch_runner --seeds 10` exits 0; committed report still matches | `tests/test_epoch_runner.py::test_e2e_ten_seeds_under_60s_and_committed_report`; `reports/sim_epoch_e2e.md` |
| 7 | §14 row: same-funder split | 50 wallets → one cluster; e2e `sybil_cluster` passes | `tests/test_sybil.py::test_fifty_wallets_same_funder_one_cluster`; e2e row `sybil_cluster` |
| 8 | §14 row: flipper 5×/day | score ≤ 10% of an equal holder | `tests/test_scoring.py::test_flipper_5x_per_day_for_48h_churn_at_most_tenth`; e2e row `flipper` |
| 9 | §14 row: 5-min sniper | ≤ 0.5% of a full-day weight (or ineligible) | `tests/test_twab.py::test_sniper_5min_weight_at_most_half_percent`; `tests/test_epoch.py::test_sniper_weight_at_most_half_percent`; e2e row `sniper` |
| 10 | §14 row: underwater farmer | boost ≤ 1.5× and a net loss | `tests/test_scoring.py::test_underwater_min_age_transfer_and_price_above_cost`; e2e row `underwater` |
| 11 | §14 row: 1h pump vs vesting TWAP | unlock change < 5% at default 24h (D14) | `tests/test_vesting.py::test_one_hour_3x_pump_on_6h_twap`, `tests/test_sim_run.py::test_sweep_k3_1h_24h_is_just_under_five_percent`; `reports/vesting_twap_sweep.md`. Margin is thin (4.97% vs 5%); D14 already notes 36h as the next lever. |
| 12 | §14 row: whale cap | every `π ≤ CAP`, conservation holds | `tests/test_rewards.py::test_whale_cap_water_filling_for_n_clusters`; e2e row `whale_cap` |
| 13 | §14 row: vested transfer-then-sell | forfeit on the cluster (D10 soft) | `tests/test_epoch.py::test_soft_vesting_transfer_then_sell_forfeits_cluster`; e2e row `vest_pump` |
| 14 | §14 row: volume −90% | seventh payout ≥ 45% of the first after zero inflow | `tests/test_rewards.py::test_zero_inflow_seventh_payout_at_least_45_percent_of_first` |
| 15 | §14 row: 6h sustained 2× pump cost ≥ unlock value | — | **Gap:** no dedicated e2e row yet (not in `reports/sim_epoch_e2e.md`). |
| 16 | §14 row: treasury bot quiet windows / 20 historical paths | — | **Gap:** `engine/treasury_bot.py` is present but has 0% coverage; no historical-path report. |
| 17 | Payout rail choice | N_eligible < `push_max_eligible` → push + carry; else merkle claims | `tests/test_epoch.py::test_push_carry_below_min_transfer_paid_next_epoch`, `tests/test_epoch.py::test_merkle_rail_when_eligible_reaches_push_max` |
| 18 | D7 leaf only for legacy SPL | merkle program is `Program<Token>` | Documented (#18, D7). **Gap:** no runtime guard tied to `pad.token_program`. |
| 19 | Kill switch works | `rewards.enabled=false` pays nothing | `tests/test_epoch.py::test_rewards_disabled_zero_payouts_pot_gains_inflow` (§2) |
| 20 | Failure modes in §4 have an operator action | conservation / overwrite / hash / window | `tests/test_epoch.py::test_conservation_random_small_worlds`; `tests/test_epoch_files.py::test_refuses_overwrite_with_different_content`; `tests/test_epoch_files.py::test_incomplete_dir_and_hash_mismatch`; `tests/test_epoch.py::test_rejects_bad_window_and_negative_pot`. Gaps for incomplete history and a broken-feed fixture are cited in §4. |
| 21 | Legal gate (COIN_MATH §16) | written opinion from kiwi's lawyers before `docs/PUBLIC_RULES.md` and before P7 | **needs kiwi** (issue #8). Not an engineering checkbox we can tick. |
| 22 | Mainnet / money | no payouts, vault funding, token creation, or public posts | **needs kiwi APPROVED** on a `needs:kiwi` issue. This runbook does not authorize those steps. |

**Go (offline):** items 1–14, 17, 19–20 are green, and every **gap** (15, 16, 18, and the feed/history gaps in §4) is either closed or explicitly accepted by Claude/kiwi in DECISIONS.md.

**No-go for launch / P7 / PUBLIC_RULES.md:** item 21 open, or any of 1–14 failing, or a conservation error, or a Token-2022 mint with a D7 merkle publish planned, or any mainnet action without kiwi APPROVED (item 22).

## 6. Out of scope

- Legal analysis (issue #8).
- Pad selection and filling `config/pad.json`.
- Reading or using kiwi's personal wallets, exchange accounts, or seeds.
- Publishing on X, Discord, or Telegram.

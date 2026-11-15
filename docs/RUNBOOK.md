# RUNBOOK — offline epoch procedure and launch-readiness (COIN_MATH v0.3.3)

Operator guide for the **offline** reward engine and for deciding whether the
system may go further. It sends no transactions, creates no tokens and touches
no wallets. Every step that would touch mainnet or money is marked
**needs kiwi APPROVED** (his own login, on the named issue) and is not done here.

Sources: `COIN_MATH.md` §13 / §14 / §16, `docs/ENGINE_DESIGN.md` §8,
`coord/DECISIONS.md` (D7, D10, D11, D16–D21). No real wallet or key appears here.

## 1. Rules for every run

- `engine/` does no I/O and never reads the clock. I/O lives in `adapters/`, `tools/`.
- Money is integers (Q base units, lamports). Payout path is exact (`Fraction`
  and ints, **no float**): floor payouts, largest remainder, ceil locks (D16).
  Guard: `tools/check_no_float.py`.
- Conservation is asserted inside `engine.epoch.run_epoch` and again by
  `tools/run_epoch.py` after the run.
- No mainnet writes, signatures, seed phrases. Devnet throwaway keys only, after kiwi APPROVED.
- Legal opinion (#8) is kiwi's (D11, §16). Engineering goes on; no `PUBLIC_RULES.md`
  and no P7 until the opinion exists.

## 2. Launch flags (COIN_MATH §16, D19)

| Feature | Flag in `config/coin.json` | At launch |
|---|---|---|
| Holder rewards (start rule, curve, cap, balances) | `rewards.enabled` | **true** |
| Draws (§9) | `draws.enabled` | **false** until ≥ 100 eligible clusters + VRF flow on devnet |
| Underwater boost (§5) | `underwater.enabled` | **false** until 7 clean epochs; `run_epoch` refuses `true` (not wired) |
| Treasury bot (§12) | `treasury_bot.enabled` / `mode` | **false** / `paper`; `live` needs kiwi `APPROVED` |
| Early-buy vesting (§11) | pad-dependent (`soft` only if kiwi OKs, D16) | off until decided |

**Tests:** `tests/test_config.py::test_launch_flags_default_off_section_16`,
`tests/test_config.py::test_live_mode_cannot_be_committed`,
`tests/test_epoch.py::test_underwater_boost_flag_is_refused_until_wired`.
Turning any flag on = DECISIONS.md entry + sim re-run (+ **needs kiwi APPROVED**
for draws, bot, LST, soft vesting).

## 3. Kill switch

Set `rewards.enabled` to `false` in `config/coin.json`, then re-run the epoch
from the last good `state.json`. Payouts are zero, the pot only grows by
`pot_inflow`, nothing is paid and no `pending` is lost (§13). Running balances
stay as they are.

**Tests:** `tests/test_epoch.py::test_rewards_disabled_zero_payouts_pot_gains_inflow`,
`tests/test_epoch.py::test_pending_never_expires_when_wallet_stops_being_eligible`.
Switching it back on **needs kiwi APPROVED** if any payout would leave the machine.

## 4. Per-epoch procedure (offline)

Work from a clean checkout of `main`. Nothing here writes to mainnet.

### 4.1 Pre-flight (same as CI)

```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run python tools/gen_schema.py --check
uv run python tools/check_no_float.py
uv run python tools/regen_golden.py --check
uv run pytest --cov=engine --cov-report=term --cov-fail-under=90
```

**Tests:** `tests/test_config.py::test_schema_files_up_to_date`,
`tests/test_check_no_float.py::test_repo_passes_the_ratchet`,
`tests/test_golden_v033.py::test_replay_is_byte_identical_to_goldens`,
`tests/test_config.py::test_committed_coin_json_equals_defaults`.
`config/pad.json` stays the unfilled template; filling it from a live pad
**needs kiwi APPROVED** (`tests/test_config.py::test_committed_pad_json_is_unfilled_template`).

### 4.2 Inputs

One fixture JSON (schema = `tools/run_epoch.py`, unknown keys rejected) with
`events`, `prices` (pool reserves, §11), `epochs[]` windows (`epoch`, `t0`, `t1`,
`slot_range`, `pot_inflow`), `total_supply`, `decimals`, `excluded`, `hubs`.
Each window is exactly 86,400 s and contiguous with the previous one
(`epochs[i].t0 == epochs[i-1].t1`). Events cover **launch through `t1`**,
including those before `t0` (ledger history). Prices and events come from a
**recorded** read-only pull, never invented at run time. Reading RPC for a
pull is read-only; anything else **needs kiwi APPROVED**.

**Tests:** `tests/test_run_epoch_cli.py::test_bad_fixture_rejected_with_clear_error`,
`tests/test_run_epoch_cli.py::test_events_before_t0_are_kept_as_ledger_history`.

### 4.3 Run

```bash
uv run python tools/run_epoch.py FIXTURE.json --out epochs --dry-run   # summary, writes nothing
uv run python tools/run_epoch.py FIXTURE.json --out epochs             # writes epochs/<n>/
uv run python tools/run_epoch.py FIXTURE.json --out epochs --epochs 1  # at most one pending epoch
```

State carries between runs in `epochs/state.json` (override with `--state`).
Do not hand-edit money fields. Exit 2 = input or engine rejection (stderr says
which); exit 0 = written. A second run with identical inputs is a no-op; a
changed overwrite is refused.

**Tests:** `tests/test_run_epoch_cli.py::test_two_epochs_one_call_writes_both_and_state`,
`tests/test_run_epoch_cli.py::test_state_carries_across_invocations_and_matches_single_run`,
`tests/test_run_epoch_cli.py::test_dry_run_writes_nothing`,
`tests/test_run_epoch_cli.py::test_rerun_is_idempotent_and_refuses_changed_artifacts`.

### 4.4 Inspect `epochs/<n>/`

Files: `result.json`, `payouts.csv`, `tree.json`, `state.json`, `balances.json`,
`inputs_hash.txt` (layout: `epochs/README.md`; canonical JSON, int money).
Check at least:

- `result.json`: `rail` (`push` | `merkle` | `none`), `review` (clusters
  ≥ `sybil.review_cluster_size` for a human look), `inputs_hash` equal to
  `inputs_hash.txt`.
- Budget is exactly `floor(alpha · pot)`; Σ payouts + rollover = `R_e`.
- `balances.json` (§13): per wallet `earned_total`, `paid_total`,
  `pending = earned_total − paid_total`. `pending` is paid only at
  `MIN_PAYOUT_Q` (`rewards.push_min_transfer_lamports`, default 1,000,000 = 0.001 SOL; never above the published
  maximum, 0.005 SOL), otherwise it stays and keeps growing. It never expires
  and is never taken back, even if the wallet stops being eligible.

**Tests:** `tests/test_exact_payout.py::test_property_conservation_and_bounds`,
`tests/test_exact_payout.py::test_epoch_budget_v033_is_floor_alpha_pot`,
`tests/test_epoch.py::test_push_carry_below_min_transfer_paid_next_epoch`,
`tests/test_epoch.py::test_min_payout_above_published_max_is_rejected`,
`tests/test_balances.py::test_pending_identity_and_threshold`,
`tests/test_balances.py::test_below_threshold_never_decreases_and_ineligibility_does_not_claw_back`,
`tests/test_epoch_files.py::test_balances_json_is_the_running_book`.

### 4.5 Rail (COIN_MATH §13)

- **< 500 eligible (`rewards.push_max_eligible`): push.** Direct transfer of
  `pending` to each wallet at or above `MIN_PAYOUT_Q`. Test:
  `tests/test_epoch.py::test_push_carry_below_min_transfer_paid_next_epoch`.
- **≥ 500: claims** through the existing audited merkle distributor (D7), leaf
  format unmodified. Unclaimed after 30 days is re-credited to the same wallet's
  `pending`; after 180 days with no claim it returns to the pot, logged.
  Tests: `tests/test_epoch.py::test_merkle_rail_when_eligible_reaches_push_max`,
  `tests/test_balances.py::test_thirty_day_recredit_and_one_hundred_eighty_day_pot_return`,
  `tests/test_merkle.py::test_vectors_match_upstream_byte_for_byte`,
  `tests/test_run_epoch_cli.py::test_merkle_rail_writes_tree_matching_claims_root`.
- The D7 program is **legacy SPL only** (#18). A Token-2022 mint must not use
  it; fallback is push. Choosing the mint program, publishing a root, funding a
  vault (wSOL fund, claim, unwrap, double-claim rejected, pull-back is only an
  assumption until the P5 devnet test) and every push transfer
  **need kiwi APPROVED**. This runbook stops at local artifacts.

### 4.6 Acceptance before any mainnet use (COIN_MATH §14)

```bash
uv run python -m sim.run --report --seeds 3 --out reports/sim_2026-11-14.md   # §14 table
uv run python -m sim.run --e2e --seeds 10                                      # full run_epoch e2e
```

Current committed result (`reports/sim_2026-11-14.md`, 3 seeds, default params):
**27 PASS · 0 FAIL · 19 GAP**. The GAPs are listed in the report: boost, draws
and bot are off (D19), ingest-layer rows (block-time clamp, two-RPC
disagreement) are outside `run_epoch`, and the rest are rows not written yet.
`--strict` fails while GAPs remain, so it is not the launch gate. A default
change is a DECISIONS.md entry, never a reaction to a nicer sweep.

**Tests:** `tests/test_acceptance_v033.py::test_every_row_passes_on_three_seeds`,
`tests/test_acceptance_attacks_v033.py::test_every_attack_row_passes_on_three_seeds`,
`tests/test_report_v033.py::test_every_row_and_gap_is_listed`,
`tests/test_epoch_runner.py::test_e2e_ten_seeds_under_60s_and_committed_report`.

## 5. Failure modes

| Failure | What you see | What to do | Test / gap |
|---|---|---|---|
| Bad price feed: `prices` missing | `prices: Field required` (exit 2) | Stop. Restore a recorded reserve series. Never interpolate with a clock. | `tests/test_run_epoch_cli.py::test_bad_fixture_rejected_with_clear_error` |
| Bad price feed: thin pool or window before first reserve (§11) | No error: the price unlock is **paused** for that minute; vested tokens stay locked | Expected and safe (locks, not payouts, are affected). Check the pool depth against `prices.d_trust_lamports` (2 SOL). | `tests/test_epoch.py::test_price_unlock_paused_on_untrusted_window`, `tests/test_prices_v033.py::test_untrusted_fraction_counts_only_untrusted_seconds`. **Gap:** no sim row for pool depth below trust (report GAP). |
| Bad price feed: manipulated pool | Pump inside a window | Bounded by the 24h harmonic mean: a 1h 3× pump moves unlock ≤ (24/23)× | `tests/test_vesting_v033.py::test_harmonic_mean_and_one_hour_3x_pump_bound` |
| Bad window | `t1-t0 must equal epoch.hours*3600`, or non-contiguous `epochs[i].t0` | Fix `t0`/`t1`. | `tests/test_epoch.py::test_rejects_bad_window_and_negative_pot`, `tests/test_epoch.py::test_epoch_length_other_than_one_day_is_rejected` |
| Negative pot / inflow | `pot and pot_inflow must be >= 0` | Inputs corrupt, do not run. | same as above |
| Missing events: duplicates, order | `duplicate event (slot, sig, ix)` rejected; order is canonical, so shuffled input gives the same result | Fix the pull. | `tests/test_run_epoch_cli.py::test_bad_fixture_rejected_with_clear_error`, `tests/test_epoch.py::test_determinism_shuffled_events`, `tests/test_events_v033.py::test_event_order_key_and_sort_events` |
| Missing events: history truncated before `t1` | Run **succeeds** with wrong holders, lots and TWAB; conservation still holds | Compare event count and `inputs_hash` with the previous epoch; §13 wants the event-log hash confirmed by two RPC sources. If counts drop, stop. | **Gap:** the engine cannot know what it was not given; two-source check and block-time clamping are ingest-layer (report GAPs). Operator check only. Clamp math: `tests/test_events_v033.py::test_clamp_block_times_examples`. |
| Conservation error | `conservation failed: L != R` | **Stop. Do not write artifacts, do not pay.** Open a `type:redteam` issue with the fixture. | `tests/test_epoch.py::test_conservation_random_small_worlds`, `tests/test_run_epoch_cli.py::test_conservation_check_catches_tampering`, `tests/test_balances.py::test_property_earned_minus_paid_minus_pot_is_conserved` |
| Overwrite with different content | `refusing to overwrite` | Keep the existing dir; find out why inputs changed. | `tests/test_epoch_files.py::test_refuses_overwrite_with_different_content` |
| Artifact hash mismatch | `inputs_hash.txt does not match result.json` | Directory is corrupt. Re-run from inputs; never edit by hand. | `tests/test_epoch_files.py::test_incomplete_dir_and_hash_mismatch` |
| Soft-vesting forfeit | cluster scored 0 for the breach epoch + 30 days | Expected after selling or moving locked tokens (D10, D18). Check `review` and vesting state. | `tests/test_epoch.py::test_run_epoch_breach_forfeits_cluster_and_fills_unlocked`, `tests/test_soft_vesting_v033.py::test_transfer_out_taints_the_moved_tokens` |
| Underwater boost set to true | `underwater.enabled: ... not wired` | Set it back to `false`. | `tests/test_epoch.py::test_underwater_boost_flag_is_refused_until_wired` |
| Kill switch left off | `rail=none`, empty payouts, pot grew | Confirm it was intentional (§3). | §3 tests |
| Token-2022 mint + D7 merkle | The program will not accept the mint | Do not publish a D7 tree; push, or wait for a decided rail (#18). | `reports/research_token2022_claims_2026-11.md`. **Gap:** no engine guard tied to `pad.token_program` (`pad.json` still unfilled). |

## 6. Offline go / no-go checklist

Tick every line before anyone talks about mainnet, a paid pad or publishing rules.

| # | Check | Go if | Test / gap |
|---|---|---|---|
| 1 | CI gate | ruff, schema check, pytest with coverage ≥ 90% green | `tests/test_config.py::test_schema_files_up_to_date` |
| 2 | Unknown config keys rejected | `extra=forbid` | `tests/test_config.py::test_unknown_keys_rejected` |
| 3 | Launch flags (§16) | draws, boost, bot off; `live` rejected | `tests/test_config.py::test_launch_flags_default_off_section_16`, `tests/test_config.py::test_live_mode_cannot_be_committed` |
| 4 | No float in the payout path | ratchet passes | `tests/test_check_no_float.py::test_repo_passes_the_ratchet` |
| 5 | Conservation and exact payout | Σ payouts + rollover = `R_e`; ceil/floor rules | `tests/test_exact_payout.py::test_property_conservation_and_bounds`, `tests/test_epoch.py::test_conservation_random_small_worlds` |
| 6 | Determinism | shuffled events and hash seed give identical bytes | `tests/test_epoch.py::test_determinism_shuffled_events`, `tests/test_golden_v033.py::test_replay_independent_of_hash_seed` |
| 7 | Golden 3-epoch replay | byte-identical to `tests/golden/v033/` | `tests/test_golden_v033.py::test_replay_is_byte_identical_to_goldens` |
| 8 | §14 table | 0 FAIL on the committed report; GAPs read and accepted | `tests/test_acceptance_v033.py::test_every_row_passes_on_three_seeds`, `tests/test_report_v033.py::test_every_row_and_gap_is_listed` |
| 9 | §14 e2e on `run_epoch` | `sim.run --e2e --seeds 10` exits 0 | `tests/test_epoch_runner.py::test_e2e_ten_seeds_under_60s_and_committed_report` |
| 10 | Start rule and curve | score 0 below `T_START` (6h, D21); h monotone, ≤ 2.8× | `tests/test_epoch.py::test_sniper_lot_under_t_start_scores_zero`, `tests/test_hold_curve.py::test_knot_table_and_t_start_discontinuity` |
| 11 | Eligibility by supply share | price-free, dust below 1/1,000,000 out | `tests/test_eligibility.py::test_is_eligible_is_price_free_and_inclusive` |
| 12 | Whale cap 5% and no gain from splitting | π ≤ cap, split ≤ single | `tests/test_rewards_v033.py::test_cap_and_uplift_bounds`, `tests/test_score_lots.py::test_splitting_a_lot_does_not_change_score` |
| 13 | Sybil: same funder is one cluster; dust and partial funding do not merge | | `tests/test_sybil_strong_v033.py::test_s2_farm_funded_by_one_wallet_lands_in_the_funders_cluster`, `tests/test_sybil_strong_v033.py::test_s2_dust_and_partial_funding_do_not_merge` |
| 14 | Sybil: one-sided links never merge | | `tests/test_sybil_links_v033.py::test_one_sided_links_never_merge_without_l1_or_l2` |
| 15 | Soft vesting: forfeit on sell or transfer; price unlock needs 24h and a trusted window | | `tests/test_soft_vesting_v033.py::test_selling_below_locked_forfeits_and_selling_unlocked_part_does_not`, `tests/test_soft_vesting_v033.py::test_price_unlock_needs_24h_and_a_trusted_window` |
| 16 | Pump ≤ 1h on the harmonic mean | unlock ≤ (24/23)× | `tests/test_vesting_v033.py::test_harmonic_mean_and_one_hour_3x_pump_bound` |
| 17 | Running balances (§13) | pending never decreases; 30d re-credit; 180d to pot | `tests/test_balances.py::test_below_threshold_never_decreases_and_ineligibility_does_not_claw_back`, `tests/test_balances.py::test_thirty_day_recredit_and_one_hundred_eighty_day_pot_return` |
| 18 | Rail choice | < 500 push, else merkle | `tests/test_epoch.py::test_merkle_rail_when_eligible_reaches_push_max` |
| 19 | Kill switch | `rewards.enabled=false` pays nothing | `tests/test_epoch.py::test_rewards_disabled_zero_payouts_pot_gains_inflow` |
| 20 | Underwater boost, draws, bot | boost refused until wired; draws off | `tests/test_epoch.py::test_underwater_boost_flag_is_refused_until_wired`. **Gap:** §14 rows for boost, draw fairness (χ²) and bot backtest are not written (report GAPs, off by D19). |
| 21 | Ingest checks | two-RPC event-hash agreement, block-time clamp, pool-depth row | **Gap:** ingest layer, outside `run_epoch`; operator check (§5). |
| 22 | D7 only for legacy SPL | | **Gap:** no runtime guard (§5). |
| 23 | Legal gate (§16) | written opinion before `PUBLIC_RULES.md` and P7 | **needs kiwi** (#8). Not an engineering box. |
| 24 | Mainnet / money | no payouts, vault funding, token creation, posts | **needs kiwi APPROVED** per action. Not authorized by this runbook. |

**Go (offline):** items 1–19 green, and every Gap (20–22) closed or accepted
in DECISIONS.md by Claude and kiwi.
**No-go:** item 23 open, any of 1–19 failing, a conservation error, a
Token-2022 mint with a D7 publish planned, or any mainnet action without
kiwi's `APPROVED` (item 24).

## 7. Out of scope

Legal analysis (#8); pad selection and filling `config/pad.json`; kiwi's
personal wallets, exchange accounts or seeds; posting on X, Discord or Telegram.

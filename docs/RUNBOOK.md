# RUNBOOK — offline epoch procedure and launch readiness

Operator guide for the **offline** reward engine (COIN_MATH **v0.3.3**) and for
deciding whether the system is ready to go further. It does not send
transactions, create tokens, fund vaults or touch wallets. Any step that would
touch mainnet or money is marked **needs kiwi APPROVED** and is not done here.

Sources: `COIN_MATH.md` §0, §2–§9, §11, §13, §14, §16; `docs/ENGINE_DESIGN.md`
§8; `coord/DECISIONS.md` (D7, D10, D16–D21). `reports/sim_2026-11-15.md` is the
committed v0.3.3 §14 report.

No real wallet, key or seed addresses appear in this document. Public program
ids live in `coord/DECISIONS.md`, not here.

---

## 1. Hard rules (every run)

- **Payout path is exact.** Sections 1–9, 11 and 13 use integers and
  `fractions.Fraction` only: no floats, `ln`, `exp` or non-integer `sqrt`
  (COIN_MATH §0, D16). `tests/test_check_no_float.py` is the ratchet.
- **Rounding only at the end.** §6 payouts are floored per cluster and wallet,
  leftovers by largest remainder. Only the §11 fixed-point harmonic mean rounds
  earlier, and it can only round *down* (D20).
- **Conservation is absolute.** `run_epoch` raises on
  `prev.pot + inflow + Σ prev.carry == pot_next + Σ transferred_or_claimable + Σ next.carry`.
  Never write artifacts when it raises.
- **No mainnet writes, no keys.** No signatures, seed phrases, token creation,
  vault funding or payouts. Read-only mainnet RPC is allowed; devnet throwaways
  only after kiwi APPROVED a named `needs:kiwi` issue.
- **Launch flags stay as §16 / D19:** rewards **on**, underwater boost **off**,
  draws **off** (fee share routes to the holder pot), LST **0**, treasury bot
  **off** in `paper` mode. `underwater.enabled=true` makes `run_epoch` raise.
- **Legal (#8) is kiwi's.** `docs/PUBLIC_RULES.md` and P7 wait for his lawyers.

## 2. Kill switch

Holder payouts are gated by `rewards.enabled` in `config/coin.json` (§16, D19).

1. Set `"rewards": {"enabled": false, ...}` in `config/coin.json`.
2. Re-run the epoch from the last good `epochs/state.json` (§3.2–§3.3).
3. Expect `result.rail == "none"`, empty payouts, `pot_next == pot_prev + inflow`
   and the pending book unchanged. Nothing is burned or clawed back.
4. Record why the switch was used in the run log before re-enabling it.

The same flag is `engine.params.RewardParams.enabled`. A low `pot` is not a
kill switch: `R_e = floor(α·Pot_e)` is skipped below
`rewards.min_epoch_payout_lamports`. `draws.enabled` is the separate draw
switch (**false** at launch); the treasury bot is gated by
`treasury_bot.enabled` (false; `live` is rejected by the config model).

**Tests:** `tests/test_epoch.py::test_rewards_disabled_zero_payouts_pot_gains_inflow`
and the `rewards_disabled` row of `uv run python -m sim.epoch_runner`.

Re-enabling payouts that would leave the machine (push transfer or merkle
vault) **needs kiwi APPROVED**. Offline re-enable against local artifacts does
not.

## 3. Per-epoch operator procedure (offline)

Work from a clean checkout of the reviewed commit. `epochs/` is gitignored
except `epochs/README.md`. Inputs come from recorded fixtures or a prior
read-only pull; never invent a feed at run time.

### 3.1 Pre-flight

```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run python tools/gen_schema.py --check
uv run pytest --cov=engine --cov-report=term --cov-fail-under=90
```

Expected: clean, schema current, tests green, engine coverage ≥ 90% (CI gate
in `.github/workflows/ci.yml`). Confirm the committed `config/coin.json` is
the params you intend and `config/pad.json` is still the unfilled template.
Filling `pad.json` from a live pad **needs kiwi APPROVED**.

**Tests:** `tests/test_config.py::test_committed_coin_json_equals_defaults`,
`tests/test_config.py::test_committed_pad_json_is_unfilled_template`,
`tests/test_config.py::test_schema_files_up_to_date`.

### 3.2 Inputs and run

`tools/run_epoch.py` validates a strict JSON `Fixture` (unknown keys rejected)
and runs every window after the carried state. History is shared: each window
sees rows with `ts < t1`, so events before `t0` are still ledger history.

```bash
# summary only: writes no artifacts
uv run python tools/run_epoch.py tests/fixtures/run_epoch_two.json --out epochs --dry-run

# write epochs/<n>/ artifacts (result, payouts, tree, state, balances, hash)
uv run python tools/run_epoch.py PATH/TO/FIXTURE --out epochs
```

Input checklist:

| Field | Meaning | Check |
|---|---|---|
| `t0`, `t1` | `[t0, t1)`, exactly `epoch.hours * 3600` (24h) | engine rejects any other length |
| `slot_range` | inclusive recorded slot span | must ascend; recorded in `inputs_hash` |
| `events` | **all** token events from launch through `t1` | see §4 missing events |
| `sol_transfers`, `fundings` | sybil evidence (§7) | in the CLI fixture; excluded from `inputs_hash` |
| `signers`, `overrides` | S1 co-signers / S3 manual merges (§7) | in-process `EpochInputs` only; **gap:** no CLI fixture fields |
| `reserves` | §0 pool reserves for the §11 price unlock | trusted seconds only; `()` = unlock paused |
| `total_supply` | token base units, > 0 | eligibility floor; **not** in `inputs_hash` |
| `prices` | legacy swap prints; not read by `run_epoch` v0.3.3 | not a payout input |
| `pot_inflow`, `decimals`, `sol_usd` | ints / display only | inflow ≥ 0; USD never enters a formula |
| `excluded`, `hubs` | excluded accounts; public hubs allowlist | excluded from `inputs_hash` |

`p_entry` (seeded vesting) is an exact positive rational in Q base units per
token base unit; prefer `"num/den"` strings. State carries through
`epochs/state.json`; start epoch 0 from `empty_state()` or `fixture.vesting`.

### 3.3 Inspect artifacts

`write_epoch` writes `epochs/<n>/`:

- `result.json` (canonical `EpochResult`, int money), `payouts.csv` (sorted
  `wallet,amount`), `tree.json` (root/layers, `root: null` without a tree).
- `state.json` (pot, pending `carry`, `paid_total`, `forfeit_until`,
  `unlocked`, `vesting`), `balances.json` (§13 `earned_total`/`paid_total`/
  `pending`), `inputs_hash.txt` (hex from the result).

Check at least:

```bash
# rail is push | merkle | none; review lists clusters needing a human look
# result.inputs_hash must equal inputs_hash.txt
# Σ payouts + rollover == R_e and Σ transferred_or_claimable is the paid total
```

`inputs_hash` covers `slot_range`, params, counts and the sorted event log. It
does **not** cover `total_supply`, `reserves`, `excluded`, `hubs`, `signers` or
`overrides`; compare those to the previous epoch yourself.

**§13 rails.** Below `rewards.push_max_eligible` (500) the rail is `push`: each
wallet whose pending reaches `push_min_transfer_lamports` (0.001 SOL) is paid;
smaller amounts stay in `pending` and never expire. At or above 500 the rail is
`merkle`: one leaf per due wallet, version = epoch. The §13 30/180-day
pull-back rules are specified and unit-tested but not yet carried in
`EpochState` (§4 gap). Publishing a root, funding a vault or pushing payouts
**needs kiwi APPROVED**.

`rail=merkle` uses the D7 jup-ag/distributor leaf, valid **only for a legacy
SPL mint**. A Token-2022 mint must not use it; v1 fallback is push (research
report §5). Choosing the mint program **needs kiwi APPROVED**.

**Token-2022 push plans (`adapters/token2022.py`).** `plan_payouts(payouts, mint,
epoch=...)` returns `gross`/`fee`/`received` and the ATA per wallet. Record
`received` (what the chain credits) and fund the gross; fee =
`ceil(gross · bps / 10 000)` capped at `maximum_fee`. Tests: `tests/test_token2022_payout.py`.

**Tests:** `tests/test_epoch_files.py::test_round_trip`,
`tests/test_epoch_files.py::test_balances_json_is_the_running_book`,
`tests/test_epoch_files.py::test_byte_identical_on_repeat_and_shuffled_order`,
`tests/test_run_epoch_cli.py::test_state_carries_across_invocations_and_matches_single_run`,
`tests/test_run_epoch_cli.py::test_rerun_is_idempotent_and_refuses_changed_artifacts`,
`tests/test_golden_v033.py::test_replay_is_byte_identical_to_goldens`.

### 3.4 Acceptance before any mainnet use (COIN_MATH §14)

```bash
uv run python -m sim.run --acceptance --seeds 20
uv run python -m sim.epoch_runner --seeds 10
uv run python -m sim.run --report --seeds 3
uv run python -m sim.run --report --seeds 3 --strict   # also fails on any GAP
```

- `sim.run --acceptance` runs the 33 implemented §14 rows on the real engine
  (score/payout, attack, the #133 offline rows and the #136 arbitrage rows).
- `sim.epoch_runner` is the e2e gate on `run_epoch`; it exits non-zero on a
  failed row or a run over 60 s. `--strict` on `sim.run` applies to `--report` and
  `--scenario` only: `--e2e` and `--acceptance` return before `strict` is read.
- `sim.run --report` writes `reports/sim_<date>.md` with PASS/FAIL/GAP and the
  §14 outputs (slow, ~3–4 min for 3 seeds). `--strict` exits 1 while any GAP
  remains; that is expected and must be accepted in `coord/DECISIONS.md`.
- Committed report: `reports/sim_2026-11-15.md` — **38 PASS · 0 FAIL · 9 GAP**.

Do not change `config/coin.json` defaults because a sweep looked nicer. A
default change needs a DECISIONS.md entry with the failing §14 evidence.

**Tests:** `tests/test_acceptance_v033.py::test_every_row_passes_on_three_seeds`,
`tests/test_acceptance_attacks_v033.py::test_every_attack_row_passes_on_three_seeds`,
`tests/test_epoch_runner.py::test_e2e_ten_seeds_under_60s_and_committed_report`,
`tests/test_report_v033.py::test_every_row_and_gap_is_listed`.

## 4. Failure modes

Each mode maps to a test, or is called out as a **gap**.

| Failure | What you see | What to do | Test / gap |
|---|---|---|---|
| Bad/empty price feed or untrusted reserves | v0.3.3 base rewards are price-free, so no `twap` crash. `u_price` is skipped when the 24h window has an untrusted or missing second; `unlocked` stays at `u_time` | Confirm `reserves` cover the window and check `state.unlocked`. A skipped price unlock is not a breach. Keep `underwater.enabled=false` | `tests/test_prices_v033.py::test_harmonic_oracle_empty_and_bad_window`; `tests/test_epoch.py::test_price_unlock_paused_on_untrusted_window`; `tests/test_soft_vesting_v033.py::test_price_unlock_needs_24h_and_a_trusted_window`. **Gap:** no operator report of the untrusted-seconds fraction and no malformed-reserve fixture. |
| Missing events (history truncated before `t1`) | Run may succeed with wrong holders, lots or TWAB; conservation can still hold on a silently incomplete set | Compare event counts and `inputs_hash` to the previous epoch and `data/MANIFEST.json`. If counts drop, stop | `tests/test_epoch.py::test_determinism_shuffled_events`; `tests/test_run_epoch_cli.py::test_events_before_t0_are_kept_as_ledger_history`. **Gap:** no detector can know what it was never given; this is an operator check. |
| Conservation error | `ValueError: conservation failed: L != R` from `run_epoch`, or `AssertionError: epoch n: conservation failed` from the CLI re-check | **Stop. Do not write artifacts. Do not pay.** File a `type:redteam` issue with the fixture | `tests/test_epoch.py::test_conservation_random_small_worlds`; `tests/test_epoch.py::test_golden_three_equal_holders`; `tests/test_run_epoch_cli.py::test_conservation_check_catches_tampering` |
| Bad epoch window, negative pot, bad supply | `t1-t0 must equal epoch.hours*3600`; `pot and pot_inflow must be >= 0`; `epoch.hours must be 24`; `total_supply must be > 0` | Fix the fixture/state. Do not run | `tests/test_epoch.py::test_rejects_bad_window_and_negative_pot`; `tests/test_epoch.py::test_epoch_length_other_than_one_day_is_rejected`; `tests/test_epoch.py::test_total_supply_is_required_and_positive` |
| Overwrite of a different `epochs/<n>/` | `FileExistsError: refusing to overwrite … with different content` | Keep the existing directory; investigate why inputs changed. Identical bytes are a no-op | `tests/test_epoch_files.py::test_refuses_overwrite_with_different_content` |
| Artifact hash mismatch / incomplete dir | `ValueError: inputs_hash.txt does not match result.json` | Treat the directory as corrupt. Re-run from inputs; never hand-edit money | `tests/test_epoch_files.py::test_incomplete_dir_and_hash_mismatch` |
| Soft-lock forfeit | cluster in `forfeit_until`, score 0; tainted lots score 0 until `tainted_until` | Expected when a vested wallet sells or transfers through the lock (D10). Confirm against `result.review` and vesting state | `tests/test_epoch.py::test_soft_vesting_transfer_then_sell_forfeits_cluster`; `tests/test_soft_vesting_v033.py::test_transfer_out_taints_the_moved_tokens` |
| Pending book wrong or pull-back missing | `pending = earned_total - paid_total`; a 30-day unclaimed amount should be re-credited and a 180-day one returned to the pot | Rebuild from `state.json`; never lower `pending` by hand. Escrow carry is **not yet** in `EpochState` | `tests/test_balances.py::test_pending_identity_and_threshold`; `tests/test_balances.py::test_thirty_day_recredit_and_one_hundred_eighty_day_pot_return`. **Gap:** `run_epoch` has a TODO for 30/180-day escrow carry, so the rules are unit-tested but not yet applied by the epoch loop. |
| Kill switch left off | `rail=none`, empty payouts, pot grew | Confirm `rewards.enabled` was intentional (§2). Re-enabling an on-chain payout **needs kiwi APPROVED** | `tests/test_epoch.py::test_rewards_disabled_zero_payouts_pot_gains_inflow` |
| Launch flag accidentally on | `underwater.enabled` raises; `draws.enabled` changes fee routing; `treasury_bot.enabled` has no payout effect yet | Set §16/D19 defaults. Any enable needs the §16 trigger and, for `live`, kiwi APPROVED | `tests/test_config.py::test_launch_flags_default_off_section_16`; `tests/test_epoch.py::test_underwater_boost_flag_is_refused_until_wired` |
| Bad fixture / `p_entry` | CLI exit 2 with a field-level message | Fix the JSON; prefer exact `"num/den"` | `tests/test_run_epoch_cli.py::test_bad_fixture_rejected_with_clear_error`; `tests/test_epoch.py::test_vesting_entry_p_entry_is_exact` |
| Token-2022 mint + merkle rail | D7 program will not accept the mint | Do not publish a D7 tree. Use push or wait for the Token-2022 rail (#18) | Documented in `reports/research_token2022_claims_2026-11.md`. **Gap:** no runtime guard tied to `pad.token_program`. |

## 5. Offline go / no-go checklist

Tick every line before anyone talks about mainnet, a paid pad or publishing
rules. Each item maps to a test or an explicit **gap**.

### 5.1 Operational gates

| # | Check | Go if | Test / gap |
|---|---|---|---|
| 1 | CI quality gate | ruff, format, schema check and `pytest --cov-fail-under=90` green | `.github/workflows/ci.yml`; `tests/test_config.py::test_schema_files_up_to_date` |
| 2 | No float in the payout path | ratchet reports zero violations, empty baseline | `tests/test_check_no_float.py::test_repo_passes_the_ratchet` |
| 3 | Unknown config keys rejected | `coin.json` / `pad.json` use `extra=forbid` | `tests/test_config.py::test_unknown_keys_rejected` |
| 4 | §16/D19 launch flags | rewards on; boost, draws, LST and bot off; bot `paper` | `tests/test_config.py::test_launch_flags_default_off_section_16` |
| 5 | Live treasury mode cannot be committed | `treasury_bot.mode` is never `live` | `tests/test_config.py::test_live_mode_cannot_be_committed` |
| 6 | Conservation | no result can break the §8 identity | `tests/test_epoch.py::test_conservation_random_small_worlds` |
| 7 | Determinism | shuffled events give identical payouts and artifacts | `tests/test_epoch.py::test_determinism_shuffled_events`; `tests/test_epoch_files.py::test_byte_identical_on_repeat_and_shuffled_order` |
| 8 | Golden replay | v0.3.3 goldens are byte-identical | `tests/test_golden_v033.py::test_replay_is_byte_identical_to_goldens` |
| 9 | Exact integer payout | `Σ payouts + rollover == R_e`; wallet split sums to the cluster payout | `tests/test_exact_payout.py::test_ten_equal_clusters_pay_half_and_roll_half`; `tests/test_acceptance_v033.py::test_every_row_passes_on_three_seeds` |
| 10 | Harmonic-mean vesting | 1h 3× pump adds no unlock beyond `u_time`; untrusted window pauses price unlock | `tests/test_vesting_v033.py::test_harmonic_mean_and_one_hour_3x_pump_bound`; `tests/test_soft_vesting_v033.py::test_price_unlock_needs_24h_and_a_trusted_window` |
| 11 | §13 pending never lost | pending monotone, paid at `MIN_PAYOUT_Q`, ineligibility does not claw back | `tests/test_balances.py::test_pending_identity_and_threshold`; `tests/test_epoch.py::test_pending_never_expires_when_wallet_stops_being_eligible` |
| 12 | Push rail and carry | sub-threshold pending is carried, never dropped | `tests/test_epoch.py::test_push_carry_below_min_transfer_paid_next_epoch` |
| 13 | Merkle rail | claims document and rebuilt tree match above 500 eligible | `tests/test_epoch.py::test_merkle_rail_when_eligible_reaches_push_max`; `tests/test_run_epoch_cli.py::test_merkle_rail_writes_tree_matching_claims_root` |
| 14 | Kill switch | `rewards.enabled=false` pays nothing and keeps the pot | `tests/test_epoch.py::test_rewards_disabled_zero_payouts_pot_gains_inflow` |
| 15 | Full-epoch e2e | `sim.epoch_runner --seeds 10` exits 0 under 60 s | `tests/test_epoch_runner.py::test_e2e_ten_seeds_under_60s_and_committed_report` |
| 16 | §14 report | every row listed as PASS/FAIL/GAP; committed report matches | `tests/test_report_v033.py::test_every_row_and_gap_is_listed` |
| 17 | Artifact contract | round-trip, int money, hash file, balances book | `tests/test_epoch_files.py::test_round_trip`; `tests/test_epoch_files.py::test_balances_json_is_the_running_book` |
| 18 | Operator CLI | state carries across calls; rerun refuses changed bytes | `tests/test_run_epoch_cli.py::test_state_carries_across_invocations_and_matches_single_run`; `tests/test_run_epoch_cli.py::test_rerun_is_idempotent_and_refuses_changed_artifacts` |
| 19 | D7 merkle only for legacy SPL | merkle publish is impossible on a Token-2022 mint | **Gap:** no runtime guard tied to `pad.token_program` (#18, D7); needs review before any publish |
| 20 | Legal gate (§16) | written opinion before `PUBLIC_RULES.md` and P7 | **Gap:** no engineering test; needs kiwi (#8) and his lawyers |
| 21 | Mainnet / money | no payout, vault, token creation or public post without approval | **Gap:** no on-chain test in this repo; needs kiwi APPROVED on a `needs:kiwi` issue |
| 22 | Docs contain no real addresses | only public identifiers; this file scans clean | `tests/test_runbook.py::test_runbook_has_no_wallet_addresses` |

### 5.2 COIN_MATH §14 acceptance rows

Status from `reports/sim_2026-11-15.md` (3 seeds per row unless noted).
Targeted tests may cover a row more than once.

| §14 rows (all PASS) | Condition | Covered by |
|---|---|---|
| Holding time 7d/30d/60d/90d; Scalper churning < 2h | score strictly rises then flattens; churn scores 0 | `tests/test_acceptance_v033.py::test_every_row_passes_on_three_seeds` |
| Snapshot sniper; Partial sale | 0 below `T_START`; sold lots leave newest first | `tests/test_acceptance_v033.py::test_every_row_passes_on_three_seeds` |
| New buy on an old bag; Transfer to another owner | old lots unchanged; receiver age resets | `tests/test_acceptance_v033.py::test_every_row_passes_on_three_seeds` |
| Whale cap, 10 clusters; S = 0; Exact payout; Multiplier bounds | π ≤ 5%, ≤ 2× proportional; Σ payouts + rollover == R_e; < 6h → 0, ≤ 2.8× | `tests/test_acceptance_v033.py::test_every_row_passes_on_three_seeds` |
| Small balance below MIN_PAYOUT_Q; Any split, 2–10 wallets, boost off; €100 holder at $50k..$50M | pending monotone; split never gains; always eligible | `tests/test_acceptance_v033.py::test_every_row_passes_on_three_seeds` |
| Whale splits into 50 funded wallets; Dust attack (tokens + SOL); Forced merge, free actions; Forced merge, funding; Chain A–B co-signed, B–C, C–D | one cluster, no gain; victim not merged; only A–B merged | `tests/test_acceptance_attacks_v033.py::test_every_attack_row_passes_on_three_seeds` |
| Soft vesting: selling locked tokens; Soft vesting: out via 3 wallets; Circular transfers A→B→C→A; Whole bag to a new funded wallet; Pump ≤ 1h, random histories | forfeit/taint applied; no gain; age/cost kept; P̃_h ≤ (24/23)·H_rest | `tests/test_acceptance_attacks_v033.py::test_every_attack_row_passes_on_three_seeds` |
| Buy and sell in the same second; Pool depth below the trust threshold; Missing / decreasing block time, skipped slots | intra-second states weight 0 and p(t) is the end-of-second price; thin pool reads no untrusted price and changes no payout; the clamped clock equals the clean log | `tests/test_gap_rows_v033.py::test_every_gap_row_passes_on_three_seeds` |
| Same fee-paying app + one-sided signals; Single commercial transfer; False merge of two independent clusters | no merge, payer in the review list; one transfer is not an edge; a forced merge leaves the tokens' score unchanged and cap damage 0 | `tests/test_gap_rows_v033.py::test_every_gap_row_passes_on_three_seeds` |
| Sybil recall (self-funded / CEX-funded); Retroactive merge | self-funded farms ≥ 95% grouped, CEX-funded residual reported; past epochs unchanged, current epoch equals a from-genesis rebuild | `tests/test_gap_rows_v033.py::test_every_gap_row_passes_on_three_seeds` |
| Dump, then 6h with no trades (arbitrage agents present); Pump, then 24h with no trades (arbitrage agents present) | arbitrage agents restore the pool mid to the external reference; attacker's net PnL < 0 on 20 seeds (price-fixed round trip, dump and pump) | `tests/test_arbitrage_v033.py::test_arbitrage_rows_pass_on_twenty_seeds` |
| Trader in 4h cycles vs a 7-day holder; Reward concentration; Reward stability (first target); Volume −90% overnight; Higher multiplier vs. concentration | ≤ 30% reward rate; top-10% not rising; ±10% moves ≤ 15%; ≥ 45% after 7 days; 2.8× curve ≤ 2.0× + 5 points | `tests/test_report_v033.py::test_every_row_and_gap_is_listed` |

**GAP rows (9).** They are explicit, not silently skipped. A gap may be
accepted only by a DECISIONS.md entry or closed by a later issue. Category
**a** = off at launch by a D19/§16 flag; **b** = offline-able but not written, or
it needs a component that does not exist yet.

| §14 row | Category | Why it is still a gap |
|---|---|---|
| Same split, boost on | a | underwater boost off at launch (D19); `run_epoch` rejects it |
| Underwater farmer | a | boost off (D19) |
| Holding the pool lower for ≤ 1h (P̄_e) | a | P̄_e feeds only the boost, off (D19) |
| Two RPC sources disagree | b | needs the P4 adapter's dual-source client; the engine has no single-source finalize path |
| Draw payout / draw fairness (χ²) | a | draws off at launch (D19); sampler unit-tested |
| Multiplier ≤ 4.2× with boost | a | boost off (D19) |
| Informed agent vs. simple holder | b | needs an optimising agent; a strategy search over the curve is not an offline fixture |
| Independent implementation | b | separate Rust/TS deliverable outside this repo (COIN_MATH §14), not a sim row |
| Treasury bot backtest | a | bot off at launch (D19); needs real price paths |

### 5.3 Verdict

**Offline go:** operational items 1–18 green, every §14 PASS row still PASS in
`sim.run --report`, and no unaccepted gap in §5.2.

**No-go for launch / P7 / `PUBLIC_RULES.md`:** any PASS row failing, a
conservation error, item 19 (Token-2022 merkle guard), item 20 (legal) or item
21 (mainnet approval) unresolved, or a §14 GAP accepted without a
DECISIONS.md entry.

## 6. Out of scope

- Legal analysis (issue #8).
- Pad selection and filling `config/pad.json`.
- Reading or using kiwi's personal wallets, exchange accounts or seeds.
- Publishing on X, Discord or Telegram.

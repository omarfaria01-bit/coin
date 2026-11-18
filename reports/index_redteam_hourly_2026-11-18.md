# Red team replay under the hourly schedule (#189, slice 1)

Update of the #162 table (`reports/index_redteam_2026-11-18.md`) for D26-D28: hourly rebalance
with hysteresis (enter 8 / exit 12), 1h wait curve (T_START 3600 s, 5x at 4h), hourly draw
(5% cap, min pot 0.01 SOL, rollover). Offline; tests in `tests/test_index_hourly_attacks.py`,
metrics from `reports/index_redteam_replay.py`.

| Attack | Still works? | Stopped by | Test | Rule issue |
|---|---|---|---|---|
| Low-float / thin-liquidity MC inflation | No, blocked at 6 consecutive hourly rebalances | F11 | `test_lowfloat_blocked_at_every_hourly_rebalance` | #167 (done) |
| Wash volume, 250 one-shot wallets | Fake traders: No (F9 needs 200 independent traders). Round-trip wash volume by few wallets: YES, still works since D35 removed the round-trip cleanup (F10 = volume > 0) | F9 only | `test_wash_volume_and_fake_traders_blocked_every_hour`, `test_round_trip_wash_is_not_filtered_after_d35` | #170 (superseded by D35; accepted risk by kiwi 18 Nov 08:22, weights now use raw volume at 50%) |
| Rank noise to churn the basket | No: incumbent stays until rank > 12, newcomer needs rank <= 8 | hysteresis | `test_hysteresis_*`, `test_select_members_size_and_membership_props` | - |
| Flash buy inside the first hour | Scores 0 | T_START = 1h | `test_curve_*`, `test_in_and_out_inside_first_hour...` | - |
| Whale / split wallets in the hourly draw | Bounded at 5% odds per cluster; pot conserved (prizes + rollover = pot) | cap, sqrt odds, min pot | `test_draw_conserves_pot`, `test_splitting_one_score...` | needs linked-wallet merge upstream (#169 F3/F6/F7 open) |
| Pot below 0.01 SOL | Rolls over, no draw | min pot | `test_below_min_pot_rolls_over_and_conserves` | - |

## Not covered yet (gaps, not fixed here)
- Prize-basket sandwich around the hourly buy with the 3% cap: needs a price-impact model; belongs
  to #172 (mainnet buy design, needs kiwi).
- Cluster-aware sybil (first-funder) scenarios: collector not built (#169).
- Cost column per scenario: use the cost model in the #162 report; not recomputed.

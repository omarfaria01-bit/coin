# Full-epoch parameter sensitivity (cap, alpha, H, M)

OFAT sweeps of `scoring.cap`, `rewards.alpha_per_day`, `hold.horizon_days`
(H), and `vesting.m` (M) on `sim.epoch_runner` §14 rows. Grid midpoints are
the current defaults. **Defaults are not changed**; proposals stay here.

Reproduce:

    uv run python -m sim.sensitivity --seeds 5 --out reports/epoch_sensitivity.md

Seeds: 5. Wall time: 0.92s. Grids: cap [0.03, 0.05, 0.10]; alpha [0.05, 0.10, 0.20]; H [14, 30, 60]; M [3, 5, 8].

Margin is the worst-seed relative slack of the row's tightest numeric
inequality. **FLAG** = any seed failed or min margin < 20%, except
cap-binding rows (equal holders, whale, sybil) whose slack is 0 by
construction; those are marked `cap-binds`. Binary rows report margin 1
when they pass.

## scoring.cap (default 0.05)

| value | scenario | result | min margin | flag | evidence |
|---|---|---|---|---|---|
| 0.03 | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[3000000000, 3000000000, 3000000000] shares=[0.03, 0.03, 0.03] pot=991000000000 rail=push |
| 0.03 | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=3000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| 0.03 | flipper | PASS | 59.1% |  | 5/5 passed. s0:holder_score=1318591407.6515 flipper_score=0.0000 score_ratio=0.000000 |
| 0.03 | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.030000 |
| 0.03 | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.030000 typ_twab=996979096.0 |
| 0.03 | vest_pump | PASS | 60.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.057009 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| 0.03 | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=3000000000 |
| 0.03 | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |
| **0.05** | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[5000000000, 5000000000, 5000000000] shares=[0.05, 0.05, 0.05] pot=985000000000 rail=push |
| **0.05** | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=5000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| **0.05** | flipper | PASS | 59.1% |  | 5/5 passed. s0:holder_score=1318591407.6515 flipper_score=0.0000 score_ratio=0.000000 |
| **0.05** | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.050000 |
| **0.05** | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| **0.05** | vest_pump | PASS | 60.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.057009 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| **0.05** | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=5000000000 |
| **0.05** | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |
| 0.10 | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[10000000000, 10000000000, 10000000000] shares=[0.1, 0.1, 0.1] pot=970000000000 rail=push |
| 0.10 | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=10000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| 0.10 | flipper | PASS | 59.1% |  | 5/5 passed. s0:holder_score=1318591407.6515 flipper_score=0.0000 score_ratio=0.000000 |
| 0.10 | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.100000 |
| 0.10 | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.100000 typ_twab=996979096.0 |
| 0.10 | vest_pump | PASS | 60.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.057009 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| 0.10 | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=10000000000 |
| 0.10 | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |

## rewards.alpha_per_day (default 0.10)

| value | scenario | result | min margin | flag | evidence |
|---|---|---|---|---|---|
| 0.05 | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[2500000000, 2500000000, 2500000000] shares=[0.05, 0.05, 0.05] pot=992500000000 rail=push |
| 0.05 | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=2500000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| 0.05 | flipper | PASS | 59.1% |  | 5/5 passed. s0:holder_score=1318591407.6515 flipper_score=0.0000 score_ratio=0.000000 |
| 0.05 | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.050000 |
| 0.05 | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| 0.05 | vest_pump | PASS | 60.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.057009 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| 0.05 | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=2500000000 |
| 0.05 | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |
| **0.10** | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[5000000000, 5000000000, 5000000000] shares=[0.05, 0.05, 0.05] pot=985000000000 rail=push |
| **0.10** | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=5000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| **0.10** | flipper | PASS | 59.1% |  | 5/5 passed. s0:holder_score=1318591407.6515 flipper_score=0.0000 score_ratio=0.000000 |
| **0.10** | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.050000 |
| **0.10** | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| **0.10** | vest_pump | PASS | 60.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.057009 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| **0.10** | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=5000000000 |
| **0.10** | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |
| 0.20 | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[10000000000, 10000000000, 10000000000] shares=[0.05, 0.05, 0.05] pot=970000000000 rail=push |
| 0.20 | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=10000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| 0.20 | flipper | PASS | 59.1% |  | 5/5 passed. s0:holder_score=1318591407.6515 flipper_score=0.0000 score_ratio=0.000000 |
| 0.20 | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.050000 |
| 0.20 | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| 0.20 | vest_pump | PASS | 60.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.057009 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| 0.20 | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=10000000000 |
| 0.20 | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |

## hold.horizon_days (default 30)

| value | scenario | result | min margin | flag | evidence |
|---|---|---|---|---|---|
| 14 | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[5000000000, 5000000000, 5000000000] shares=[0.05, 0.05, 0.05] pot=985000000000 rail=push |
| 14 | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=5000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| 14 | flipper | PASS | 60.3% |  | 5/5 passed. s0:holder_score=1404265511.7282 flipper_score=0.0000 score_ratio=0.000000 |
| 14 | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.050000 |
| 14 | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| 14 | vest_pump | PASS | 60.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.057009 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| 14 | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=5000000000 |
| 14 | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |
| **30** | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[5000000000, 5000000000, 5000000000] shares=[0.05, 0.05, 0.05] pot=985000000000 rail=push |
| **30** | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=5000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| **30** | flipper | PASS | 59.1% |  | 5/5 passed. s0:holder_score=1318591407.6515 flipper_score=0.0000 score_ratio=0.000000 |
| **30** | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.050000 |
| **30** | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| **30** | vest_pump | PASS | 60.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.057009 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| **30** | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=5000000000 |
| **30** | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |
| 60 | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[5000000000, 5000000000, 5000000000] shares=[0.05, 0.05, 0.05] pot=985000000000 rail=push |
| 60 | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=5000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| 60 | flipper | PASS | 58.2% |  | 5/5 passed. s0:holder_score=1265966765.9736 flipper_score=0.0000 score_ratio=0.000000 |
| 60 | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.050000 |
| 60 | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| 60 | vest_pump | PASS | 60.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.057009 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| 60 | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=5000000000 |
| 60 | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |

## vesting.m (default 5)

| value | scenario | result | min margin | flag | evidence |
|---|---|---|---|---|---|
| 3 | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[5000000000, 5000000000, 5000000000] shares=[0.05, 0.05, 0.05] pot=985000000000 rail=push |
| 3 | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=5000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| 3 | flipper | PASS | 59.1% |  | 5/5 passed. s0:holder_score=1318591407.6515 flipper_score=0.0000 score_ratio=0.000000 |
| 3 | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.050000 |
| 3 | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| 3 | vest_pump | PASS | 41.5% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.083517 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| 3 | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=5000000000 |
| 3 | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |
| **5** | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[5000000000, 5000000000, 5000000000] shares=[0.05, 0.05, 0.05] pot=985000000000 rail=push |
| **5** | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=5000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| **5** | flipper | PASS | 59.1% |  | 5/5 passed. s0:holder_score=1318591407.6515 flipper_score=0.0000 score_ratio=0.000000 |
| **5** | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.050000 |
| **5** | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| **5** | vest_pump | PASS | 60.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.057009 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| **5** | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=5000000000 |
| **5** | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |
| 8 | honest_holders | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:payouts=[5000000000, 5000000000, 5000000000] shares=[0.05, 0.05, 0.05] pot=985000000000 rail=push |
| 8 | sniper | PASS | 100.0% |  | 5/5 passed. s0:holder_pay=5000000000 sniper_pay=0 sniper_score=0.000000 pay_ratio=0.000000 |
| 8 | flipper | PASS | 59.1% |  | 5/5 passed. s0:holder_score=1318591407.6515 flipper_score=0.0000 score_ratio=0.000000 |
| 8 | whale_cap | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:n=5 max_pi=0.050000 |
| 8 | sybil_cluster | PASS | 0.0% (cap binds) | cap-binds | 5/5 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| 8 | vest_pump | PASS | 69.1% |  | 5/5 passed. s0:unlocked=0.142857 u_time=0.142857 u_price=0.044124 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| 8 | underwater | PASS | 11.7% | FLAG | 5/5 passed. s0:U=1.3241 mtm=-2430672823.2 mid=1.0273 farmer_pay=5000000000 |
| 8 | rewards_disabled | PASS | 100.0% |  | 5/5 passed. s0:payouts={} pot=1000000000000 rail=none |

## Findings

- Cap-binding rows (honest_holders, sybil_cluster, whale_cap) have 0% slack on `π ≤ cap` at every cap in the grid, including the 0.05 default. That is by construction: those scenarios sit on the cap. It is not a proposal to raise or lower the default.
- **FLAG** (12 cell(s) with a failure or margin < 20% that is not cap-binding):
  - underwater: margin 11.7% on every cell (independent of cap, alpha, H, and M)
- vest_pump price-unlock slack (u_time − u_price)/u_time: M=3 41.5%, M=5 60.1%, M=8 69.1%. All stay above 20% on this grid.
- underwater margin is 11.7% on every cell (U≈1.324 vs the U≤1.5 cap; the U>1 side is looser). The row still passes. This tightness is in the scenario, not in cap/alpha/H/M.
- flipper worst-seed margin moves slightly with H (H=14 60.3%, H=30 59.1%, H=60 58.2%); seed 0 often has a zero flipper score (min_hold), tighter seeds still stay well above 20%.
- alpha scales payouts but does not move the §14 pass/fail pattern or the margins (inequalities are on shares, scores, or boost).
- **Proposal: none.** Defaults stay cap=0.05, alpha_per_day=0.10, horizon_days=30, vesting.m=5. The underwater <20% flag is a note on the existing U≤1.5 acceptance row, not a reason to change these knobs.

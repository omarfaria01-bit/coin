# Full-epoch simulator e2e (run_epoch)

Each row drives the real `engine.epoch.run_epoch` from a `sim` world. Defaults are unchanged. Conservation is the §8 identity, also asserted in the runner.

Seeds: 10. Wall time: 0.16s.

| scenario | pass condition | result | evidence |
|---|---|---|---|
| honest_holders | 3 equal holders: conservation, each paid, each π ≤ CAP, payouts equal | PASS | 10/10 passed. s0:payouts=[5000000000, 5000000000, 5000000000] shares=[0.05, 0.05, 0.05] pot=985000000000 rail=push |
| sniper | 5-min sniper: score 0 or score ≤ 0.5% of a full-day holder | PASS | 10/10 passed. s0:holder_pay=5000000000 sniper_pay=0 holder_score=1181856352.342000 sniper_score=0.000000 score_ratio=0.000000 |
| flipper | 5×/day flipper: reward per token-hour ≤ 30% of a 7-day holder's (v0.3.3 §14) | PASS | 10/10 passed. s0:flipper_per_token_hour=0.6132 holder_1d=1.6250 h7d=2.10 ratio=0.2920 |
| whale_cap | 1 whale + 4 small holders: every π ≤ CAP, conservation holds | PASS | 10/10 passed. s0:n=5 max_pi=0.050000 |
| sybil_cluster | 10 wallets, same first funder: one cluster, all 10 paid a split of one capped share | PASS | 10/10 passed. s0:big_clusters=1 split_paid=10 pi=0.050000 typ_twab=996979096.0 |
| vest_pump | 1h ~3× pump: no extra unlock beyond u_time (1/7); selling the bag forfeits | PASS | 10/10 passed. s0:unlocked=0.142857 u_time=0.142857 forfeit={'5vvq5iHo6CwyEDMcz93dxv1tFbYqjq6jdNZbPxQGjAot': 2676600} dev_score=0.0 |
| underwater | Farmer buys near the top, 48h+ later: boost off at launch (U = 1), loss kept | PASS | 10/10 passed. s0:U=1.0000 mtm=-2430672823.2 mid=1.0273 farmer_pay=5000000000 |
| rewards_disabled | rewards.enabled=False: zero payouts, pot += inflow only, conservation holds | PASS | 10/10 passed. s0:payouts={} pot=1000000000000 rail=none |

All rows passed.

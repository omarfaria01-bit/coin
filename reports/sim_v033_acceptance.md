# COIN_MATH v0.3.3 §14 rows (#84 step 1)

Seeds: 20 per row.

| §14 row | pass condition | result | evidence (worst seed) |
|---|---|---|---|
| Holding time 7d/30d/60d/90d | strictly increasing, flat after 90d | PASS | seed 0: h=2.114,2.503,2.702,2.800,2.800 |
| Scalper churning < 2h | score = 0 | PASS | seed 0: score=0.0 trips=21 |
| Snapshot sniper | score = 0 for 2h | PASS | seed 0: score=0.0 |
| Partial sale | loses exactly the sold lots' score (newest first) | PASS | seed 0: after_sale=142481154944811 expected=142481154944811 |
| New buy on an old bag | old lots' score unchanged | PASS | seed 0: before=118050378227855 after=118050378227855 |
| Transfer to another owner | receiver starts at age 0 | PASS | seed 0: recv=12354863072522 bound=20772641005492 |
| Whale cap, 10 clusters | π ≤ 5%, ≤ 2× proportional, rest in pot | PASS | seed 0: max_pi=0.0500 paid/R=0.105 |
| S = 0 | nothing paid, pot unchanged | PASS | seed 0: pot=745416409846 paid={} |
| Exact payout | Σ payouts + rollover == R_e | PASS | seed 0: sum+rollover=511494146497 R_e=511494146497 |
| Multiplier bounds | < 2h → 0, ≤ 2.8× without boost | PASS | seed 0: h(<2h)=0 max_h=2.800 |
| Small balance below MIN_PAYOUT_Q | pending never decreases, paid at threshold | PASS | seed 0: pending_epochs=6 paid_at_epoch=6 |
| Any split, 2–10 wallets, boost off | total score never higher | PASS | seed 0: n=3 split=532097231262114 single=532097231262114 |
| €100 holder at $50k..$50M | eligible in every case | PASS | seed 0: $50,000:ok $500,000:ok $5,000,000:ok $50,000,000:ok |
| Whale splits into 50 funded wallets | one cluster, no gain, cap | PASS | seed 0: single=5000000000 split=5000000000 one_cluster=True |
| Dust attack (tokens + SOL) | victim not merged, score not lower | PASS | seed 0: score 216288355752460→219608164336754 unmerged=True |
| Forced merge, free actions | no merge | PASS | seed 0: clusters=2 |
| Forced merge, funding | merge only at ≥ 50% inflow + spend | PASS | seed 0: no merge at 3999999999 lamports; merge costs ≥ 8000000000 lamports |
| Chain A–B co-signed, B–C, C–D | only A–B merged | PASS | seed 0: clusters=3 (want 3) |
| Soft vesting: selling locked tokens | forfeit applied | PASS | seed 0: forfeit_until=2610270 |
| Soft vesting: out via 3 wallets | forfeit; tainted every hop; no gain | PASS | seed 0: forfeit=True score 101757257991030→5924997395833 |
| Circular transfers A→B→C→A | no gain in score or age | PASS | seed 0: score 445560893311343→419222862955917 |
| Whole bag to a new funded wallet | age and cost preserved | PASS | seed 0: score 74401197802103→74403369227202 merged=True |
| Pump ≤ 1h, random histories | P̃_h ≤ (24/23)·H_rest | PASS | seed 0: tau=3175s P̃h/base=1.0147 bound/base=1.0147 |
| Buy and sell in the same second | intra-second states zero; p(t) end-of-second | PASS | seed 0: round trips 0; p(t)=end-of-second=2.0e+00; score same=True |
| Pool depth below the trust threshold | boost off, unlock paused, base rewards unchanged | PASS | seed 0: thin untrusted=1.0 unlock=None; payouts/score equal=True |
| Missing / decreasing block time, skipped slots | same output as the clean log | PASS | seed 0: 6 slots → 3 seconds; same epoch=True |
| Same fee-paying app + one-sided signals | no merge; payer in the review list | PASS | seed 0: clusters=6 merged=False review=('APP',) |
| Single commercial transfer | no merge | PASS | seed 0: clusters=2 (want 2) |
| False merge of two independent clusters | tokens' score same; cap damage reported | PASS | seed 0: score same=True damage=0.0% ≤ 20% |
| Sybil recall (self-funded / CEX-funded) | self ≥ 95%; CEX reported as residual | PASS | seed 0: self=100% (12/12); cex=0/12 (hub residual) |
| Retroactive merge | past epochs unchanged; equals a from-genesis rebuild | PASS | seed 0: past hash unchanged; 2→1 cluster; scores == fresh rebuild=True |
| Dump, then 6h with no trades (arbitrage agents present) | attacker's net PnL < 0; pool mid restored to the reference | PASS | seed 0: pnl=-4390380 (-12.99% of notional) in 6h; mid/ref=1.0000; arbs=1 profit=2155168; no-arb pnl=-0.56% |
| Pump, then 24h with no trades (arbitrage agents present) | attacker's net PnL < 0; pool mid restored to the reference | PASS | seed 0: pnl=-1297026 (-5.42% of notional) in 24h; mid/ref=1.0000; arbs=1 profit=525606; no-arb pnl=-0.58% |

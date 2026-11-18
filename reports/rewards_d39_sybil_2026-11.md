# D39 sybil split: old sqrt odds vs linear odds (18 Nov 2026)

Audit #271 C1, decision D39. Model `sim/rewards_d39_sybil.py` (exact Fractions, engine weights,
no randomness needed: these are the exact odds). 300 honest groups at 0.25% of supply each; the
attacker splits a fixed holding over N **unlinked** wallets. "D39" uses the defaults (5% supply
cap, 5% odds cap, minimum 0.01% of supply per entrant); the last column lowers the minimum to
1e-9 of supply to show the pure linear invariance.

## Attacker holds 3% of supply (proportional share 3.8462%)

| wallets N | old isqrt odds | D39 odds | D39, minimum 1e-9 |
|---|---|---|---|
| 1 | 1.1415% | 3.8462% | 3.8462% |
| 10 | 3.5228% | 3.8462% | 3.8462% |
| 100 | 10.3517% | 3.8462% | 3.8462% |
| 1,000 | 26.7479% | 0.0000% | 3.8462% |

With linear odds the total is **identical for every N** while each piece is above the minimum;
1,000 pieces of 0.003% fall below the 0.01% minimum and get **0**. The old rule paid splitting.

## Attacker holds 20% of supply (proportional share 21.0526%)

| wallets N | old isqrt odds | D39 odds | D39, minimum 1e-9 |
|---|---|---|---|
| 1 | 2.8951% | 5.0000% | 5.0000% |
| 10 | 8.6158% | 21.0526% | 21.0526% |
| 100 | 22.9668% | 21.0526% | 21.0526% |
| 1,000 | 48.5281% | 21.0526% | 21.0526% |

N = 1 is held to 5% of supply and then 5% of the odds. Splitting can escape the per-group caps,
but with linear odds the result is **never above the proportional share**; it is the cap's
known limit and no longer a profit from splitting itself.

## Proofs (COIN_MATH §9, D39)

1. Split invariance: weights are `w = s·D` (one common D), so N pieces with `Σ s_i = s` have
   `Σ w_i = w`; the total weight W is unchanged, so the odds `Σ w_i / W = w / W` are equal.
2. Merging never helps: `min(Σ b_i, C) ≤ Σ min(b_i, C)` (supply cap) and the odds cap is a
   `min` too, so a merged group's weight is ≤ the sum of its pieces' weights.
3. Splitting is bounded: each piece's weight is ≤ its uncapped linear weight, so a split group
   never exceeds its proportional share of the uncapped total.
4. Pieces below `0.01% · S` get 0, so dust spam costs 0.01% of supply per wallet and wins nothing.

Reproduce: `uv run python -m sim.rewards_d39_sybil > reports/rewards_d39_sybil_2026-11.md`

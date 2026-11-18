# Hourly draw fairness (D28): cap, sqrt odds, sybil merge, rollover (18 Nov 2026)

Issue: [#225](https://github.com/omarfaria01-bit/coin/issues/225). Model:
`sim/hourly_draw_fairness.py`. **Simulation only** — draws stay off in production (legal #8 /
§16); no network, no wallet, no transaction. Engine and spec untouched.

## Rules

- `w_c = isqrt(score_c)` (`engine/draws.py`), then the exact water-filling 5% cap: with ≥ 20
  clusters no cluster exceeds 5.00% of the odds.
- Ten prizes per hour, sampled without replacement (at most one per cluster), bps
  `(4000, 1000, 1000, 1000, 500, 500, 500, 500, 500, 500)`, integer floor, remainder stays in the pot.
- Below the 0.01 SOL minimum (`10,000,000` lamports) the whole pot rolls over.
- Seed `rho = SHA-256("<seed>:<i>")`; 10,000 draws per population (a–c), 10,000 hourly
  steps for (d), populations constant.

## (a) One whale + 500 small holders

| class | clusters | odds share | rank-1 share | slot share |
|---|---|---|---|---|
| whale | 1 | 5.00% | 4.93% | 4.07% |
| small | 500 | 95.00% | 95.07% | 95.93% |

Max cluster `w00`: **5.00%** odds, rank-1 **4.93%** (±0.43 pp),
all-prize share **4.07%**. The whale's raw sqrt share is
16.67%; the cap turns it into
5.00%, the small class keeps 95.00%. Rank-1
wins estimate the capped odds; the all-prize share is lower for a big cluster because the ten
prizes are drawn without replacement, so it stays under the cap.

## (b) Sybil split: linked wallets must merge

| case | whale class clusters | whale class odds | rank-1 share | same winners as unsplit |
|---|---|---|---|---|
| unsplit | 1 | 5.00% | 4.93% | — |
| split 10, linked | 1 | 5.00% | 4.93% | True |

The linked split gives the **same capped weights and winner sequences** as the unsplit whale
(same seed, cluster id `w00`), so merging is exact. With the links missed, the 10 fragments
would hold **38.74%** of the odds — each is below the 5% per-cluster cap, so §7
clustering, not the cap, is what removes the split advantage.

## (c) 1,000 equal holders

All 1,000 clusters are at 0.10% odds; largest observed rank-1 **0.22%**,
largest all-prize share **0.13%**. The cap is not binding.

## (d) Pot below the minimum: rollover

Inflow 400,000 lamports/h (0.0004 SOL/h), so the pot needs 24 hours to reach the
0.01 SOL minimum. First cycle:

| hour | pot before | drawn? | paid | rollover after |
|---|---|---|---|---|
| 1 | 400,000 | no | 0 | 400,000 |
| 2 | 800,000 | no | 0 | 800,000 |
| 3 | 1,200,000 | no | 0 | 1,200,000 |
| 4 | 1,600,000 | no | 0 | 1,600,000 |
| 5 | 2,000,000 | no | 0 | 2,000,000 |
| 6 | 2,400,000 | no | 0 | 2,400,000 |
| 7 | 2,800,000 | no | 0 | 2,800,000 |
| 8 | 3,200,000 | no | 0 | 3,200,000 |
| 9 | 3,600,000 | no | 0 | 3,600,000 |
| 10 | 4,000,000 | no | 0 | 4,000,000 |
| 11 | 4,400,000 | no | 0 | 4,400,000 |
| 12 | 4,800,000 | no | 0 | 4,800,000 |
| 13 | 5,200,000 | no | 0 | 5,200,000 |
| 14 | 5,600,000 | no | 0 | 5,600,000 |
| 15 | 6,000,000 | no | 0 | 6,000,000 |
| 16 | 6,400,000 | no | 0 | 6,400,000 |
| 17 | 6,800,000 | no | 0 | 6,800,000 |
| 18 | 7,200,000 | no | 0 | 7,200,000 |
| 19 | 7,600,000 | no | 0 | 7,600,000 |
| 20 | 8,000,000 | no | 0 | 8,000,000 |
| 21 | 8,400,000 | no | 0 | 8,400,000 |
| 22 | 8,800,000 | no | 0 | 8,800,000 |
| 23 | 9,200,000 | no | 0 | 9,200,000 |
| 24 | 9,600,000 | no | 0 | 9,600,000 |
| 25 | 10,000,000 | yes | 10,000,000 | 0 |

Over 10,000 hours: **400 draws**, **9,600 rollover hours**, paid
4,000,000,000 lamports (4.0 SOL), largest amount carried 9,600,000. The pot is never
split, partially paid below the minimum, or lost.

## Conservation and floor

30,000 draw plans plus 10,000 rollover steps: **0 violations** of
`Σ prizes + rollover == pot`; all amounts are ints and prizes are floored. Example: pot
10,000,003 -> paid 10,000,001, rollover 2.

## Acceptance

All four checks pass: cap (highest odds 5.00%, all-prize share 4.07% in (a)
and 0.13% in (c)), sqrt odds (whale 4.93% vs
5.00%, small 95.07% vs
95.00%), sybil merge (linked split == unsplit, identical winners) and
rollover (whole-pot carry for 24 hours, then a draw, conservation holds).

## Limits

- Rank-1 is a sample (SE 0.22 pp at 5%, 10,000 draws); the cap is exact on the odds.
- Cap impossible below 20 live clusters (`n · cap < 1`); not an issue here.
- Sybil invariance needs detected links; scores are constant, draws off (legal #8).

## Reproduce

```
$ uv run python -m sim.hourly_draw_fairness > reports/hourly_draw_fairness_2026-11.md
$ uv run python -m sim.hourly_draw_fairness | diff - reports/hourly_draw_fairness_2026-11.md \
    && echo identical
identical
```

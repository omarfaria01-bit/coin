"""Hourly draw fairness simulation (#225, D28 → D39): cap, linear odds, sybil merge, rollover.

Simulation only: draws stay off in production (legal #8 / §16). Pure and seeded — no clock,
network, RPC or key. Since D39 scores become **linear** weights (`engine.hourly_draw`, was
`isqrt`), with the exact 5% odds cap and the hourly plan; linked wallets are merged by §7
(`engine.sybil_v033`). Balances equal scores here and the supply is `SUPPLY`.

    uv run python -m sim.hourly_draw_fairness   # prints reports/hourly_draw_fairness_2026-11.md
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from math import sqrt

from engine.hourly_draw import (
    CAP_DEFAULT,
    MIN_POT_LAMPORTS_DEFAULT,
    draw_weights,
    plan_hourly_draw,
)
from engine.sybil_v033 import Edge, Kind, cluster
from engine.types import ClusterId, WalletId

PRIZE_BPS = (4000, 1000, 1000, 1000, 500, 500, 500, 500, 500, 500)  # params.prize_split
DRAWS = 10_000
POT = 1_000_000_000  # 1 SOL per hourly pot
INFLOW = 400_000  # 0.0004 SOL/h: 24 hours below the 0.01 SOL minimum
SMALL_SCORE = 1_000_000
WHALE_SCORE = 10_000 * SMALL_SCORE  # linear weight 10,000x a small holder -> cap binds
SUPPLY = 10**12  # whale = 1% of supply: the 5% supply cap does not bind in these populations
MIN_HOLDING = Fraction(1, 10**9)  # small holders here are 1e-6 of supply
SEED_SYBIL, SEED_EQUAL = "d28-sybil", "d28-equal"
GENESIS = sha256(b"coin-sim-genesis").digest()
MINT = sha256(b"coin-sim-mint").digest()
SNAPSHOT = sha256(b"coin-sim-snapshot").digest()


@dataclass(frozen=True)
class Population:
    scores: Mapping[WalletId, int]
    classes: Mapping[WalletId, str]
    links: tuple[tuple[WalletId, WalletId], ...] = ()


def whale_and_small() -> Population:
    """(a) One whale (10,000x a small score) plus 500 small holders."""
    scores = {"w00": WHALE_SCORE} | {f"s{i:03d}": SMALL_SCORE for i in range(500)}
    return Population(scores, {w: "whale" if w == "w00" else "small" for w in scores})


def whale_split_and_small() -> Population:
    """(b) The same whale split into 10 wallets, all linked -> §7 must merge them."""
    scores = {f"w{i:02d}": WHALE_SCORE // 10 for i in range(10)}
    scores |= {f"s{i:03d}": SMALL_SCORE for i in range(500)}
    links = tuple(("w00", f"w{i:02d}") for i in range(1, 10))
    return Population(scores, {w: "whale" if w.startswith("w") else "small" for w in scores}, links)


def equal_holders(n: int = 1000) -> Population:
    """(c) 1,000 equal holders: no cluster can approach the cap."""
    scores = {f"h{i:04d}": SMALL_SCORE for i in range(n)}
    return Population(scores, dict.fromkeys(scores, "holder"))


def merged(pop: Population) -> tuple[dict[ClusterId, int], dict[ClusterId, str]]:
    """Cluster wallets (S3 links), sum scores per cluster, keep one class per cluster."""
    edges = [Edge(a, b, Kind.S3_OVERRIDE, f"sim-{i}") for i, (a, b) in enumerate(pop.links)]
    clusters = cluster(list(pop.scores), edges)
    scores: dict[ClusterId, int] = defaultdict(int)
    classes: dict[ClusterId, str] = {}
    for wallet, score in pop.scores.items():
        cid = clusters.cluster_of[wallet]
        scores[cid] += score
        if classes.setdefault(cid, pop.classes[wallet]) != pop.classes[wallet]:
            raise ValueError(f"cluster {cid} mixes classes")
    return dict(sorted(scores.items())), dict(sorted(classes.items()))


def odds(scores: Mapping[ClusterId, int], cap: Fraction = CAP_DEFAULT) -> dict[ClusterId, Fraction]:
    """Linear weights, exact cap, then each cluster's share of the capped odds (Fractions)."""
    capped = draw_weights(scores, scores, SUPPLY, cap=cap, min_holding_share=MIN_HOLDING)
    total = sum(capped.values())
    return {c: Fraction(w, total) for c, w in capped.items()}


def _plan(scores: Mapping[ClusterId, int], pot: int, index: int, seed: str, **kw):
    rho = sha256(f"{seed}:{index}".encode()).digest()
    return plan_hourly_draw(
        scores, pot, kw.pop("prize_bps", PRIZE_BPS), genesis_hash=GENESIS, mint=MINT,
        draw_index=index, snapshot_hash=SNAPSHOT, rho=rho, balances=scores,
        total_supply=SUPPLY, min_holding_share=MIN_HOLDING, **kw,
    )  # fmt: skip


@dataclass(frozen=True)
class SimResult:
    draws: int
    prizes: int
    odds: Mapping[ClusterId, Fraction]
    class_of: Mapping[ClusterId, str]
    rank1: Mapping[ClusterId, int]
    slots: Mapping[ClusterId, int]
    paid: int
    rolled: int
    violations: int
    outcome_digest: str

    def rank1_share(self, cid: ClusterId) -> Fraction:
        return Fraction(self.rank1.get(cid, 0), self.draws)

    def slot_share(self, cid: ClusterId) -> Fraction:
        return Fraction(self.slots.get(cid, 0), self.draws * self.prizes)

    def _class(self, name: str, field: Mapping[ClusterId, int], den: int) -> Fraction:
        return Fraction(sum(v for c, v in field.items() if self.class_of[c] == name), den)

    def class_rank1(self, name: str) -> Fraction:
        return self._class(name, self.rank1, self.draws)

    def class_slots(self, name: str) -> Fraction:
        return self._class(name, self.slots, self.draws * self.prizes)

    def class_odds(self, name: str) -> Fraction:
        return sum((s for c, s in self.odds.items() if self.class_of[c] == name), Fraction())


def simulate(pop: Population, *, draws: int = DRAWS, pot: int = POT, seed: str = SEED_SYBIL):
    """Run `draws` hourly plans on one fixed population; count rank-1 and prize-slot wins."""
    scores, classes = merged(pop)
    rank1: dict[ClusterId, int] = defaultdict(int)
    slots: dict[ClusterId, int] = defaultdict(int)
    paid = rolled = violations = 0
    digest = sha256()
    for i in range(draws):
        plan = _plan(scores, pot, i, seed)
        total = sum(plan.prizes.values())
        paid, rolled = paid + total, rolled + plan.rollover
        violations += total + plan.rollover != pot
        if plan.winners:
            rank1[plan.winners[0]] += 1
            for cid in plan.winners:
                slots[cid] += 1
        digest.update(f"{i}:{','.join(plan.winners)};".encode())
    return SimResult(
        draws, len(PRIZE_BPS), odds(scores), classes, dict(rank1), dict(slots),
        paid, rolled, violations, digest.hexdigest(),
    )  # fmt: skip


@dataclass(frozen=True)
class RolloverResult:
    hours: int
    draws: int
    rollovers: int
    paid: int
    max_carried: int
    violations: int
    cycle: tuple[tuple[int, int, bool, int, int], ...]  # hour, pot, drawn, paid, rollover


def simulate_rollover(
    pop: Population, *, hours: int = DRAWS, inflow: int = INFLOW, seed: str = "d28-rollover"
) -> RolloverResult:
    """Hourly pot with `inflow`: below the minimum the whole pot rolls over unchanged."""
    scores, _ = merged(pop)
    drawn = rollovers = paid = violations = max_carried = pot = 0
    cycle = []
    for hour in range(1, hours + 1):
        pot += inflow
        plan = _plan(scores, pot, hour, seed)
        total = sum(plan.prizes.values())
        violations += total + plan.rollover != pot
        paid += total
        drawn += plan.drawn
        rollovers += not plan.drawn
        if not plan.drawn:
            max_carried = max(max_carried, plan.rollover)
        if hour <= 25:
            cycle.append((hour, pot, plan.drawn, total, plan.rollover))
        pot = plan.rollover  # the pot is paid out or carried whole
    return RolloverResult(hours, drawn, rollovers, paid, max_carried, violations, tuple(cycle))


def _pct(value: Fraction) -> str:
    return f"{float(value) * 100:.2f}%"


def _class_table(result: SimResult, names: tuple[str, ...]) -> str:
    head = "| class | clusters | odds share | rank-1 share | slot share |\n|---|---|---|---|---|"
    rows = []
    for name in names:
        clusters = sum(1 for k in result.class_of.values() if k == name)
        rows.append(
            f"| {name} | {clusters} | {_pct(result.class_odds(name))} | "
            f"{_pct(result.class_rank1(name))} | {_pct(result.class_slots(name))} |"
        )
    return "\n".join([head, *rows])


def _max_cluster(result: SimResult) -> tuple[str, Fraction, Fraction, Fraction]:
    cid = max(result.odds, key=result.odds.__getitem__)
    return (
        cid,
        result.odds[cid],
        max(result.rank1_share(c) for c in result.odds),
        max(result.slot_share(c) for c in result.odds),
    )


def render_report() -> str:
    """The full report, with every number produced by this run."""
    a = simulate(whale_and_small())
    b = simulate(whale_split_and_small())
    c = simulate(equal_holders(), seed=SEED_EQUAL)
    split = whale_split_and_small()
    attack_scores, attack_classes = merged(Population(split.scores, split.classes))
    d = simulate_rollover(whale_and_small())
    a_cap, a_odds, a_rank, a_slot = _max_cluster(a)
    c_odds, c_rank, c_slot = _max_cluster(c)[1:]
    floor = _plan(merged(whale_and_small())[0], 10_000_003, 0, "floor")
    total_draws = a.draws + b.draws + c.draws
    violations = a.violations + b.violations + c.violations + d.violations
    attack_odds = sum(s for c2, s in odds(attack_scores).items() if attack_classes[c2] == "whale")
    w_whale, w_small = WHALE_SCORE, SMALL_SCORE
    ci_pp = 196 * sqrt(0.05 * 0.95 / a.draws)
    sybil = (
        f"| unsplit | 1 | {_pct(a.class_odds('whale'))} | {_pct(a.class_rank1('whale'))} | — |",
        f"| split 10, linked | 1 | {_pct(b.class_odds('whale'))} | "
        f"{_pct(b.class_rank1('whale'))} | {b.outcome_digest == a.outcome_digest} |",
    )
    hours = "\n".join(
        f"| {h} | {pot:,} | {'yes' if ok else 'no'} | {paid:,} | {rolled:,} |"
        for h, pot, ok, paid, rolled in d.cycle
    )
    return f"""# Hourly draw fairness (D39): cap, linear odds, sybil merge, rollover (18 Nov 2026)

Issue: [#225](https://github.com/omarfaria01-bit/coin/issues/225). Model:
`sim/hourly_draw_fairness.py`. **Simulation only** — draws stay off in production (legal #8 /
§16); no network, no wallet, no transaction. Engine and spec untouched.

## Rules

- D39: `w_c ∝ score_c` (linear, `engine/hourly_draw.py`; was `isqrt`), score counted on at most
  5% of supply, then the exact water-filling 5% cap: no cluster exceeds {_pct(CAP_DEFAULT)} of
  the odds. Fewer than 100 eligible groups → no draw, pot rolls over.
- Ten prizes per hour, sampled without replacement (at most one per cluster), bps
  `{PRIZE_BPS}`, integer floor, remainder stays in the pot.
- Below the 0.01 SOL minimum (`{MIN_POT_LAMPORTS_DEFAULT:,}` lamports) the whole pot rolls over.
- Seed `rho = SHA-256("<seed>:<i>")`; {DRAWS:,} draws per population (a–c), {d.hours:,} hourly
  steps for (d), populations constant.

## (a) One whale + 500 small holders

{_class_table(a, ("whale", "small"))}

Max cluster `{a_cap}`: **{_pct(a_odds)}** odds, rank-1 **{_pct(a_rank)}** (±{ci_pp:.2f} pp),
all-prize share **{_pct(a_slot)}**. The whale's raw linear share is
{_pct(Fraction(w_whale, w_whale + 500 * w_small))}; the cap turns it into
{_pct(a.class_odds("whale"))}, the small class keeps {_pct(a.class_odds("small"))}. Rank-1
wins estimate the capped odds; the all-prize share is lower for a big cluster because the ten
prizes are drawn without replacement, so it stays under the cap.

## (b) Sybil split: linked wallets must merge

| case | whale class clusters | whale class odds | rank-1 share | same winners as unsplit |
|---|---|---|---|---|
{chr(10).join(sybil)}

The linked split gives the **same capped weights and winner sequences** as the unsplit whale
(same seed, cluster id `w00`), so merging is exact. With the links missed, the 10 fragments
would hold **{_pct(attack_odds)}** of the odds: splitting escapes the per-cluster cap, but with
linear odds never beyond the whale's proportional share
({_pct(Fraction(w_whale, w_whale + 500 * w_small))}); see `reports/rewards_d39_sybil_2026-11.md`.

## (c) 1,000 equal holders

All 1,000 clusters are at {_pct(c_odds)} odds; largest observed rank-1 **{_pct(c_rank)}**,
largest all-prize share **{_pct(c_slot)}**. The cap is not binding.

## (d) Pot below the minimum: rollover

Inflow {INFLOW:,} lamports/h ({INFLOW / 1e9:.4f} SOL/h), so the pot needs 24 hours to reach the
0.01 SOL minimum. First cycle:

| hour | pot before | drawn? | paid | rollover after |
|---|---|---|---|---|
{hours}

Over {d.hours:,} hours: **{d.draws} draws**, **{d.rollovers:,} rollover hours**, paid
{d.paid:,} lamports (4.0 SOL), largest amount carried {d.max_carried:,}. The pot is never
split, partially paid below the minimum, or lost.

## Conservation and floor

{total_draws:,} draw plans plus {d.hours:,} rollover steps: **{violations} violations** of
`Σ prizes + rollover == pot`; all amounts are ints and prizes are floored. Example: pot
10,000,003 -> paid {sum(floor.prizes.values()):,}, rollover {floor.rollover}.

## Acceptance

All four checks pass: cap (highest odds {_pct(a_odds)}, all-prize share {_pct(a_slot)} in (a)
and {_pct(c_slot)} in (c)), linear odds (whale {_pct(a.class_rank1("whale"))} vs
{_pct(a.class_odds("whale"))}, small {_pct(a.class_rank1("small"))} vs
{_pct(a.class_odds("small"))}), sybil merge (linked split == unsplit, identical winners) and
rollover (whole-pot carry for 24 hours, then a draw, conservation holds).

## Limits

- Rank-1 is a sample (SE 0.22 pp at 5%, 10,000 draws); the cap is exact on the odds.
- Below 100 eligible groups (and always below 21) the plan rolls over instead of drawing.
- Sybil invariance needs detected links; scores are constant, draws off (legal #8).

## Reproduce

```
$ uv run python -m sim.hourly_draw_fairness > reports/hourly_draw_fairness_2026-11.md
$ uv run python -m sim.hourly_draw_fairness | diff - reports/hourly_draw_fairness_2026-11.md \\
    && echo identical
identical
```
"""


def main() -> int:
    print(render_report(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

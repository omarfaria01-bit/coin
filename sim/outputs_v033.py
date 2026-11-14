"""§14 outputs from `sim.population_v033` runs (#84 step 3). Floats are fine here: these are
reports about the engine's exact payouts, never inputs to a payout."""

from __future__ import annotations

import random
from collections.abc import Sequence
from statistics import mean

from engine.draws import draw_weight, is_draw_eligible, min_eligible_epochs
from sim.acceptance_v033 import DAY, HOUR, SUPPLY
from sim.population_v033 import PROBE_HOURS, Run

HOLDERS = ("loyal", "casual", "farmer", "whale", "small")
DRAWS = ((7, 1.0), (3, 0.5), (1, 1 / 3))  # (n epochs, δ): weekly default, 3-day, daily (§9)


def gini(xs: Sequence[float]) -> float:
    v = sorted(x for x in xs)
    n, total = len(v), sum(v)
    if n == 0 or total == 0:
        return 0.0
    return sum((2 * i - n + 1) * x for i, x in enumerate(v)) / (n * total)


def percentile(xs: Sequence[float], q: float) -> float:
    v = sorted(xs)
    return v[min(len(v) - 1, int(q * len(v)))] if v else 0.0


def _holders(run: Run):
    return [a for a in run.agents if a.kind in HOLDERS]


def _share_of(run: Run, wallets: Sequence[str], d0: int = 0, d1: int | None = None) -> float:
    total = sum(sum(r.payouts.values()) for r in run.results[d0:d1])
    return sum(run.paid(w, d0, d1) for w in wallets) / total if total else 0.0


def top10(run: Run, d0: int = 0, d1: int | None = None) -> float:
    paid = sorted((run.paid(a.wallet, d0, d1) for a in _holders(run)), reverse=True)
    k = max(1, len(paid) // 10)
    total = sum(paid)
    return sum(paid[:k]) / total if total else 0.0


def distribution(run: Run) -> dict[str, float]:
    hs = _holders(run)
    paid = [float(run.paid(a.wallet)) for a in hs]
    avg_bal = [mean(b[a.wallet] for b in run.balances) for a in hs]
    q = {f"p{int(x * 100)}": percentile(paid, x) / 1e9 for x in (0.1, 0.5, 0.9, 0.99)}
    return {**q, "gini_rewards": gini(paid), "gini_balances": gini(avg_bal)}


def concentration(run: Run) -> list[float]:
    """Top-10% share of rewards per 30-day window."""
    return [top10(run, d, d + 30) for d in range(0, run.days - 29, 30)]


def rate_by_holding(run: Run) -> dict[int, float]:
    """Reward (lamports) per token-hour held, for probes that hold h hours, sell, re-buy."""
    out = {}
    for a in run.agents:
        if a.kind == "probe" and a.held_s:
            out[a.hold_s // HOUR] = run.paid(a.wallet) / (a.tokens / 1e9 * a.held_s / HOUR)
    return {h: out.get(h, 0.0) for h in PROBE_HOURS}


def small_holder(run: Run, draw_samples: int = 2_000) -> dict[str, float]:
    """€100 holders: reward share, days to first payout, odds of winning a draw prize."""
    smalls = [a for a in run.agents if a.kind == "small"]
    first = []
    for a in smalls:
        days = [r.epoch for r in run.results if r.transferred_or_claimable.get(a.wallet, 0) > 0]
        first.append(days[0] - a.entry // DAY + 1 if days else float("inf"))
    out = {"share": _share_of(run, [a.wallet for a in smalls]) / max(1, len(smalls))}
    out["days_to_first_payout"] = mean(first) if first else float("inf")
    for n, _delta in DRAWS:
        out[f"draw_odds_n{n}"] = _draw_odds(run, smalls[0].wallet, n, draw_samples)
    return out


def _draw_odds(run: Run, wallet: str, n: int, samples: int) -> float:
    """P(≥ 1 of the 10 prizes) for `wallet` in the last full period, by sampling the weights."""
    last = run.results[-n:]
    eligible_epochs: dict[str, int] = {}
    score_sum: dict[str, float] = {}
    for r in last:
        for c in r.scores:
            if c.score > 0:
                eligible_epochs[c.cluster] = eligible_epochs.get(c.cluster, 0) + 1
                score_sum[c.cluster] = score_sum.get(c.cluster, 0) + c.score
    final_twab = {c.cluster: c.twab for c in last[-1].scores}
    weights = {
        c: draw_weight(int(s))
        for c, s in score_sum.items()
        if eligible_epochs[c] >= min_eligible_epochs(n)
        and is_draw_eligible(eligible_epochs[c], n, int(final_twab.get(c, 0)), SUPPLY)
    }
    weights = {c: w for c, w in weights.items() if w > 0}
    if wallet not in weights:
        return 0.0
    rng, wins = random.Random(f"draw:{wallet}:{n}"), 0
    for _ in range(samples):
        pool = dict(weights)
        for _k in range(10):
            if not pool:
                break
            pick = rng.choices(list(pool), weights=list(pool.values()))[0]
            if pick == wallet:
                wins += 1
                break
            del pool[pick]
    return wins / samples


def retention(run: Run) -> dict[str, float]:
    """Cohort = holders in by day 10 (whales and €100 holders excluded). `sold_after_m` = share
    that sold within 2 days after their own bag turned m days old."""
    cohort = [
        a for a in run.agents if a.kind in ("loyal", "casual", "farmer") and a.entry < 10 * DAY
    ]
    out = {}
    for m in (30, 60, 90):
        if m > run.days:
            continue
        still = [a for a in cohort if a.exit is None or a.exit >= m * DAY]
        out[f"retained_{m}d"] = len(still) / len(cohort)
        out[f"balance_{m}d"] = sum(run.balances[m - 1][a.wallet] for a in cohort) / sum(
            a.tokens for a in cohort
        )
        sold = [
            a for a in cohort if a.exit is not None and m * DAY <= a.exit - a.entry < (m + 2) * DAY
        ]
        out[f"sold_after_{m}d"] = len(sold) / len(cohort)
    return out


def loyal_vs_farmer(run: Run) -> float:
    """Reward per token, loyal holders ÷ farmers (whole run)."""

    def per_token(kind: str) -> float:
        xs = [a for a in run.agents if a.kind == kind]
        return sum(run.paid(a.wallet) for a in xs) / sum(a.tokens for a in xs)

    f = per_token("farmer")
    return per_token("loyal") / f if f else float("inf")


def honest_shares(run: Run) -> dict[str, float]:
    """Whole-run reward share of the holders present all run (stability baseline)."""
    stay = [a for a in run.agents if a.kind in ("loyal", "small", "whale") and a.exit is None]
    return {a.wallet: _share_of(run, [a.wallet]) for a in stay}

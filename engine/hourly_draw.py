"""Hourly draw plan (D28, kiwi 18 Nov): sqrt odds, per-cluster cap, minimum pot with rollover.

Pure integer math, no I/O, no clock. Randomness only from the passed bytes (`rho` comes from the
verifiable source in COIN_MATH §9 and is never produced here). Eligibility is upstream: a cluster
scores 0 until its lots are `T_START` (1h) old, so a zero-score cluster never enters.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from engine.draws import draw_weight, sample_draw_winners
from engine.types import ClusterId

CAP_DEFAULT = Fraction(1, 20)  # D28: no cluster above 5% of the odds
MIN_POT_LAMPORTS_DEFAULT = 10_000_000  # 0.01 SOL, D26/D28: below this the pot rolls over
_BPS = 10_000


def cap_weights(
    weights: Mapping[ClusterId, int], cap: Fraction = CAP_DEFAULT
) -> dict[ClusterId, int]:
    """Scale weights so no cluster's share of the total exceeds `cap`, exactly (water-filling).

    With fewer than 1/cap clusters the cap cannot hold (n·cap < 1): all weights become equal,
    which is the closest legal outcome. Weights are scaled by one common integer, so the
    shares of uncapped clusters keep their exact ratios.
    """
    if not (0 < cap <= 1):
        raise ValueError("cap must be in (0, 1]")
    live = {c: w for c, w in weights.items() if w > 0}
    if not live:
        return {}
    if len(live) * cap <= 1:
        return {c: 1 for c in live}
    capped: set[ClusterId] = set()
    while True:
        if cap * len(capped) >= 1:  # cannot happen for n·cap > 1; fail safe, never divide by 0
            return {c: 1 for c in live}
        free_sum = sum(w for c, w in live.items() if c not in capped)
        # c_val is the cap on an absolute weight: c_val = cap · (free_sum + |capped| · c_val)
        c_val = cap * free_sum / (1 - cap * len(capped))
        newly = {c for c, w in live.items() if c not in capped and w > c_val}
        if not newly:
            break
        capped |= newly
    d = c_val.denominator
    return {c: (c_val.numerator if c in capped else w * d) for c, w in live.items()}


@dataclass(frozen=True)
class DrawPlan:
    drawn: bool
    winners: tuple[ClusterId, ...]
    prizes: dict[ClusterId, int]  # lamports (base units of the pot), floor
    rollover: int  # pot units not paid out (kept in the draw pot)
    reason: str  # "ok" | "below_min_pot" | "no_eligible"


def plan_hourly_draw(
    scores: Mapping[ClusterId, int | Fraction],
    pot: int,
    prize_bps: tuple[int, ...],
    *,
    genesis_hash: bytes,
    mint: bytes,
    draw_index: int,
    snapshot_hash: bytes,
    rho: bytes,
    cap: Fraction = CAP_DEFAULT,
    min_pot: int = MIN_POT_LAMPORTS_DEFAULT,
) -> DrawPlan:
    """One hourly draw. Σ prizes + rollover == pot always (conservation)."""
    if pot < 0 or any(b <= 0 for b in prize_bps) or sum(prize_bps) > _BPS:
        raise ValueError("pot >= 0, prize_bps > 0 and summing to <= 10_000")
    if pot < min_pot:
        return DrawPlan(False, (), {}, pot, "below_min_pot")
    weights = {c: draw_weight(s) for c, s in scores.items()}
    weights = cap_weights({c: w for c, w in weights.items() if w > 0}, cap)
    if not weights:
        return DrawPlan(False, (), {}, pot, "no_eligible")
    winners = sample_draw_winners(
        weights,
        genesis_hash=genesis_hash,
        mint=mint,
        draw_index=draw_index,
        snapshot_hash=snapshot_hash,
        rho=rho,
        k=len(prize_bps),
    )
    prizes = {c: pot * bps // _BPS for c, bps in zip(winners, prize_bps, strict=False)}
    return DrawPlan(True, tuple(winners), prizes, pot - sum(prizes.values()), "ok")

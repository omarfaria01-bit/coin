"""Hourly draw plan (D28 → D39): linear odds, supply cap, minimum holding, group gate, rollover.

Pure integer/Fraction math, no I/O, no clock. Randomness only from the passed bytes (`rho` comes
from the committed VRF flow in `engine/draw_commit.py`, COIN_MATH §9, and is never produced here).

D39 (kiwi 18 Nov, "risolvi tu tutto questi problemi usando la matematica", audit #271):
- odds are **proportional to score** (was `isqrt`): a holding split over N unlinked wallets has
  exactly the same total odds, and merging wallets never raises odds (COIN_MATH §9, proofs);
- each group's score counts at most `supply_cap` (5%) of total supply: score × min(1, 5%·S / B);
- each group needs a balance ≥ `min_holding_share` (0.01%) of supply (`is_draw_eligible`);
- fewer than `min_groups` (100, COIN_MATH §16) eligible groups → no draw, the pot rolls over
  (never the old equal-odds fallback);
- no group above `cap` (5%) of the odds (exact water-filling, kept from D28).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from math import lcm

from engine.draws import is_draw_eligible, sample_draw_winners
from engine.loyalty import loyalty_scores
from engine.types import ClusterId

CAP_DEFAULT = Fraction(1, 20)  # D28: no group above 5% of the odds
SUPPLY_CAP_DEFAULT = Fraction(1, 20)  # D39: no group counts more than 5% of supply
MIN_HOLDING_SHARE_DEFAULT = Fraction(1, 10_000)  # D39: 0.01% of supply to enter
MIN_GROUPS_DEFAULT = 100  # COIN_MATH §16: draws need ≥ 100 eligible groups
MIN_POT_LAMPORTS_DEFAULT = 10_000_000  # 0.01 SOL, D26/D28: v0.3.3 field, unchanged
# GTASP10 draw (D43): one SOL prize. Below 0.1 SOL the whole pot rolls over.
SOL_PRIZE_MIN_LAMPORTS = 100_000_000
DRAW_COMING_SOON = "coming_soon"
_BPS = 10_000
_WEIGHT_LIMIT = 1 << 128
_SCALE_BITS = 120


def cap_weights(
    weights: Mapping[ClusterId, int], cap: Fraction = CAP_DEFAULT
) -> dict[ClusterId, int]:
    """Scale weights so no cluster's share of the total exceeds `cap`, exactly (water-filling).

    With fewer than 1/cap clusters the cap cannot hold (n·cap < 1): all weights become equal.
    `plan_hourly_draw` never reaches that branch since D39 (it rolls over below the group gate).
    Weights are scaled by one common integer, so uncapped clusters keep their exact ratios.
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


def _frac(x: int | Fraction) -> Fraction:
    if isinstance(x, bool) or not isinstance(x, int | Fraction):
        raise TypeError("expected int or Fraction")
    return Fraction(x)


def supply_capped_score(
    score: int | Fraction,
    balance: int | Fraction,
    total_supply: int,
    supply_cap: Fraction = SUPPLY_CAP_DEFAULT,
) -> Fraction:
    """Score computed on min(B, supply_cap·S): s · min(1, supply_cap·S / B), exact.

    The score is linear in the balance held (COIN_MATH §3/§6), so scaling it by the fraction of
    the balance that counts is the same as scoring the capped balance.
    """
    s, b = _frac(score), _frac(balance)
    if s < 0 or b < 0 or total_supply <= 0 or not (0 < supply_cap <= 1):
        raise ValueError("score, balance >= 0, total_supply > 0, supply_cap in (0, 1]")
    limit = supply_cap * total_supply
    return s if b <= limit else s * limit / b


def linear_weights(scores: Mapping[ClusterId, int | Fraction]) -> dict[ClusterId, int]:
    """Integer weights proportional to score: w_c = s_c · D with D = lcm(denominators), exact.

    If the exact total would reach 2^128 (sampler domain), use w_c = floor(s_c · 2^120 / Σs):
    relative error < 2^-120 per group. Zero scores are dropped.
    """
    live = {c: _frac(s) for c, s in scores.items() if _frac(s) > 0}
    if not live:
        return {}
    d = lcm(*(s.denominator for s in live.values()))
    exact = {c: s.numerator * (d // s.denominator) for c, s in live.items()}
    if sum(exact.values()) < _WEIGHT_LIMIT:
        return exact
    total = sum(live.values(), Fraction(0))
    scaled = {c: (s * (1 << _SCALE_BITS) / total).__floor__() for c, s in live.items()}
    return {c: w for c, w in scaled.items() if w > 0}


@dataclass(frozen=True)
class DrawPlan:
    drawn: bool
    winners: tuple[ClusterId, ...]
    prizes: dict[ClusterId, int]  # lamports (base units of the pot), floor
    rollover: int  # pot units not paid out (kept in the draw pot)
    reason: str  # "ok" | "below_min_pot" | "no_eligible" | "too_few_groups"
    eligible: int = 0


def eligible_groups(
    scores: Mapping[ClusterId, int | Fraction],
    balances: Mapping[ClusterId, int | Fraction],
    total_supply: int,
    min_holding_share: Fraction = MIN_HOLDING_SHARE_DEFAULT,
) -> set[ClusterId]:
    """Score > 0 (lots ≥ T_START old) and balance ≥ min_holding_share · S (COIN_MATH §9)."""
    return {
        c
        for c, s in scores.items()
        if _frac(s) > 0
        and is_draw_eligible(
            1, 1, _frac(balances.get(c, 0)), total_supply, min_draw_share=min_holding_share
        )
    }


def min_groups_required(min_groups: int, cap: Fraction) -> int:
    """At least `min_groups` and strictly more than 1/cap, so the odds cap can always hold."""
    return max(min_groups, int(1 / cap) + 1)


def draw_weights(
    scores: Mapping[ClusterId, int | Fraction],
    balances: Mapping[ClusterId, int | Fraction],
    total_supply: int,
    *,
    cap: Fraction = CAP_DEFAULT,
    supply_cap: Fraction = SUPPLY_CAP_DEFAULT,
    min_holding_share: Fraction = MIN_HOLDING_SHARE_DEFAULT,
) -> dict[ClusterId, int]:
    """Eligible → supply cap → linear integer weights → 5% odds cap. Empty if none eligible."""
    ok = eligible_groups(scores, balances, total_supply, min_holding_share)
    capped = {c: supply_capped_score(scores[c], balances[c], total_supply, supply_cap) for c in ok}
    return cap_weights(linear_weights(capped), cap)


def plan_hourly_draw(
    scores: Mapping[ClusterId, int | Fraction],
    pot: int,
    prize_bps: tuple[int, ...],
    *,
    balances: Mapping[ClusterId, int | Fraction],
    total_supply: int,
    genesis_hash: bytes,
    mint: bytes,
    draw_index: int,
    snapshot_hash: bytes,
    rho: bytes,
    cap: Fraction = CAP_DEFAULT,
    supply_cap: Fraction = SUPPLY_CAP_DEFAULT,
    min_holding_share: Fraction = MIN_HOLDING_SHARE_DEFAULT,
    min_groups: int = MIN_GROUPS_DEFAULT,
    min_pot: int = MIN_POT_LAMPORTS_DEFAULT,
) -> DrawPlan:
    """One hourly draw. Σ prizes + rollover == pot always (conservation)."""
    if pot < 0 or any(b <= 0 for b in prize_bps) or sum(prize_bps) > _BPS:
        raise ValueError("pot >= 0, prize_bps > 0 and summing to <= 10_000")
    if total_supply <= 0 or min_groups < 1:
        raise ValueError("total_supply > 0 and min_groups >= 1")
    if pot < min_pot:
        return DrawPlan(False, (), {}, pot, "below_min_pot")
    ok = eligible_groups(scores, balances, total_supply, min_holding_share)
    if not ok:
        return DrawPlan(False, (), {}, pot, "no_eligible")
    if len(ok) < min_groups_required(min_groups, cap):
        return DrawPlan(False, (), {}, pot, "too_few_groups", len(ok))
    weights = draw_weights(
        {c: scores[c] for c in ok},
        balances,
        total_supply,
        cap=cap,
        supply_cap=supply_cap,
        min_holding_share=min_holding_share,
    )
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
    return DrawPlan(True, tuple(winners), prizes, pot - sum(prizes.values()), "ok", len(ok))


def plan_sol_prize(
    balances: Mapping[ClusterId, int],
    hold_seconds: Mapping[ClusterId, int],
    pot: int,
    *,
    total_supply: int,
    genesis_hash: bytes,
    mint: bytes,
    draw_index: int,
    snapshot_hash: bytes,
    rho: bytes,
    enabled: bool = False,
    min_pot: int = SOL_PRIZE_MIN_LAMPORTS,
    min_groups: int = MIN_GROUPS_DEFAULT,
    cap: Fraction = CAP_DEFAULT,
) -> DrawPlan:
    """One SOL prize for one winner. Off by default (`coming_soon`): the pot rolls over.

    Odds use `loyalty_scores` (the same multiplier as holder rewards). A pot below
    0.1 SOL rolls over. Σ prize + rollover == pot.
    """
    if isinstance(pot, bool) or not isinstance(pot, int) or pot < 0:
        raise ValueError("pot must be an int >= 0")
    if not enabled:
        return DrawPlan(False, (), {}, pot, DRAW_COMING_SOON)
    return plan_hourly_draw(
        loyalty_scores(balances, hold_seconds),
        pot,
        (_BPS,),  # single prize: the winner takes the pot
        balances=balances,
        total_supply=total_supply,
        genesis_hash=genesis_hash,
        mint=mint,
        draw_index=draw_index,
        snapshot_hash=snapshot_hash,
        rho=rho,
        min_pot=min_pot,
        min_groups=min_groups,
        cap=cap,
    )

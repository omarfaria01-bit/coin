"""Hold multiplier, churn discount, underwater boost, score (COIN_MATH §3-6). Owner: Grok."""

from __future__ import annotations

import math
from collections.abc import Sequence

from engine.params import ChurnParams, HoldParams, UnderwaterParams
from engine.types import Lot, LotSource

_DAY = 86_400
_EPS = 1.0  # one token base unit, as in ENGINE_DESIGN / the issue spec


def hold_multiplier(age_days: float, p: HoldParams) -> float:
    """h(a) = 1 + min(1, ln(1+a) / ln(1+horizon_days))."""
    age = max(0.0, age_days)
    return 1.0 + min(1.0, math.log(1.0 + age) / math.log(1.0 + p.horizon_days))


def amount_weighted_hold(lots: Sequence[Lot], t: int, p: HoldParams) -> float:
    """H = Σ amount·h(age) / Σ amount, at time t. 1.0 for no lots."""
    total = 0
    weighted = 0.0
    for lot in lots:
        if lot.amount <= 0:
            continue
        age_days = (t - lot.t_acquired) / _DAY
        total += lot.amount
        weighted += lot.amount * hold_multiplier(age_days, p)
    if total == 0:
        return 1.0
    return weighted / total


def churn_factor(v_buy: int, v_sell: int, twab_balance: float, p: ChurnParams) -> float:
    """F = 1 / (1 + κ · min(v_buy, v_sell) / max(twab, ε))."""
    chi = min(v_buy, v_sell) / max(twab_balance, _EPS)
    return 1.0 / (1.0 + p.kappa * chi)


def underwater_boost(lots: Sequence[Lot], twap: float, t: int, p: UnderwaterParams) -> float:
    """U = 1 + β · min(D, D_max) / D_max over POOL_BUY lots aged ≥ min_age_hours."""
    if twap <= 0:
        raise ValueError(f"twap must be > 0, got {twap}")
    min_age = p.min_age_hours * 3600.0
    weighted_d = 0.0
    total = 0
    for lot in lots:
        if lot.source is not LotSource.POOL_BUY or lot.cost_lamports_per_token <= 0:
            continue
        if t - lot.t_acquired < min_age or lot.amount <= 0:
            continue
        drawdown = max(0.0, 1.0 - twap / lot.cost_lamports_per_token)
        weighted_d += lot.amount * drawdown
        total += lot.amount
    if total == 0:
        return 1.0
    d_bar = weighted_d / total
    return 1.0 + p.beta * min(d_bar, p.d_max) / p.d_max


def score(twab_balance: float, hold: float, churn: float, boost: float) -> float:
    """s = B̄ · H · F · U."""
    if twab_balance < 0 or hold < 0 or churn < 0 or boost < 0:
        raise ValueError("score inputs must be >= 0")
    return twab_balance * hold * churn * boost

"""Hold multiplier, churn discount, underwater boost, score (COIN_MATH §3-6). Owner: Claude."""

from __future__ import annotations

from collections.abc import Sequence

from engine.params import ChurnParams, HoldParams, UnderwaterParams
from engine.types import Lot


def hold_multiplier(age_days: float, p: HoldParams) -> float:
    """h(a) = 1 + min(1, ln(1+a) / ln(1+horizon_days))."""
    raise NotImplementedError


def amount_weighted_hold(lots: Sequence[Lot], t: int, p: HoldParams) -> float:
    """H = Σ amount·h(age) / Σ amount, at time t. 1.0 for no lots."""
    raise NotImplementedError


def churn_factor(v_buy: int, v_sell: int, twab_balance: float, p: ChurnParams) -> float:
    """F = 1 / (1 + κ · min(v_buy, v_sell) / max(twab, ε))."""
    raise NotImplementedError


def underwater_boost(lots: Sequence[Lot], twap: float, t: int, p: UnderwaterParams) -> float:
    """U = 1 + β · min(D, D_max) / D_max over POOL_BUY lots aged ≥ min_age_hours."""
    raise NotImplementedError


def score(twab_balance: float, hold: float, churn: float, boost: float) -> float:
    """s = B̄ · H · F · U."""
    raise NotImplementedError

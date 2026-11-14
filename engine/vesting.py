"""Price-weighted vesting and soft-mode forfeits (COIN_MATH §11). Owner: Grok."""

from __future__ import annotations

import math
from decimal import ROUND_DOWN, Decimal, localcontext

from engine.params import VestingParams

_DEC_PREC = 80
_DAY = 86_400


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def unlocked_fraction(
    prev: float, t: int, t0: int, twap: float, p_entry: float, p: VestingParams
) -> float:
    """max(prev, u_time, u_price); monotone, in [0, 1]."""
    u_time = _clamp((t - t0) / (p.t_v_days * _DAY), 0.0, 1.0)
    ratio = twap / p_entry if p_entry > 0 else 0.0
    u_price = 0.0 if ratio <= 0 else _clamp(math.log(ratio) / math.log(p.m), 0.0, 1.0)
    return _clamp(max(prev, u_time, u_price), 0.0, 1.0)


def locked_amount(vested_amount: int, unlocked: float) -> int:
    """ceil((1 - unlocked) · vested_amount), so rounding never unlocks early.

    For integer vested, this equals vested - floor(unlocked · vested). unlocked=0
    returns exactly vested. Results are clamped to [0, vested].
    """
    if vested_amount < 0:
        raise ValueError(f"vested_amount must be >= 0, got {vested_amount}")
    frac = _clamp(unlocked, 0.0, 1.0)
    with localcontext() as ctx:
        ctx.prec = _DEC_PREC
        floored = (Decimal(str(frac)) * Decimal(vested_amount)).to_integral_value(
            rounding=ROUND_DOWN
        )
    locked = vested_amount - int(floored)
    return 0 if locked < 0 else vested_amount if locked > vested_amount else locked


def breaches_soft_lock(balance_after_outflow: int, locked: int) -> bool:
    """Soft mode: any outflow (sell OR transfer) that leaves balance < locked is a breach."""
    return balance_after_outflow < locked

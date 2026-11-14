"""Price-weighted vesting and soft-mode forfeits (COIN_MATH §11). Owner: Grok."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_DOWN, Decimal, localcontext
from fractions import Fraction

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


# ---------------------------------------------------------------------------
# COIN_MATH v0.3.3 §11. Linear u_price on the 24h harmonic mean.
# This supersedes D14 (log unlock + arithmetic TWAP) and the 36h follow-up.
# Keep unlocked_fraction (v0.2) above unchanged until epoch is rewired.
# ---------------------------------------------------------------------------

_HOUR = 3_600


def _as_frac(value: int | Fraction) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, int | Fraction):
        raise TypeError("value must be an int or Fraction")
    return value if isinstance(value, Fraction) else Fraction(value)


def _clamp_frac(value: Fraction, lo: Fraction, hi: Fraction) -> Fraction:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def harmonic_mean(prices: Sequence[int | Fraction]) -> Fraction:
    """Equal-weight harmonic mean of strictly positive prices."""
    if not prices:
        raise ValueError("prices must be non-empty")
    acc = Fraction(0)
    for raw in prices:
        price = _as_frac(raw)
        if price <= 0:
            raise ValueError("prices must be > 0")
        acc += 1 / price
    return Fraction(len(prices), 1) / acc


def u_price_linear(
    p_harmonic: int | Fraction, p_entry: int | Fraction, m: int | Fraction
) -> Fraction:
    """u_price = clamp((P̃_h / P_entry − 1) / (M − 1), 0, 1). Each +1× unlocks 1/(M−1)."""
    mean = _as_frac(p_harmonic)
    entry = _as_frac(p_entry)
    cap = _as_frac(m)
    if cap <= 1:
        raise ValueError("M must be > 1")
    if entry <= 0 or mean <= 0:
        return Fraction(0)
    ratio = mean / entry
    return _clamp_frac((ratio - 1) / (cap - 1), Fraction(0), Fraction(1))


def unlocked_fraction_v033(
    prev: int | Fraction,
    t: int,
    t0: int,
    p_harmonic: int | Fraction,
    p_entry: int | Fraction,
    p: VestingParams,
    *,
    window_trusted: bool = True,
) -> Fraction:
    """max(prev, u_time, u_price); u_price only if t ≥ t0 + 24h and the window is trusted."""
    prior = _as_frac(prev)
    if prior < 0 or prior > 1:
        prior = _clamp_frac(prior, Fraction(0), Fraction(1))
    horizon = int(Fraction(str(p.t_v_days)) * _DAY)
    if horizon <= 0:
        raise ValueError("t_v_days must be > 0")
    elapsed = t - t0
    u_time = _clamp_frac(
        Fraction(elapsed, horizon) if elapsed > 0 else Fraction(0), Fraction(0), Fraction(1)
    )
    window_s = int(Fraction(str(p.unlock_twap_hours)) * _HOUR)
    u_price = Fraction(0)
    if window_trusted and elapsed >= window_s:
        u_price = u_price_linear(p_harmonic, p_entry, Fraction(str(p.m)))
    return _clamp_frac(max(prior, u_time, u_price), Fraction(0), Fraction(1))

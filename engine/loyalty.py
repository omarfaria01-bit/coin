"""Loyalty multiplier for GTASP10 rewards and the SOL draw (D43).

One pure function, used by both. 0 before 1 hour. 1× on [1h, 1h30]. Piecewise
linear through 1.5× at 1h45, 2× at 2h, 3× at 2h30, 4× at 3h and 5× at 4h.
After 4h it grows with the logarithm of hold time and caps at 10× at 30 days.
Integers and Fractions only. No I/O and no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction

HOUR = 3_600
DAY = 86_400
T_START = HOUR
T_4H = 4 * HOUR
T_CAP = 30 * DAY
CAP = Fraction(10)
_LOG_SCALE = 10**9  # log branch shares one denominator so draw weights stay bounded

# Flat 1× from 1h through 1h30, then the named steps. Linear between them.
_KNOTS: tuple[tuple[int, Fraction], ...] = (
    (HOUR, Fraction(1)),
    (90 * 60, Fraction(1)),
    (105 * 60, Fraction(3, 2)),
    (2 * HOUR, Fraction(2)),
    (150 * 60, Fraction(3)),
    (3 * HOUR, Fraction(4)),
    (T_4H, Fraction(5)),
)

# ln(2), error < 10^-36. Combined with the artanh cutoff this stays well inside
# the gap ln(n+1) - ln(n) on every age the curve evaluates.
_LN2 = Fraction(281788184111715588, 406534415799078269)
_SERIES_TERMS = 20


def _ln(n: int) -> Fraction:
    """Natural log of a positive integer, truncated artanh series after a power-of-two reduction."""
    if n <= 0:
        raise ValueError("ln argument must be positive")
    if n == 1:
        return Fraction(0)
    k = n.bit_length() - 1
    base = 1 << k
    y = Fraction(n - base, n + base)  # in [0, 1/3)
    y2 = y * y
    term = y
    acc = term
    for i in range(1, _SERIES_TERMS):
        term *= y2
        acc += term / (2 * i + 1)
    return k * _LN2 + 2 * acc


def _lerp(age: int) -> Fraction:
    if age <= _KNOTS[0][0]:
        return _KNOTS[0][1]
    for i in range(len(_KNOTS) - 1):
        a0, h0 = _KNOTS[i]
        a1, h1 = _KNOTS[i + 1]
        if a0 <= age <= a1:
            return h0 + (h1 - h0) * Fraction(age - a0, a1 - a0)
    return _KNOTS[-1][1]


def loyalty_multiplier(hold_seconds: int) -> Fraction:
    """h(hold): 0 below 1h, the knot table through 5× at 4h, then log to 10× at 30 days."""
    if isinstance(hold_seconds, bool) or not isinstance(hold_seconds, int):
        raise TypeError("hold_seconds must be an int")
    if hold_seconds < 0:
        raise ValueError(f"hold_seconds must be >= 0, got {hold_seconds}")
    if hold_seconds < T_START:
        return Fraction(0)
    if hold_seconds <= T_4H:
        return _lerp(hold_seconds)
    if hold_seconds >= T_CAP:
        return CAP
    # 5 + 5 · ln(t / 4h) / ln(30d / 4h). Endpoints are handled above.
    extra = 5 * (_ln(hold_seconds) - _ln(T_4H)) / (_ln(T_CAP) - _ln(T_4H))
    snapped = Fraction(int(extra * _LOG_SCALE), _LOG_SCALE)  # floor; monotone
    if snapped <= 0:
        return Fraction(5)
    if snapped >= 5:
        return CAP
    return Fraction(5) + snapped


def loyalty_weight(balance: int, hold_seconds: int) -> Fraction:
    """Balance counted at `loyalty_multiplier`. Rewards and the draw both use this."""
    if isinstance(balance, bool) or not isinstance(balance, int):
        raise TypeError("balance must be an int")
    if balance < 0:
        raise ValueError(f"balance must be >= 0, got {balance}")
    return Fraction(balance) * loyalty_multiplier(hold_seconds)


def loyalty_scores(
    balances: Mapping[str, int], hold_seconds: Mapping[str, int]
) -> dict[str, Fraction]:
    """One score per id. A missing hold counts as 0, so it earns nothing."""
    return {
        key: loyalty_weight(int(balances.get(key, 0)), int(hold_seconds.get(key, 0)))
        for key in set(balances) | set(hold_seconds)
    }

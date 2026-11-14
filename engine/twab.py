"""Time-weighted average balance, exact (COIN_MATH §2). Owner: Grok."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction


def twab_exact(
    start_balance: int, changes: Sequence[tuple[int, int]], t0: int, t1: int
) -> Fraction:
    """Exact integral of a piecewise-constant balance over [t0, t1) divided by (t1 - t0).

    `changes` are (ts, new_balance) pairs sorted by ts; entries outside [t0, t1) are ignored
    except that the last one before t0 sets the starting balance if given.
    """
    if t1 <= t0:
        raise ValueError(f"t1 must be > t0, got t0={t0} t1={t1}")
    balance = start_balance
    last_pre: int | None = None
    window: dict[int, int] = {}
    for ts, new_balance in changes:
        if ts < t0:
            if last_pre is None or ts >= last_pre:
                balance = new_balance
                last_pre = ts
        elif ts < t1:
            window[ts] = new_balance
    numerator = 0
    cursor = t0
    for ts, new_balance in sorted(window.items()):
        numerator += balance * (ts - cursor)
        balance = new_balance
        cursor = ts
    numerator += balance * (t1 - cursor)
    return Fraction(numerator, t1 - t0)

"""Time-weighted average balance, exact (COIN_MATH §2). Owner: Claude."""

from __future__ import annotations

from collections.abc import Sequence


def twab(start_balance: int, changes: Sequence[tuple[int, int]], t0: int, t1: int) -> float:
    """Exact integral of a piecewise-constant balance over [t0, t1) divided by (t1 - t0).

    `changes` are (ts, new_balance) pairs sorted by ts; entries outside [t0, t1) are ignored
    except that the last one before t0 sets the starting balance if given.
    """
    raise NotImplementedError

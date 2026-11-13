"""Price-weighted vesting and soft-mode forfeits (COIN_MATH §11). Owner: Claude."""

from __future__ import annotations

from engine.params import VestingParams


def unlocked_fraction(
    prev: float, t: int, t0: int, twap: float, p_entry: float, p: VestingParams
) -> float:
    """max(prev, u_time, u_price); monotone, in [0, 1]."""
    raise NotImplementedError


def locked_amount(vested_amount: int, unlocked: float) -> int:
    """ceil((1 - unlocked) · vested_amount), so rounding never unlocks early."""
    raise NotImplementedError


def breaches_soft_lock(balance_after_outflow: int, locked: int) -> bool:
    """Soft mode: any outflow (sell OR transfer) that leaves balance < locked is a breach."""
    raise NotImplementedError

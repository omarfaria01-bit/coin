"""Tests for engine/twab.py (COIN_MATH §2, ENGINE_DESIGN §1)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.twab import twab

EPOCH = 24 * 3600  # 24h in seconds


def test_constant_balance_and_boundaries() -> None:
    assert twab(42, [], 0, 10) == 42.0
    # Change at t0 applies for the whole window; change at t1 is ignored.
    assert twab(100, [(0, 200), (100, 300)], 0, 100) == 200.0
    assert twab(5, [(10, 999)], 0, 10) == 5.0
    # Last change with ts < t0 is the opening balance; earlier pre-t0 is overwritten.
    assert twab(1, [(-8, 3), (-1, 9), (20, 99)], 0, 10) == 9.0


def test_same_ts_last_change_wins() -> None:
    assert twab(0, [(5, 10), (5, 20)], 0, 10) == twab(0, [(5, 20)], 0, 10) == 10.0
    # Last in input order wins, even if the list is not pre-sorted.
    assert twab(0, [(8, 1), (3, 9), (3, 4)], 0, 10) == twab(0, [(3, 4), (8, 1)], 0, 10)


def test_sniper_5min_weight_at_most_half_percent() -> None:
    # COIN_MATH §14 row 3: 5 min / 1440 min ≈ 0.347% ≤ 0.5%.
    bal = 1_000_000
    got = twab(0, [(EPOCH - 300, bal)], 0, EPOCH)
    assert got == bal * 300 / EPOCH
    assert got / bal <= 0.005


def test_t1_le_t0_raises() -> None:
    with pytest.raises(ValueError, match="t1"):
        twab(0, [], 5, 5)
    with pytest.raises(ValueError, match="t1"):
        twab(0, [], 5, 4)


def _opening_and_window(start: int, changes: list[tuple[int, int]], t0: int, t1: int) -> list[int]:
    balance = start
    last_pre: int | None = None
    window: dict[int, int] = {}
    for ts, new in changes:
        if ts < t0:
            if last_pre is None or ts >= last_pre:
                balance = new
                last_pre = ts
        elif ts < t1:
            window[ts] = new
    return [balance, *(new for _, new in sorted(window.items()))]


@given(
    st.integers(min_value=0, max_value=10**12),
    st.lists(st.tuples(st.integers(-80, 200), st.integers(0, 10**12)), max_size=25),
    st.integers(-20, 80),
    st.integers(1, 200),
)
@settings(max_examples=80, deadline=None)
def test_twab_within_seen_balance_bounds(
    start: int, changes: list[tuple[int, int]], t0: int, span: int
) -> None:
    t1 = t0 + span
    seen = _opening_and_window(start, changes, t0, t1)
    got = twab(start, changes, t0, t1)
    assert min(seen) <= got <= max(seen)
    # Numerator is exact; a one-step window of 1 second equals the opening or in-window bal.
    if span == 1 and not any(t0 <= ts < t1 for ts, _ in changes):
        assert got == float(seen[0])

"""Tests for the v0.3.3 hold curve and E1/E2 integrators (COIN_MATH §3–4)."""

from __future__ import annotations

from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.scoring import (
    _DAY,
    DEFAULT_BOOST_AGE_SECONDS,
    DEFAULT_T_START_SECONDS,
    HOUR,
    h_of_age,
    lot_epoch_parts,
    sum_h_of_age,
)

KNOT_TABLE = (
    (0, Fraction(0)),
    (DEFAULT_T_START_SECONDS - 1, Fraction(0)),
    (1 * HOUR, Fraction(1)),
    (90 * 60, Fraction(1)),
    (105 * 60, Fraction(3, 2)),
    (2 * HOUR, Fraction(2)),
    (150 * 60, Fraction(3)),
    (3 * HOUR, Fraction(4)),
    (4 * HOUR, Fraction(5)),
    (24 * HOUR, Fraction(5)),
    (90 * _DAY, Fraction(5)),
)


def test_knot_table_and_t_start_discontinuity() -> None:
    for age, expected in KNOT_TABLE:
        assert h_of_age(age) == expected
    # Not a ramp from 0: one second under T_START is exactly 0, then it jumps to the 1h knot.
    assert DEFAULT_T_START_SECONDS == 1 * HOUR
    assert h_of_age(DEFAULT_T_START_SECONDS) == 1
    assert h_of_age(DEFAULT_T_START_SECONDS - 1) == 0
    # Linear between knots: 1h30 -> 1h45 is 1 -> 1.5, so 1h37m30s is 1.25; 3h30 is 4.5.
    assert h_of_age(97 * 60 + 30) == Fraction(5, 4)
    assert h_of_age(210 * 60) == Fraction(9, 2)
    # A later start is still available as a variant and does not change the default table.
    assert h_of_age(2 * HOUR, t_start_seconds=6 * HOUR) == 0
    assert h_of_age(6 * HOUR, t_start_seconds=6 * HOUR) == 5
    mid_curve = (
        (12 * HOUR, Fraction(1)),
        (24 * HOUR, Fraction(21, 20)),  # 1.05
        (7 * _DAY, Fraction(3, 2)),
        (30 * _DAY, Fraction(2)),
        (90 * _DAY, Fraction(47, 20)),  # 2.35
    )
    assert h_of_age(90 * _DAY, knots=mid_curve, t_start_seconds=12 * HOUR) == Fraction(47, 20)
    assert h_of_age(2 * HOUR) == 2  # default unchanged


@given(st.integers(-100, 200 * _DAY), st.integers(-100, 200 * _DAY))
@settings(max_examples=80, deadline=None)
def test_h_nondecreasing_and_bounded(a: int, b: int) -> None:
    lo, hi = (a, b) if a <= b else (b, a)
    h_lo, h_hi = h_of_age(lo), h_of_age(hi)
    assert h_lo <= h_hi
    assert Fraction(0) <= h_lo <= Fraction(5)
    assert Fraction(0) <= h_hi <= Fraction(5)


def test_sum_h_matches_second_by_second_on_a_short_window() -> None:
    # A 3-hour window from 30 minutes before T_START to 2.5h after, crossing every knot.
    age_lo, age_hi = HOUR // 2, 3 * HOUR
    closed = sum_h_of_age(age_lo, age_hi)
    slow = sum((h_of_age(a) for a in range(age_lo, age_hi)), Fraction(0))
    assert closed == slow
    # Empty / all-under-T_START windows are zero.
    assert sum_h_of_age(0, HOUR) == 0
    assert sum_h_of_age(10, 10) == 0
    # After 4h the sum is just n · 5.
    start = 4 * HOUR
    assert sum_h_of_age(start, start + 100) == 100 * Fraction(5)


def test_e1_e2_split_taint_and_zero_below_t_start() -> None:
    amount = 100
    t0, t1 = 0, 24 * HOUR
    # Acquired at t0: ages 0..24h over the epoch. First 1h (T_START) score 0; rest is E1; no E2.
    e1, e2 = lot_epoch_parts(amount, t_acquired=0, t0=t0, t1=t1)
    assert e2 == 0
    expected_e1 = Fraction(amount, t1 - t0) * sum_h_of_age(0, 24 * HOUR)
    assert e1 == expected_e1
    assert e1 > 0
    # A bag sold at 30 minutes (window ends before T_START) scores 0.
    e1_short, e2_short = lot_epoch_parts(amount, t_acquired=0, t0=0, t1=30 * 60)
    assert e1_short == 0 and e2_short == 0
    # Acquired 48h before t0: the whole epoch is E2.
    acquired = t0 - DEFAULT_BOOST_AGE_SECONDS
    e1_old, e2_old = lot_epoch_parts(amount, t_acquired=acquired, t0=t0, t1=t1)
    assert e1_old == 0
    assert e2_old == Fraction(amount, t1 - t0) * sum_h_of_age(t0 - acquired, t1 - acquired)
    assert e2_old > 0
    # Taint excludes the first 9 hours of the epoch (past the 1h start).
    e1_t, e2_t = lot_epoch_parts(amount, t_acquired=0, t0=t0, t1=t1, tainted_until=9 * HOUR)
    assert e2_t == 0
    assert e1_t == Fraction(amount, t1 - t0) * sum_h_of_age(9 * HOUR, 24 * HOUR)
    assert e1_t < e1
    # Zero amount / empty epoch.
    assert lot_epoch_parts(0, 0, 0, t1) == (0, 0)
    assert lot_epoch_parts(amount, 0, 10, 10) == (0, 0)


def test_lot_epoch_parts_matches_naive_sum_across_the_48h_split() -> None:
    amount = 7
    t0, t1 = 0, 6 * HOUR
    acquired = t0 - (47 * HOUR)  # ages 47h .. 53h, crosses the 48h split
    e1, e2 = lot_epoch_parts(amount, t_acquired=acquired, t0=t0, t1=t1)
    e = t1 - t0
    naive_e1 = naive_e2 = Fraction(0)
    for t in range(t0, t1):
        age = t - acquired
        contrib = Fraction(amount, e) * h_of_age(age)
        if DEFAULT_T_START_SECONDS <= age < DEFAULT_BOOST_AGE_SECONDS:
            naive_e1 += contrib
        elif age >= DEFAULT_BOOST_AGE_SECONDS:
            naive_e2 += contrib
    assert e1 == naive_e1
    assert e2 == naive_e2
    assert e1 > 0 and e2 > 0

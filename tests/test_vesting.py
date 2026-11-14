"""Price-weighted vesting is monotone; locked amount never unlocks early (§11, §14 row 5)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.params import VestingParams
from engine.vesting import breaches_soft_lock, locked_amount, unlocked_fraction

P = VestingParams()
_LN2_LN5 = math.log(2) / math.log(5)
_DAY = 86_400


def test_unlock_at_2x_5x_and_after_seven_days() -> None:
    t0, entry = 0, 100.0
    at_2x = unlocked_fraction(0.0, t0, t0, 2 * entry, entry, P)
    assert at_2x == pytest.approx(_LN2_LN5, abs=1e-9)
    assert at_2x == pytest.approx(0.430676558, abs=1e-9)
    assert unlocked_fraction(0.0, t0, t0, 5 * entry, entry, P) == 1.0
    # Time alone unlocks fully after T_v, even if price dumped.
    t_end = t0 + int(P.t_v_days * _DAY)
    assert unlocked_fraction(0.0, t_end, t0, 0.1 * entry, entry, P) == 1.0
    assert unlocked_fraction(0.0, t_end - 1, t0, 0.0, entry, P) < 1.0


def test_price_dump_and_non_positive_twap_do_not_unlock() -> None:
    t0, entry = 0, 50.0
    up = unlocked_fraction(0.0, t0, t0, 2 * entry, entry, P)
    assert unlocked_fraction(up, t0 + 3600, t0, 0.5 * entry, entry, P) == up
    assert unlocked_fraction(0.0, t0, t0, 0.0, entry, P) == 0.0
    assert unlocked_fraction(0.0, t0, t0, 100.0, 0.0, P) == 0.0
    assert unlocked_fraction(0.25, t0, t0, -1.0, entry, P) == 0.25


def test_locked_amount_zero_unlock_is_exact_and_ceils() -> None:
    assert locked_amount(1_000, 0.0) == 1_000
    assert locked_amount(1_000, 1.0) == 0
    # 0.01 of 10 would floor to 0 unlocked tokens; ceil keeps all 10 locked.
    assert locked_amount(10, 0.01) == 10
    assert locked_amount(7, 0.5) == 4  # ceil(3.5)
    assert locked_amount(0, 0.3) == 0
    with pytest.raises(ValueError, match="vested"):
        locked_amount(-1, 0.0)


def test_breaches_soft_lock() -> None:
    assert breaches_soft_lock(9, 10) is True
    assert breaches_soft_lock(10, 10) is False
    assert breaches_soft_lock(11, 10) is False


def test_one_hour_3x_pump_on_6h_twap() -> None:
    # §14 row 5 proxy: 5h at entry, 1h at 3× → TWAP = (5·1 + 1·3)/6 = 4/3 · entry.
    # ln(4/3)/ln(5) ≈ 0.1787, which is *not* < 5% at default M=5, UNLOCK_TWAP_H=6.
    # COIN_MATH §11 already flags this: if it fails, raise the window or M (DECISIONS).
    entry = 100.0
    twap = (5 * entry + 1 * 3 * entry) / 6
    assert twap / entry == pytest.approx(4 / 3)
    got = unlocked_fraction(0.0, 0, 0, twap, entry, P)
    expect = math.log(4 / 3) / math.log(5)
    assert got == pytest.approx(expect, abs=1e-12)
    # A 24h window would bring a 1h 3× pump under 5% (ln(1+2/24)/ln(5) ≈ 0.0494).
    twap24 = (23 * entry + 1 * 3 * entry) / 24
    slow = unlocked_fraction(0.0, 0, 0, twap24, entry, P)
    assert slow < 0.05


@given(
    st.lists(
        st.tuples(
            st.integers(0, 14 * _DAY),
            st.floats(0, 1e6, allow_nan=False, allow_infinity=False),
        ),
        min_size=1,
        max_size=30,
    ),
    st.floats(0.01, 1e6, allow_nan=False, allow_infinity=False),
    st.integers(1, 10**12),
)
@settings(max_examples=60, deadline=None)
def test_unlock_is_monotone_and_locked_never_increases(
    steps: list[tuple[int, float]], p_entry: float, vested: int
) -> None:
    prev = 0.0
    prev_locked = locked_amount(vested, prev)
    t0 = 0
    for t, twap in steps:
        prev = unlocked_fraction(prev, t, t0, twap, p_entry, P)
        assert 0.0 <= prev <= 1.0
        locked = locked_amount(vested, prev)
        assert 0 <= locked <= vested
        assert locked <= prev_locked
        prev_locked = locked

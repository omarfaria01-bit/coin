"""Tests for v0.3.3 linear vesting on the 24h harmonic mean (COIN_MATH §11)."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.params import VestingParams
from engine.vesting import harmonic_mean, u_price_linear, unlocked_fraction, unlocked_fraction_v033

P = VestingParams()
DAY = 86_400
HOUR = 3_600
ENTRY = 100


def test_plus_one_x_unlocks_twenty_five_percent() -> None:
    assert u_price_linear(2 * ENTRY, ENTRY, 5) == Fraction(1, 4)
    assert u_price_linear(5 * ENTRY, ENTRY, 5) == 1
    assert u_price_linear(ENTRY, ENTRY, 5) == 0
    assert u_price_linear(ENTRY // 2, ENTRY, 5) == 0
    assert u_price_linear(3 * ENTRY, ENTRY, 5) == Fraction(1, 2)
    # 4× is 75%.
    assert u_price_linear(4 * ENTRY, ENTRY, 5) == Fraction(3, 4)


def test_harmonic_mean_and_one_hour_3x_pump_bound() -> None:
    # 23h at entry + 1h at 3×: H = 24 / (23/P + 1/(3P)) = 36/35 · P.
    prices = [ENTRY] * 23 + [3 * ENTRY]
    mean = harmonic_mean(prices)
    assert mean == Fraction(36, 35) * ENTRY
    # From a flat price, unlock change is (r − 1)/(M − 1) = (1/35)/4 = 1/140 < 5%.
    # The analytical pump bound P̃_h ≤ (24/23)·H_rest is saturated when the
    # pumped hour → ∞; here the 3× hour is well inside that bound.
    assert mean < 24 / 23 * ENTRY
    u = u_price_linear(mean, ENTRY, 5)
    assert u == Fraction(1, 140)
    assert u < Fraction(1, 20)
    with pytest.raises(ValueError, match="non-empty"):
        harmonic_mean([])
    with pytest.raises(ValueError, match="> 0"):
        harmonic_mean([ENTRY, 0])


def test_price_gate_and_dump_do_not_unlock() -> None:
    t0 = 0
    # Before 24h, even a 5× harmonic mean is ignored; only time unlocks.
    early = unlocked_fraction_v033(0, t0 + 23 * HOUR, t0, 5 * ENTRY, ENTRY, P)
    assert early == Fraction(23 * HOUR, 7 * DAY)
    assert early < Fraction(1, 4)
    # Untrusted window: price skipped at t = t0 + 24h.
    untrusted = unlocked_fraction_v033(
        0, t0 + 24 * HOUR, t0, 5 * ENTRY, ENTRY, P, window_trusted=False
    )
    assert untrusted == Fraction(24 * HOUR, 7 * DAY)
    # Trusted 24h window at 5×: fully unlocked by price.
    assert unlocked_fraction_v033(0, t0 + 24 * HOUR, t0, 5 * ENTRY, ENTRY, P) == 1
    # At 2× after the gate: exactly 25% (time unlock is 24h/7d < 25%).
    at_2x = unlocked_fraction_v033(0, t0 + 24 * HOUR, t0, 2 * ENTRY, ENTRY, P)
    assert at_2x == Fraction(1, 4)
    # A later dump does not reduce the unlock (monotone).
    after = unlocked_fraction_v033(at_2x, t0 + 25 * HOUR, t0, ENTRY // 5, ENTRY, P)
    assert after == at_2x
    # Time alone still unlocks fully at T_v, even if price dumped.
    t_end = t0 + 7 * DAY
    assert unlocked_fraction_v033(0, t_end, t0, ENTRY // 10, ENTRY, P) == 1


def test_v02_unlocked_fraction_is_unchanged() -> None:
    # The log path stays until epoch is rewired; 2× is still ln(2)/ln(5), not 25%.
    got = unlocked_fraction(0.0, 0, 0, 2 * 100.0, 100.0, P)
    assert got != 0.25
    assert got == pytest.approx(0.430676558, abs=1e-9)


@given(
    st.lists(st.integers(1, 10**6), min_size=1, max_size=40),
    st.integers(1, 10**6),
)
@settings(max_examples=60, deadline=None)
def test_harmonic_mean_between_min_and_max(prices: list[int], entry: int) -> None:
    mean = harmonic_mean(prices)
    assert min(prices) <= mean <= max(prices)
    u = u_price_linear(mean, entry, 5)
    assert 0 <= u <= 1

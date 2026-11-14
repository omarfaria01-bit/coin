"""Tests for engine/scoring.py (COIN_MATH §3–5 and the §6 product)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.params import ChurnParams, HoldParams, UnderwaterParams
from engine.scoring import (
    amount_weighted_hold,
    churn_factor,
    hold_multiplier,
    score,
    underwater_boost,
)
from engine.types import Lot, LotSource

HOLD = HoldParams()
CHURN = ChurnParams()
UNDER = UnderwaterParams()
DAY = 86_400
# 48h and one second under, for the min-age gate.
AGE_48H = 48 * 3600
AGE_47H59M = 47 * 3600 + 59 * 60

# Table from the issue / COIN_MATH §3, tolerance 0.005, default horizon 30d.
HOLD_TABLE = (
    (0, 1.00),
    (1, 1.20),
    (3, 1.40),
    (7, 1.61),
    (14, 1.79),
    (30, 2.00),
    (365, 2.00),
)


def lot(
    amount: int = 100,
    cost: float = 10.0,
    t_acquired: int = 0,
    source: LotSource = LotSource.POOL_BUY,
) -> Lot:
    return Lot(amount, cost, t_acquired, source)


def test_hold_multiplier_table_and_negative_age() -> None:
    for age, expected in HOLD_TABLE:
        assert hold_multiplier(age, HOLD) == pytest.approx(expected, abs=0.005)
    # Negative age is clamped to 0 → h = 1.
    assert hold_multiplier(-10, HOLD) == 1.0
    assert hold_multiplier(0, HOLD) == 1.0


def test_amount_weighted_hold_empty_and_mix() -> None:
    assert amount_weighted_hold([], 10_000, HOLD) == 1.0
    assert amount_weighted_hold([lot(amount=0)], 10_000, HOLD) == 1.0
    lots = [lot(amount=1, t_acquired=0), lot(amount=1, t_acquired=DAY)]
    t = 8 * DAY  # first lot 8d old, second 7d old
    got = amount_weighted_hold(lots, t, HOLD)
    expect = (hold_multiplier(8, HOLD) + hold_multiplier(7, HOLD)) / 2
    assert got == pytest.approx(expect)


def test_flipper_5x_per_day_for_48h_churn_at_most_tenth() -> None:
    # 5× balance per day over 48h → χ = 10, F = 1/(1+2·10) ≈ 0.0476 ≤ 0.10.
    twab = 1_000
    v_round_trip = 5 * twab * 2
    f = churn_factor(v_round_trip, v_round_trip, float(twab), CHURN)
    assert f == pytest.approx(1.0 / 21.0)
    assert f <= 0.10
    # Score is ≤ 10% of an equal-balance, equal-H holder with F=1, U=1.
    holder = score(float(twab), 1.5, 1.0, 1.0)
    flipper = score(float(twab), 1.5, f, 1.0)
    assert flipper <= 0.10 * holder
    assert churn_factor(0, 0, 0.0, CHURN) == 1.0  # ε = 1, χ = 0


def test_underwater_min_age_transfer_and_price_above_cost() -> None:
    t = 100_000
    young = lot(t_acquired=t - AGE_47H59M, cost=10.0)
    old = lot(t_acquired=t - AGE_48H, cost=10.0)
    xfer = lot(t_acquired=t - AGE_48H, cost=10.0, source=LotSource.TRANSFER_IN)
    # 47h59m ignored; 48h counts. Price at half cost → d = 0.5, U = 1 + 0.5·(0.5/0.75).
    assert underwater_boost([young], 5.0, t, UNDER) == 1.0
    assert underwater_boost([xfer], 5.0, t, UNDER) == 1.0
    got = underwater_boost([old], 5.0, t, UNDER)
    assert got == pytest.approx(1.0 + 0.5 * (0.5 / 0.75))
    # Price at or above cost → no drawdown.
    assert underwater_boost([old], 10.0, t, UNDER) == 1.0
    assert underwater_boost([old], 12.0, t, UNDER) == 1.0
    # Zero/negative cost lots are ignored; empty → 1.0.
    assert underwater_boost([lot(cost=0.0, t_acquired=0)], 5.0, t, UNDER) == 1.0
    assert underwater_boost([], 5.0, t, UNDER) == 1.0
    with pytest.raises(ValueError, match="twap"):
        underwater_boost([old], 0.0, t, UNDER)
    with pytest.raises(ValueError, match="twap"):
        underwater_boost([old], -1.0, t, UNDER)


def test_boost_never_exceeds_one_plus_beta_and_saturates() -> None:
    t = 200_000
    deep = lot(amount=10, cost=100.0, t_acquired=t - AGE_48H)  # d = 1 at twap→0+, cap at d_max
    # twap very small → D ≈ 1 ≥ d_max → U = 1+β.
    assert underwater_boost([deep], 1e-9, t, UNDER) == pytest.approx(1.0 + UNDER.beta)
    # Mix: only POOL_BUY aged lots enter the average.
    mixed = [deep, lot(amount=10, cost=100.0, t_acquired=t - 10, source=LotSource.TRANSFER_IN)]
    assert underwater_boost(mixed, 1e-9, t, UNDER) == pytest.approx(1.0 + UNDER.beta)


def test_score_is_product_and_rejects_negatives() -> None:
    assert score(2.0, 1.5, 0.5, 1.2) == pytest.approx(2.0 * 1.5 * 0.5 * 1.2)
    assert score(0.0, 2.0, 1.0, 1.0) == 0.0
    for args in ((-1, 1, 1, 1), (1, -0.1, 1, 1), (1, 1, -1, 1), (1, 1, 1, -2)):
        with pytest.raises(ValueError, match="score"):
            score(*args)


@given(st.floats(-10, 400), st.floats(-10, 400))
@settings(max_examples=60, deadline=None)
def test_hold_nondecreasing_in_age(a: float, b: float) -> None:
    lo, hi = (a, b) if a <= b else (b, a)
    assert hold_multiplier(lo, HOLD) <= hold_multiplier(hi, HOLD) + 1e-12


@given(
    st.integers(0, 10**9),
    st.integers(0, 10**9),
    st.integers(0, 10**6),
    st.floats(0.1, 1e9, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=60, deadline=None)
def test_churn_nonincreasing_in_volume(v: int, extra: int, twab_i: int, kappa: float) -> None:
    p = ChurnParams(kappa=kappa)
    twab = float(twab_i)
    lo = churn_factor(v, v, twab, p)
    hi = churn_factor(v + extra, v + extra, twab, p)
    assert hi <= lo + 1e-12


@given(
    st.floats(1e-6, 1e6, allow_nan=False, allow_infinity=False),
    st.floats(1e-6, 1e6, allow_nan=False, allow_infinity=False),
    st.integers(1, 10**6),
)
@settings(max_examples=60, deadline=None)
def test_boost_nonincreasing_in_twap_and_capped(twap_a: float, twap_b: float, amount: int) -> None:
    t = 300_000
    lots = [lot(amount=amount, cost=50.0, t_acquired=t - AGE_48H)]
    u_lo = underwater_boost(lots, min(twap_a, twap_b), t, UNDER)
    u_hi = underwater_boost(lots, max(twap_a, twap_b), t, UNDER)
    assert u_hi <= u_lo + 1e-12
    assert 1.0 <= u_lo <= 1.0 + UNDER.beta + 1e-12
    assert 1.0 <= u_hi <= 1.0 + UNDER.beta + 1e-12

"""Tests for v0.3.3 score as a sum over lots (COIN_MATH §6)."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.scoring import (
    DEFAULT_BOOST_AGE_SECONDS,
    HOUR,
    lot_epoch_parts,
    lot_score,
    score,
    score_lot,
    score_lots,
)
from engine.types import Lot, LotSource

DAY = 86_400


def _lot(
    amount: int,
    t_acquired: int,
    source: LotSource = LotSource.POOL_BUY,
) -> Lot:
    return Lot(amount, 1.0, t_acquired, source)


def test_score_is_sum_of_e1_and_u_times_e2() -> None:
    t0, t1 = 0, DAY
    # Acquired at t0: only E1 (never reaches 48h), u must not change the score.
    e1, e2 = lot_epoch_parts(100, 0, t0, t1)
    assert e2 == 0 and e1 > 0
    assert lot_score(e1, e2, 1) == e1
    assert lot_score(e1, e2, Fraction(3, 2)) == e1
    assert score_lot(100, 0, t0, t1) == e1
    assert score_lot(100, 0, t0, t1, u_lot=Fraction(3, 2)) == e1
    # Acquired 48h before t0: the whole epoch is E2, so u scales the score.
    acquired = t0 - DEFAULT_BOOST_AGE_SECONDS
    e1_old, e2_old = lot_epoch_parts(100, acquired, t0, t1)
    assert e1_old == 0 and e2_old > 0
    assert lot_score(e1_old, e2_old, 1) == e2_old
    assert lot_score(e1_old, e2_old, Fraction(3, 2)) == Fraction(3, 2) * e2_old
    assert score_lot(100, acquired, t0, t1, u_lot=Fraction(3, 2)) == Fraction(3, 2) * e2_old
    with pytest.raises(ValueError, match="u_lot"):
        lot_score(1, 1, -1)


def test_score_lots_sums_and_forces_transfer_u_to_one() -> None:
    t0, t1 = 0, DAY
    young = _lot(40, 0)
    old = _lot(60, t0 - DEFAULT_BOOST_AGE_SECONDS)
    xfer = _lot(60, t0 - DEFAULT_BOOST_AGE_SECONDS, LotSource.TRANSFER_IN)
    assert score_lots([], t0, t1) == 0
    assert score_lots([_lot(100, t1 - HOUR)], t0, t1) == 0  # all under T_START
    got = score_lots([young, old], t0, t1)
    assert got == score_lot(40, 0, t0, t1) + score_lot(60, old.t_acquired, t0, t1)
    # Boost on the old pool lot; the transfer lot stays at u=1 despite the same input.
    boosted = score_lots([old, xfer], t0, t1, u_lots=(Fraction(3, 2), Fraction(3, 2)))
    assert boosted == score_lot(60, old.t_acquired, t0, t1, u_lot=Fraction(3, 2)) + score_lot(
        60, xfer.t_acquired, t0, t1, u_lot=1
    )
    # Taint on the first 9 hours (past T_START=6h) reduces the score, never below 0.
    full = score_lots([young], t0, t1)
    tainted = score_lots([young], t0, t1, tainted_until=(9 * HOUR,))
    assert 0 <= tainted < full
    with pytest.raises(ValueError, match="u_lots"):
        score_lots([young], t0, t1, u_lots=(1, 1))


def test_v02_product_score_is_unchanged() -> None:
    assert score(2.0, 1.5, 0.5, 1.2) == pytest.approx(2.0 * 1.5 * 0.5 * 1.2)


@given(st.integers(1, 10**6), st.integers(1, 10**6))
@settings(max_examples=60, deadline=None)
def test_splitting_a_lot_does_not_change_score(a: int, b: int) -> None:
    t0, t1 = 0, DAY
    acquired = t0 - 24 * HOUR
    one = score_lots([_lot(a + b, acquired)], t0, t1)
    two = score_lots([_lot(a, acquired), _lot(b, acquired)], t0, t1)
    assert one == two
    assert one > 0

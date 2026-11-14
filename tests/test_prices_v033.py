"""Tests for engine/prices.py: price step function, means, trusted seconds (COIN_MATH §0)."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.prices import (
    ReservePoint,
    arithmetic_mean,
    constant_product_price_after,
    harmonic_mean,
    is_trusted_second,
    price_at,
    untrusted_fraction,
)


def test_reserve_point_price_and_validation() -> None:
    assert ReservePoint(0, 10, 4).price == Fraction(5, 2)
    with pytest.raises(ValueError, match="positive"):
        ReservePoint(0, 0, 100)
    with pytest.raises(ValueError, match="positive"):
        ReservePoint(0, 100, 0)


def test_price_at_is_a_step_function_of_the_second() -> None:
    points = [
        ReservePoint(100, 10, 10),  # price 1
        ReservePoint(110, 30, 10),  # price 3
        ReservePoint(200, 20, 10),  # price 2
    ]
    assert [price_at(points, t) for t in (100, 105, 109, 110, 150, 200, 10_000)] == [
        1,
        1,
        1,
        3,
        3,
        2,
        2,
    ]
    with pytest.raises(ValueError, match="no reserve point known"):
        price_at(points, 99)
    with pytest.raises(ValueError, match="duplicate"):
        price_at([ReservePoint(100, 10, 10), ReservePoint(100, 20, 10)], 100)


def test_arithmetic_mean_weights_by_duration() -> None:
    assert arithmetic_mean([ReservePoint(0, 7, 2)], 0, 1000) == Fraction(7, 2)
    # price 1 for 90s, then price 3 for 10s -> mean = (90*1 + 10*3)/100 = 1.2
    points = [ReservePoint(0, 1, 1), ReservePoint(90, 3, 1)]
    assert arithmetic_mean(points, 0, 100) == Fraction(6, 5)
    with pytest.raises(ValueError, match="non-empty"):
        arithmetic_mean(points, 10, 10)


def test_harmonic_mean_of_two_equal_segments() -> None:
    # price 1 for 50s, price 3 for 50s -> harmonic = 100 / (50/1 + 50/3) = 3/2
    points = [ReservePoint(0, 1, 1), ReservePoint(50, 3, 1)]
    assert harmonic_mean(points, 0, 100) == Fraction(3, 2)


def test_constant_product_price_after_matches_closed_form() -> None:
    # y=100, x=10 -> p=10; buy delta=20 -> y'=120, p' = 120**2/(100*10) = 14.4
    assert constant_product_price_after(100, 10, 20) == Fraction(14_400, 1_000)
    assert constant_product_price_after(100, 10, 0) == Fraction(100, 10)  # no-op
    with pytest.raises(ValueError, match="drains"):
        constant_product_price_after(100, 10, -100)


def test_trusted_second_boundary_near_81_sol_matches_spec_comment() -> None:
    # COIN_MATH §0: "for a constant-product pool this means a Q reserve above ~81 SOL".
    # Ratio after a D_TRUST=2 buy is (1 + 2/y)^2; reserve_base is irrelevant to the ratio.
    assert is_trusted_second(reserve_quote=81, reserve_base=1_000, d_trust=2) is True
    assert is_trusted_second(reserve_quote=80, reserve_base=1_000, d_trust=2) is False


def test_trusted_second_directions_pluggable_math_and_validation() -> None:
    assert is_trusted_second(reserve_quote=10**9, reserve_base=10**9, d_trust=2) is True
    assert is_trusted_second(reserve_quote=3, reserve_base=10**6, d_trust=2) is False
    with pytest.raises(ValueError, match="d_trust must be positive"):
        is_trusted_second(reserve_quote=100, reserve_base=10, d_trust=0)

    def always_doubles(reserve_quote: int, reserve_base: int, delta_quote: int) -> Fraction:
        return Fraction(reserve_quote, reserve_base) * 2

    assert (
        is_trusted_second(reserve_quote=100, reserve_base=10, d_trust=1, pool_math=always_doubles)
        is False
    )


def test_untrusted_fraction_counts_only_untrusted_seconds() -> None:
    points = [
        ReservePoint(0, 1_000, 1),  # huge pool: trusted
        ReservePoint(700, 3, 1),  # tiny pool: untrusted
    ]
    assert untrusted_fraction(points, 0, 1_000, d_trust=2) == Fraction(300, 1_000)


@given(
    st.lists(
        st.tuples(
            st.integers(1, 500),  # segment duration
            st.integers(1, 10_000),  # reserve_quote
            st.integers(1, 10_000),  # reserve_base
        ),
        min_size=1,
        max_size=6,
    ),
    st.integers(-1000, 1000),
)
@settings(max_examples=100)
def test_arithmetic_and_harmonic_means_are_bounded_by_min_and_max_price(
    segments: list[tuple[int, int, int]], t_start: int
) -> None:
    ts = t_start
    points = []
    prices = []
    for duration, rq, rb in segments:
        points.append(ReservePoint(ts, rq, rb))
        prices.append(Fraction(rq, rb))
        ts += duration
    t_end = ts
    am = arithmetic_mean(points, t_start, t_end)
    hm = harmonic_mean(points, t_start, t_end)
    assert min(prices) <= hm <= am <= max(prices)


@given(
    st.integers(1, 10_000),  # a_rest reserve_quote
    st.integers(1, 10_000),  # a_rest reserve_base
    st.integers(1, 10_000),  # dump reserve_quote
    st.integers(1, 10_000),  # dump reserve_base
    st.integers(1, 86_399),  # tau: dump duration
    st.integers(-1000, 1000),  # t_start
)
@settings(max_examples=100)
def test_dump_bound_arithmetic_mean_floor(
    rest_quote: int,
    rest_base: int,
    dump_quote: int,
    dump_base: int,
    tau: int,
    t_start: int,
) -> None:
    """A tau-second dump can't pull P̄_e below (E-tau)/E * A_rest (COIN_MATH §0, §5)."""
    epoch_seconds = 86_400
    a_rest = Fraction(rest_quote, rest_base)
    points = [
        ReservePoint(t_start, rest_quote, rest_base),
        ReservePoint(t_start + epoch_seconds - tau, dump_quote, dump_base),
    ]
    p_bar = arithmetic_mean(points, t_start, t_start + epoch_seconds)
    bound = Fraction(epoch_seconds - tau, epoch_seconds) * a_rest
    assert p_bar >= bound

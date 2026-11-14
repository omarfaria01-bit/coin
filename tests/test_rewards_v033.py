"""Tests for the v0.3.3 whale cap with G=2 (COIN_MATH §6)."""

from __future__ import annotations

from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.rewards import DEFAULT_CAP, DEFAULT_G, capped_shares_v033

CAP = DEFAULT_CAP
G = DEFAULT_G


def test_ten_equal_clusters_pay_five_percent_and_roll_half() -> None:
    scores = {f"C{i:02d}": 1 for i in range(10)}
    shares = capped_shares_v033(scores)
    assert all(s == CAP for s in shares.values())
    assert sum(shares.values()) == Fraction(1, 2)
    assert 1 - sum(shares.values()) == Fraction(1, 2)


def test_ninety_one_plus_nine_ones_pays_twenty_three_percent() -> None:
    scores = {"W": 91, **{f"S{i}": 1 for i in range(9)}}
    shares = capped_shares_v033(scores)
    assert shares["W"] == CAP
    assert all(shares[f"S{i}"] == Fraction(1, 50) for i in range(9))  # 2%
    assert sum(shares.values()) == Fraction(23, 100)
    assert 1 - sum(shares.values()) == Fraction(77, 100)
    # 2× proportional: small clusters have s/S = 1/100, 2× is 2%.
    assert shares["S0"] == G * Fraction(1, 100)


def test_s_zero_does_not_divide() -> None:
    assert capped_shares_v033({}) == {}
    assert capped_shares_v033({"a": 0, "b": 0}) == {"a": 0, "b": 0}
    assert capped_shares_v033({"a": 0, "b": -3}) == {"a": 0, "b": 0}


def test_many_equal_clusters_fill_the_unit() -> None:
    scores = {f"C{i:02d}": 1 for i in range(25)}
    shares = capped_shares_v033(scores)
    assert all(s == Fraction(1, 25) for s in shares.values())
    assert sum(shares.values()) == 1


@given(
    st.dictionaries(
        st.text(min_size=1, max_size=4, alphabet="ABCDE0123"),
        st.integers(0, 10**6),
        min_size=0,
        max_size=25,
    )
)
@settings(max_examples=80, deadline=None)
def test_cap_and_uplift_bounds(scores: dict[str, int]) -> None:
    shares = capped_shares_v033(scores)
    assert list(shares) == sorted(scores)
    assert all(0 <= s <= CAP for s in shares.values())
    total = sum((s for s in scores.values() if s > 0), 0)
    paid = sum(shares.values())
    assert 0 <= paid <= 1
    if total == 0:
        assert paid == 0
        return
    s_total = Fraction(total)
    for cid, share in shares.items():
        score = scores[cid]
        if score <= 0:
            assert share == 0
        else:
            assert share <= G * Fraction(score) / s_total

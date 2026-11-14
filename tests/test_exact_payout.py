"""Exact integer payout and per-wallet split (COIN_MATH v0.3.3 §6)."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.rewards import (
    capped_shares_v033,
    epoch_budget_v033,
    exact_payout,
    split_cluster_payout,
)


def test_ten_equal_clusters_pay_half_and_roll_half() -> None:
    res = exact_payout(1_000, capped_shares_v033({f"C{i}": 1 for i in range(10)}))
    assert res.total == 500 and res.rollover_units == 500
    assert set(res.payouts.values()) == {50}


def test_leftover_units_go_by_largest_remainder_ties_by_cluster_id() -> None:
    thirds = {"b": Fraction(1, 3), "a": Fraction(1, 3), "c": Fraction(1, 3)}
    res = exact_payout(10, thirds)  # 3.33 each: T = 10, one leftover unit
    assert res.payouts == {"a": 4, "b": 3, "c": 3}  # tie on remainder → smallest id
    res = exact_payout(10, {"a": Fraction(1, 5), "b": Fraction(27, 100)})
    # exact 2.0 and 2.7; T = floor(4.7) = 4; floors 2+2 = 4, no leftover
    assert res.payouts == {"a": 2, "b": 2} and res.rollover_units == 6
    res = exact_payout(10, {"a": Fraction(13, 100), "b": Fraction(47, 100)})
    # exact 1.3 and 4.7; T = 6; floors 1+4 = 5; the larger remainder (b) gets the unit
    assert res.payouts == {"a": 1, "b": 5} and res.rollover_units == 4


def test_s_zero_pays_nothing_and_rolls_everything() -> None:
    res = exact_payout(12_345, capped_shares_v033({"a": 0, "b": 0}))
    assert res.total == 0 and res.rollover_units == 12_345
    assert res.payouts == {"a": 0, "b": 0}
    assert exact_payout(7, {}).rollover_units == 7
    assert exact_payout(0, {"a": Fraction(1, 20)}).payouts == {"a": 0}


def test_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        exact_payout(-1, {})
    with pytest.raises(TypeError):
        exact_payout(1.5, {})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="<= 1"):
        exact_payout(10, {"a": Fraction(2, 3), "b": Fraction(2, 3)})
    with pytest.raises(ValueError, match="shares"):
        exact_payout(10, {"a": Fraction(-1, 3)})
    with pytest.raises(TypeError):
        exact_payout(10, {"a": 0.5})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="zero score"):
        split_cluster_payout(5, {"w1": 0})
    with pytest.raises(ValueError, match="payout_c"):
        split_cluster_payout(-1, {"w1": 1})
    with pytest.raises(ValueError, match="wallet scores"):
        split_cluster_payout(1, {"w1": -1})


def test_wallet_split_largest_remainder_ties_by_address() -> None:
    assert split_cluster_payout(10, {"w2": 1, "w1": 1, "w3": 1}) == {"w1": 4, "w2": 3, "w3": 3}
    assert split_cluster_payout(7, {"a": Fraction(3, 2), "b": Fraction(1, 2)}) == {"a": 5, "b": 2}
    assert split_cluster_payout(0, {"a": 0, "b": 0}) == {"a": 0, "b": 0}
    assert split_cluster_payout(9, {"a": 0, "b": 4}) == {"a": 0, "b": 9}


_scores = st.dictionaries(
    st.text("abcdefgh", min_size=1, max_size=3),
    st.fractions(min_value=0, max_value=10**6, max_denominator=10**4),
    max_size=40,
)


@given(_scores, st.integers(0, 10**15))
@settings(max_examples=200, deadline=None)
def test_property_conservation_and_bounds(scores: dict[str, Fraction], r_e: int) -> None:
    shares = capped_shares_v033(scores)
    res = exact_payout(r_e, shares)
    assert sum(res.payouts.values()) == res.total
    assert sum(res.payouts.values()) + res.rollover_units == r_e
    for cid, pi in shares.items():
        exact = r_e * pi
        assert exact - 1 < res.payouts[cid] < exact + 1  # off by < one unit
    if sum(scores.values()) == 0:
        assert res.rollover_units == r_e


@given(st.integers(0, 10**12), _scores.filter(lambda d: sum(d.values()) > 0))
@settings(max_examples=200, deadline=None)
def test_property_wallet_split_sums_to_cluster_payout(payout: int, s_w: dict) -> None:
    parts = split_cluster_payout(payout, s_w)
    assert sum(parts.values()) == payout
    s_c = sum(s_w.values())
    for wid, s in s_w.items():
        assert payout * s / s_c - 1 < parts[wid] < payout * s / s_c + 1


@given(st.integers(0, 10**24), st.integers(1, 1000), st.integers(1, 1000))
@settings(max_examples=200, deadline=None)
def test_epoch_budget_v033_is_floor_alpha_pot(pot: int, a: int, b: int) -> None:
    alpha = Fraction(min(a, b), max(a, b))
    r = epoch_budget_v033(pot, alpha)
    assert 0 <= r <= pot
    assert r <= alpha * pot < r + 1


@pytest.mark.parametrize(
    ("pot", "alpha", "exc"),
    [(-1, Fraction(1, 10), ValueError), (True, Fraction(1, 10), TypeError),
     (10, Fraction(0), ValueError), (10, Fraction(11, 10), ValueError), (10, 0.1, ValueError)],
)  # fmt: skip
def test_epoch_budget_v033_rejects_bad_input(pot, alpha, exc) -> None:
    with pytest.raises(exc):
        epoch_budget_v033(pot, alpha)

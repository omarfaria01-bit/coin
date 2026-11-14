"""Tests for engine/rewards.py (COIN_MATH §6 cap/split, §8 pot smoothing)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.params import RewardParams, ScoringParams
from engine.rewards import allocate, capped_shares, epoch_budget, split_to_wallets

CAP = ScoringParams().cap  # 0.05
ALPHA = RewardParams().alpha_per_day  # 0.10
N_CAP = int(math.floor(1 / CAP))  # 20


def test_epoch_budget_24h_is_floor_alpha_pot_and_rejects_negative() -> None:
    assert epoch_budget(1_000, ALPHA, 24) == 100
    assert epoch_budget(7, ALPHA, 24) == 0
    assert epoch_budget(0, ALPHA, 24) == 0
    assert epoch_budget(1_000, 1.0, 24) == 1_000
    with pytest.raises(ValueError, match="pot"):
        epoch_budget(-1, ALPHA, 24)


def test_zero_inflow_seventh_payout_at_least_45_percent_of_first() -> None:
    # COIN_MATH §14 row 10: α=0.10, 0 inflow, 7 daily epochs → 0.9^6 ≈ 53% ≥ 45%.
    pot = 10**12
    first = seventh = 0
    for i in range(7):
        r = epoch_budget(pot, ALPHA, 24)
        if i == 0:
            first = r
        if i == 6:
            seventh = r
        pot -= r
    assert first > 0
    assert seventh >= 0.45 * first
    assert seventh == pytest.approx(first * (0.9**6), rel=1e-9)


@pytest.mark.parametrize("n", [5, 10, 19, 20, 100])
def test_whale_cap_water_filling_for_n_clusters(n: int) -> None:
    # COIN_MATH §14 row 7: skewed scores, every π ≤ CAP; N < 1/CAP → Σ = N·CAP.
    scores = {f"C{i:03d}": float(2**i) for i in range(n)}
    shares = capped_shares(scores, CAP)
    assert list(shares) == sorted(scores)
    assert all(s <= CAP + 1e-15 for s in shares.values())
    assert all(shares[c] == 0.0 or scores[c] > 0 for c in scores)
    budget = 10**9
    payouts, rollover = allocate(budget, shares)
    assert sum(payouts.values()) + rollover == budget
    assert rollover >= 0
    if n < N_CAP:
        assert sum(shares.values()) == pytest.approx(n * CAP, abs=1e-12)
        # Each of N payouts is floor(budget·cap) or less; leftover at least
        # budget·(1 − N·cap) minus at most N lamports of floor dust.
        assert rollover >= budget * (1 - n * CAP) - n
    else:
        assert sum(shares.values()) == pytest.approx(1.0, abs=1e-9)


def test_capped_shares_zeros_order_and_empty() -> None:
    scores = {"z": 0.0, "n": -3.0, "a": 1.0, "b": 1.0}
    # 2 positive scores, cap=0.05, 1/cap=20 → both under cap, equal 0.5? Wait
    # N_free=2 < 20, both would get 0.5 > cap, so both fixed at cap.
    shares = capped_shares(scores, CAP)
    assert shares == {"a": CAP, "b": CAP, "n": 0.0, "z": 0.0}
    assert capped_shares({}, CAP) == {}
    assert capped_shares({"x": 0.0}, CAP) == {"x": 0.0}
    # Input order must not change the result.
    a = {"c": 5.0, "a": 1.0, "b": 100.0}
    assert capped_shares(a, CAP) == capped_shares({k: a[k] for k in reversed(list(a))}, CAP)
    with pytest.raises(ValueError, match="cap"):
        capped_shares({"a": 1.0}, 0.0)


def test_allocate_and_split_conservation_and_keys() -> None:
    shares = {"b": 0.1, "a": 0.2, "c": 0.0}
    payouts, rem = allocate(1_000, shares)
    assert list(payouts) == ["a", "b", "c"]
    assert payouts["a"] == 200 and payouts["b"] == 100 and payouts["c"] == 0
    assert rem == 700
    assert sum(payouts.values()) + rem == 1_000
    with pytest.raises(ValueError, match="budget"):
        allocate(-1, shares)

    weights = {"w2": 1.0, "w1": 3.0, "w0": 0.0, "wn": -2.0}
    amts, dust = split_to_wallets(100, weights)
    assert list(amts) == ["w0", "w1", "w2", "wn"]
    assert amts["w1"] == 75 and amts["w2"] == 25
    assert amts["w0"] == 0 and amts["wn"] == 0 and dust == 0
    # All non-positive weights → everything is dust.
    amts, dust = split_to_wallets(50, {"a": 0.0, "b": -1.0})
    assert amts == {"a": 0, "b": 0} and dust == 50
    amts, dust = split_to_wallets(7, {"a": 1.0, "b": 1.0})
    assert amts["a"] + amts["b"] + dust == 7
    with pytest.raises(ValueError, match="payout"):
        split_to_wallets(-1, {"a": 1.0})


@given(
    st.dictionaries(
        st.text(min_size=1, max_size=6, alphabet="ABCDE0123456789"),
        st.floats(-10, 1e9, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=25,
    ),
    st.integers(0, 10**9),
    st.floats(0.01, 0.5, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50, deadline=None)
def test_conservation_cap_and_order(scores: dict[str, float], budget: int, cap: float) -> None:
    shares = capped_shares(scores, cap)
    assert list(shares) == sorted(scores)
    assert all(s <= cap + 1e-12 for s in shares.values())
    shuffled = {k: scores[k] for k in reversed(list(scores))}
    assert capped_shares(shuffled, cap) == shares
    payouts, rem = allocate(budget, shares)
    assert sum(payouts.values()) + rem == budget
    assert set(payouts) == set(shares)
    n_pos = sum(1 for s in scores.values() if s > 0)
    if n_pos and n_pos < math.floor(1 / cap):
        assert sum(shares.values()) == pytest.approx(n_pos * cap, abs=1e-9)


@given(
    st.integers(0, 10**9),
    st.dictionaries(
        st.text(min_size=1, max_size=4, alphabet="WXYZ"),
        st.floats(-5, 1e6, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=10,
    ),
)
@settings(max_examples=50, deadline=None)
def test_wallet_split_conserves(payout: int, weights: dict[str, float]) -> None:
    amts, dust = split_to_wallets(payout, weights)
    assert sum(amts.values()) + dust == payout
    assert list(amts) == sorted(weights)
    if all(w <= 0 for w in weights.values()):
        assert dust == payout and all(v == 0 for v in amts.values())


@given(
    st.integers(21, 40),
    st.integers(1_000, 10**7),
    st.floats(0.2, 0.8, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=40, deadline=None)
def test_splitting_a_score_does_not_raise_payout(n: int, budget: int, frac: float) -> None:
    # Equal scores, n ≥ 21 → each share = 1/n < cap, so the cap does not bind.
    scores = {f"C{i:02d}": 1.0 for i in range(n)}
    shares = capped_shares(scores, CAP)
    assert all(s < CAP - 1e-9 for s in shares.values())
    payouts, _ = allocate(budget, shares)
    victim, a, b = "C00", "C00a", "C00b"
    new_scores = {k: v for k, v in scores.items() if k != victim}
    new_scores[a] = scores[victim] * frac
    new_scores[b] = scores[victim] * (1.0 - frac)
    new_shares = capped_shares(new_scores, CAP)
    assert all(s < CAP - 1e-9 for s in new_shares.values())
    new_pay, _ = allocate(budget, new_shares)
    # Linear pro-rata: combined payout must not rise, up to ±N lamports of floor.
    assert new_pay[a] + new_pay[b] <= payouts[victim] + len(new_scores)

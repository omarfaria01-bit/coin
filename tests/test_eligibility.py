"""Tests for engine/eligibility.py and epoch wiring (COIN_MATH v0.3.3 §2)."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.eligibility import (
    DEFAULT_MIN_ELIGIBLE_SHARE,
    as_rational,
    eligibility_floor,
    is_eligible,
    parse_share,
)
from engine.epoch import empty_state, run_epoch
from engine.params import CoinParams, EligibilityParams, RewardParams, ScoringParams
from tests.test_epoch import T0, W, _buy, _inputs


def test_default_share_and_one_billion_supply_floor() -> None:
    assert parse_share("1/1000000") == DEFAULT_MIN_ELIGIBLE_SHARE
    supply = 1_000_000_000 * 10**9  # 1B tokens, 9 decimals
    assert eligibility_floor(supply) == Fraction(1_000 * 10**9)
    assert eligibility_floor(0, "1/1000000") == 0
    assert eligibility_floor(100, 0) == 0
    assert eligibility_floor(100, 1) == 100


def test_share_parser_rejects_decimals_and_out_of_range() -> None:
    assert parse_share(0) == 0
    assert parse_share(Fraction(1, 2)) == Fraction(1, 2)
    with pytest.raises(ValueError, match="num/den"):
        parse_share("0.000001")
    with pytest.raises(ValueError, match="num/den"):
        parse_share("1e-6")
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        parse_share("2/1")
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        parse_share("-1/1000")
    with pytest.raises(TypeError):
        parse_share(True)  # type: ignore[arg-type]


def test_is_eligible_is_price_free_and_inclusive() -> None:
    supply = 1_000_000
    share = "1/1000"  # floor = 1000
    assert is_eligible(1000, supply, share) is True
    assert is_eligible(999, supply, share) is False
    assert is_eligible(Fraction(999_999, 1000), supply, share) is False
    assert is_eligible(Fraction(1000), supply, share) is True
    # A float TWAB equal to the floor still qualifies (exact integer ratio).
    assert is_eligible(1000.0, supply, share) is True
    # No price argument exists; USD cannot enter the comparison.
    assert is_eligible(0, 0, share) is True
    with pytest.raises(ValueError, match="twab"):
        is_eligible(-1, supply, share)
    with pytest.raises(ValueError, match="total_supply"):
        eligibility_floor(-1, share)
    with pytest.raises(ValueError, match="finite"):
        as_rational(float("nan"))


@given(
    st.integers(0, 10**12),
    st.integers(0, 10**18),
    st.integers(0, 1_000_000),
)
@settings(max_examples=80, deadline=None)
def test_eligibility_monotone_in_twab_and_share(twab: int, supply: int, den: int) -> None:
    den = den + 1
    share = Fraction(1, den)
    got = is_eligible(twab, supply, share)
    assert got == (Fraction(twab) >= share * supply)
    assert is_eligible(twab + 1, supply, share) is True or not got


def _params(share: str = "0") -> CoinParams:
    return CoinParams(
        eligibility=EligibilityParams(min_eligible_share=share),
        scoring=ScoringParams(cap=1.0),
        rewards=RewardParams(
            enabled=True,
            min_epoch_payout_lamports=0,
            push_min_transfer_lamports=1,
        ),
    )


def test_epoch_dust_below_share_is_ineligible() -> None:
    """A 999-unit bag is dust against a 1/1000 floor of a 1_000_000 supply."""
    supply = 1_000_000
    share = "1/1000"
    dust = W("dust")
    holder = W("holder")
    events = [_buy("d", dust, 999, T0, ix=0), _buy("h", holder, 1000, T0, ix=1)]
    inp = replace(_inputs(events, inflow=10**12), total_supply=supply)
    result, _nxt = run_epoch(inp, _params(share), empty_state())
    scores = {row.cluster: row.score for row in result.scores}
    assert scores[dust] == 0.0
    assert scores[holder] > 0.0
    # sol_usd is still on the inputs but must not decide eligibility: a huge
    # price would have passed the old $10 gate for the dust bag, and must not now.
    expensive = replace(inp, sol_usd=1_000_000.0)
    result2, _ = run_epoch(expensive, _params(share), empty_state())
    scores2 = {row.cluster: row.score for row in result2.scores}
    assert scores2[dust] == 0.0
    assert scores2[holder] > 0.0

"""D28 hourly draw plan: cap, conservation, minimum pot rollover, determinism."""

from __future__ import annotations

from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.hourly_draw import (
    CAP_DEFAULT,
    MIN_POT_LAMPORTS_DEFAULT,
    cap_weights,
    plan_hourly_draw,
)

B = b"\x01" * 32
KW = {"genesis_hash": B, "mint": B, "draw_index": 7, "snapshot_hash": B, "rho": b"\x02" * 32}
BPS = (4000, 1000, 1000, 1000, 500, 500, 500, 500, 500, 500)


@given(st.dictionaries(st.integers(0, 80), st.integers(1, 10**15), min_size=1, max_size=60))
@settings(max_examples=120, deadline=None)
def test_cap_holds_exactly_or_all_equal(ws: dict[int, int]) -> None:
    out = cap_weights(ws)
    total = sum(out.values())
    assert set(out) == set(ws)
    if len(ws) * CAP_DEFAULT <= 1:
        assert len(set(out.values())) == 1  # cap impossible: equal odds
    else:
        assert all(Fraction(w, total) <= CAP_DEFAULT for w in out.values())


def test_cap_keeps_ratios_of_uncapped_and_caps_a_whale() -> None:
    ws = {i: 100 for i in range(30)} | {99: 10**9}
    out = cap_weights(ws)
    assert Fraction(out[99], sum(out.values())) == CAP_DEFAULT
    assert len({out[i] for i in range(30)}) == 1


@given(
    st.dictionaries(st.integers(0, 50), st.integers(0, 10**18), max_size=40),
    st.integers(0, 10**13),
)
@settings(max_examples=80, deadline=None)
def test_prizes_plus_rollover_equal_pot(scores: dict[int, int], pot: int) -> None:
    plan = plan_hourly_draw(scores, pot, BPS, **KW)
    assert sum(plan.prizes.values()) + plan.rollover == pot
    assert len(set(plan.winners)) == len(plan.winners) <= len(BPS)
    assert all(scores[c] > 0 for c in plan.winners)
    if pot < MIN_POT_LAMPORTS_DEFAULT:
        assert not plan.drawn and plan.reason == "below_min_pot" and plan.rollover == pot
    assert plan == plan_hourly_draw(dict(reversed(list(scores.items()))), pot, BPS, **KW)


def test_no_eligible_rolls_over_and_zero_score_never_wins() -> None:
    plan = plan_hourly_draw({1: 0, 2: 0}, 10**9, BPS, **KW)
    assert (plan.drawn, plan.reason, plan.rollover) == (False, "no_eligible", 10**9)
    plan = plan_hourly_draw({1: 0, 2: 10**6}, 10**9, BPS, **KW)
    assert plan.winners == (2,) and plan.prizes == {2: 10**9 * 4000 // 10_000}
    assert plan.rollover == 10**9 - plan.prizes[2]


def test_whale_score_weighs_sqrt_before_the_cap() -> None:
    from engine.draws import draw_weight

    assert draw_weight(10**8) == 10 * draw_weight(10**6)  # 100x score -> 10x weight
    small = {i: 10**6 for i in range(60)}
    assert plan_hourly_draw(small | {99: 10**8}, 10**10, BPS, **KW).drawn

"""Hourly draw plan (D28 + D39): cap, conservation, rollover, gates, determinism."""

from __future__ import annotations

from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.hourly_draw import (
    CAP_DEFAULT,
    MIN_POT_LAMPORTS_DEFAULT,
    cap_weights,
    draw_weights,
    plan_hourly_draw,
)

B = b"\x01" * 32
S = 10**18  # total supply in these tests: every test balance is far below the 5% cap
KW = {
    "genesis_hash": B,
    "mint": B,
    "draw_index": 7,
    "snapshot_hash": B,
    "rho": b"\x02" * 32,
    "total_supply": S,
    "min_holding_share": Fraction(1, 10**18),
}
BPS = (4000, 1000, 1000, 1000, 500, 500, 500, 500, 500, 500)


def plan(scores, pot, **kw):
    return plan_hourly_draw(scores, pot, BPS, balances=dict(scores), **(KW | kw))


@given(st.dictionaries(st.integers(0, 80), st.integers(1, 10**15), min_size=1, max_size=60))
@settings(max_examples=120, deadline=None)
def test_cap_holds_exactly_or_all_equal(ws: dict[int, int]) -> None:
    out = cap_weights(ws)
    total = sum(out.values())
    assert set(out) == set(ws)
    if len(ws) * CAP_DEFAULT <= 1:
        assert len(set(out.values())) == 1  # cap impossible: equal odds (never used by the plan)
    else:
        assert all(Fraction(w, total) <= CAP_DEFAULT for w in out.values())


def test_cap_keeps_ratios_of_uncapped_and_caps_a_whale() -> None:
    ws = {i: 100 for i in range(30)} | {99: 10**9}
    out = cap_weights(ws)
    assert Fraction(out[99], sum(out.values())) == CAP_DEFAULT
    assert len({out[i] for i in range(30)}) == 1


@given(
    st.dictionaries(st.integers(0, 150), st.integers(0, 10**15), max_size=140),
    st.integers(0, 10**13),
)
@settings(max_examples=80, deadline=None)
def test_prizes_plus_rollover_equal_pot(scores: dict[int, int], pot: int) -> None:
    p = plan(scores, pot)
    assert sum(p.prizes.values()) + p.rollover == pot
    assert len(set(p.winners)) == len(p.winners) <= len(BPS)
    assert all(scores[c] > 0 for c in p.winners)
    if pot < MIN_POT_LAMPORTS_DEFAULT:
        assert not p.drawn and p.reason == "below_min_pot" and p.rollover == pot
    elif p.drawn:
        assert p.eligible >= 100
    assert p == plan(dict(reversed(list(scores.items()))), pot)


def test_no_eligible_rolls_over_and_zero_score_never_wins() -> None:
    p = plan({1: 0, 2: 0}, 10**9)
    assert (p.drawn, p.reason, p.rollover) == (False, "no_eligible", 10**9)
    scores = {i: 10**6 for i in range(1, 120)} | {0: 0}
    p = plan(scores, 10**9)
    assert p.drawn and 0 not in p.winners


def test_score_weighs_linearly() -> None:
    sc = {"a": 10**8, "b": 10**6} | {f"h{i}": 10**6 for i in range(10_000)}
    w = draw_weights(sc, sc, S, min_holding_share=Fraction(1, 10**18))
    assert w["a"] == 100 * w["b"]  # 100x score -> 100x weight (was 10x with isqrt)

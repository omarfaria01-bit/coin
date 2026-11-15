"""Soft-mode vesting forfeit + taint, minute-boundary unlocks (COIN_MATH v0.3.3 §11 B)."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.params import VestingParams
from engine.types import EventKind, TokenEvent
from engine.vesting import VestedLot, soft_vesting_breaches

B, S, T = EventKind.BUY, EventKind.SELL, EventKind.TRANSFER
P = VestingParams()
DAY, T0 = 86_400, 1_700_000_040  # T0 is a minute boundary
FORFEIT = 30 * DAY
DEV = VestedLot("dev", 100, T0, Fraction(1))


def ev(kind, ts, src=None, dst=None, amount=10, sig=None) -> TokenEvent:
    lam = amount if kind is not T else None
    return TokenEvent(ts, ts, sig or f"s{ts}", 0, kind, src, dst, amount, lam, "P")


def flat(price):
    return lambda _t: Fraction(price)


def _run(events, price=1, vested=(DEV,), **kw):
    return soft_vesting_breaches(
        events, vested, P, flat(price) if price else (lambda _t: None), **kw
    )


def test_selling_below_locked_forfeits_and_selling_unlocked_part_does_not() -> None:
    buy = ev(B, T0, dst="dev", amount=100)
    # After 1 day u_time = 1/7: locked = 600/7 ≈ 85.7. Selling 14 keeps 86 ≥ locked.
    ok = _run([buy, ev(S, T0 + DAY, src="dev", amount=14)])
    assert ok.forfeit_until == {} and ok.taint_until == {}
    bad = _run([buy, ev(S, T0 + DAY, src="dev", amount=15)])
    assert bad.forfeit_until == {"dev": T0 + DAY + FORFEIT}
    assert bad.taint_until == {}  # a sale to the pool taints nothing


def test_transfer_out_taints_the_moved_tokens() -> None:
    events = [
        ev(B, T0, dst="dev", amount=100),
        ev(T, T0 + 3_600, src="dev", dst="friend", amount=50, sig="leak"),
        ev(T, T0 + 7_200, src="friend", dst="buyer", amount=50),
    ]
    res = _run(events)
    until = T0 + 3_600 + FORFEIT
    assert res.forfeit_until == {"dev": until} and res.taint_until == {("leak", 0): until}


def test_internal_moves_never_breach() -> None:
    events = [ev(B, T0, dst="dev", amount=100), ev(T, T0 + 60, src="dev", dst="dev2", amount=100)]
    res = _run(events, cluster_of={"dev": "dev", "dev2": "dev"})
    assert res.forfeit_until == {}


def test_price_unlock_needs_24h_and_a_trusted_window() -> None:
    sell_all = ev(S, T0 + DAY + 60, src="dev", amount=100)
    buy = ev(B, T0, dst="dev", amount=100)
    assert _run([buy, sell_all], price=5).forfeit_until == {}  # 5× entry: fully unlocked
    assert _run([buy, sell_all], price=None).forfeit_until != {}  # untrusted: time only
    early = ev(S, T0 + 3_600, src="dev", amount=100)
    assert _run([buy, early], price=5).forfeit_until != {}  # before 24h: no price unlock


def test_unlock_is_evaluated_on_minute_boundaries_only() -> None:
    buy = ev(B, T0, dst="dev", amount=100)
    assert _run([buy, ev(S, T0 + 7 * DAY - 1, src="dev", amount=100)]).forfeit_until != {}
    assert _run([buy, ev(S, T0 + 7 * DAY, src="dev", amount=100)]).forfeit_until == {}


def test_excluded_and_validation() -> None:
    events = [ev(T, T0, src="HUB", dst="dev", amount=100), ev(S, T0 + 60, src="dev", amount=1)]
    assert _run(events, excluded=frozenset({"HUB"})).forfeit_until == {"dev": T0 + 60 + FORFEIT}
    with pytest.raises(ValueError, match="vested lot"):
        _run([], vested=(VestedLot("x", 0, T0, Fraction(1)),))


@given(st.lists(st.integers(1, 30), max_size=12), st.integers(1, 5))
@settings(max_examples=100, deadline=None)
def test_property_keeping_the_vested_amount_never_forfeits(sells: list[int], price: int) -> None:
    # The dev also holds 300 unvested tokens; selling only those never breaches.
    events = [ev(B, T0, dst="dev", amount=400)]
    held = 400
    for i, amt in enumerate(sells, start=1):
        if held - amt >= 100:
            events.append(ev(S, T0 + i * 3_600, src="dev", amount=amt))
            held -= amt
    assert _run(events, price=price).forfeit_until == {}

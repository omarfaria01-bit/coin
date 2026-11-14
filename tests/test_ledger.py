"""Tests for engine/ledger.py (COIN_MATH §1, price unit D13)."""

from __future__ import annotations

from collections import defaultdict

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from engine.ledger import build_lots
from engine.types import EventKind, Lot, LotSource, TokenEvent, WalletId


def ev(
    kind: EventKind,
    *,
    slot: int = 1,
    ts: int = 1,
    sig: str = "s",
    ix: int = 0,
    src: str | None = None,
    dst: str | None = None,
    amount: int = 10,
    lamports: int | None = None,
) -> TokenEvent:
    if kind is EventKind.BUY and lamports is None:
        lamports = amount
    return TokenEvent(slot, ts, sig, ix, kind, src, dst, amount, lamports, "P")


def twap(ts: int) -> float:
    return float(ts)


def test_lifo_partial_sell_keeps_oldest_lot_age() -> None:
    events = [
        ev(EventKind.BUY, slot=1, ts=10, sig="b1", dst="A", amount=5, lamports=10),
        ev(EventKind.BUY, slot=2, ts=20, sig="b2", dst="A", amount=5, lamports=20),
        ev(EventKind.SELL, slot=3, ts=30, sig="s1", src="A", amount=7),
    ]
    lots = build_lots(events, frozenset(), twap)
    assert lots["A"] == (Lot(3, 2.0, 10, LotSource.POOL_BUY),)


def test_selling_all_clears_wallet_and_keys_sorted() -> None:
    events = [
        ev(EventKind.BUY, slot=1, ts=1, sig="z", dst="Z", amount=1, lamports=3),
        ev(EventKind.BUY, slot=2, ts=2, sig="a", dst="A", amount=8, lamports=8),
        ev(EventKind.SELL, slot=3, ts=3, sig="s", src="A", amount=8),
    ]
    lots = build_lots(events, frozenset(), twap)
    assert "A" not in lots
    assert list(lots) == ["Z"]
    assert lots["Z"] == (Lot(1, 3.0, 1, LotSource.POOL_BUY),)


def test_transfer_in_cost_is_twap_and_excluded_skips() -> None:
    calls: list[int] = []

    def tracked(ts: int) -> float:
        calls.append(ts)
        return 3.5

    buy = ev(EventKind.BUY, ts=1, sig="b", dst="A", amount=4, lamports=8)
    transfer = ev(EventKind.TRANSFER, slot=2, ts=7, sig="t", src="A", dst="B", amount=4)

    def boom(_ts: int) -> float:
        raise AssertionError("twap must not be called for an excluded dst")

    # Excluded dst: src is still debited, twap_1h is not called, dst holds nothing.
    lots = build_lots([buy, transfer], frozenset({"B"}), boom)
    assert "A" not in lots and "B" not in lots

    lots = build_lots([buy, transfer], frozenset(), tracked)
    assert lots["B"] == (Lot(4, 3.5, 7, LotSource.TRANSFER_IN),)
    assert "A" not in lots
    assert calls == [7]
    # Excluded src is not debited, but a non-excluded dst still receives.
    lots = build_lots([buy, transfer], frozenset({"A"}), twap)
    assert "A" not in lots
    assert lots["B"][0].source is LotSource.TRANSFER_IN


def test_oversell_raises_naming_wallet_and_sig() -> None:
    events = [
        ev(EventKind.BUY, sig="b", dst="A", amount=50, lamports=50),
        ev(EventKind.SELL, slot=2, sig="sig123", src="A", amount=100),
    ]
    with pytest.raises(ValueError, match=r"wallet=A.*sig=sig123"):
        build_lots(events, frozenset(), twap)
    # Excluded src never raises.
    assert (
        build_lots([ev(EventKind.SELL, sig="x", src="H", amount=9)], frozenset({"H"}), twap) == {}
    )


def test_replay_sorts_by_slot_sig_ix_not_input_order() -> None:
    # Unsorted: sell first in the list, but buy sorts earlier (sig "a" < "z", same slot).
    events = [
        ev(EventKind.SELL, slot=1, sig="z", ix=0, src="A", amount=1),
        ev(EventKind.BUY, slot=1, sig="a", ix=0, dst="A", amount=1, lamports=2),
    ]
    lots = build_lots(events, frozenset(), twap)
    assert "A" not in lots


def test_self_transfer_resets_age_to_twap() -> None:
    events = [
        ev(EventKind.BUY, ts=1, sig="b", dst="A", amount=4, lamports=8),
        ev(EventKind.TRANSFER, slot=2, ts=9, sig="t", src="A", dst="A", amount=4),
    ]
    lots = build_lots(events, frozenset(), twap)
    assert lots["A"] == (Lot(4, 9.0, 9, LotSource.TRANSFER_IN),)


def _net_flow(events: list[TokenEvent], excluded: frozenset[WalletId]) -> dict[str, int]:
    flow: dict[str, int] = defaultdict(int)
    for e in events:
        if e.kind is EventKind.BUY and e.dst is not None and e.dst not in excluded:
            flow[e.dst] += e.amount
        elif e.kind is EventKind.SELL and e.src is not None and e.src not in excluded:
            flow[e.src] -= e.amount
        elif e.kind is EventKind.TRANSFER:
            if e.src is not None and e.src not in excluded:
                flow[e.src] -= e.amount
            if e.dst is not None and e.dst not in excluded:
                flow[e.dst] += e.amount
    return flow


@st.composite
def _event_lists(draw: st.DrawFn) -> list[TokenEvent]:
    n = draw(st.integers(0, 10))
    evs: list[TokenEvent] = []
    wallets = ("A", "B", "C")
    for i in range(n):
        kind = draw(st.sampled_from(list(EventKind)))
        w = draw(st.sampled_from(wallets))
        amt = draw(st.integers(1, 15))
        if kind is EventKind.BUY:
            evs.append(ev(kind, slot=i, ts=i, sig=f"s{i}", dst=w, amount=amt, lamports=amt * 3))
        elif kind is EventKind.SELL:
            evs.append(ev(kind, slot=i, ts=i, sig=f"s{i}", src=w, amount=amt))
        else:
            other = draw(st.sampled_from(("A", "B", "C", "P")))
            evs.append(ev(kind, slot=i, ts=i, sig=f"s{i}", src=w, dst=other, amount=amt))
    return evs


@given(_event_lists(), st.sampled_from((frozenset(), frozenset({"P"}), frozenset({"P", "C"}))))
@settings(max_examples=60, deadline=None)
def test_shuffle_same_output_and_amounts_match_net_flow(
    events: list[TokenEvent], excluded: frozenset[str]
) -> None:
    try:
        out = build_lots(events, excluded, twap)
    except ValueError:
        assume(False)
        return
    shuffled = list(reversed(events))
    assert build_lots(shuffled, excluded, twap) == out
    flow = _net_flow(events, excluded)
    assert list(out) == sorted(out)
    for wid, lots in out.items():
        assert lots == tuple(lots)
        assert sum(lot.amount for lot in lots) == flow[wid]
    for wid, net in flow.items():
        if net > 0:
            assert sum(lot.amount for lot in out[wid]) == net
        else:
            assert wid not in out

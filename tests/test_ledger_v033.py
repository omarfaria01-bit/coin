"""v0.3.3 ledger: origin, taint, cluster-internal moves, no-grief LIFO (COIN_MATH §1)."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.ledger import LedgerLot, Origin, build_ledger
from engine.types import EventKind, LotSource, TokenEvent

B, S, T = EventKind.BUY, EventKind.SELL, EventKind.TRANSFER


def ev(kind, slot, src=None, dst=None, amount=10, lamports=None, ix=0) -> TokenEvent:
    if kind is not T and lamports is None:
        lamports = amount * 3 if kind is B else 0
    return TokenEvent(slot, slot * 10, f"sig{slot}", ix, kind, src, dst, amount, lamports, "P")


def test_buy_has_exact_cost_and_origin() -> None:
    led = build_ledger([ev(B, 1, dst="A", amount=3, lamports=10)], frozenset())
    cost = Fraction(10, 3)
    assert led["A"] == (LedgerLot(3, cost, 10, LotSource.POOL_BUY, Origin("sig1", 10, cost)),)


def test_cross_cluster_transfer_resets_age_keeps_origin() -> None:
    events = [ev(B, 1, dst="A", amount=10, lamports=20), ev(T, 2, src="A", dst="B", amount=4)]
    led = build_ledger(events, frozenset())
    assert led["A"][0].amount == 6 and led["A"][0].t_acquired == 10
    moved = led["B"][0]
    assert (moved.amount, moved.cost_q, moved.t_acquired, moved.source) == (
        4,
        None,
        20,
        LotSource.TRANSFER_IN,
    )
    assert moved.origin == Origin("sig1", 10, Fraction(2))


def test_internal_move_keeps_everything_and_retroactive_merge_restores_age() -> None:
    events = [ev(B, 1, dst="A", amount=10), ev(T, 2, src="A", dst="B", amount=10)]
    merged = build_ledger(events, frozenset(), cluster_of={"A": "A", "B": "A"})
    assert merged["B"] == (
        LedgerLot(10, Fraction(3), 10, LotSource.POOL_BUY, Origin("sig1", 10, Fraction(3))),
    )
    unmerged = build_ledger(events, frozenset())
    assert unmerged["B"][0].t_acquired == 20


def test_no_grief_received_tokens_are_newest_and_leave_first() -> None:
    events = [
        ev(B, 1, dst="A", amount=5),
        ev(B, 2, dst="X", amount=7),
        ev(T, 3, src="X", dst="A", amount=7),  # griefer sends tokens to A
        ev(S, 4, src="A", amount=7),  # A sells: the received tokens go first
    ]
    led = build_ledger(events, frozenset())
    assert [(lot.amount, lot.t_acquired) for lot in led["A"]] == [(5, 10)]


def test_taint_follows_the_lot_through_further_transfers() -> None:
    events = [
        ev(B, 1, dst="A", amount=10),
        ev(T, 2, src="A", dst="B", amount=6),  # locked outflow: tainted
        ev(T, 3, src="B", dst="C", amount=6),
        ev(T, 4, src="C", dst="D", amount=2, ix=0),
    ]
    led = build_ledger(events, frozenset(), taint_until={("sig2", 0): 999})
    assert led["A"][0].tainted_until == 0
    assert led["C"][0].tainted_until == 999 and led["D"][0].tainted_until == 999
    # A later, earlier-ending taint never shortens the lot's taint.
    led2 = build_ledger(events, frozenset(), taint_until={("sig2", 0): 999, ("sig3", 0): 5})
    assert led2["C"][0].tainted_until == 999


def test_excluded_accounts_and_validation() -> None:
    events = [
        ev(T, 1, src="HUB", dst="A", amount=4),  # hub/treasury source: fresh transfer lot
        ev(T, 2, src="A", dst="POOLVAULT", amount=1),  # to excluded: just leaves
        ev(B, 3, dst="POOLVAULT", amount=9),
        ev(T, 4, src="A", dst="A", amount=3),  # self-transfer: no-op
    ]
    led = build_ledger(events, frozenset({"HUB", "POOLVAULT"}))
    assert set(led) == {"A"}
    assert led["A"][0].amount == 3 and led["A"][0].origin == Origin("sig1", 10, None)
    with pytest.raises(ValueError, match="oversell"):
        build_ledger([ev(S, 1, src="A", amount=1)], frozenset())
    for bad in (ev(B, 1, dst=None), ev(S, 1, src=None), ev(B, 1, dst="A", amount=0)):
        with pytest.raises(ValueError, match="bad event"):
            build_ledger([bad], frozenset())


_ops = st.lists(
    st.tuples(
        st.sampled_from("BST"), st.sampled_from("ABC"), st.sampled_from("ABC"), st.integers(1, 9)
    ),
    max_size=25,
)


@given(_ops, st.booleans())
@settings(max_examples=200, deadline=None)
def test_property_conservation_and_lot_invariants(ops, merge_all: bool) -> None:
    events, bal = [], {"A": 0, "B": 0, "C": 0}
    for slot, (kind, src, dst, amt) in enumerate(ops, start=1):
        if kind == "B":
            events.append(ev(B, slot, dst=dst, amount=amt))
            bal[dst] += amt
        elif bal[src] >= amt:
            events.append(
                ev(
                    S if kind == "S" else T,
                    slot,
                    src=src,
                    dst=None if kind == "S" else dst,
                    amount=amt,
                )
            )
            bal[src] -= amt
            bal[dst] += amt if kind == "T" else 0
    cmap = {"A": "A", "B": "A", "C": "A"} if merge_all else None
    led = build_ledger(events, frozenset(), cluster_of=cmap)
    for w, expected in bal.items():
        lots = led.get(w, ())
        assert sum(lot.amount for lot in lots) == expected
        for lot in lots:
            assert lot.amount > 0
            assert (lot.cost_q is None) == (lot.source is LotSource.TRANSFER_IN)
            if merge_all:  # one cluster: every lot is still an original pool buy
                assert lot.source is LotSource.POOL_BUY and lot.t_acquired == lot.origin.ts


def test_segments_step_function_of_the_second() -> None:
    from engine.ledger import ledger_segments

    events = [
        ev(B, 1, dst="A", amount=10),  # ts 10, before the window
        ev(S, 3, src="A", amount=4),  # ts 30
        ev(T, 5, src="A", dst="B", amount=6),  # ts 50: A empties
        ev(B, 7, dst="C", amount=1),  # ts 70 = t1: outside [20, 70)
    ]
    segs = ledger_segments(events, frozenset(), 20, 70)
    assert [(a, b, [lot.amount for lot in lots]) for a, b, lots in segs["A"]] == [
        (20, 30, [10]),
        (30, 50, [6]),
    ]
    assert [(a, b) for a, b, _ in segs["B"]] == [(50, 70)] and "C" not in segs
    # Bought and sold in the same second: zero duration, no segment.
    flash = [ev(B, 3, dst="F", amount=5, ix=0), ev(S, 3, src="F", amount=5, ix=1)]
    assert ledger_segments(flash, frozenset(), 0, 100) == {}
    with pytest.raises(ValueError, match="t1"):
        ledger_segments([], frozenset(), 5, 4)

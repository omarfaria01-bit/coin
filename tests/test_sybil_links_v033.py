"""v0.3.3 one-sided link signals L4–L6 and hub candidates (COIN_MATH §7)."""

from __future__ import annotations

from engine.sybil_v033 import (
    Kind,
    cluster,
    hub_candidates,
    l4_co_trades,
    l5_identical_balances,
    l6_shared_proceeds,
    transfer_links,
)
from engine.types import EventKind, SolTransfer, TokenEvent

NO_HUBS: frozenset[str] = frozenset()
B, S = EventKind.BUY, EventKind.SELL


def trade(kind, w, ts, amount, n=0) -> TokenEvent:
    src, dst = (None, w) if kind is B else (w, None)
    return TokenEvent(ts, ts, f"{w}{ts}{n}", 0, kind, src, dst, amount, amount, w)


def sol(src, dst, ts) -> SolTransfer:
    return SolTransfer(ts, ts, f"s{src}{dst}{ts}", src, dst, 1)


def test_l4_needs_three_matching_trades_within_one_second_and_ten_percent() -> None:
    copy = [trade(B, "A", t, 100) for t in (10, 50, 90)]
    copy += [trade(B, "B", t + 1, 109) for t in (10, 50, 90)]
    edges = l4_co_trades(copy, NO_HUBS)
    assert [(e.a, e.b, e.kind) for e in edges] == [("A", "B", Kind.L4_CO_TRADE)]
    # Two occasions only, a 2-second gap, an 11% size gap, or the opposite side: none count.
    assert l4_co_trades(copy[:2] + copy[3:5], NO_HUBS) == []
    late = [trade(B, "A", t, 100) for t in (10, 50, 90)] + [
        trade(B, "B", t + 2, 100) for t in (10, 50, 90)
    ]
    assert l4_co_trades(late, NO_HUBS) == []
    big = [trade(B, "A", t, 100) for t in (10, 50, 90)] + [
        trade(B, "B", t, 112) for t in (10, 50, 90)
    ]
    assert l4_co_trades(big, NO_HUBS) == []
    mirror = [trade(B, "A", t, 100) for t in (10, 50, 90)] + [
        trade(S, "B", t, 100) for t in (10, 50, 90)
    ]
    assert l4_co_trades(mirror, NO_HUBS) == []
    # One copier trade matched against three of the leader's does not count three times.
    burst = [trade(B, "A", 10, 100, n) for n in range(3)] + [trade(B, "B", 10, 100)]
    assert l4_co_trades(burst, NO_HUBS) == []
    assert l4_co_trades(copy, frozenset({"B"})) == []


def test_l5_four_identical_balances_created_within_a_day() -> None:
    bal = {"w1": 1_000_000, "w2": 1_000_500, "w3": 999_900, "w4": 1_000_800, "x": 2_000_000}
    created = {"w1": 0, "w2": 3_600, "w3": 7_200, "w4": 86_400, "x": 0}
    edges = l5_identical_balances(bal, created, NO_HUBS)
    assert {(e.a, e.b) for e in edges} == {
        ("w1", "w2"), ("w1", "w3"), ("w1", "w4"), ("w2", "w3"), ("w2", "w4"), ("w3", "w4"),
    }  # fmt: skip
    late = {**created, "w4": 86_400 + 7_200 + 1}  # spread > 24h from w3's group start
    assert l5_identical_balances(bal, {**late, "w1": 0}, NO_HUBS) == []
    far = {**bal, "w4": 1_002_000}  # > 0.1% away
    assert l5_identical_balances(far, created, NO_HUBS) == []


def test_l6_shared_destination_after_sales() -> None:
    events = [trade(S, "A", 100, 10), trade(S, "B", 200, 10), trade(S, "C", 300, 10)]
    sols = [sol("A", "D", 150), sol("B", "D", 250), sol("C", "D", 300 + 86_401)]
    edges = l6_shared_proceeds(events, sols, NO_HUBS)
    assert [(e.a, e.b, e.kind) for e in edges] == [("A", "B", Kind.L6_SHARED_PROCEEDS)]
    assert l6_shared_proceeds(events, sols, frozenset({"D"})) == []  # CEX deposit = hub


def test_one_sided_links_never_merge_without_l1_or_l2() -> None:
    copy = [trade(B, "A", t, 100) for t in (10, 50, 90)] + [
        trade(B, "B", t, 100) for t in (10, 50, 90)
    ]
    sells = [trade(S, "A", 500, 1), trade(S, "B", 500, 1)]
    edges = l4_co_trades(copy, NO_HUBS)
    edges += l6_shared_proceeds(sells, [sol("A", "D", 600), sol("B", "D", 600)], NO_HUBS)
    assert cluster({"A", "B"}, edges).members == {"A": ("A",), "B": ("B",)}  # 0.9, one-sided
    both_ways = [sol("A", "B", 1), sol("B", "A", 2)]
    merged = cluster({"A", "B"}, edges + transfer_links([], both_ways, NO_HUBS))
    assert merged.members == {"A": ("A", "B")}  # 0.4 + 0.5 + L2 0.5 = 1.4 with L2


def test_hub_candidates_are_review_only() -> None:
    sols = [sol("EXCH", f"u{i:02d}", i) for i in range(25)] + [sol("u00", "u01", 99)]
    assert hub_candidates([], sols, NO_HUBS) == ("EXCH",)
    assert hub_candidates([], sols, frozenset({"EXCH"})) == ()
    assert hub_candidates([], sols[:24], NO_HUBS) == ()

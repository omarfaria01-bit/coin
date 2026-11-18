"""D39 (#271 M2): one-way funding (S2) needs bidirectional evidence when s2_two_sided=True."""

from __future__ import annotations

from engine.sybil_v033 import cluster, s2_funded_buys, transfer_links
from engine.types import EventKind, SolTransfer, TokenEvent

SOL = 10**9
NO_HUBS: frozenset[str] = frozenset()


def buy(w, ts, lamports) -> TokenEvent:
    return TokenEvent(ts, ts, f"b{w}{ts}", 0, EventKind.BUY, None, w, 100, lamports, w)


def sol(src, dst, ts, lamports) -> SolTransfer:
    return SolTransfer(ts, ts, f"s{src}{dst}{ts}", src, dst, lamports)


def test_one_way_funding_goes_to_review_and_does_not_merge() -> None:
    sols = [sol("X", "W1", 1, SOL), sol("X", "W2", 1, SOL)]
    events = [buy("W1", 2, SOL), buy("W2", 3, SOL)]
    edges = s2_funded_buys(events, sols, NO_HUBS)
    res = cluster({"W1", "W2"}, edges, s2_two_sided=True)
    assert res.members == {"W1": ("W1",), "W2": ("W2",)}
    assert res.funding_review == (("W1", "X"), ("W2", "X"))
    # default (v0.3.3 daily epoch) is unchanged
    assert cluster({"W1", "W2"}, edges).members == {"W1": ("W1", "W2", "X")}


def test_funding_plus_sol_back_merges() -> None:
    sols = [
        sol("X", "W1", 1, SOL),
        sol("X", "W2", 1, SOL),
        sol("W1", "X", 5, 1),
        sol("W2", "X", 6, 1),
    ]
    events = [buy("W1", 2, SOL), buy("W2", 3, SOL)]
    edges = s2_funded_buys(events, sols, NO_HUBS) + transfer_links(events, sols, NO_HUBS)
    res = cluster({"W1", "W2"}, edges, s2_two_sided=True)
    assert res.members == {"W1": ("W1", "W2", "X")} and res.funding_review == ()


def test_framing_a_victim_by_sending_it_sol_does_not_merge_it() -> None:
    sols = [sol("ATK", "VIC", 1, 5 * SOL)]
    events = [buy("ATK", 1, SOL), buy("VIC", 2, SOL)]
    res = cluster({"ATK", "VIC"}, s2_funded_buys(events, sols, NO_HUBS), s2_two_sided=True)
    assert res.cluster_of["VIC"] == "VIC" and res.cluster_of["ATK"] == "ATK"
    assert res.funding_review == (("ATK", "VIC"),)

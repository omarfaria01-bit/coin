"""v0.3.3 sybil clustering: S1–S3, L1–L3, merge rule, review lists (COIN_MATH §7)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.sybil_v033 import (
    Edge,
    Kind,
    cluster,
    s1_cosigned,
    s2_funded_buys,
    s3_overrides,
    transfer_links,
)
from engine.types import EventKind, SolTransfer, TokenEvent

SOL = 10**9
NO_HUBS: frozenset[str] = frozenset()


def buy(w, ts, lamports, payer=None) -> TokenEvent:
    return TokenEvent(ts, ts, f"b{w}{ts}", 0, EventKind.BUY, None, w, 100, lamports, payer or w)


def tok(src, dst, ts) -> TokenEvent:
    return TokenEvent(ts, ts, f"t{src}{dst}{ts}", 0, EventKind.TRANSFER, src, dst, 5, None, src)


def sol(src, dst, ts, lamports) -> SolTransfer:
    return SolTransfer(ts, ts, f"s{src}{dst}{ts}", src, dst, lamports)


def test_s1_cosigned_holders_merge_hubs_and_non_holders_do_not() -> None:
    signers = {"tx1": frozenset({"A", "B", "RELAY"}), "tx2": frozenset({"C", "D"})}
    edges = s1_cosigned(frozenset({"A", "B", "C", "RELAY"}), signers, frozenset({"RELAY"}))
    assert edges == [Edge("A", "B", Kind.S1_COSIGNED, "tx1")]
    assert cluster({"A", "B", "C"}, edges).members == {"A": ("A", "B"), "C": ("C",)}


def test_s2_farm_funded_by_one_wallet_lands_in_the_funders_cluster() -> None:
    sols = [sol("X", "W1", 1, SOL), sol("X", "W2", 1, SOL)]
    events = [buy("W1", 2, SOL), buy("W2", 3, SOL)]
    res = cluster({"W1", "W2"}, s2_funded_buys(events, sols, NO_HUBS))
    assert res.members == {"W1": ("W1", "W2", "X")}  # X holds no token, still a member


def test_s2_dust_and_partial_funding_do_not_merge() -> None:
    hubs = frozenset({"CEX"})
    # Dust: the victim's own 10 SOL came from a CEX; 0.01 SOL from the attacker.
    dust = [sol("CEX", "V", 1, 10 * SOL), sol("ATK", "V", 2, SOL // 100)]
    assert s2_funded_buys([buy("V", 3, 5 * SOL)], dust, hubs) == []
    # Attacker sent 2 of 3 SOL received (≥ 50%) but V spent 5 SOL: 2 < 2.5, no merge.
    part = [sol("CEX", "V", 1, SOL), sol("ATK", "V", 2, 2 * SOL)]
    assert s2_funded_buys([buy("V", 3, 5 * SOL)], part, hubs) == []
    # Hubs are never funders.
    assert s2_funded_buys([buy("V", 3, SOL)], [sol("CEX", "V", 1, SOL)], hubs) == []
    # Same funding, smaller buy: both 50% conditions hold → merge, ref = the buy.
    edges = s2_funded_buys([buy("V", 3, 4 * SOL)], part, hubs)
    assert edges == [Edge("ATK", "V", Kind.S2_FUNDED_BUY, "bV3")]


def test_s3_override_and_merge_rule_needs_a_two_sided_link() -> None:
    assert cluster({"A", "B"}, s3_overrides([("B", "A", "ov-1"), ("C", "C", "x")])).members == {
        "A": ("A", "B")
    }
    one_sided = [Edge("A", "B", k, "r") for k in (Kind.L3_TOKEN_ONE_WAY, Kind.L4_CO_TRADE)]
    one_sided.append(Edge("A", "B", Kind.L6_SHARED_PROCEEDS, "r"))  # Σ = 1.2, no L1/L2
    assert cluster({"A", "B"}, one_sided).members == {"A": ("A",), "B": ("B",)}
    l1_l3 = [
        Edge("A", "B", Kind.L1_TOKEN_BOTH_WAYS, "r"),
        Edge("A", "B", Kind.L3_TOKEN_ONE_WAY, "r"),
    ]
    assert cluster({"A", "B"}, l1_l3).members == {"A": ("A",), "B": ("B",)}  # 0.9 < 1
    l1_l6 = [l1_l3[0], Edge("A", "B", Kind.L6_SHARED_PROCEEDS, "r")]
    res = cluster({"A", "B"}, l1_l6)  # 1.1 with L1 → merge, listed as link-only
    assert res.members == {"A": ("A", "B")} and res.link_only == (("A", "B"),)


def test_transfer_links_l1_l2_l3_and_alice_pays_bob_once() -> None:
    assert transfer_links([tok("Alice", "Bob", 10)], [], NO_HUBS) == []
    events = [tok("A", "B", 10), tok("B", "A", 20), tok("C", "D", 10), tok("C", "D", 86_410)]
    sols = [sol("A", "B", 5, 1), sol("B", "A", 6, 1), sol("A", "HUB", 7, 1), sol("HUB", "A", 8, 1)]
    kinds = {(e.a, e.b, e.kind) for e in transfer_links(events, sols, frozenset({"HUB"}))}
    assert kinds == {
        ("A", "B", Kind.L1_TOKEN_BOTH_WAYS),
        ("A", "B", Kind.L2_SOL_BOTH_WAYS),
        ("C", "D", Kind.L3_TOKEN_ONE_WAY),
    }
    res = cluster({"A", "B", "C", "D"}, transfer_links(events, sols, frozenset({"HUB"})))
    assert res.members == {"A": ("A", "B"), "C": ("C",), "D": ("D",)}


def test_shared_fee_payer_is_informational_and_big_clusters_go_to_review() -> None:
    holders = {f"h{i}" for i in range(5)}
    events = [buy(h, 1, SOL, payer="APP") for h in sorted(holders)]
    res = cluster(holders, [], events=events)
    assert len(res.members) == 5 and res.shared_payers == ("APP",)
    big = {f"w{i:02d}" for i in range(51)}
    chain = [Edge(f"w{i:02d}", f"w{i + 1:02d}", Kind.S3_OVERRIDE, "ov") for i in range(50)]
    assert cluster(big, chain).review == ("w00",)


_edge = st.builds(
    lambda a, b, k: Edge(min(a, b), max(a, b), k, "r"),
    st.sampled_from("ABCDE"),
    st.sampled_from("ABCDE"),
    st.sampled_from(list(Kind)),
).filter(lambda e: e.a != e.b)


@given(st.lists(_edge, max_size=15), st.lists(_edge, max_size=5))
@settings(max_examples=200, deadline=None)
def test_property_monotone_more_evidence_never_splits(base: list[Edge], extra: list[Edge]) -> None:
    holders = set("ABCDE")
    before = cluster(holders, base).cluster_of
    after = cluster(holders, base + extra).cluster_of
    for x in holders:
        for y in holders:
            if before[x] == before[y]:
                assert after[x] == after[y]

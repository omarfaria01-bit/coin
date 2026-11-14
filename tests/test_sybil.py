"""Tests for engine/sybil.py (ENGINE_DESIGN §4.3)."""

from __future__ import annotations

import random
import time
from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.params import SybilParams
from engine.sybil import EvidenceKind, build_evidence, cluster
from engine.types import EventKind, FirstFunding, SolTransfer, TokenEvent

P, W, H = SybilParams(), 72 * 3600, 24 * 3600


_TE = TokenEvent(1, 1_000, "s", 0, EventKind.BUY, None, "A", 1_000, None, "P")


def te(**kw) -> TokenEvent:
    return replace(_TE, **kw)


def ff(wallet: str, funder: str, ts: int, created: int | None = None) -> FirstFunding:
    return FirstFunding(wallet, funder, ts, created if created is not None else ts)


def kinds(evs) -> set[tuple[str, str, EvidenceKind]]:
    return {(e.a, e.b, e.kind) for e in evs}


def ev(holders, events=(), sols=(), fundings=(), bals=None, hubs=frozenset()):
    return build_evidence(holders, list(events), list(sols), list(fundings), bals or {}, hubs, P)


def test_hubs_and_non_holders_never_create_edges():
    holders, hubs = ["A", "B", "H"], frozenset({"H", "CEX"})
    events = [
        te(sig="1", src="A", dst="H", kind=EventKind.TRANSFER, fee_payer="A"),
        te(sig="2", src="A", dst="CEX", kind=EventKind.TRANSFER, fee_payer="A"),
        te(sig="3", dst="A", fee_payer="CEX"),
        te(sig="4", src="A", dst="Z", kind=EventKind.TRANSFER, fee_payer="A"),
        te(sig="7", src="A", dst="A", kind=EventKind.TRANSFER, fee_payer="A"),
    ]
    sols = [
        SolTransfer(1, 1, "5", "A", "H", 10),
        SolTransfer(1, 1, "6", "A", "Z", 10),
        SolTransfer(1, 1, "8", "A", "A", 1),
    ]
    funds = [ff("A", "CEX", 1), ff("B", "CEX", 1), ff("H", "X", 1)]
    evs = ev(holders, events, sols, funds, {"A": 1, "B": 1, "H": 1}, hubs)
    assert evs == []
    result = cluster(holders, evs, P)
    assert set(result.cluster_of) == {"A", "B", "H"}
    assert result.cluster_of["A"] == "A" and result.confidence["A"] == 1.0


def test_each_evidence_rule_thresholds():
    holders = ["A", "B"]
    own = [te(sig="a", dst="A", fee_payer="A"), te(sig="b", dst="B", fee_payer="B")]
    assert kinds(ev(holders, own)) == set()
    paid = [te(sig="z", dst="Z", fee_payer="P"), te(sig="a", dst="A"), te(sig="b", dst="B")]
    evs = ev(holders, paid)
    assert kinds(evs) == {("A", "B", EvidenceKind.SAME_FEE_PAYER)} and evs[0].ref == "a"

    evs = ev(holders, [te(sig="t", kind=EventKind.TRANSFER, src="A", dst="B", fee_payer="A")])
    assert ("A", "B", EvidenceKind.DIRECT_TRANSFER) in kinds(evs)
    evs2 = ev(holders, sols=[SolTransfer(1, 1, "u", "B", "A", 9)])
    assert kinds(evs2) == {("A", "B", EvidenceKind.DIRECT_TRANSFER)}
    none = [te(sig="t", kind=EventKind.TRANSFER, src="A", dst="Z", fee_payer="A")]
    assert kinds(ev(holders, none)) == set()

    buy_ts = 1_000 + W
    buys = [
        te(sig="ba", dst="A", ts=buy_ts, fee_payer="A"),
        te(sig="bb", dst="B", ts=buy_ts, fee_payer="B"),
    ]
    pos = [ff("A", "F", 1_000), ff("B", "F", 1_000)]
    assert kinds(ev(holders, buys, fundings=pos)) == {("A", "B", EvidenceKind.SAME_FIRST_FUNDER)}
    early = [ff("A", "F", 999), ff("B", "F", 1_000)]
    assert kinds(ev(holders, buys, fundings=early)) == set()
    assert kinds(ev(holders, buys, fundings=pos, hubs=frozenset({"F"}))) == set()

    def cobuy(slots: list[int], amt_a: int = 1_000, amt_b: int = 1_000) -> list[TokenEvent]:
        out = []
        for i, sl in enumerate(slots):
            out.append(te(slot=sl, sig=f"a{i}", dst="A", amount=amt_a, fee_payer="A"))
            out.append(te(slot=sl, sig=f"b{i}", dst="B", amount=amt_b, fee_payer="B"))
        return out

    assert kinds(ev(holders, cobuy([10, 20]))) == set()
    assert kinds(ev(holders, cobuy([10, 20, 30]))) == {("A", "B", EvidenceKind.CO_BUY)}
    assert kinds(ev(holders, cobuy([10, 20, 30], 1_000, 900))) == {("A", "B", EvidenceKind.CO_BUY)}
    assert kinds(ev(holders, cobuy([10, 20, 30], 1_000, 899))) == set()

    many, fund4 = ["A", "B", "C", "D", "E"], [ff(w, "X", 1, 1) for w in "ABCD"]
    bal4 = {w: 1_000 for w in "ABCD"}
    fund3 = [ff(w, "X", 1, 1) for w in "ABC"]
    assert kinds(ev(many, fundings=fund3, bals={w: 1_000 for w in "ABC"})) == set()
    ib = EvidenceKind.IDENTICAL_BALANCES
    want = {
        (a, b, ib)
        for a, b in (("A", "B"), ("A", "C"), ("A", "D"), ("B", "C"), ("B", "D"), ("C", "D"))
    }
    assert kinds(ev(many, fundings=fund4, bals=bal4)) == want
    close = {"A": 1000, "B": 1000, "C": 1000, "D": 1001}
    far = {"A": 1000, "B": 1000, "C": 1000, "D": 1002}
    assert kinds(ev(many, fundings=fund4, bals=close))
    assert kinds(ev(many, fundings=fund4, bals=far)) == set()
    late = [ff("A", "X", 1, 0), ff("B", "X", 1, 0), ff("C", "X", 1, 0), ff("D", "X", 1, H + 1)]
    on = [ff("A", "X", 1, 0), ff("B", "X", 1, 0), ff("C", "X", 1, 0), ff("D", "X", 1, H)]
    assert kinds(ev(many, fundings=late, bals=bal4)) == set()
    assert kinds(ev(many, fundings=on, bals=bal4))


def test_fifty_wallets_same_funder_one_cluster():
    holders = [f"W{i:02d}" for i in range(50)]
    buy_ts = 10_000 + W
    events = [
        te(slot=i + 1, sig=f"b{i}", dst=w, ts=buy_ts, fee_payer=w) for i, w in enumerate(holders)
    ]
    evs = ev(
        holders,
        events,
        fundings=[ff(w, "FUNDER", 10_000) for w in holders],
        bals={w: 1 for w in holders},
    )
    result = cluster(holders, evs, P)
    cid = min(holders)
    assert set(result.members[cid]) == set(holders)
    assert result.review == (cid,) and 0 < result.confidence[cid] <= 1.0


@given(st.randoms())
@settings(max_examples=40, deadline=None)
def test_output_stable_under_shuffle(rng: random.Random):
    holders = ["A", "B", "C", "D"]
    events = [
        te(slot=1, sig="t", kind=EventKind.TRANSFER, src="A", dst="B", fee_payer="A"),
        te(slot=2, sig="ba", dst="A", ts=10_000, fee_payer="A"),
        te(slot=2, sig="bb", dst="B", ts=10_000, fee_payer="B"),
        te(slot=3, sig="ca", dst="C", ts=10_000, fee_payer="P"),
        te(slot=3, sig="cb", dst="D", ts=10_000, fee_payer="P"),
    ]
    sols = [SolTransfer(4, 4, "sol", "C", "A", 5)]
    fundings = [ff("A", "F", 1, 1), ff("B", "F", 1, 1), ff("C", "G", 1, 1), ff("D", "G", 1, 1)]
    bals = {w: 100 for w in holders}
    evs = ev(holders, events, sols, fundings, bals)
    cl = cluster(holders, evs, P)
    h2, e2, s2, f2 = holders[:], events[:], sols[:], fundings[:]
    rng.shuffle(h2)
    rng.shuffle(e2)
    rng.shuffle(s2)
    rng.shuffle(f2)
    evs2 = ev(h2, e2, s2, f2, bals)
    cl2 = cluster(h2, evs2, P)
    assert evs2 == evs and cl2.cluster_of == cl.cluster_of and cl2.members == cl.members
    assert cl2.confidence == cl.confidence and cl2.review == cl.review


def test_10k_sparse_benchmark() -> None:
    n = 10_000
    holders = [f"W{i:05d}" for i in range(n)]
    tr = EventKind.TRANSFER
    events = [
        te(slot=i, sig=f"t{i}", kind=tr, src=holders[i], dst=holders[i + 1], fee_payer=holders[i])
        for i in range(0, n - 1, 20)
    ]
    t0 = time.perf_counter()
    evs = ev(holders, events, bals={w: 1 for w in holders})
    result = cluster(holders, evs, P)
    dt = time.perf_counter() - t0
    print(f"10k-holder sparse benchmark: {dt:.3f}s ev={len(evs)} clusters={len(result.members)}")
    assert dt < 5.0 and len(result.cluster_of) == n

"""Tests for v0.3.3 clustering: fee payer informational, one-way transfers (COIN_MATH §7)."""

from __future__ import annotations

from engine.sybil import (
    EvidenceKind,
    build_evidence_v033,
    cluster,
    cluster_v033,
)
from engine.types import EventKind, SolTransfer
from tests.test_sybil import P, ev, kinds, te


def ev033(holders, events=(), sols=(), fundings=(), bals=None, hubs=frozenset()):
    return build_evidence_v033(
        holders, list(events), list(sols), list(fundings), bals or {}, hubs, P
    )


def test_fee_payer_is_recorded_but_does_not_merge() -> None:
    holders = ["A", "B"]
    paid = [te(sig="z", dst="Z", fee_payer="P"), te(sig="a", dst="A"), te(sig="b", dst="B")]
    evs = ev033(holders, paid)
    assert kinds(evs) == {("A", "B", EvidenceKind.SAME_FEE_PAYER)}
    result = cluster_v033(holders, evs, P)
    assert result.cluster_of["A"] == "A" and result.cluster_of["B"] == "B"
    # v0.2 still merges on a shared fee payer (entry point unchanged).
    old = cluster(holders, ev(holders, paid), P)
    assert old.cluster_of["A"] == old.cluster_of["B"] == "A"


def test_one_way_token_does_not_merge() -> None:
    holders = ["A", "B"]
    # A single one-way transfer is not L3 and does not merge.
    once = [te(sig="t", kind=EventKind.TRANSFER, src="A", dst="B", fee_payer="A", ts=1)]
    evs = ev033(holders, once)
    assert EvidenceKind.ONE_WAY_TOKEN not in {e.kind for e in evs}
    assert EvidenceKind.TWO_SIDED_TOKEN not in {e.kind for e in evs}
    result = cluster_v033(holders, evs, P)
    assert result.cluster_of["A"] == "A" and result.cluster_of["B"] == "B"
    # Same direction on two distinct days → L3, still no merge (no two-sided signal).
    two_days = [
        te(sig="t0", kind=EventKind.TRANSFER, src="A", dst="B", fee_payer="A", ts=1, slot=1),
        te(
            sig="t1",
            kind=EventKind.TRANSFER,
            src="A",
            dst="B",
            fee_payer="A",
            ts=86_400 + 10,
            slot=2,
        ),
    ]
    evs2 = ev033(holders, two_days)
    assert ("A", "B", EvidenceKind.ONE_WAY_TOKEN) in kinds(evs2)
    result2 = cluster_v033(holders, evs2, P)
    assert result2.cluster_of["A"] == "A" and result2.cluster_of["B"] == "B"


def test_two_sided_token_and_sol_can_merge() -> None:
    holders = ["A", "B"]
    tokens = [
        te(sig="ab", kind=EventKind.TRANSFER, src="A", dst="B", fee_payer="A", ts=1, slot=1),
        te(sig="ba", kind=EventKind.TRANSFER, src="B", dst="A", fee_payer="B", ts=2, slot=2),
    ]
    evs = ev033(holders, tokens)
    assert ("A", "B", EvidenceKind.TWO_SIDED_TOKEN) in kinds(evs)
    assert EvidenceKind.ONE_WAY_TOKEN not in {e.kind for e in evs}
    # L1 alone is 0.6 < 1.0, so no merge without another two-sided signal.
    alone = cluster_v033(holders, evs, P)
    assert alone.cluster_of["A"] == "A" and alone.cluster_of["B"] == "B"
    sols = [SolTransfer(3, 3, "s1", "A", "B", 5), SolTransfer(4, 4, "s2", "B", "A", 5)]
    evs2 = ev033(holders, tokens, sols)
    kindset = kinds(evs2)
    assert ("A", "B", EvidenceKind.TWO_SIDED_TOKEN) in kindset
    assert ("A", "B", EvidenceKind.TWO_SIDED_SOL) in kindset
    merged = cluster_v033(holders, evs2, P)
    assert merged.cluster_of["A"] == merged.cluster_of["B"] == "A"
    assert merged.members["A"] == ("A", "B")


def test_link_only_merge_requires_a_two_sided_signal() -> None:
    # One-way L3 (0.3) plus a shared fee payer (informational) must not merge.
    holders = ["A", "B"]
    events = [
        te(sig="t0", kind=EventKind.TRANSFER, src="A", dst="B", fee_payer="P", ts=1, slot=1),
        te(
            sig="t1",
            kind=EventKind.TRANSFER,
            src="A",
            dst="B",
            fee_payer="P",
            ts=86_400 + 10,
            slot=2,
        ),
        te(sig="a", dst="A", fee_payer="P", slot=3, ts=86_400 + 20),
        te(sig="b", dst="B", fee_payer="P", slot=4, ts=86_400 + 21),
    ]
    evs = ev033(holders, events)
    assert EvidenceKind.SAME_FEE_PAYER in {e.kind for e in evs}
    assert EvidenceKind.ONE_WAY_TOKEN in {e.kind for e in evs}
    result = cluster_v033(holders, evs, P)
    assert result.cluster_of["A"] == "A" and result.cluster_of["B"] == "B"


def test_v02_direct_transfer_entry_point_unchanged() -> None:
    holders = ["A", "B"]
    events = [te(sig="t", kind=EventKind.TRANSFER, src="A", dst="B", fee_payer="A")]
    evs = ev(holders, events)
    assert ("A", "B", EvidenceKind.DIRECT_TRANSFER) in kinds(evs)
    result = cluster(holders, evs, P)
    assert result.cluster_of["A"] == result.cluster_of["B"]

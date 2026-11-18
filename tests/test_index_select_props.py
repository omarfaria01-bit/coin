"""Property tests for the pure index math in index/select.py (#193).

Covers conservation of ``weights_bps`` basis points, conservation of ``split_prize`` lamports,
determinism, and the buffer/hysteresis invariants of ``select_members``. Only tests change here;
``index/`` is untouched.

``weights_bps`` is fed members in rank order: ties in the largest-remainder step go to the earlier
member (the better rank). Permuting members can therefore move one basis point between mints, so
the order property below asserts a stable sum and multiset of weights, not per-mint equality.
"""

from __future__ import annotations

import json
from pathlib import Path

import base58
import pytest
from hypothesis import given
from hypothesis import strategies as st

from index.params import IndexParams, frac
from index.select import select_members, split_prize, weights_bps

ROOT = Path(__file__).resolve().parents[1]
P = IndexParams.model_validate(json.loads((ROOT / "index" / "params.json").read_text()))
CAPPED = P.model_copy(update={"weights": P.weights.model_copy(update={"mode": "score_capped"})})
SMALL = P.model_copy(
    update={
        "membership": P.membership.model_copy(update={"size": 5, "enter_rank": 3, "exit_rank": 7})
    }
)
BPS = 10_000


def mint(i: int) -> str:
    """Unique, valid base58 mint for index ``i`` (0 <= i <= 65_535)."""
    return base58.b58encode(i.to_bytes(2, "big") * 16).decode()


# ------------------------------------------------------------------ strategies


@st.composite
def scored_members(draw, min_size: int = 1, max_size: int = 30):
    """Unique members in rank order, each with one finite log-score."""
    idx = draw(st.lists(st.integers(0, 65_535), min_size=min_size, max_size=max_size, unique=True))
    members = [mint(i) for i in idx]
    scores = draw(
        st.lists(
            st.floats(-200, 200, allow_nan=False, allow_infinity=False),
            min_size=len(members),
            max_size=len(members),
        )
    )
    return members, dict(zip(members, scores, strict=True))


@st.composite
def ranked_and_previous(draw):
    """Unique ranked mints plus a previous member set (some still ranked, some gone)."""
    n = draw(st.integers(0, 30))
    ranked_idx = draw(st.lists(st.integers(0, 30_000), min_size=n, max_size=n, unique=True))
    ranked = [mint(i) for i in ranked_idx]
    keep_count = draw(st.integers(0, min(n, 20)))
    keep_pos = draw(
        st.lists(
            st.integers(0, max(n - 1, 0)),
            min_size=keep_count,
            max_size=keep_count,
            unique=True,
        )
    )
    keep = [ranked_idx[i] for i in keep_pos]
    gone = draw(st.lists(st.integers(40_000, 65_535), min_size=0, max_size=20, unique=True))
    return ranked, [mint(i) for i in keep + gone]


# ------------------------------------------------------------------ §6 weights


@given(scored_members())
def test_weights_bps_conserve_10000(case: tuple[list[str], dict[str, float]]) -> None:
    members, log_s = case
    assert members  # the strategy is non-empty
    for params in (P, CAPPED):
        bps = weights_bps(members, log_s, params)
        cap_bps = int(frac(params.weights.cap_pct) * 100)
        assert set(bps) == set(members)
        assert sum(bps.values()) == BPS
        assert all(share >= 0 for share in bps.values())
        if params is CAPPED and len(members) * cap_bps >= BPS:
            assert max(bps.values()) <= cap_bps


@given(scored_members(max_size=10), st.data())
def test_weights_bps_deterministic_for_any_member_order(
    case: tuple[list[str], dict[str, float]], data: st.DataObject
) -> None:
    members, log_s = case
    order = data.draw(st.permutations(members), label="member order")
    for params in (P, CAPPED):
        first = weights_bps(members, log_s, params)
        assert first == weights_bps(list(members), dict(log_s), params)
        reordered = weights_bps(order, log_s, params)
        assert set(reordered) == set(members)
        assert sum(reordered.values()) == BPS
        assert sorted(reordered.values()) == sorted(first.values())


# ------------------------------------------------------------------ §7 prize split


@given(st.integers(0, 2**63 - 1), scored_members())
def test_split_prize_conserves_lamports(
    lamports: int, case: tuple[list[str], dict[str, float]]
) -> None:
    members, log_s = case
    for params in (P, CAPPED):
        bps = weights_bps(members, log_s, params)
        parts = split_prize(lamports, members, bps)
        floors = {m: lamports * bps[m] // BPS for m in members}
        assert set(parts) == set(members)
        assert sum(parts.values()) == lamports
        assert all(share >= 0 for share in parts.values())
        assert all(parts[m] == floors[m] for m in members[1:])  # only rank 1 gets the remainder
        assert parts[members[0]] == floors[members[0]] + lamports - sum(floors.values())
        assert parts == split_prize(lamports, members, bps)


def test_split_prize_empty_basket_and_zero_prize() -> None:
    assert split_prize(0, [], {}) == {}
    with pytest.raises(ValueError, match="needs at least one member"):
        split_prize(1, [], {})


# ------------------------------------------------------------------ §5 membership


@given(ranked_and_previous())
def test_select_members_invariants(case: tuple[list[str], list[str]]) -> None:
    ranked, previous = case
    pos = {m: i + 1 for i, m in enumerate(ranked)}
    prev_set = set(previous)
    for params in (P, SMALL):
        mp = params.membership
        out = select_members(ranked, previous, params)
        assert len(out) == min(mp.size, len(ranked))
        assert len(set(out)) == len(out)  # no duplicates
        assert set(out) <= set(ranked)  # never an unranked or vanished mint
        assert out == sorted(out, key=lambda m: pos[m])  # rank order
        assert out == select_members(ranked, previous, params)  # deterministic
        assert out == select_members(ranked, list(reversed(previous)), params)  # prev order free

        # Hysteresis: a mint outside the enter/exit buffer only fills a short basket.
        eligible = [
            m
            for m in ranked
            if pos[m] <= mp.enter_rank or (m in prev_set and pos[m] <= mp.exit_rank)
        ]
        for m in out:
            if m not in eligible:
                assert len(eligible) < mp.size


@given(st.integers(0, 30))
def test_select_members_stable_ranking_keeps_previous(n: int) -> None:
    for params in (P, SMALL):
        ranked = [mint(i) for i in range(n)]
        previous = ranked[: params.membership.size]
        assert select_members(ranked, previous, params) == previous
        assert select_members(ranked, list(reversed(previous)), params) == previous
